"""Pre-2025 selection, frozen final evaluation: python -m housing.phase5."""

import hashlib
import json
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.stats import nbinom

from housing.database import PROJECT
from housing.download import now, sha256
from housing.phase4 import QUERY, design, fit, score, validate

MODELS = ("poisson", "nb2", "nb_size", "nb_size_flat", "poisson_size_nb_variance")
PLAN = {
    "folds": [
        {"train": [2021, 2022], "validation": 2023},
        {"train": [2021, 2022, 2023], "validation": 2024},
    ],
    "models": MODELS,
    "size_knots_apartments": [10, 50],
    "selection": "minimum mean across folds of absolute log aggregate O/E plus mean absolute log O/E in three size bands; tie break by validation negative log likelihood",
    "final_fit": [2021, 2022, 2023, 2024],
    "final_evaluation": 2025,
    "bootstrap_replicates": 300,
    "bootstrap_seed": 501,
}


def matrix(d, name, last_year):
    x = design(d).copy()
    if name == "nb_size_flat":
        x[:, 3] = np.minimum(d.year, last_year) - 2021
    if name not in ("poisson", "nb2"):
        log_size = np.log(d.selected_units.to_numpy(float))
        x = np.column_stack(
            [x, np.maximum(log_size - np.log(10), 0), np.maximum(log_size - np.log(50), 0)]
        )
    return x


def estimate(train, name):
    if train.year.max() >= 2025:
        raise ValueError("2025 cannot enter estimation")
    x = matrix(train, name, int(train.year.max()))
    family = "poisson" if name in ("poisson", "poisson_size_nb_variance") else "nb2"
    b, a = fit(train, family, design_matrix=x)
    if name == "poisson_size_nb_variance":
        mu = np.exp(x @ b) * train.selected_units.to_numpy(float)
        y = train.hazardous.to_numpy(float)
        result = minimize_scalar(
            lambda loga: -nbinom.logpmf(y, 1 / np.exp(loga), 1 / (1 + np.exp(loga) * mu)).mean(),
            bounds=(-8, 8),
            method="bounded",
        )
        if not result.success:
            raise RuntimeError("Dispersion fit failed")
        a = float(np.exp(result.x))
    return b, a


def evaluate(train, test, name, b, a):
    out, m = score(test, b, a, design_matrix=matrix(test, name, int(train.year.max())))
    out["bbl"] = test.bbl.to_numpy()
    historical = train.groupby("building_id").hazardous.mean()
    out["history"] = pd.cut(
        out.building_id.map(historical),
        [-1, 0, 5, 20, np.inf],
        labels=["zero", "0–5", "5–20", "20+"],
    ).astype(str)
    out["size_band"] = pd.cut(
        out.selected_units, [0, 9, 49, np.inf], labels=["3–9", "10–49", "50+"]
    ).astype(str)
    units = train.drop_duplicates("building_id").selected_units
    edges = np.unique(np.r_[-np.inf, np.quantile(units, np.arange(0.1, 1, 0.1)), np.inf])
    out["size_decile"] = pd.cut(out.selected_units, edges).astype(str)
    tables = []
    for group in ["size_band", "size_decile", "borough_id", "history"]:
        g = (
            out.groupby(group, observed=True)
            .agg(
                n=("hazardous", "size"),
                observed=("hazardous", "sum"),
                expected=("expected", "sum"),
                zero_fraction=("hazardous", lambda x: (x == 0).mean()),
            )
            .reset_index()
            .rename(columns={group: "group"})
        )
        g["oe"] = g.observed / g.expected
        g["group_type"] = group
        tables.append(g)
    groups = pd.concat(tables)
    m["calibration_loss"] = (
        abs(np.log(m["aggregate_oe"]))
        + np.abs(np.log(groups.loc[groups.group_type == "size_band", "oe"])).mean()
    )
    return out, m, groups


def select(validation):
    if not validation.year.isin([2023, 2024]).all():
        raise ValueError("Selection accepts only pre-2025 validation folds")
    return (
        validation.groupby("model")[["calibration_loss", "mean_negative_log_likelihood"]]
        .mean()
        .sort_values(["calibration_loss", "mean_negative_log_likelihood"])
        .index[0]
    )


def bootstrap(out, previous):
    paired = out[["building_id", "bbl", "hazardous", "expected", "selected_units"]].merge(
        previous[["building_id", "hazardous"]],
        on="building_id",
        suffixes=("", "_previous"),
        validate="one_to_one",
    )
    blocks = (
        paired.groupby("bbl")[["hazardous", "expected", "hazardous_previous", "selected_units"]]
        .sum()
        .to_numpy()
    )
    rng = np.random.default_rng(PLAN["bootstrap_seed"])
    draws = []
    for _ in range(PLAN["bootstrap_replicates"]):
        totals = blocks[rng.integers(0, len(blocks), len(blocks))].sum(axis=0)
        draws.append([totals[0] / totals[1], totals[0] / totals[2] - 1])
    return dict(
        zip(
            ["aggregate_oe", "year_over_year_change"],
            np.quantile(draws, [0.025, 0.975], axis=0).T.tolist(),
            strict=True,
        )
    )


