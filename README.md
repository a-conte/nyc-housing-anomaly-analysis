# Investigating Unusual Patterns in NYC Housing Complaints and Violations

Can publicly available NYC housing data identify buildings with unusually high or persistent
complaint and violation activity relative to comparable properties?

This project is a concise data-science portfolio sample designed to demonstrate Python,
substantive SQL, data-quality judgment, and interpretable statistical analysis. A recorded
anomaly is a lead for investigation, not a finding of misconduct.

**Phase 2 completed November 5, 2026: snapshot verification, DuckDB loading, and data-quality auditing.**
Read the [Phase 2 findings and unresolved decisions](reports/phase2/QUALITY_REVIEW.md) and
[generated audit](reports/phase2/README.md). All 17 blocking integrity checks pass.
The approved [analytical design](docs/analytical_design.md) sets the scope. Phase 3 is now complete; see the [cohort and feature report](reports/phase3/README.md).
Rebuild it without downloading data using `python -m housing.phase3`. No models have been fitted.

## Reproduce Phase 2

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). Run commands from the repository root:

```bash
uv sync --locked
uv run python -m housing run
uv run python -m pytest -q
uv run python -m ruff check housing tests
```

The first run downloads the four public sources and creates `data/housing.duckdb` plus
[aggregate audit outputs](reports/phase2/README.md). Large source downloads require network
access and can take time. Completed annual partitions are resumable and checksum-verified.
An optional `SOCRATA_APP_TOKEN` environment variable can reduce unauthenticated API throttling;
the token is never written to manifests.

For separate steps or a new dated snapshot:

```bash
uv run python -m housing download --snapshot data/snapshot-2026-11-02
uv run python -m housing load --snapshot data/snapshot-2026-11-02
```

`config.toml` controls the **provisional** study window, API page size/concurrency, and DuckDB
resources. Use a new `--snapshot` directory when changing the period or refreshing the live
data. An existing complete snapshot is reused, not silently refreshed. Loading requires a
complete snapshot matching the configured period. Database builds use a temporary file and
replace the published database only after blocking integrity checks pass.

All raw data, manifests, and the database live under the ignored `data/` directory. The small,
aggregate audit reports and their provenance can be version-controlled. A fresh download may
differ from this run: NYC revises live records. Exact reruns require retaining the local snapshot.

## Four core sources

