-- Aggregate evidence for the Phase 2 review; no modeling or cohort finalization.
CREATE VIEW audit.pluto_unjoinable AS
SELECT *, 'missing or invalid BBL; excluded from property joins' AS exclusion_reason
FROM raw.pluto WHERE valid_bbl(bbl) IS NULL;

CREATE TABLE audit.identifier_quality AS
SELECT 'complaints' AS source, _partition AS extract_partition, count(*) AS rows,
       count(*) FILTER (WHERE problem_id IS NULL) AS invalid_primary_ids,
       count(*) FILTER (WHERE building_id IS NULL) AS missing_building_ids,
       count(*) FILTER (WHERE reported_bbl IS NULL) AS missing_reported_bbls,
       count(*) FILTER (WHERE component_bbl IS NULL) AS missing_component_bbls,
       count(*) FILTER (WHERE reported_bin IS NULL) AS missing_bins
FROM clean.complaints GROUP BY _partition
UNION ALL
SELECT 'violations', _partition, count(*),
       count(*) FILTER (WHERE violation_id IS NULL),
       count(*) FILTER (WHERE building_id IS NULL),
       count(*) FILTER (WHERE reported_bbl IS NULL),
       count(*) FILTER (WHERE component_bbl IS NULL),
       count(*) FILTER (WHERE reported_bin IS NULL)
FROM clean.violations GROUP BY _partition;

CREATE TABLE audit.building_linkage AS
SELECT borough_id, count(*) AS buildings,
       count(*) FILTER (WHERE bbl IS NULL) AS invalid_bbls,
       count(*) FILTER (WHERE bin IS NULL) AS missing_bins,
       count(*) FILTER (WHERE pluto_matched) AS pluto_matches,
       count(*) FILTER (WHERE NOT pluto_matched) AS pluto_unmatched,
       count(*) FILTER (WHERE candidate_multifamily) AS candidates,
       count(rate_units) AS with_denominator
FROM mart.buildings GROUP BY borough_id;

CREATE TABLE audit.key_cardinality AS
WITH keys AS (
    SELECT 'HPD BBL' AS key_type, bbl AS key, count(*) AS records
    FROM clean.buildings WHERE bbl IS NOT NULL GROUP BY bbl
    UNION ALL
    SELECT 'Active HPD BBL', bbl, count(*) FROM clean.buildings
    WHERE bbl IS NOT NULL AND record_status = 'ACTIVE' AND lifecycle = 'BUILDING' GROUP BY bbl
    UNION ALL
    SELECT 'HPD BIN', bin, count(*) FROM clean.buildings WHERE bin IS NOT NULL GROUP BY bin
    UNION ALL
    SELECT 'Active HPD BIN', bin, count(*) FROM clean.buildings
    WHERE bin IS NOT NULL AND record_status = 'ACTIVE' AND lifecycle = 'BUILDING' GROUP BY bin
    UNION ALL
    SELECT 'PLUTO BBL', bbl, count(*) FROM clean.pluto WHERE bbl IS NOT NULL GROUP BY bbl
)
SELECT key_type, count(*) AS distinct_keys, sum(records) AS records_with_key,
       count(*) FILTER (WHERE records > 1) AS shared_keys,
       coalesce(sum(records) FILTER (WHERE records > 1), 0) AS records_on_shared_keys,
       max(records) AS max_records_per_key
FROM keys GROUP BY key_type;

-- Mutually exclusive, ordered exclusions: counts sum to the full HPD inventory.
CREATE TABLE audit.cohort_exclusions AS
WITH classified AS (
    SELECT *, CASE
        WHEN record_status IS DISTINCT FROM 'ACTIVE' THEN '01 not active'
        WHEN lifecycle IS DISTINCT FROM 'BUILDING' THEN '02 not a current building'
        WHEN hpd_units IS NULL THEN '03 missing or invalid apartment count'
        WHEN hpd_units < 3 THEN '04 fewer than three apartments'
        WHEN hpd_class_b_rooms IS NULL THEN '05 missing or invalid Class B room count'
        WHEN hpd_class_b_rooms > 0 THEN '06 Class B rooms present'
        WHEN management_program IS NULL OR management_program = '' THEN '07 unknown management'
        WHEN management_program = 'NYCHA' THEN '08 NYCHA'
        ELSE '09 provisional multifamily candidate' END AS cohort_reason
    FROM mart.buildings
)
SELECT cohort_reason, count(*) AS buildings, count(rate_units) AS with_denominator
FROM classified GROUP BY cohort_reason;

CREATE TABLE audit.denominator_selection AS
SELECT borough_id,
       CASE WHEN hpd_units < 10 THEN '3-9' WHEN hpd_units < 50 THEN '10-49'
            ELSE '50+' END AS apartment_band,
       count(*) AS candidate_buildings, count(rate_units) AS with_denominator,
       count(*) - count(rate_units) AS withheld,
       round(100.0 * count(rate_units) / count(*), 2) AS retained_percent
FROM mart.buildings WHERE candidate_multifamily GROUP BY borough_id, apartment_band;

CREATE TABLE audit.cohort_property_types AS
SELECT building_class, pluto_building_class, land_use, management_program,
       count(*) AS candidate_buildings, count(rate_units) AS with_denominator
FROM mart.buildings WHERE candidate_multifamily
GROUP BY building_class, pluto_building_class, land_use, management_program;

