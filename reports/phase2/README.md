# Phase 2: extraction, validation, and linkage audit

Generated from the local frozen extracts completed at **2026-11-05T17:44:45.707375+00:00**.
Configured event window: **2021–2025**, using complaint receipt and violation inspection dates.
Reference tables are current snapshots; historical ownership/occupancy is not reconstructed.

## Integrity and reproducibility

**Passed: all blocking integrity checks**.
Every downloaded partition reconciled to source counts before and after extraction and was
verified by SHA-256 before loading. Exact queries and source metadata are retained in the local
snapshot; portable selection criteria and hashes are in [provenance.json](provenance.json).

Sources whose data-update timestamp changed during extraction: **[]**.
The live API offers no transactional snapshot. Matching counts cannot rule out in-place revisions.

Partitions replaced after failed verification: **2**.
Any replacements, original and replacement hashes, and extraction dates are recorded in the
provenance snapshot's `repairs` list. A repaired partition may have a later snapshot date than
the other partitions; current statuses must be interpreted at their respective extraction times.
See [snapshot_verification.csv](snapshot_verification.csv) for all expected/loaded row counts,
including header-only undated extracts, and [row_reconciliation.csv](row_reconciliation.csv)
for raw-to-clean, monthly-aggregate, and matched-panel conservation checks.

## Coverage

| Source | Months | Months without records | Minimum monthly rows | Maximum monthly rows |
| --- | --- | --- | --- | --- |
| complaints | 60 | 0 | 35,437 | 117,276 |
| violations | 60 | 0 | 36,870 | 214,025 |

| Year | Problem rows | Distinct complaints |
| --- | --- | --- |
| 2021 | 617,503 | 371,078 |
| 2022 | 733,471 | 461,364 |
| 2023 | 747,466 | 443,881 |
| 2024 | 823,169 | 491,912 |
| 2025 | 856,280 | 532,962 |

Nonzero records in every month establish observed coverage, not proof that every event was
published. Review [monthly_coverage.csv](monthly_coverage.csv) for changes in recording volume.
The window remains provisional; 2025 is a potential holdout, not a locked modeling split.
Undated events are retained for audit only and excluded from all dated outcomes.

## Event linkage

| Source | Study rows | No HPD building match | BBL conflicts | BIN conflicts |
| --- | --- | --- | --- | --- |
| complaints | 3,777,889 | 370 | 15,023 | 17,988 |
| violations | 4,422,541 | 220 | 20,324 | 19,956 |

Linkage uses HPD BuildingID; BBL/BIN disagreements are flags, not automatic rematches.
Unmatched events remain in clean tables and audit views. The building panel contains only
the HPD reference inventory; it does not silently represent unmatched events as zero.
Reference-inventory match rates are in [building_linkage.csv](building_linkage.csv),
identifier missingness in [identifier_quality.csv](identifier_quality.csv), and shared BBL/BIN
cardinality in [key_cardinality.csv](key_cardinality.csv). Event linkage counts are problem or
violation rows; the complaint source has multiple problem rows per distinct complaint.

## Apartment exposure

The inventory has **381,275** HPD records, **152,361** provisional multifamily
candidates, and **97,663** candidates with the conservative comparison denominator.

| Unit comparison for candidate buildings | Buildings |
| --- | --- |
| agreement | 97,663 |
| not_one_building_to_one_lot | 27,209 |
| disagreement | 26,605 |
| missing_or_zero_pluto_units | 614 |
| no_pluto_match | 270 |

Candidates are current active buildings with at least three HPD apartments, zero reported
Class B rooms, and a known management program other than NYCHA. This is a review flag, not
a final historical rental cohort. Missing or different housing types remain in the database.

**Provisional denominator:** use the positive apartment count only when HPD and PLUTO agree,
PLUTO reports one building, and exactly one active HPD building maps to the lot. Otherwise,
`rate_units` is NULL and both source counts and the disagreement classification are retained.
No lot-level unit count is used as per-building exposure on a multi-building lot.
This strict choice sacrifices coverage;
the final analysis must assess that selection and compare HPD-denominator sensitivity results.
Neither source establishes occupied units or a historical unit-year denominator. Rates are
current-capacity-normalized summaries, not evidence of historical occupancy.

The mutually exclusive [cohort exclusions](cohort_exclusions.csv) explain inventory selection.
[Denominator selection](denominator_selection.csv) shows retention by borough and size;
[property types](cohort_property_types.csv) expose unresolved rental/co-op/condo distinctions.
[Outcome selection](outcome_selection.csv) reports event burden and zero-activity building-years
inside and outside the provisional rate cohort. [Construction exposure](construction_exposure.csv)
counts missing construction years and properties built since the study began. The rate view
excludes years before the recorded construction year, but treats the construction year as a full
year and permits missing construction years. Those assumptions require review before modeling.

## Checks requiring attention

| Check | Severity | Rows or groups |
| --- | --- | --- |
| approval_before_inspection | warning | 400 |
| pluto_bbl_missing_or_invalid | warning | 1 |
| substantial_monthly_change_review | warning | 8 |

See [checks.csv](checks.csv), [date_quality.csv](date_quality.csv), and
[violation_classes.csv](violation_classes.csv). Warnings remain visible; they are not assertions
of misconduct or reasons to delete records automatically.
[Violation date comparisons](violation_date_comparison.csv) quantify timing differences between
inspection, approval, and notice. [Complaint categories](complaint_categories.csv) retain annual
category volumes, duplicate flags, and unknown flags for review of reporting changes.

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