| Official NYC Open Data source | Dataset ID | Observation | Project use |
| --- | --- | --- | --- |
| [HPD complaints and problems](https://data.cityofnewyork.us/d/ygpa-z7cr) | `ygpa-z7cr` | One reported problem, linked to a complaint | Distinct complaints, problems, categories, recurrence |
| [Housing Maintenance Code violations](https://data.cityofnewyork.us/d/wvxf-dwi5) | `wvxf-dwi5` | One violation | Separate Class B, Class C, and combined B/C outcomes |
| [Buildings subject to HPD jurisdiction](https://data.cityofnewyork.us/d/kj4p-ruqc) | `kj4p-ruqc` | One HPD building record | Primary BuildingID, building characteristics, apartment counts |
| [PLUTO](https://data.cityofnewyork.us/d/64uk-42ks) | `64uk-42ks` | One tax lot | Property characteristics and unit-count comparison |

Registration and owner contacts may be added later. **Neither they nor 311 are core dependencies.**
The source definitions and exact selected columns are in [housing/sources.py](housing/sources.py).
Apartment identifiers, tenant information, and contact names are not requested by this ETL.

## What the code demonstrates

| Component | Responsibility |
| --- | --- |
| [housing/download.py](housing/download.py) | Schema checks, ordered keyset pagination, retries, annual extracts, source-count reconciliation, hashes, metadata |
| [housing/database.py](housing/database.py) | Verified loading, SQL orchestration, blocking checks, aggregate reports |
| [sql/01_staging.sql](sql/01_staging.sql) | Safe identifier and date normalization; no float-rounded IDs |
| [sql/02_linkage.sql](sql/02_linkage.sql) | Building/lot cardinality, geographic conflicts, explicit denominator comparison |
| [sql/03_metrics.sql](sql/03_metrics.sql) | Distinct event aggregation, zero-event inventory, temporal panels, rolling windows, peer comparisons, ranks |
| [sql/04_audits.sql](sql/04_audits.sql) | Monthly coverage, date quality, join failures, units, severity, and analytical invariants |
| [sql/05_quality.sql](sql/05_quality.sql) | Event conservation, key cardinality, cohort exclusions, denominator selection, and construction exposure |
| [tests/](tests/) | Synthetic edge cases for fan-out, distinct complaints, missing links, denominators, rolling boundaries, pagination, and corruption |

Python handles acquisition and orchestration. SQL performs the meaningful transformations.
There is no cloud service, scheduler, application framework, or mandatory notebook runtime.
The final project will have 1–2 polished analytical notebooks rather than a notebook per ETL step.

## Analytical safeguards

- **Building is primary.** Join on HPD BuildingID; use BBL/BIN for enrichment and validation.
  Keep unmatched events and conflicting geographic keys in audit views.
- **Different event grains stay distinct.** Count complaints by `complaint_id`, problems by
  `problem_id`, and violations by `violationid`. Aggregate each source before joining it.
- **Severity remains visible.** Keep B, C, and B/C separately; Class I is not a hazardous outcome.
- **Property size is explicit.** Preserve HPD apartment and PLUTO residential-unit counts.
  PLUTO units describe the lot and cannot be assigned wholesale to each building on that lot.
- **Disagreements are not silently resolved.** Provisional rate views require agreement on a
  single-building lot; other records retain both counts with a reason for withholding the rate.
  This conservative subset is subject to coverage and selection-bias review before modeling.
- **Zero activity is not proof of good conditions.** The panel includes the current HPD inventory;
  source coverage, construction timing, and historical exposure still require interpretation.
- **Dates have defined meanings.** Complaints use receipt date; violations use inspection date.
  Undated records are extracted separately and excluded from dated metrics. Source floating
  timestamps are preserved without inventing a UTC conversion. Current statuses do not reconstruct
  historical repair or closure sequences.
- **Snapshots are not historical ownership records.** Current PLUTO and HPD attributes may differ
  from those in effect when a complaint or violation occurred.

## Query the database

```python
import duckdb

with duckdb.connect("data/housing.duckdb", read_only=True) as con:
    print(con.sql("SELECT * FROM audit.checks ORDER BY severity, check_name"))
    print(con.sql("""
        SELECT year, sum(complaints) AS complaints,
               sum(class_b) AS class_b, sum(class_c) AS class_c
        FROM mart.building_year
        GROUP BY year ORDER BY year
    """))
```

`raw.*` preserves selected source values. `clean.*` holds typed records. `mart.*` contains
building metrics. `audit.*` contains the quality and linkage evidence. See the generated
[Phase 2 report](reports/phase2/README.md) for the actual run findings and unresolved concerns.

## Later analysis

After reviewing Phase 2, compare **raw-count**, **per-unit**, **regression-adjusted**, and
**Isolation Forest** rankings. The question is: **How does our definition of unusual change
depending on methodology?**

Start with a Poisson baseline and use Negative Binomial only if overdispersion supports it.
Interpret observed versus expected activity and persistence. Keep 2025 as a potential holdout
if coverage supports it, and prioritize ranking stability over an elaborate validation framework.
Simulation calibration and multiple-testing correction are optional, diagnostic-driven additions.
Do not construct a subjective composite bad-landlord score or assume Isolation Forest is superior.

## Phase 4 baselines

[Exploration and model diagnostics](reports/phase4/README.md) compare Poisson and NB2
baselines trained on 2021–2024 and evaluated retrospectively on 2025. Reproduce with
`uv run python -m housing.phase4`. NB2 improves distributional fit but substantial mean
miscalibration remains; no investigative rankings or formal anomaly thresholds were produced.
