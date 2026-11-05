"""Load a frozen extract, run the SQL, and publish aggregate audit artifacts."""

import csv
import json
import platform
import uuid
from pathlib import Path

import duckdb

from housing.download import save_json, sha256
from housing.sources import SOURCES, partitions

PROJECT = Path(__file__).resolve().parent.parent


def execute_sql(connection, directory=PROJECT / "sql"):
    for path in sorted(directory.glob("*.sql")):
        print(f"SQL {path.name}", flush=True)
        connection.execute(path.read_text())


def verify_snapshot(root, config):
    run = json.loads((root / "run.json").read_text())
    if not run.get("complete") or run["contract"]["study"] != config["study"]:
        raise ValueError("Complete a matching download before loading this snapshot.")
    manifests = []
    for name, source in SOURCES.items():
        for label, where in partitions(
            source, config["study"]["start_year"], config["study"]["end_year"]
        ):
            manifest = json.loads((root / "manifests" / f"{name}-{label}.json").read_text())
            selection = {
                "dataset_id": source.dataset_id,
                "columns": list(source.columns),
                "where": where,
            }
            if manifest["selection"] != selection:
                raise ValueError(f"Selection changed for {name}/{label}")
            if sha256(root / manifest["path"]) != manifest["sha256"]:
                raise ValueError(f"Checksum mismatch for {manifest['path']}")
            manifests.append({"source": name, "partition": label, **manifest})
    return run, manifests


def load_raw(connection, root, manifests, config):
    for schema in ("raw", "clean", "mart", "audit"):
        connection.execute(f"CREATE SCHEMA {schema}")
    connection.execute("CREATE TABLE run_config(start_date DATE, end_date DATE)")
    connection.execute(
        "INSERT INTO run_config VALUES (?, ?)",
        [f"{config['study']['start_year']}-01-01", f"{config['study']['end_year'] + 1}-01-01"],
    )
    for name, source in SOURCES.items():
        entries = [m for m in manifests if m["source"] == name]
        files = [str((root / m["path"]).resolve()) for m in entries]
        # Explicit source column types prevent identifiers being inferred as floats.
        columns = {column: "VARCHAR" for column in source.columns}
        connection.execute(
            f"""
            CREATE TABLE raw.{name} AS
            SELECT * EXCLUDE (filename),
                   regexp_extract(filename, '([^/]+)[.]csv[.]gz$', 1) AS _partition
            FROM read_csv(?, columns = ?, header = true, auto_detect = false,
                          delim = ',', quote = '"', escape = '"', filename = true)
        """,
            [files, columns],
        )
        actual = dict(
            connection.execute(
                f"SELECT _partition, count(*) FROM raw.{name} GROUP BY _partition"
            ).fetchall()
        )
        for entry in entries:
            if actual.get(entry["partition"], 0) != entry["rows"]:
                raise ValueError(f"Loaded row count differs for {name}/{entry['partition']}")
        print(f"loaded {name}: {sum(actual.values()):,} rows", flush=True)


def export_csv(connection, query, path):
    cursor = connection.execute(query)
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([d[0] for d in cursor.description])
        writer.writerows(cursor.fetchall())


def markdown_table(headers, rows):
    def cell(value):
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:,.2f}"
        if isinstance(value, int):
            return f"{value:,}"
        return str(value).replace("|", "\\|").replace("\n", " ")

    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(cell(x) for x in row) + " |" for row in rows),
        ]
    )


