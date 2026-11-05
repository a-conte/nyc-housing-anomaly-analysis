# Phase 2 data-quality review — November 5, 2026

**Phase 2 is complete.** The verified snapshot is loaded into `data/housing.duckdb`.
All **17 blocking database checks pass**. No Phase 3 modeling or analytical notebooks were
started. The findings below distinguish resolved ingestion problems from decisions still
required before finalizing an analytical cohort, exposure denominator, or holdout period.

## Snapshot and database verification

All 14 expected partitions passed selection/schema checks, SHA-256 and byte-count checks,
full gzip decompression, and reconciliation of source-before, source-after, page, and loaded
row counts. The two undated extracts are valid header-only files with zero records.

Twelve original files from November 2 were reused. Only two files failed verification and
were downloaded again on November 5:

- **Violations, 2021:** the compressed file did not match its recorded SHA-256, although it
  decompressed. The replacement reconciled to 768,978 rows.
- **Complaints, 2023:** the saved checksum matched, but full decompression found an invalid
  gzip stream. The replacement reconciled to 747,466 rows. This demonstrates why a matching
  checksum alone is insufficient to establish that an originally saved file was valid.

Original files, manifests, run records, replacement metadata, and repair records are retained
under `data/snapshot/repairs/`. [Provenance](provenance.json) records both repairs, extraction
times, hashes, configuration, Python/DuckDB versions, code hashes, and metadata hashes.
This is explicitly a **mixed extraction-date snapshot**. Unchanged counts do not exclude
in-place changes to current statuses. No update timestamp changed within the recorded
extraction intervals; that does not make the live API a transactional snapshot.

| Loaded source | Raw rows | Grain |
| --- | ---: | --- |
| HPD complaints/problems | 3,777,889 | Problem; 2,301,197 distinct complaints |
| HPD violations | 4,422,541 | Violation |
| HPD buildings | 381,275 | HPD BuildingID |
| PLUTO, release 26v2 | 858,284 | Source tax-lot record; one invalid BBL |
| **Total** | **9,439,989** | |

Raw/clean event counts and independent monthly aggregates reconcile. Joined panels contain
exactly the matched event totals, without fan-out. The annual panel has 381,275 records in
each year, each with 12 calendar months. B/C counts equal B plus C.

The published database was reopened read-only. The rolling view returned 60 sample months,
11 initial incomplete windows and 49 full windows; the peer view evaluated successfully for
486,389 provisional rate building-years. [Database integrity evidence](database_integrity.json)
contains the database file hash, queries, and results. [Snapshot verification](snapshot_verification.csv),
[row reconciliation](row_reconciliation.csv), and [checks](checks.csv) provide detailed evidence.

## Coverage, event definitions, and dates

Both event sources have records in all **60 months of 2021–2025**, including every month of
2025. Annual extracts have no missing/invalid primary dates, wrong-year records, missing event
IDs, or inconsistent complaint-to-building/month assignments. This supports retaining the
provisional extraction window; it does not establish complete reporting or fix a modeling split.

There are **eight monthly volume warnings, all in violations**. Separating classes materially
changes their interpretation: the flagged months have total year-over-year ratios of
0.223–3.646, while their B/C ratios range from 0.915 to 1.448. Class A and I fluctuations
account for much of the extreme total-volume movement. For example, April 2022 total
violations fell to 22.3% of April 2021, while B/C increased by 2.9%.
This comparison does not establish the administrative cause of the shifts or prove complete
coverage. See [monthly change review](monthly_change_review.csv) before interpreting trends.

The study contains **1,653,257 Class B** and **1,205,026 Class C** violations, for
**2,858,283 B/C** outcomes. The 423,942 Class I records remain separate; all severity labels
are recognized. Complaints are counted distinctly from their problem rows. The **591,655
duplicate-flagged problems** remain in reporting-volume measures and are not treated as
erroneous duplicate records. Major categories are populated and duplicate flags are recognized.

**400 violations have approval dates one day before inspection**, all in November 2024.
They remain flagged; dates are not silently corrected. There are 424,694 missing notice dates:
423,942 Class I records and 752 A/B/C records. Approval and inspection fall in different years
for 39,274 records; notice and inspection differ in year for 71,715 records. Inspection remains
the primary violation date, with sensitivity to alternatives unresolved. See
[date quality](date_quality.csv), [date comparisons](violation_date_comparison.csv), and
[the supplemental review queries](review_queries.json).

Current statuses cannot reconstruct historical closure or repair. This five-year event extract
also cannot establish the complete current backlog, which could include older or newer events.

## Linkage and identifier quality

