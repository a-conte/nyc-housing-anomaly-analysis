CREATE TABLE audit.monthly_coverage AS
WITH observed AS (
    SELECT 'complaints' AS source, event_month, count(*) AS rows,
           count(DISTINCT complaint_id) AS distinct_events,
           count(DISTINCT building_id) AS buildings,
           count(*) FILTER (WHERE duplicate_flag = 'Y') AS duplicate_flagged_rows
    FROM clean.complaints WHERE in_study GROUP BY event_month
    UNION ALL
    SELECT 'violations', event_month, count(*), count(DISTINCT violation_id),
           count(DISTINCT building_id), 0
    FROM clean.violations WHERE in_study GROUP BY event_month
), complete AS (
    SELECT source, event_month, coalesce(rows, 0) AS rows,
           coalesce(distinct_events, 0) AS distinct_events, coalesce(buildings, 0) AS buildings,
           coalesce(duplicate_flagged_rows, 0) AS duplicate_flagged_rows
    FROM mart.calendar CROSS JOIN (VALUES ('complaints'), ('violations')) AS sources(source)
    LEFT JOIN observed USING (source, event_month)
)
SELECT *, lag(rows, 12) OVER (PARTITION BY source ORDER BY event_month) AS rows_prior_year,
       rows / nullif(lag(rows, 12) OVER (PARTITION BY source ORDER BY event_month), 0)::DOUBLE
           AS year_over_year_ratio
FROM complete;

CREATE TABLE audit.linkage_summary AS
SELECT source, year(event_month) AS year, in_study, count(*) AS rows,
       count(*) FILTER (WHERE building_matched) AS building_matched,
       count(*) FILTER (WHERE NOT building_matched) AS building_unmatched,
       count(*) FILTER (WHERE pluto_matched) AS pluto_matched,
       count(*) FILTER (WHERE bbl_conflict) AS bbl_conflicts,
       count(*) FILTER (WHERE bin_conflict) AS bin_conflicts,
       count(*) FILTER (WHERE source_bbl_conflict) AS source_bbl_conflicts
FROM audit.event_links GROUP BY source, year(event_month), in_study;

CREATE TABLE audit.unit_comparison AS
SELECT borough_id, candidate_multifamily, unit_comparison, count(*) AS buildings,
       median(unit_difference) AS median_unit_difference,
       median(abs(unit_relative_difference)) AS median_absolute_relative_difference,
       count(rate_units) AS buildings_with_provisional_denominator
FROM mart.buildings GROUP BY borough_id, candidate_multifamily, unit_comparison;

CREATE TABLE audit.violation_classes AS
SELECT year(event_month) AS year, violation_class, count(*) AS rows
FROM clean.violations WHERE in_study GROUP BY year(event_month), violation_class;

CREATE TABLE audit.date_quality AS
SELECT 'complaints' AS source, _partition AS extract_partition, count(*) AS rows,
       count(*) FILTER (WHERE received_at IS NULL) AS missing_primary_date,
       count(*) FILTER (WHERE NOT in_study) AS outside_window,
       0 AS approval_before_inspection, 0 AS notice_before_inspection
FROM clean.complaints GROUP BY _partition
UNION ALL
SELECT 'violations', _partition, count(*), count(*) FILTER (WHERE inspected_at IS NULL),
       count(*) FILTER (WHERE NOT in_study),
       count(*) FILTER (WHERE approved_at < inspected_at),
       count(*) FILTER (WHERE notice_issued_at < inspected_at)
FROM clean.violations GROUP BY _partition;

CREATE TABLE audit.cohort_summary AS
SELECT record_status, lifecycle, management_program, count(*) AS buildings,
       count(*) FILTER (WHERE candidate_multifamily) AS candidate_multifamily,
       count(rate_units) AS with_provisional_denominator
FROM mart.buildings GROUP BY record_status, lifecycle, management_program;

CREATE TABLE audit.complaint_conflicts AS
SELECT complaint_id, count(DISTINCT coalesce(building_id, 'MISSING')) AS buildings,
       count(DISTINCT event_month) AS months
FROM clean.complaints WHERE in_study GROUP BY complaint_id
HAVING count(DISTINCT coalesce(building_id, 'MISSING')) > 1 OR count(DISTINCT event_month) > 1;

CREATE TABLE audit.checks AS
SELECT 'unique_building_ids' AS check_name, 'error' AS severity,
       count(*) - count(DISTINCT building_id) AS failures FROM clean.buildings
UNION ALL SELECT 'unique_pluto_bbls', 'error', count(*) - count(DISTINCT bbl) FROM clean.pluto
UNION ALL SELECT 'unique_problem_ids', 'error', count(*) - count(DISTINCT problem_id) FROM clean.complaints
UNION ALL SELECT 'unique_violation_ids', 'error', count(*) - count(DISTINCT violation_id) FROM clean.violations
UNION ALL SELECT 'complaint_id_present', 'error', count(*) FROM clean.complaints
          WHERE in_study AND complaint_id IS NULL
UNION ALL SELECT 'complaint_building_month_consistent', 'error', count(*) FROM audit.complaint_conflicts
UNION ALL SELECT 'building_join_does_not_multiply', 'error',
          abs((SELECT count(*) FROM mart.buildings) - (SELECT count(*) FROM clean.buildings))
UNION ALL SELECT 'event_join_does_not_multiply', 'error',
          abs((SELECT count(*) FROM audit.event_links)
            - (SELECT count(*) FROM clean.complaints) - (SELECT count(*) FROM clean.violations))
UNION ALL SELECT 'hazardous_equals_b_plus_c', 'error', count(*) FROM mart.building_year
          WHERE hazardous <> class_b + class_c
UNION ALL SELECT 'all_calendar_months_have_records', 'warning', count(*) FROM audit.monthly_coverage
          WHERE rows = 0
UNION ALL SELECT 'complaint_building_missing', 'warning', count(*) FROM clean.complaints
          WHERE in_study AND building_id IS NULL
UNION ALL SELECT 'violation_building_missing', 'warning', count(*) FROM clean.violations
          WHERE in_study AND building_id IS NULL
UNION ALL SELECT 'unrecognized_violation_class', 'warning', count(*) FROM clean.violations
          WHERE in_study AND (violation_class NOT IN ('A', 'B', 'C', 'I') OR violation_class IS NULL)
UNION ALL SELECT 'invalid_primary_dates_in_annual_extracts', 'error', count(*)
          FROM (SELECT _partition, in_study FROM clean.complaints
                UNION ALL SELECT _partition, in_study FROM clean.violations)
          WHERE _partition <> 'undated' AND NOT in_study
UNION ALL SELECT 'pluto_bbl_components_disagree', 'warning', count(*) FROM clean.pluto
          WHERE bbl <> component_bbl
UNION ALL SELECT 'substantial_monthly_change_review', 'warning', count(*) FROM audit.monthly_coverage
          WHERE year_over_year_ratio < 0.5 OR year_over_year_ratio > 2;
