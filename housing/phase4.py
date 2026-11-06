"""Retrospective count baselines: python -m housing.phase4 (no source writes)."""

import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp/housing-matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/housing-cache")
import json
import platform
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
import statsmodels.api as sm
from scipy.special import xlogy
from scipy.stats import nbinom, poisson
from statsmodels.discrete.discrete_model import NegativeBinomial

from housing.database import PROJECT
from housing.download import now, sha256

QUERY = """SELECT a.building_id,a.year,a.complaints,a.class_b,a.class_c,a.hazardous,
 a.calendar_months,a.source_coverage_present,f.selected_units,f.pluto_units,
 f.unit_counts_comparable,f.agreement_sensitivity,f.year_built,f.borough_id,
 f.building_class,f.bbl
 FROM analytical.annual a JOIN analytical.features f USING(building_id)
 ORDER BY a.building_id,a.year"""
NAMES = [
    "intercept",
    "log_units",
    "age_centuries",
    "year_trend",
    "Bronx",
    "Brooklyn",
    "Queens",
    "Staten_Island",
]


def validate(d):
    if d.duplicated(["building_id", "year"]).any():
        raise ValueError("Duplicate building-year")
    for field in ["selected_units", "year_built", "borough_id", "hazardous", "class_b", "class_c"]:
        if not np.isfinite(d[field]).all():
            raise ValueError(f"Invalid {field}")
    if not ((d.selected_units > 0) & (d.calendar_months == 12) & d.source_coverage_present).all():
        raise ValueError("Invalid or unavailable exposure")
    if not (
        (d.hazardous >= 0)
        & (d.hazardous == np.floor(d.hazardous))
        & (d.hazardous == d.class_b + d.class_c)
    ).all():
        raise ValueError("Invalid outcome")
    if not d.borough_id.isin(range(1, 6)).all():
        raise ValueError("Unknown borough")


def design(d):
    # No complaint, status, persistence, identifier, or evaluation-outcome predictors.
    return np.column_stack(
        [
            np.ones(len(d)),
            np.log(d.selected_units),
            (2021 - d.year_built) / 100,
            (d.year - 2021),
            *[(d.borough_id == k).astype(float) for k in range(2, 6)],
        ]
    )


def fit(d, family="poisson", denominator="selected_units"):
    exposure = d[denominator].to_numpy(float)
    if not np.isfinite(exposure).all() or (exposure <= 0).any():
        raise ValueError("Invalid exposure denominator")
    x = design(d)
    y = d.hazardous.to_numpy(float)
    offset = np.log(exposure)
    p = sm.GLM(y, x, offset=offset, family=sm.families.Poisson()).fit(maxiter=100)
    if not p.converged:
        raise RuntimeError("Poisson did not converge")
    if family == "poisson":
        return p.params, 0.0
    start = np.r_[p.params, 1.0]
    model = NegativeBinomial(y, x, offset=offset, loglike_method="nb2")
    result = model.fit(start_params=start, method="bfgs", maxiter=200, disp=False)
    if (
        not result.mle_retvals["converged"]
        or not np.isfinite(result.params).all()
        or result.params[-1] <= 0
    ):
        raise RuntimeError("NB2 did not converge")
    return result.params[:-1], float(result.params[-1])


def score(d, beta, alpha, denominator="selected_units"):
    y = d.hazardous.to_numpy(float)
    mu = np.exp(design(d) @ beta) * d[denominator].to_numpy(float)
    if not np.isfinite(mu).all() or (mu <= 0).any():
        raise ValueError("Invalid predictions")
    variance = mu + alpha * mu**2
    distribution = poisson(mu) if alpha == 0 else nbinom(1 / alpha, 1 / (1 + alpha * mu))
    out = d[["building_id", "year", "borough_id", "selected_units", "hazardous"]].copy()
    out["expected"] = mu
    out["observed_minus_expected"] = y - mu
    out["oe"] = y / mu
    out["pearson_residual"] = (y - mu) / np.sqrt(variance)
    out["small_expected"] = mu < 1
    out["lower95"] = distribution.ppf(0.025)
    out["upper95"] = distribution.ppf(0.975)
    metrics = {
        "n": len(d),
        "observed": float(y.sum()),
        "expected": float(mu.sum()),
        "aggregate_oe": float(y.sum() / mu.sum()),
        "mae": float(np.abs(y - mu).mean()),
        "mean_negative_log_likelihood": float(-distribution.logpmf(y).mean()),
        "pearson_dispersion": float(np.sum((y - mu) ** 2 / variance) / (len(y) - len(beta))),
        "poisson_deviance_per_row": float(2 * np.mean(xlogy(y, y / mu) - (y - mu))),
        "observed_zero_fraction": float(np.mean(y == 0)),
        "predicted_zero_fraction": float(distribution.pmf(0).mean()),
        "interval95_coverage": float(np.mean((y >= out.lower95) & (y <= out.upper95))),
        "residual_p99": float(np.quantile(out.pearson_residual, 0.99)),
        "small_expected_fraction": float(np.mean(mu < 1)),
    }
    return out, metrics


