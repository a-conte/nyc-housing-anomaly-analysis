# Phase 3: analytical cohort and SQL features

Completed using the existing frozen inputs; no models or new source downloads.
Reproduce with `python -m housing.phase3` after Phase 2. SQL lives in
`sql/phase3/features.sql`. Rebuilds replace only the analytical schema tables inside a transaction.

## Denominator decision

The Phase 2 missing-denominator fraction (35.9%) is mostly a validation-policy exclusion:
all 152,361 candidates already have positive HPD apartment counts. Agreement retained
97,663 buildings; 26,605 disagree and 27,209 lack comparable building/lot cardinality.
The median signed relative discrepancy among comparable disagreements is +4.55%; see
unit_discrepancies.csv for dispersion, not just the median. Lot totals cannot be assigned
as building exposure. Use HPD apartments as current building capacity, without imputation.
Retain PLUTO counts and agreement_sensitivity for an independently corroborated subset.
This expands coverage but does not establish that HPD is always correct. Extreme discrepancies
need case review in Phase 4. denominator_review.csv quantifies selection jointly by borough,
size, building class and complaint/B-C activity. Phase 2 retention was 67.72% for small
buildings versus 42.24% for 50+ units, so agreement-only analysis is selectively restrictive.

## Eligibility and retained coverage

Rules are ordered; exclusions are mutually exclusive. Step 1 is the full HPD inventory;
step 2 has passed identifier validation, and step 8 has passed every rule:

1. Valid BuildingID, BBL and BIN.
2. Current active building, at least three HPD apartments, zero Class B rooms, known non-NYCHA management.
3. PLUTO match with positive residential units and residential area, corroborating residential use.
4. No BIN shared by multiple active HPD records. Shared lots are retained with HPD denominators.
5. Known construction year strictly before the study start; never use event occurrence as eligibility evidence.
6. No recorded alteration year at or after study start (a conservative history sensitivity restriction).
7. Both event sources present in every study month. A missing month blocks the cohort rather than creating zeros.

| step | retained_buildings | retained_complaints | complaint_percent | retained_violations | violation_percent |
| --- | --- | --- | --- | --- | --- |
| 1 | 381,275 | 2,300,918 | 99.99 | 4,422,321 | 100.00 |
| 2 | 362,445 | 2,292,748 | 99.63 | 4,419,848 | 99.94 |
| 3 | 152,267 | 2,043,252 | 88.79 | 3,955,319 | 89.44 |
| 4 | 150,187 | 2,019,059 | 87.74 | 3,905,828 | 88.32 |
| 5 | 149,284 | 2,011,500 | 87.41 | 3,891,750 | 88.00 |
| 6 | 147,102 | 1,991,920 | 86.56 | 3,871,000 | 87.53 |
| 7 | 145,832 | 1,961,330 | 85.23 | 3,828,752 | 86.57 |
| 8 | 145,832 | 1,961,330 | 85.23 | 3,828,752 | 86.57 |

The final cohort contains **145,832 buildings**, **1,961,330 complaints**, **1,445,019 B**
and **1,089,687 C** violations. **75,106 buildings** have no recorded complaints or B/C
violations across the study. Exclusion totals are in exclusions.csv; rule_coverage.csv includes
all-class violations and source-wide event shares, including events outside the current inventory.
Residential eligibility is a documented capacity proxy, not verified rental tenure; co-ops,
condominiums and mixed-use properties are not silently declared rental buildings.

## Linkage and monthly shifts

No events are rematched using BBL or BIN. Shared active BINs affected 917 candidates,
including 146 with Phase 2 denominators. These physical-building ambiguities are excluded
explicitly. Event geographic conflicts remain attached to BuildingID, counted in conflicting_events,
with clean_linkage_sensitivity available. Geographic changes, errors and lot restructuring
cannot be distinguished from these snapshots. Unmatched events stay in Phase 2 audit tables.

All eight monthly warnings involve violations. Their all-class ratios span 0.223–3.646,
but B/C ratios span 0.915–1.448. Class A/I composition accounts for much of the discrepancy;
this is compatible with administrative batches as well as changes in recorded activity and
is not evidence of a cause. shift_composition.csv adds distinct buildings, order-code diversity
and peak inspection-day counts for each flagged month/class. Compare with
../phase2/monthly_change_review.csv; no months are deleted, adjusted or imputed.
400 approval dates precede inspection; inspection remains the event date. Date sensitivity remains necessary.

## Feature contract and readiness

analytical.features has exactly one row per eligible BuildingID; analytical.annual has one
row per eligible building/year. These contain original characteristics, both unit sources,
selected_units, annual and total distinct complaints and problems, separate B/C counts,
months and years with activity, capacity_unit_years and rates per 100 capacity-unit-years.
Persistence means recorded activity, not statistically elevated activity. Zero means no matched
record within observed source months. No observed events are required for inclusion.

Capacity-unit-years use current HPD units multiplied by complete calendar years. Pre-study
construction and absence of recorded alterations do **not** prove stable units, continuous occupancy,
or historical eligibility. The estimand is historical recorded activity in the current inventory
with conservative history screens, not historical NYC rental housing as a whole.
The mixed November 2/5 extraction dates and mutable statuses remain limitations.

Ready for conditional descriptive modeling, not causal or misconduct conclusions. Phase 4 should
compare HPD and agreement-subset results on explicit common populations, assess large unit
discrepancies and conflict-free subsets, test pandemic/date sensitivity, and begin with a Poisson
baseline and overdispersion diagnostics. Reserve 2025 only after specifying the training design:
the five-year total/persistence fields include 2025 and must never be training predictors for it.
Use annual rows through 2024 to construct training-only features. No Phase 4 work was performed.
