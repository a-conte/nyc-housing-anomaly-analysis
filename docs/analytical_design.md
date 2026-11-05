# Investigating Unusual Patterns in NYC Housing Complaints and Violations

## Research and analytical design

**Status:** Approved with portfolio-scope adjustments; Phase 2 ETL and data auditing underway.  
**Research date:** November 2, 2026.  
**Intended use:** Portfolio-quality code sample for a Data Scientist position with the Research & Analytics Department of the New York State Attorney General.

### Central investigative question

> Can publicly available NYC housing data identify buildings or property owners exhibiting unusually high rates or persistent patterns of housing complaints and violations relative to comparable properties?

### Recommendation

Use a building-centered investigation with four core datasets: HPD violations, HPD complaints and problems, HPD buildings, and PLUTO. Registration records and contacts may be added later as optional enrichment and must not block the building-level analysis. 311 is not a dependency of the core pipeline.

Use 2021–2025 as a provisional extraction window. Confirm coverage and quality in Phase 2 before fixing analytical assumptions or a holdout period. Treat current violation status as a separate snapshot.

The project should identify properties warranting further investigation, with uncertainty and supporting records. Its findings should concern **unusual recorded housing conditions and enforcement patterns**, not establish owner misconduct.

This document records the analytical design. Phase 2 implements extraction, validation, linkage auditing, and DuckDB loading; modeling follows the data audit.

### Approved scope adjustments

Prioritize interpretability, reproducibility, and interview-ready clarity over publication-grade complexity. Keep buildings primary; retain distinct complaints, useful problem counts, Class B, Class C, combined B/C, and persistence separately. Compare HPD and PLUTO unit counts explicitly. Do not construct a subjective composite bad-landlord score.

The modeling progression is raw counts → per-unit rates → Poisson baseline → Negative Binomial if overdispersion supports it → observed versus expected activity → anomaly identification. Compare raw-count, per-unit, regression-adjusted, and Isolation Forest rankings to answer: **How does our definition of unusual change depending on methodology?** Isolation Forest is a secondary comparison, not a presumed improvement.

Multiple-testing correction is optional and should be added only if it improves interpretation. Simulation-based calibration is optional and requires a diagnostic justification. Keep temporal validation simple; retain 2025 as a potential holdout if coverage supports it. Ranking stability and defensibility are the primary validation goals.

Use substantive DuckDB SQL for aggregation, property metrics, temporal and rolling features, peer comparisons, and window functions. Prefer a few readable Python modules and SQL files, focused tests, 1–2 polished notebooks, and a strong README; avoid unnecessary infrastructure.

## 1. What was inspected

The research inspected official API schemas, sample records, aggregate queries, and actual joins on November 2, 2026. Field names below are actual API field names, not inferred names. The inspection was targeted research, not a complete ingestion or data-quality audit. Some broad aggregate queries timed out; smaller queries were used where practical.

The schemas were inspected through each dataset's `/api/views/{dataset_id}.json` endpoint, and records and aggregate queries through `/resource/{dataset_id}.json`.

These findings materially affect the design:

| Inspection finding | Implication |
| --- | --- |
| In 2025, HPD recorded **856,280 problem rows representing 532,962 distinct complaint IDs**. | Counting rows would overstate the number of complaints. |
| **21.85%** of those problem rows lacked a 311 `unique_key`; **17.45%** had `problem_duplicate_flag = 'Y'`. | Retain HPD records without 311 matches; distinguish reporting volume from repeated conditions. |
| The building file contained **381,275 rows and 381,275 distinct `buildingid` values**. | HPD BuildingID is a strong primary identifier. |
| Registrations contained **204,856 rows, 195,186 distinct registration IDs, and 204,779 distinct building IDs**. | Neither registration ID nor building ID is unique in that table. |
| A deterministic 100-problem sample from January 2025 represented 85 complaints, 100 311 requests, 70 buildings, and 69 BBLs. All building and PLUTO links resolved, but four buildings lacked registration matches. | Complaint IDs, service requests, buildings, and lots are different units. These sample results are not citywide match-rate estimates. |
| HPD and PLUTO apartment counts disagreed for some sampled single-building lots. | Denominator source and disagreements must be documented and tested. |