def write_reports(connection, report_dir, run, manifests, config):
    report_dir.mkdir(parents=True, exist_ok=True)
    exports = {
        "checks": "SELECT * FROM audit.checks ORDER BY severity, check_name",
        "monthly_coverage": "SELECT * FROM audit.monthly_coverage ORDER BY source, event_month",
        "linkage_summary": "SELECT * FROM audit.linkage_summary ORDER BY source, year",
        "unit_comparison": "SELECT * FROM audit.unit_comparison ORDER BY borough_id, candidate_multifamily, unit_comparison",
        "violation_classes": "SELECT * FROM audit.violation_classes ORDER BY year, violation_class",
        "date_quality": "SELECT * FROM audit.date_quality ORDER BY source, extract_partition",
        "cohort_summary": "SELECT * FROM audit.cohort_summary ORDER BY buildings DESC",
    }
    for name, query in exports.items():
        export_csv(connection, query, report_dir / f"{name}.csv")
    provenance = {
        "snapshot": run,
        "config": config,
        "python_version": platform.python_version(),
        "duckdb_version": duckdb.__version__,
        "extracts": [
            {
                k: m[k]
                for k in (
                    "source",
                    "partition",
                    "selection",
                    "rows",
                    "sha256",
                    "started_at",
                    "completed_at",
                )
            }
            for m in manifests
        ],
    }
    save_json(report_dir / "provenance.json", provenance)

    annual = connection.execute("""
        SELECT year(event_month) AS year, count(*) AS problem_rows,
               count(DISTINCT complaint_id) AS complaints FROM clean.complaints
        WHERE in_study GROUP BY year(event_month) ORDER BY year
    """).fetchall()
    links = connection.execute("""
        SELECT source, sum(rows), sum(building_unmatched), sum(bbl_conflicts), sum(bin_conflicts)
        FROM audit.linkage_summary WHERE in_study GROUP BY source ORDER BY source
    """).fetchall()
    units = connection.execute("""
        SELECT unit_comparison, count(*) FROM mart.buildings WHERE candidate_multifamily
        GROUP BY unit_comparison ORDER BY count(*) DESC
    """).fetchall()
    checks = connection.execute(
        "SELECT * FROM audit.checks WHERE failures > 0 ORDER BY severity, check_name"
    ).fetchall()
    counts = connection.execute("""
        SELECT count(*), count(*) FILTER (WHERE candidate_multifamily), count(rate_units)
        FROM mart.buildings
    """).fetchone()
    monthly = connection.execute("""
        SELECT source, count(*), count(*) FILTER (WHERE rows = 0), min(rows), max(rows)
        FROM audit.monthly_coverage GROUP BY source ORDER BY source
    """).fetchall()
    errors = [row for row in checks if row[1] == "error"]
    start, end = config["study"]["start_year"], config["study"]["end_year"]
    body = f"""# Phase 2: extraction, validation, and linkage audit

Generated from the local frozen extracts completed at **{run["completed_at"]}**.
Configured event window: **{start}–{end}**, using complaint receipt and violation inspection dates.
Reference tables are current snapshots; historical ownership/occupancy is not reconstructed.

## Integrity and reproducibility

**{"FAILED: database not published" if errors else "Passed: all blocking integrity checks"}**.
Every downloaded partition reconciled to source counts before and after extraction and was
verified by SHA-256 before loading. Exact queries and source metadata are retained in the local
snapshot; portable selection criteria and hashes are in [provenance.json](provenance.json).

Sources whose data-update timestamp changed during extraction: **{run.get("sources_updated_during_extract", [])}**.
The live API offers no transactional snapshot. Matching counts cannot rule out in-place revisions.

## Coverage

{markdown_table(["Source", "Months", "Months without records", "Minimum monthly rows", "Maximum monthly rows"], monthly)}

{markdown_table(["Year", "Problem rows", "Distinct complaints"], annual)}

Nonzero records in every month establish observed coverage, not proof that every event was
published. Review [monthly_coverage.csv](monthly_coverage.csv) for changes in recording volume.
The window remains provisional; 2025 is a potential holdout, not a locked modeling split.
Undated events are retained for audit only and excluded from all dated outcomes.

## Event linkage

{markdown_table(["Source", "Study rows", "No HPD building match", "BBL conflicts", "BIN conflicts"], links)}

Linkage uses HPD BuildingID; BBL/BIN disagreements are flags, not automatic rematches.
Unmatched events remain in clean tables and audit views. The building panel contains only
the HPD reference inventory; it does not silently represent unmatched events as zero.

## Apartment exposure

The inventory has **{counts[0]:,}** HPD records, **{counts[1]:,}** provisional multifamily
candidates, and **{counts[2]:,}** candidates with the conservative comparison denominator.

{markdown_table(["Unit comparison for candidate buildings", "Buildings"], units)}

Candidates are current active buildings with at least three HPD apartments, zero reported
Class B rooms, and a known management program other than NYCHA. This is a review flag, not
a final historical rental cohort. Missing or different housing types remain in the database.

**Provisional denominator:** use the positive apartment count only when HPD and PLUTO agree,
PLUTO reports one building, and exactly one active HPD building maps to the lot. Otherwise,
`rate_units` is NULL and both source counts and the disagreement classification are retained.
No lot-level unit count is copied to multiple buildings. This strict choice sacrifices coverage;
the final analysis must assess that selection and compare HPD-denominator sensitivity results.
Neither source establishes occupied units or a historical unit-year denominator. Rates are
current-capacity-normalized summaries, not evidence of historical occupancy.

## Checks requiring attention

{markdown_table(["Check", "Severity", "Rows or groups"], checks) if checks else "No automated checks flagged records."}

See [checks.csv](checks.csv), [date_quality.csv](date_quality.csv), and
[violation_classes.csv](violation_classes.csv). Warnings remain visible; they are not assertions
of misconduct or reasons to delete records automatically.

## DuckDB outputs and next analytical decisions

- `raw.*`: selected original source values, plus extraction partition.
- `clean.*`: typed identifiers, dates, classes, and study-window flags.
- `mart.buildings`: linkage, property characteristics, and denominator comparisons.
- `mart.complaints_monthly`, `mart.complaint_categories_monthly`, `mart.violations_monthly`:
  independent event aggregates, including unmatched building IDs.
- `mart.building_month`, `mart.building_year`: current-inventory panels including zero activity.
- `mart.rolling_activity`: complete 12-calendar-month totals; early partial windows stay NULL.
- `mart.provisional_rates`, `mart.peer_comparisons`: transparent preliminary rates and SQL ranks.
- `audit.*`: coverage, linkage, date, denominator, and integrity diagnostics.

Before modeling, review cohort selection, denominator disagreements, unmatched events, and
monthly changes. Fit a Poisson baseline before considering Negative Binomial. Compare raw,
per-unit, regression-adjusted, and Isolation Forest rankings in the later analytical phase.
No model, subjective composite score, or formal statistical anomaly label is produced here.
"""
    (report_dir / "README.md").write_text(body)


def build_database(root, database, report_dir, config):
    root, database, report_dir = Path(root), Path(database), Path(report_dir)
    run, manifests = verify_snapshot(root, config)
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_name(f".{database.stem}-{uuid.uuid4().hex}.duckdb")
    connection = duckdb.connect(str(temporary))
    try:
        connection.execute("SET memory_limit = ?", [config["database"]["memory_limit"]])
        connection.execute("SET threads = ?", [config["database"]["threads"]])
        load_raw(connection, root, manifests, config)
        execute_sql(connection)
        write_reports(connection, report_dir, run, manifests, config)
        errors = connection.execute(
            "SELECT check_name, failures FROM audit.checks WHERE severity='error' AND failures>0"
        ).fetchall()
        if errors:
            raise ValueError(f"Blocking integrity checks failed: {errors}")
        connection.close()
        temporary.replace(database)
        print(f"published {database}; audit: {report_dir / 'README.md'}", flush=True)
    except Exception:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