| Event source | No BuildingID match | Reported BBL conflicts with HPD | BIN conflicts with HPD |
| --- | ---: | ---: | ---: |
| Problem rows | 370 (0.0098%) | 15,023 | 17,988 |
| Violations | 220 (0.0050%) | 20,324 | 19,956 |

These are event-row counts, and conflict columns overlap. Every event has a normalized
BuildingID, so unmatched means an ID absent from the current reference inventory. Unmatched
events remain in clean tables and `audit.event_links`; they do not enter the inventory panel.
There are 146 unmatched B/C violations. BBL/BIN conflicts remain flags rather than rematching
events away from their HPD BuildingID. Reported-versus-component BBL disagreements and
component-versus-reference conflicts are separately recorded in [linkage_summary.csv](linkage_summary.csv).

Of the HPD inventory, **15,971 records lack a PLUTO match**. Among active HPD buildings,
5,047 BBLs are shared by 21,953 records; 774 BINs are shared by 1,895 records. These keys
cannot be assumed to identify one building. Shared active BINs affect 917 multifamily
candidates, including **146 with a provisional denominator**. Review these ambiguous physical
building relationships before treating BuildingID counts as independently resolved properties.
See [key cardinality](key_cardinality.csv) and [building linkage](building_linkage.csv).

The PLUTO row with source BBL `2000008900.00000000` has block `0`, so its normalized BBL
is NULL. It is preserved in both raw and clean data and exposed in `audit.pluto_unjoinable`;
it cannot supply a property join or denominator. The original uniqueness check incorrectly
counted this unjoinable NULL as a duplicate. It now warns separately about invalid/missing
PLUTO keys and still blocks duplicate **joinable** keys. Regression tests cover both cases.
No valid PLUTO BBL is duplicated.

## Denominator and cohort decisions still required

The current inventory screen identifies **152,361 provisional multifamily candidates**.
Only **97,663 (64.10%)** have agreeing HPD/PLUTO units on an unambiguous single-building lot.
The remaining **54,698 (35.90%)** have no provisional rate denominator:

| Reason | Candidate buildings |
| --- | ---: |
| Not one building to one lot | 27,209 |
| HPD/PLUTO unit disagreement | 26,605 |
| Missing or zero PLUTO units | 614 |
| No PLUTO match | 270 |

This restriction is selective: retention is **67.72% for 3–9 apartments**, **59.03% for
10–49**, and **42.24% for 50+**. Borough retention ranges from **33.80% in Staten Island**
to **69.68% in Brooklyn**. The rate cohort contains 1,500,601 B/C violations versus
2,858,283 across all source events. These coverage differences must be considered before
comparing rankings or generalizing rate results. Do not assign a whole lot's residential
units to every building or silently choose between disagreeing counts. Preserve both counts
and decide the HPD-denominator sensitivity policy before analysis. See
[unit comparison](unit_comparison.csv), [denominator selection](denominator_selection.csv),
and [outcome selection](outcome_selection.csv).

The screen requires an active current building, at least three HPD apartments, zero reported
Class B rooms, and a known non-NYCHA management program. It **does not establish rental
tenure or fully resolve conventional apartments versus other property types**. The ordered
[cohort exclusions](cohort_exclusions.csv) sum to the inventory, and
[candidate property types](cohort_property_types.csv) are available for that decision.

Current capacity and building status do not establish historical exposure. Among the 97,663
denominator-eligible buildings, **119 have no construction year** and **1,310 were built in
2021 or later**. The current view excludes 1,926 building-years preceding construction, but
permits missing years and counts the construction year as a full year. That is insufficient
for a finalized apartment-year denominator. Historical unit changes, demolition/conversion,
and survivorship also remain unresolved. Either explicitly study historical events in the
current building stock with defensible exposure restrictions, or establish additional historical
evidence before broader claims. No historical source downloads were added in this phase.

Zero-event records are preserved: the provisional rate subset includes **360,488 building-years
with neither complaints nor B/C violations**. This means no matched recorded activity in those
outcomes, not verified good housing conditions or proven occupancy. Inspection opportunity
and reporting intensity remain unmeasured; there is no complete inspection denominator.

## Completion and remaining boundaries

No technical ingestion or publication blocker remains. Final cohort membership, ambiguous
physical-building links, denominator selection and historical exposure, date sensitivity, and
interpretation of class-specific volume shifts still require decisions **before Phase 3**.
Registration/owner enrichment and 311 are optional and did not block this phase.

Validation: **25 tests passed**, Ruff lint passed, Ruff formatting check passed, and
`git diff --check` passed. Commands and their output are retained in [validation.txt](validation.txt).