These measurements came from the official [complaints API](https://data.cityofnewyork.us/resource/ygpa-z7cr.json), [buildings API](https://data.cityofnewyork.us/resource/kj4p-ruqc.json), [registrations API](https://data.cityofnewyork.us/resource/tesw-yqqr.json), [PLUTO API](https://data.cityofnewyork.us/resource/64uk-42ks.json), and [311 API](https://data.cityofnewyork.us/resource/erm2-nwe9.json). Counts describe the inspected live snapshot and may change as agencies revise records.

## 2. Dataset inventory

### 2.1 HPD Housing Maintenance Code Violations

**Role:** Core dataset.

- Official source: [NYC Open Data dataset — `wvxf-dwi5`](https://data.cityofnewyork.us/d/wvxf-dwi5)
- API: [JSON records](https://data.cityofnewyork.us/resource/wvxf-dwi5.json)
- Schema: [Official metadata and columns](https://data.cityofnewyork.us/api/views/wvxf-dwi5.json)

**Unit of observation:** One violation, identified by `violationid`.

**Relevant fields:**

| Purpose | Actual API fields |
| --- | --- |
| Identifiers and geography | `violationid`, `buildingid`, `registrationid`, `boroid`, `block`, `lot`, `bin`, `bbl` |
| Severity and condition | `class`, `ordernumber`, `novdescription`, `apartment` |
| Event dates | `inspectiondate`, `approveddate`, `novissueddate` |
| Current status | `violationstatus`, `currentstatus`, `currentstatusid`, `currentstatusdate` |
| Correction and certification | `originalcorrectbydate`, `newcorrectbydate`, `originalcertifybydate`, `newcertifybydate`, `certifieddate` |

**Potential join keys:** Primarily `buildingid`; BBL and BIN for checks and property enrichment. `registrationid` needs a separate, audited relationship table.

**Data-quality and interpretation concerns:**

- Class I represents information orders and should not enter the hazardous-condition outcome. Class A is non-hazardous, Class B hazardous, and Class C immediately hazardous.
- The historical base comprises violations open on October 1, 2012, with subsequent violations added. It is not a complete history of all violations before that date.
- Current status is mutable; the file does not provide a complete status-transition history.
- Multiple violations can arise from one inspection.
- An open record does not necessarily mean the physical condition remains uncorrected.
- Observation, approval, and notice dates describe different events. The analysis must specify which date defines each metric.

**Contribution:** Principal evidence of recorded hazardous conditions: separate Class B and C rates, repeated condition categories, and current open-violation burden. See [HPD's official dataset documentation](https://www.nyc.gov/site/hpd/about/open-data.page).

### 2.2 HPD Housing Maintenance Code Complaints and Problems

**Role:** Core dataset.

- Official source: [NYC Open Data dataset — `ygpa-z7cr`](https://data.cityofnewyork.us/d/ygpa-z7cr)
- API: [JSON records](https://data.cityofnewyork.us/resource/ygpa-z7cr.json)
- Schema: [Official metadata and columns](https://data.cityofnewyork.us/api/views/ygpa-z7cr.json)

**Unit of observation:** One reported problem, identified by `problem_id`, associated with `complaint_id`.

**Relevant fields:**

| Purpose | Actual API fields |
| --- | --- |
| Identifiers and geography | `problem_id`, `complaint_id`, `building_id`, `borough`, `block`, `lot`, `bin`, `bbl`, `unique_key` |
| Receipt date | `received_date` |
| Location within building | `apartment`, `unit_type`, `space_type` |
| Problem classification | `type`, `major_category`, `minor_category`, `problem_code` |
| Administrative status | `complaint_status`, `complaint_status_date`, `problem_status`, `problem_status_date`, `status_description` |
| Flags | `problem_duplicate_flag`, `complaint_anonymous_flag` |

**Potential join keys:** `building_id` to HPD buildings; `unique_key` to 311. A complaint can contain multiple problems and multiple 311 request keys.

**Data-quality and interpretation concerns:**

- Duplicate flags can represent repeated reports about a shared condition, not erroneous duplicate rows.
- Closed complaints do not necessarily establish repair. Inspected examples included closure after inability to obtain access.
- Category definitions, reporting practices, and missing 311 linkage require temporal checks.
- A non-null building identifier does not, by itself, establish that the identifier is valid or resolves to the reference table.
- Distinct complaint counts, problem counts, and reporting-day counts measure different things.

**Contribution:** Complaint burden, issue-specific recurrence, and reporting patterns. This is the primary complaint source; unmatched 311 records must not determine whether a complaint is retained.

### 2.3 Buildings Subject to HPD Jurisdiction

**Role:** Core dataset and building reference table.

- Official source: [NYC Open Data dataset — `kj4p-ruqc`](https://data.cityofnewyork.us/d/kj4p-ruqc)
- API: [JSON records](https://data.cityofnewyork.us/resource/kj4p-ruqc.json)
- Schema: [Official metadata and columns](https://data.cityofnewyork.us/api/views/kj4p-ruqc.json)

**Unit of observation:** One HPD building record, keyed by `buildingid`.

**Relevant fields:**

| Purpose | Actual API fields |
| --- | --- |
| Identifiers and geography | `buildingid`, `boroid`, `block`, `lot`, `bin`, `communityboard` |
| Building characteristics | `dobbuildingclass`, `legalstories`, `legalclassa`, `legalclassb` |
| Management and registration | `managementprogram`, `registrationid` |
| Record and building lifecycle | `lifecycle`, `recordstatus` |

**Potential join keys:** `buildingid`, BIN, and a BBL constructed from borough, block, and lot. **This dataset does not have a standalone `bbl` field.**

**Data-quality and interpretation concerns:**

- The file contains inactive records, demolished buildings, land, and placeholder identifiers.
- `legalclassa` counts apartments; `legalclassb` counts rooms without individual baths and kitchens. They should not be added as interchangeable housing units.
- These building-unit classes are distinct from violation severity classes.
- Current attributes do not establish historical occupancy or unit counts.
- Coverage reflects HPD jurisdiction and administrative activity. It is not an unrestricted census of all NYC housing.

**Contribution:** Building linkage, apartment denominator, building classification, and identification of eligible properties with zero recorded events.

### 2.4 Primary Land Use Tax Lot Output — PLUTO

**Role:** Core property-characteristics dataset.

- Official source: [NYC Open Data dataset — `64uk-42ks`](https://data.cityofnewyork.us/d/64uk-42ks)
- API: [JSON records](https://data.cityofnewyork.us/resource/64uk-42ks.json)
- Schema: [Official metadata and columns](https://data.cityofnewyork.us/api/views/64uk-42ks.json)
- Documentation: [Official data dictionary](https://s-media.nyc.gov/agencies/dcp/assets/files/pdf/data-tools/bytes/pluto_datadictionary.pdf)
- Historical releases: [DCP PLUTO resources](https://www.nyc.gov/content/planning/pages/resources/datasets/mappluto-pluto-change)

**Unit of observation:** One tax-lot record. The inspected release was **26v2**, with 858,284 distinct BBLs.

**Relevant fields:**

| Purpose | Actual API fields |
| --- | --- |
| Identifiers | `bbl`, `borough`, `block`, `lot`, `borocode`, `condono` |
| Units and structures | `unitsres`, `unitstotal`, `numbldgs`, `numfloors` |
| Construction and alteration | `yearbuilt`, `yearalter1`, `yearalter2` |
| Property use and area | `bldgclass`, `landuse`, `resarea`, `bldgarea` |
| Geography | `cd`, `bct2020` |
| Ownership context | `ownertype`, `ownername` |
| Release identification | `version` |

**Potential join key:** BBL.

**Data-quality and interpretation concerns:**

- `unitsres` sums residential units across the entire lot; `numfloors` describes the tallest building.
- Condominium billing lots complicate matching.
- Year built can be approximate, and zero means unknown.
- HPD and PLUTO unit counts can disagree even on single-building lots.
- `ownername` is corroborating information, not a reliable identifier of ultimate ownership.
- Historical releases are available, but their individual schemas still require inspection before use. Only the current 26v2 schema and sample records were inspected in this phase.

**Contribution:** Property age, size, use, neighborhood, and denominator validation. Historical releases can help evaluate changes in the property stock and reduce reliance on present-day attributes.

### 2.5 Multiple Dwelling Registrations

**Role:** Secondary ownership layer.

- Official source: [NYC Open Data dataset — `tesw-yqqr`](https://data.cityofnewyork.us/d/tesw-yqqr)
- API: [JSON records](https://data.cityofnewyork.us/resource/tesw-yqqr.json)
- Schema: [Official metadata and columns](https://data.cityofnewyork.us/api/views/tesw-yqqr.json)

**Unit of observation:** A published building–registration association. The observed repetitions rule out treating each row as a uniquely identified registration.

**Relevant fields:** `registrationid`, `buildingid`, `boroid`, `block`, `lot`, `bin`, `lastregistrationdate`, `registrationenddate`.

**Potential join keys:** `buildingid` to buildings; `registrationid` to contacts.

**Data-quality and interpretation concerns:**

- Some registration IDs span many buildings; some buildings have multiple registration records.
- `lastregistrationdate` is the processing date, not an ownership acquisition date.
- Missing or expired records do not establish ownership history.
- Deduplicating on registration ID alone would discard legitimate building associations.

**Contribution:** Connect buildings to registered parties and describe registration coverage. Missing registration matches must not remove buildings from the core analysis.

### 2.6 Registration Contacts

**Role:** Secondary ownership and management layer.

- Official source: [NYC Open Data dataset — `feu5-w2e2`](https://data.cityofnewyork.us/d/feu5-w2e2)
- API: [JSON records](https://data.cityofnewyork.us/resource/feu5-w2e2.json)
- Schema: [Official metadata and columns](https://data.cityofnewyork.us/api/views/feu5-w2e2.json)

**Unit of observation:** One contact record associated with a registration, identified by `registrationcontactid`.

**Relevant fields:**

| Purpose | Actual API fields |
| --- | --- |
| Identifiers and role | `registrationcontactid`, `registrationid`, `type`, `contactdescription` |
| Organization and person names | `corporationname`, `firstname`, `middleinitial`, `lastname`, `title` |
| Business address | `businesshousenumber`, `businessstreetname`, `businessapartment`, `businesscity`, `businessstate`, `businesszip` |

**Potential join key:** `registrationid`.

**Data-quality and interpretation concerns:**

- Actual role values include `CorporateOwner`, `IndividualOwner`, `JointOwner`, `Agent`, `HeadOfficer`, and others.
- A contact ID identifies a record, not necessarily a unique person or company.
- Names vary, addresses may be shared by unrelated entities, and managing agents are not necessarily owners.
- These records cannot reveal ultimate beneficial ownership reliably.

**Contribution:** Conservative registered-owner groups and a separate management network. Preserve role distinctions and match confidence.

### 2.7 311 Service Requests from 2020 to Present

**Role:** Optional enrichment.

- Official source: [NYC Open Data dataset — `erm2-nwe9`](https://data.cityofnewyork.us/d/erm2-nwe9)
- API: [JSON records](https://data.cityofnewyork.us/resource/erm2-nwe9.json)
- Schema: [Official metadata and columns](https://data.cityofnewyork.us/api/views/erm2-nwe9.json)
- Dataset changes: [Official NYC Open Data notice](https://www.nyc.gov/opendata/news/all-news/311-Service-Requests-Updates)

**Unit of observation:** One service request, identified by `unique_key`.

**Relevant fields:** `unique_key`, `created_date`, `closed_date`, `agency`, `complaint_type`, `descriptor`, `descriptor_2`, `status`, `resolution_description`, `resolution_action_updated_date`, `open_data_channel_type`, `bbl`, `borough`, `incident_address`.

**Potential join key:** HPD problem `unique_key` to 311 `unique_key`. Filter to `agency = 'HPD'`.

**Data-quality and interpretation concerns:**

- Missing linkage, changing categories, administrative closure, and inconsistent geography.
- The inspected schema has no HPD BuildingID or BIN.
- The familiar `erm2-nwe9` dataset now covers 2020 onward; older records moved to a separate archive.
- Display labels changed, but API names such as `complaint_type` remained.

**Contribution:** Reporting channel and service-request context. Do not append these records to HPD complaints and count both.

## 3. Final dataset selection and analytical population

### Dataset selection

| Layer | Datasets | Purpose |
| --- | --- | --- |
| Required core | HPD violations; HPD complaints/problems; HPD buildings; PLUTO | Building-level burden, comparisons, and persistence |
| Optional, later | Multiple Dwelling Registrations; Registration Contacts | Registered-owner and management associations; not a completion dependency |
| Optional | HPD-related 311 service requests | Reporting-channel and administrative context |

### Population and unit of analysis

The initial analytical population should be **conventional multifamily apartment buildings under HPD jurisdiction, with at least three documented apartments and a usable exposure denominator**.

Analyze NYCHA, rooming/SRO properties, and other materially different housing types separately. HPD describes a different inspection pathway for NYCHA properties, making direct pooling problematic. See the [official enforcement process](https://www.nyc.gov/site/hpd/services-and-information/code-enforcement.page).

Use **HPD BuildingID** as the primary identifier. Build a **building-month panel**, with annual summaries for reporting and persistence. Use BBL as the property linkage and a secondary aggregation level; use BIN to validate physical-building relationships. Owner groups are a later aggregation, not the foundational analytical unit.

### Time window and exposure

Use **January 2021–December 2025 provisionally**, controlled by configuration. Observations were verified in each year during research, but monthly completeness, linkage, and date quality must be audited before settling the analytical window. Exclude partial years from full-year comparisons. A sensitivity analysis excluding 2021 may assess pandemic-era effects.

The cohort must include eligible buildings with **zero recorded complaints or violations**. Zero should mean no matching event within a verified data window, not missing source data.

Current building eligibility creates survivorship concerns. Historical PLUTO releases should help identify construction, demolition, conversion, and unit-count changes. Where historical exposure cannot be supported, label the analysis as historical outcomes for the current building stock and test a stable-property subset.

Current HPD unit counts remain an imperfect proxy for historical capacity. Historical PLUTO does not automatically solve that problem, especially on multi-building lots. Exposure assumptions and exclusions must be explicit.

## 4. Joining and entity resolution

### Join plan

| Relationship | Keys | Required treatment |
| --- | --- | --- |
| Problems → buildings | `building_id = buildingid` | Many-to-one; retain unmatched records in an audit table. |
| Violations → buildings | `buildingid` | Many-to-one; aggregate independently from complaints. |
| Buildings → PLUTO | Constructed BBL → `bbl` | Multiple buildings may share a lot. |
| Problems → 311 | `unique_key` | Check uniqueness and coverage; retain unmatched problems. |
| Buildings → registrations | `buildingid` | Preserve an explicit relationship table. |
| Registrations → contacts | `registrationid` | One-to-many/many-to-many in the resulting building network. |

Construct BBL as the borough digit, five-digit block, and four-digit lot. Normalize identifiers as strings, handling numeric representations such as PLUTO's decimal-formatted BBLs. Validate boroughs, placeholders, and conflicting identifiers before joining.

**Aggregate complaints and violations separately before combining their building-month summaries.** Joining raw event tables on building would create a many-to-many multiplication.

Do not assign an entire lot's `unitsres` to each building. Prefer validated HPD apartment counts for building rates; use PLUTO denominators directly only where the building–lot relationship supports them. Report denominator disagreements and sensitivity to source choice.

There is **no direct complaint-to-violation identifier in the inspected violation schema**. Temporal and category proximity can support an explicitly approximate association, but cannot establish which complaint produced which violation.

### Owner and manager resolution

Begin with exact, conservative matches of normalized owner names and complete business addresses. Keep managing-agent links separate, prohibit address-only merges, and manually review consequential matches.

Preserve the original contact records, registration associations, role, normalized values, matching rule, and confidence for every derived group. Do not equate a registration ID or a connected component of shared contacts with a verified legal owner.

Historical building events associated with a currently registered owner must be labeled as such; they cannot automatically be attributed to that owner's tenure.

## 5. Investigative hypotheses

1. **Excess hazardous-condition burden:** Some buildings have more Class B/C violations than comparable properties after accounting for size, age, building type, location, and time.
2. **Persistent or recurring problems:** Some buildings repeatedly exceed expectations across years or repeatedly receive reports in the same condition category.
3. **Concentration across registered-owner groups:** Some conservatively linked portfolios contain multiple buildings with elevated adjusted burdens, beyond one unusually large or problematic property.

An exploratory fourth question is whether high complaint burden coexists with low recorded violation burden. Such a discrepancy could reflect access problems, reporting patterns, resolution before inspection, or enforcement differences. It does not establish false complaints or adequate conditions.

## 6. Candidate metrics

Metrics should remain separately interpretable.

| Metric | Definition and interpretation |
| --- | --- |
| Complaint rate | Distinct `complaint_id` per 100 apartment-years. |
| Problem rate | Distinct `problem_id` per 100 apartment-years, overall and by category. |
| Reporting recurrence | Distinct building–category reporting days/months; reduces domination by same-day bursts. |
| Hazardous violation rate | Distinct Class B and Class C violations per 100 apartment-years, reported separately and combined. |
| Adjusted excess | Observed minus model-expected events, alongside observed/expected ratio. |
| Persistence | Number of years with elevated adjusted burden; repeat-category months and consecutive elevated periods. |
| Current backlog | Open B/C violations at extraction, with age since observation; an administrative-status measure. |
| Portfolio burden | Sum of observed events divided by sum of expected events across unique linked buildings. |

**Apartment-years** means documented apartments multiplied by supported observation time. It is a housing-capacity denominator, not occupied apartments or residents.

Retain duplicate-flagged reports in the reporting-volume measure. Run sensitivity analyses excluding flagged problems and collapsing reports into building–category–day or week episodes. Those episodes are analytical approximations, not verified unique physical defects.

Use `received_date` for complaint timing. For violations, distinguish observation (`inspectiondate`), approval (`approveddate`), and notice issuance (`novissueddate`); document the chosen primary date and check sensitivity to alternatives. Missing or inconsistent dates must be audited before finalizing event definitions.

Current backlog measures must use the extraction date explicitly. Do not infer historical monthly open inventories from today's status alone.

## 7. Statistical modeling strategy

### Primary models

Start with raw counts and per-unit rates, then a **Poisson baseline**. Add **negative-binomial count regression only if overdispersion and diagnostics support it**. Model complaint counts and hazardous violation counts separately. Use Class C as a particularly consequential secondary outcome.

A monthly specification would be:

$$
\log E[Y_{it}]
=
\log(\text{apartment-month exposure}_{it})
+f(\text{building age})
+g(\text{building size})
+\text{building type}
+\text{stories}
+\text{geography}
+\text{calendar effects}.
$$

Calendar effects should capture seasonality and changes in citywide recording/enforcement. Geography can use community district, with a borough-only sensitivity model. Size can enter both the exposure offset and a flexible adjustment to test whether counts actually scale proportionally with apartments.

The principal peer model should exclude building and owner identifiers as predictors. Otherwise, it could learn that a persistently problematic building is normally problematic and absorb the signal under investigation.

Contemporary complaint counts should not be a primary control in the violation model: they partly determine inspection activity. A conditional model can be a separately interpreted sensitivity analysis.

### Diagnostics

Assess:

- Overdispersion and comparison with the Poisson baseline.
- Residual patterns and influential observations.
- Calibration and predictive interval coverage.
- Performance by borough, building size, and building type.
- Sensitivity to denominator source, cohort definition, and geographic adjustment.

Do not add zero inflation automatically. Investigate whether excess zeros arise from population definition, exposure, or the reporting process.

### Validation

- Keep 2025 as a potential temporal holdout if Phase 2 confirms adequate coverage; avoid a rigid train/tune/test framework before that audit.
- Prioritize ranking stability across years, denominator choices, and methods. Source coverage checks are distinct from model or threshold selection.
- Use grouped building/BBL validation if estimating generalization to other properties requires it.
- Evaluate calibration and stability by borough, size, and building type.
- Compare raw-count, per-unit, regression-adjusted, and Isolation Forest rankings; explain disagreements rather than assuming one method is superior.

Because live records and current property attributes are revised retrospectively, this is **retrospective validation**, not a perfect reconstruction of what an investigator could have known at an earlier date. Historical model evaluation must not use later status or ownership information as though it had been available earlier.

## 8. Anomaly-detection strategy

Use the statistical model as the primary method:

1. Estimate expected counts and predictive uncertainty for comparable buildings.
2. Calculate upper-tail probabilities, adjusted excess counts, and relative burden.
3. Check calibration and uncertainty with straightforward diagnostics. Add simulation-based calibration only if a demonstrated diagnostic problem requires it.
4. Treat multiple-testing correction, including Benjamini–Yekutieli FDR, as optional. Add it only if it materially improves interpretation; otherwise describe exploratory rankings without formal significance claims.
5. Require practical importance and examine persistence, rather than ranking solely by statistical extremeness.

Candidate practical thresholds could include a twofold expected rate and a minimum excess event count. Select any thresholds transparently and freeze them before evaluating a supported temporal holdout. Unstable small-building rates need uncertainty intervals and, where appropriate, shrinkage.

If calibration is inadequate, present exploratory priority scores without calling buildings statistically significant outliers. Retain Isolation Forest as a secondary comparison on documented features. The final project must compare its rankings with raw-count, per-unit, and regression-adjusted rankings, but it should not drive the principal findings or be treated as automatically superior.

Each flagged property should have a compact evidence record containing:

- Observed and expected counts.
- Denominator provenance and uncertainty.
- Complaint and violation time series.
- Relevant condition categories and recurrence.
- Join-quality and entity-resolution flags.
- Links to source records.

Complaint and violation agreement is useful corroboration, although the two processes are not independent.

## 9. Limitations and confounders

| Limitation | Consequence |
| --- | --- |
| Unequal reporting propensity | Recorded complaints cannot measure all underlying housing problems. Language, access, fear, and tenant organization may affect reporting. |
| Selective inspections | Violation counts reflect both conditions and opportunities to observe them; the core files do not supply a complete inspection denominator. |
| Administrative closure | Complaint closure, certification, and violation closure are not interchangeable measures of physical repair. |
| Current snapshots | Historical statuses, ownership, building characteristics, and exposure may be incompletely reconstructable. |
| Property changes | Demolition, vacancy, construction, conversion, and parcel changes affect comparability and exposure. |
| Unmeasured housing differences | Occupancy, rent regulation, renovations, subsidized housing, and weather can influence outcomes. |
| Geographic adjustment | Local comparisons can normalize widespread poor conditions; publish both local and broader benchmarks. |
| Owner linkage uncertainty | LLC structures, shared agents, stale records, and ownership changes limit attribution. |
| Repeated records and conditions | Neither a complaint nor a violation necessarily represents an independent defect or affected household. |
| No definitive anomaly labels | Future persistence and record review evaluate usefulness, not the accuracy of a wrongdoing classifier. |

Defer repair-time survival analysis: the inspected current-status fields do not establish a complete sequence of correction and reopening events.

Avoid an overall bad-landlord score that hides severity, persistence, and attribution uncertainty inside arbitrary weights.

## 10. Proposed repository architecture

Prefer a compact structure with substantive SQL rather than a large framework:

```text
nyc-housing-data/
├── README.md
├── pyproject.toml
├── uv.lock
├── config.toml
├── housing/                 # A few readable Python modules
├── sql/                     # Staging, linkage, aggregation, and audit queries
├── tests/                   # Focused ETL and analytical-contract tests
├── docs/
│   └── analytical_design.md
├── reports/phase2/          # Aggregate audit outputs and findings
├── notebooks/              # 1–2 polished notebooks in the final project
└── data/                   # Ignored raw snapshots and local DuckDB database
```

Use local Python and DuckDB. Source manifests preserve extraction times, exact queries, metadata, release versions, checksums, and row counts. Python orchestrates acquisition and validation; SQL owns meaningful feature transformations. No notebook or modeling framework is required to complete Phase 2.

## 11. Intended deliverables and review decisions

The strongest submission would deliver:

- A reproducible investigation with documented source snapshots and data-quality checks.
- A transparent comparison model with meaningful baselines and validation.
- Building-level evidence records showing why particular properties were flagged.
- A short investigative memo explaining findings, uncertainty, and sensitivity to alternative assumptions.
- A secondary registered-owner analysis where linkage is sufficiently reliable.

**Building-level findings should be the principal result; owner-level conclusions should remain conditional on verified linkage and ownership timing.**

The design is approved with the scope adjustments above. Phase 2 must confirm source coverage, date quality, join cardinality, unmatched records, and denominator disagreement before finalizing the cohort and study window. Owner enrichment must not block completion. Historical PLUTO enrichment and additional statistical complexity are optional, justified additions.
