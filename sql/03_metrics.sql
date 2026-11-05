-- Independent aggregations prevent multiplying complaint rows by violation rows.
CREATE TABLE mart.complaints_monthly AS
SELECT building_id, event_month,
       count(DISTINCT complaint_id) AS complaints,
       count(DISTINCT problem_id) AS problems,
       count(DISTINCT received_at::DATE) AS reporting_days,
       count(*) FILTER (WHERE duplicate_flag = 'Y') AS duplicate_flagged_problems,
       count(DISTINCT complaint_id) FILTER (WHERE duplicate_flag = 'N') AS complaints_unflagged
FROM clean.complaints WHERE in_study GROUP BY building_id, event_month;

CREATE TABLE mart.complaint_categories_monthly AS
SELECT building_id, event_month, major_category,
       count(DISTINCT complaint_id) AS complaints, count(DISTINCT problem_id) AS problems,
       count(DISTINCT received_at::DATE) AS reporting_days
FROM clean.complaints WHERE in_study GROUP BY building_id, event_month, major_category;

CREATE TABLE mart.violations_monthly AS
SELECT building_id, event_month,
       count(DISTINCT violation_id) AS violations_all_classes,
       count(DISTINCT violation_id) FILTER (WHERE violation_class = 'A') AS class_a,
       count(DISTINCT violation_id) FILTER (WHERE violation_class = 'B') AS class_b,
       count(DISTINCT violation_id) FILTER (WHERE violation_class = 'C') AS class_c,
       count(DISTINCT violation_id) FILTER (WHERE violation_class = 'I') AS class_i,
       count(DISTINCT violation_id) FILTER (WHERE violation_class IN ('B', 'C')) AS hazardous
FROM clean.violations WHERE in_study GROUP BY building_id, event_month;

CREATE TABLE mart.calendar AS
SELECT month::DATE AS event_month
FROM run_config,
     generate_series(start_date::TIMESTAMP, (end_date - INTERVAL '1 month')::TIMESTAMP,
                     INTERVAL '1 month') AS dates(month);

CREATE TABLE mart.source_months AS
SELECT d.event_month,
       d.event_month IN (SELECT event_month FROM mart.complaints_monthly) AS complaints_present,
       d.event_month IN (SELECT event_month FROM mart.violations_monthly) AS violations_present
FROM mart.calendar d;

-- A view avoids materializing ~20 million mostly-zero building-month rows.
-- These are recorded events for the CURRENT inventory, not proven historical occupancy.
CREATE VIEW mart.building_month AS
SELECT b.building_id, b.borough_id, b.bbl, b.building_class, b.hpd_units, b.pluto_units,
       b.rate_units, b.candidate_multifamily, b.unit_comparison, b.year_built, d.event_month,
       d.complaints_present AND d.violations_present AS source_month_present,
       CASE WHEN d.complaints_present THEN coalesce(c.complaints, 0) END AS complaints,
       CASE WHEN d.complaints_present THEN coalesce(c.problems, 0) END AS problems,
       CASE WHEN d.complaints_present THEN coalesce(c.reporting_days, 0) END AS reporting_days,
       CASE WHEN d.complaints_present THEN coalesce(c.duplicate_flagged_problems, 0) END AS duplicate_flagged_problems,
       CASE WHEN d.violations_present THEN coalesce(v.class_b, 0) END AS class_b,
       CASE WHEN d.violations_present THEN coalesce(v.class_c, 0) END AS class_c,
       CASE WHEN d.violations_present THEN coalesce(v.hazardous, 0) END AS hazardous,
       b.year_built IS NOT NULL AND b.year_built > year(d.event_month) AS predates_construction
FROM mart.buildings b CROSS JOIN mart.source_months d
LEFT JOIN mart.complaints_monthly c USING (building_id, event_month)
LEFT JOIN mart.violations_monthly v USING (building_id, event_month);

-- ROWS is appropriate because the calendar gives every building every month.
-- Require 12 observed calendar months before exposing a complete rolling total.
CREATE VIEW mart.rolling_activity AS
SELECT *,
       count(*) OVER trailing_year AS months_in_window,
       CASE WHEN count(*) OVER trailing_year = 12 AND bool_and(source_month_present) OVER trailing_year
            THEN sum(complaints) OVER trailing_year END AS complaints_12m,
       CASE WHEN count(*) OVER trailing_year = 12 AND bool_and(source_month_present) OVER trailing_year
            THEN sum(hazardous) OVER trailing_year END AS hazardous_12m
FROM mart.building_month
WINDOW trailing_year AS (PARTITION BY building_id ORDER BY event_month
                         ROWS BETWEEN 11 PRECEDING AND CURRENT ROW);

CREATE TABLE mart.building_year AS
SELECT building_id, year(event_month)::INTEGER AS year,
       any_value(borough_id) AS borough_id, any_value(building_class) AS building_class,
       any_value(hpd_units) AS hpd_units, any_value(pluto_units) AS pluto_units,
       any_value(rate_units) AS rate_units,
       any_value(candidate_multifamily) AS candidate_multifamily,
       any_value(unit_comparison) AS unit_comparison,
       count(*) AS calendar_months, bool_and(source_month_present) AS source_coverage_present,
       sum(complaints) AS complaints, sum(problems) AS problems,
       sum(class_b) AS class_b, sum(class_c) AS class_c, sum(hazardous) AS hazardous,
       count(*) FILTER (WHERE complaints > 0) AS months_with_complaints,
       count(*) FILTER (WHERE hazardous > 0) AS months_with_hazardous,
       bool_or(predates_construction) AS predates_construction
FROM mart.building_month GROUP BY building_id, year(event_month);

CREATE VIEW mart.provisional_rates AS
SELECT *, 100.0 * complaints / (rate_units * calendar_months / 12.0) AS complaints_per_100_units,
       100.0 * class_b / (rate_units * calendar_months / 12.0) AS class_b_per_100_units,
       100.0 * class_c / (rate_units * calendar_months / 12.0) AS class_c_per_100_units,
       100.0 * hazardous / (rate_units * calendar_months / 12.0) AS hazardous_per_100_units
FROM mart.building_year
WHERE rate_units > 0 AND NOT predates_construction AND source_coverage_present;

-- Descriptive peer comparisons for later review, not model-based anomaly labels.
CREATE VIEW mart.peer_comparisons AS
SELECT *,
       count(*) OVER peers AS peer_buildings,
       avg(hazardous_per_100_units) OVER peers AS peer_mean_hazardous_rate,
       dense_rank() OVER (PARTITION BY year ORDER BY hazardous DESC) AS raw_hazardous_rank,
       dense_rank() OVER (PARTITION BY year ORDER BY hazardous_per_100_units DESC) AS unit_rate_rank,
       lag(hazardous) OVER (PARTITION BY building_id ORDER BY year) AS prior_year_hazardous
FROM mart.provisional_rates
WINDOW peers AS (PARTITION BY year, borough_id, building_class,
                 CASE WHEN rate_units < 10 THEN '3-9' WHEN rate_units < 50 THEN '10-49'
                      ELSE '50+' END);