def main():
    report = PROJECT / "reports/phase4"
    report.mkdir(parents=True, exist_ok=True)
    local = PROJECT / "data/phase4"
    local.mkdir(exist_ok=True)
    with duckdb.connect(str(PROJECT / "data/housing.duckdb"), read_only=True) as con:
        d = con.sql(QUERY).df()
        # Linkage sensitivity selected solely using training-period events.
        conflict_ids = set(
            con.sql(
                "SELECT DISTINCT building_id FROM audit.event_links WHERE in_study AND year(event_month)<=2024 AND (bbl_conflict OR bin_conflict OR component_bbl_conflict)"
            ).fetchnumpy()["building_id"]
        )
    validate(d)
    if (
        set(d.year) != {2021, 2022, 2023, 2024, 2025}
        or not (d.groupby("building_id").size() == 5).all()
    ):
        raise ValueError("Expected complete 2021–2025 panel")
    annual = d.groupby("year").agg(
        buildings=("building_id", "size"),
        complaints=("complaints", "sum"),
        class_b=("class_b", "sum"),
        class_c=("class_c", "sum"),
        mean=("hazardous", "mean"),
        variance=("hazardous", "var"),
        zero_fraction=("hazardous", lambda x: (x == 0).mean()),
    )
    annual["variance_mean_ratio"] = annual.variance / annual["mean"]
    annual.to_csv(report / "annual_eda.csv")
    desc = (
        d.assign(rate=100 * d.hazardous / d.selected_units)[
            ["selected_units", "complaints", "class_b", "class_c", "hazardous", "rate"]
        ]
        .describe(percentiles=[0.5, 0.9, 0.95, 0.99])
        .T
    )
    desc.to_csv(report / "distributions.csv")
    for key in ["borough_id", "building_class"]:
        d.groupby(key).agg(
            rows=("hazardous", "size"),
            mean=("hazardous", "mean"),
            variance=("hazardous", "var"),
            units=("selected_units", "sum"),
            violations=("hazardous", "sum"),
        ).assign(rate=lambda x: 100 * x.violations / x.units).to_csv(report / f"eda_{key}.csv")
    train = d[d.year <= 2024]
    metrics = []
    coefficients = []
    outputs = {}
    calibrations = []
    configs = [("poisson", d, 2021, "selected_units", "poisson")]
    # NB justified using training dispersion, never evaluation performance.
    beta, alpha = fit(train)
    _, diagnostic = score(train, beta, alpha)
    if diagnostic["pearson_dispersion"] > 1.5:
        comparable = d[d.unit_counts_comparable & (d.pluto_units > 0)]
        configs += [
            ("nb2", d, 2021, "selected_units", "nb2"),
            ("comparable_hpd", comparable, 2021, "selected_units", "nb2"),
            ("comparable_pluto", comparable, 2021, "pluto_units", "nb2"),
            ("agreement", d[d.agreement_sensitivity], 2021, "selected_units", "nb2"),
            (
                "training_linkage_clean",
                d[~d.building_id.isin(conflict_ids)],
                2021,
                "selected_units",
                "nb2",
            ),
            ("exclude_2021", d, 2022, "selected_units", "nb2"),
        ]
    for name, subset, start, denominator, family in configs:
        tr = subset[(subset.year >= start) & (subset.year <= 2024)]
        te = subset[subset.year == 2025]
        print(f"Fitting {name}: {len(tr):,} training rows", flush=True)
        b, a = fit(tr, family, denominator)
        coefficients.extend(
            {"model": name, "term": term, "coefficient": float(value), "alpha": a}
            for term, value in zip(NAMES, b, strict=True)
        )
        for period, frame in [("training", tr), ("evaluation", te)]:
            out, m = score(frame, b, a, denominator)
            metrics.append({"model": name, "period": period, "alpha": a, **m})
            if period == "evaluation":
                out.to_csv(local / f"{name}_2025.csv.gz", index=False)
                outputs[name] = out
                for group in ["borough_id", "size_band", "expected_decile"]:
                    out["size_band"] = pd.cut(
                        out.selected_units, [0, 9, 49, np.inf], labels=["3–9", "10–49", "50+"]
                    )
                    out["expected_decile"] = pd.qcut(out.expected, 10, duplicates="drop").astype(
                        str
                    )
                    cal = (
                        out.groupby(group, observed=True)
                        .agg(
                            n=("hazardous", "size"),
                            observed=("hazardous", "mean"),
                            expected=("expected", "mean"),
                            residual_mean=("pearson_residual", "mean"),
                        )
                        .reset_index()
                        .rename(columns={group: "group"})
                    )
                    cal["group_type"] = group
                    cal["model"] = name
                    calibrations.append(cal)
    m = pd.DataFrame(metrics)
    m.to_csv(report / "model_metrics.csv", index=False)
    pd.DataFrame(coefficients).to_csv(report / "coefficients.csv", index=False)
    cal = pd.concat(calibrations)
    cal.to_csv(report / "calibration.csv", index=False)
    sensitivity = []
    base = outputs.get("nb2", outputs["poisson"])
    for name, out in outputs.items():
        joint = base.merge(
            out, on="building_id", suffixes=("_base", "_alternative"), validate="one_to_one"
        )
        sensitivity.append(
            {
                "model": name,
                "common_buildings": len(joint),
                "expected_spearman": joint.expected_base.corr(
                    joint.expected_alternative, method="spearman"
                ),
                "median_expected_ratio": np.median(
                    joint.expected_alternative / joint.expected_base
                ),
                "residual_spearman": joint.pearson_residual_base.corr(
                    joint.pearson_residual_alternative, method="spearman"
                ),
            }
        )
    pd.DataFrame(sensitivity).to_csv(report / "sensitivity.csv", index=False)
    plt.rcParams.update({"figure.dpi": 140, "font.size": 10})
    fig, axs = plt.subplots(2, 2, figsize=(11, 8))
    for ax, col, label in zip(
        axs.flat,
        ["selected_units", "complaints", "hazardous", "rate"],
        [
            "Apartments",
            "Annual complaints",
            "Annual B/C violations",
            "B/C per 100 capacity-unit-years",
        ],
        strict=True,
    ):
        vals = d[col] if col != "rate" else 100 * d.hazardous / d.selected_units
        ax.hist(np.log1p(vals), bins=60, color="#287890")
        ax.set(xlabel=f"log(1 + {label})", ylabel="Building-years")
    fig.tight_layout()
    fig.savefig(report / "distributions.png")
    plt.close(fig)
    fig, axs = plt.subplots(1, 2, figsize=(11, 4))
    annual[["class_b", "class_c", "complaints"]].plot(ax=axs[0], marker="o")
    axs[0].set(ylabel="Recorded events", title="Fixed cohort annual activity")
    annual.zero_fraction.plot(ax=axs[1], marker="o")
    axs[1].set(ylabel="Fraction", title="Zero B/C building-years", ylim=(0, 1))
    fig.tight_layout()
    fig.savefig(report / "annual_trends.png")
    plt.close(fig)
    fig, axs = plt.subplots(1, 3, figsize=(14, 4))
    for name in ["poisson", "nb2"]:
        if name not in outputs:
            continue
        out = outputs[name]
        bins = pd.qcut(out.expected, 10, duplicates="drop")
        grouped = out.groupby(bins, observed=True)[["expected", "hazardous"]].mean()
        axs[0].plot(grouped.expected, grouped.hazardous, "o-", label=name)
    limit = max(axs[0].get_xlim()[1], axs[0].get_ylim()[1])
    axs[0].plot([0, limit], [0, limit], "k--")
    axs[0].legend()
    axs[0].set(xlabel="Mean expected", ylabel="Mean observed", title="2025 calibration bins")
    axs[1].hexbin(
        np.log1p(base.expected), np.log1p(base.hazardous), gridsize=45, bins="log", mincnt=1
    )
    axs[1].set(
        xlabel="log(1 + expected)", ylabel="log(1 + observed)", title="2025 observed vs expected"
    )
    axs[2].hexbin(
        np.log1p(base.expected),
        np.arcsinh(base.pearson_residual),
        gridsize=45,
        bins="log",
        mincnt=1,
    )
    axs[2].axhline(0, color="black")
    axs[2].set(
        xlabel="log(1 + expected)",
        ylabel="asinh(Pearson residual)",
        title="NB2 residuals (all rows)",
    )
    fig.tight_layout()
    fig.savefig(report / "diagnostics.png")
    plt.close(fig)
    provenance = {
        "generated_at": now(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "statsmodels": sm.__version__,
        "sql": QUERY,
        "input_sha256": __import__("hashlib")
        .sha256(pd.util.hash_pandas_object(d, index=False).values.tobytes())
        .hexdigest(),
        "code_sha256": sha256(Path(__file__)),
        "report_code_sha256": sha256(PROJECT / "housing/phase4_report.py"),
        "lock_sha256": sha256(PROJECT / "uv.lock"),
        "training_years": [2021, 2022, 2023, 2024],
        "evaluation_year": 2025,
        "predictors": NAMES,
    }
    (report / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    from housing.phase4_report import write_report

    write_report(report)
    print(m.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