def main():
    root = PROJECT / "reports/phase5"
    root.mkdir(parents=True, exist_ok=True)
    local = PROJECT / "data/phase5"
    local.mkdir(exist_ok=True)
    (root / "plan.json").write_text(json.dumps(PLAN, indent=2) + "\n")
    with duckdb.connect(str(PROJECT / "data/housing.duckdb"), read_only=True) as c:
        pre = c.sql(f"SELECT * FROM ({QUERY}) WHERE year<2025").df()
    validate(pre)
    results = []
    subgroup = []
    for year in [2023, 2024]:
        tr = pre[pre.year < year]
        te = pre[pre.year == year]
        for name in MODELS:
            print("validation", year, name, flush=True)
            b, a = estimate(tr, name)
            _, m, g = evaluate(tr, te, name, b, a)
            results.append({"model": name, "year": year, "alpha": a, **m})
            g["model"] = name
            g["year"] = year
            subgroup.append(g)
    validation = pd.DataFrame(results)
    winner = select(validation)
    validation.to_csv(root / "validation_models.csv", index=False)
    pd.concat(subgroup).to_csv(root / "validation_groups.csv", index=False)
    decision = {
        "selected": winner,
        "selected_at": now(),
        "plan_sha256": sha256(root / "plan.json"),
        "validation_sha256": sha256(root / "validation_models.csv"),
    }
    # Persist selection before querying any final-period outcomes.
    (root / "decision.json").write_text(json.dumps(decision, indent=2) + "\n")
    print("Frozen choice:", winner, flush=True)
    with duckdb.connect(str(PROJECT / "data/housing.duckdb"), read_only=True) as c:
        final = c.sql(f"SELECT * FROM ({QUERY}) WHERE year=2025").df()
    validate(final)
    if set(final.building_id) != set(pre.building_id):
        raise ValueError("Cohort changed")
    if not (pre.groupby("building_id").selected_units.nunique() == 1).all():
        raise ValueError("Exposure changed")
    if not np.array_equal(
        pre[pre.year == 2024].sort_values("building_id").selected_units,
        final.sort_values("building_id").selected_units,
    ):
        raise ValueError("Final exposure changed")
    summaries = []
    groups = []
    intervals = {}
    predictions = {}
    parameters = {}
    for name in dict.fromkeys(["poisson", "nb2", winner]):
        print("final", name, flush=True)
        b, a = estimate(pre, name)
        out, m, g = evaluate(pre, final, name, b, a)
        parameters[name] = {"coefficients": b.tolist(), "alpha": a}
        summaries.append({"model": name, **m})
        g["model"] = name
        groups.append(g)
        predictions[name] = out
        intervals[name] = bootstrap(out, pre[pre.year == 2024])
        out.to_csv(local / f"{name}_2025.csv.gz", index=False)
    summary = pd.DataFrame(summaries)
    summary.to_csv(root / "final_metrics.csv", index=False)
    grouped = pd.concat(groups)
    grouped.to_csv(root / "final_groups.csv", index=False)
    (root / "uncertainty.json").write_text(json.dumps(intervals, indent=2) + "\n")
    (root / "parameters.json").write_text(json.dumps(parameters, indent=2) + "\n")
    all_data = pd.concat([pre, final])
    trend = all_data.groupby("year").agg(
        buildings=("building_id", "size"),
        apartments=("selected_units", "sum"),
        violations=("hazardous", "sum"),
    )
    trend["rate_per_100"] = 100 * trend.violations / trend.apartments
    trend["change"] = trend.rate_per_100.pct_change()
    trend.to_csv(root / "temporal_rates.csv")
    # Diagnostic breakdowns do not feed model selection.
    all_data["size_band"] = pd.cut(
        all_data.selected_units, [0, 9, 49, np.inf], labels=["3–9", "10–49", "50+"]
    )
    all_data.groupby(["year", "size_band", "borough_id"], observed=True).agg(
        buildings=("building_id", "size"),
        exposure=("selected_units", "sum"),
        violations=("hazardous", "sum"),
    ).to_csv(root / "temporal_composition.csv")
    size = (
        pre.groupby("selected_units")
        .agg(
            buildings=("hazardous", "size"),
            mean_count=("hazardous", "mean"),
            total=("hazardous", "sum"),
        )
        .reset_index()
    )
    size["rate"] = 100 * size.mean_count / size.selected_units
    size.to_csv(root / "training_size_curve.csv", index=False)
    plt.rcParams.update({"figure.dpi": 140})
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    axes[0].plot(trend.index, trend.rate_per_100, "o-")
    axes[0].set(
        xticks=trend.index,
        xlabel="Year",
        ylabel="B/C per 100 capacity-unit-years",
        title="Fixed composition and exposure",
    )
    axes[1].scatter(
        size.selected_units, size.rate, s=np.maximum(3, np.log1p(size.buildings)), alpha=0.4
    )
    axes[1].set(
        xscale="log",
        yscale="log",
        xlabel="Apartments (log)",
        ylabel="Training rate (log)",
        title="Nonlinear size relationship; sparse tail",
    )
    for name in predictions:
        g = (
            grouped[(grouped.model == name) & (grouped.group_type == "size_band")]
            .set_index("group")
            .reindex(["3–9", "10–49", "50+"])
        )
        axes[2].plot(g.index, g.oe, "o-", label=name)
    axes[2].axhline(1, color="black", linestyle="--")
    axes[2].set(ylabel="Observed / expected", title="Final 2025 size calibration")
    axes[2].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(root / "diagnostics.png")
    plt.close(fig)
    (root / "provenance.json").write_text(
        json.dumps(
            {
                "generated_at": now(),
                "code_sha256": sha256(Path(__file__)),
                "phase4_code_sha256": sha256(PROJECT / "housing/phase4.py"),
                "lock_sha256": sha256(PROJECT / "uv.lock"),
                "pre2025_input_sha256": hashlib.sha256(
                    pd.util.hash_pandas_object(pre, index=False).values.tobytes()
                ).hexdigest(),
                "final_input_sha256": hashlib.sha256(
                    pd.util.hash_pandas_object(final, index=False).values.tobytes()
                ).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    from housing.phase5_report import write_report

    write_report(root, validation, summary, trend, winner, intervals)
    print(summary.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