CREATE TABLE audit.outcome_selection AS
SELECT year, CASE WHEN NOT candidate_multifamily THEN 'not a candidate'
                 WHEN rate_units IS NULL THEN 'candidate: denominator withheld'
                 WHEN predates_construction THEN 'candidate: predates construction'
                 WHEN NOT source_coverage_present THEN 'candidate: incomplete source coverage'
                 ELSE 'provisional rate cohort' END AS cohort,
       count(*) AS building_years,
       count(*) FILTER (WHERE complaints = 0 AND hazardous = 0) AS zero_complaint_and_bc_years,
       sum(complaints) AS complaints, sum(problems) AS problems,
       sum(class_b) AS class_b, sum(class_c) AS class_c, sum(hazardous) AS hazardous
FROM mart.building_year GROUP BY year, cohort;

CREATE TABLE audit.construction_exposure AS
SELECT candidate_multifamily, count(*) AS buildings,
       count(*) FILTER (WHERE year_built IS NULL) AS missing_year_built,
       count(*) FILTER (WHERE year_built >= year(start_date)) AS built_since_study_start,
       count(*) FILTER (WHERE rate_units IS NOT NULL AND year_built IS NULL)
           AS denominator_with_unknown_construction,
       count(*) FILTER (WHERE rate_units IS NOT NULL AND year_built >= year(start_date))
           AS denominator_built_since_study_start
FROM mart.buildings CROSS JOIN run_config GROUP BY candidate_multifamily;

CREATE TABLE audit.complaint_categories AS
SELECT year(event_month) AS year, major_category, count(*) AS problems,
       count(DISTINCT complaint_id) AS complaints,
       count(*) FILTER (WHERE duplicate_flag = 'Y') AS duplicate_flagged_problems,
       count(*) FILTER (WHERE duplicate_flag IS NULL OR duplicate_flag NOT IN ('Y', 'N'))
           AS unknown_duplicate_flag
FROM clean.complaints WHERE in_study GROUP BY year(event_month), major_category;

CREATE TABLE audit.violation_date_comparison AS
SELECT _partition AS extract_partition, count(*) AS violations,
       count(*) FILTER (WHERE approved_at IS NULL) AS missing_approval_date,
       count(*) FILTER (WHERE notice_issued_at IS NULL) AS missing_notice_date,
       count(*) FILTER (WHERE year(approved_at) <> year(inspected_at)) AS approval_in_different_year,
       count(*) FILTER (WHERE year(notice_issued_at) <> year(inspected_at)) AS notice_in_different_year,
       median(date_diff('day', inspected_at, approved_at)) AS median_days_to_approval,
       median(date_diff('day', inspected_at, notice_issued_at)) AS median_days_to_notice
FROM clean.violations GROUP BY _partition;

CREATE TABLE audit.row_reconciliation AS
SELECT 'complaints' AS source, (SELECT count(*) FROM raw.complaints) AS raw_rows,
       count(*) AS clean_rows, count(*) FILTER (WHERE in_study) AS study_rows,
       (SELECT sum(problems) FROM mart.complaints_monthly) AS aggregated_study_rows,
       'problems' AS panel_measure,
       (SELECT count(*) FROM audit.event_links WHERE source = 'complaints'
        AND in_study AND building_matched) AS matched_panel_events,
       (SELECT sum(problems) FROM mart.building_year) AS panel_events
FROM clean.complaints
UNION ALL
SELECT 'violations', (SELECT count(*) FROM raw.violations), count(*),
       count(*) FILTER (WHERE in_study),
       (SELECT sum(violations_all_classes) FROM mart.violations_monthly),
       'Class B/C violations',
       (SELECT count(*) FROM audit.event_links WHERE source = 'violations'
        AND in_study AND building_matched AND event_id IN
            (SELECT violation_id FROM clean.violations WHERE violation_class IN ('B', 'C'))),
       (SELECT sum(hazardous) FROM mart.building_year)
FROM clean.violations;

INSERT INTO audit.checks
SELECT 'raw_clean_event_counts_preserved', 'error', sum(abs(raw_rows - clean_rows))
FROM audit.row_reconciliation
UNION ALL SELECT 'monthly_event_totals_reconcile', 'error',
    sum(abs(study_rows - aggregated_study_rows)) FROM audit.row_reconciliation
UNION ALL SELECT 'matched_panel_outcomes_reconcile', 'error',
    sum(abs(matched_panel_events - panel_events)) FROM audit.row_reconciliation
UNION ALL SELECT 'extract_year_matches_event_year', 'error', count(*)
    FROM (SELECT _partition, event_month FROM clean.complaints
          UNION ALL SELECT _partition, event_month FROM clean.violations)
    WHERE _partition <> 'undated' AND _partition <> year(event_month)::VARCHAR
UNION ALL SELECT 'undated_extract_has_no_dated_events', 'error', count(*)
    FROM (SELECT _partition, received_at AS event_at FROM clean.complaints
          UNION ALL SELECT _partition, inspected_at FROM clean.violations)
    WHERE _partition = 'undated' AND event_at IS NOT NULL
UNION ALL SELECT 'building_year_panel_cardinality', 'error',
    abs((SELECT count(*) FROM mart.building_year)
      - (SELECT count(*) FROM clean.buildings)
      * (SELECT count(DISTINCT year(event_month)) FROM mart.calendar))
UNION ALL SELECT 'cohort_exclusion_counts_reconcile', 'error',
    abs((SELECT sum(buildings) FROM audit.cohort_exclusions
         WHERE cohort_reason = '09 provisional multifamily candidate')
      - (SELECT count(*) FROM mart.buildings WHERE candidate_multifamily));
