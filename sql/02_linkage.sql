-- The building dimension keeps ALL HPD buildings, including unmatched properties.
-- Neither BBL nor BIN is assumed to identify one HPD record.
CREATE TABLE mart.buildings AS
WITH lot_counts AS (
    SELECT bbl,
           count(*) AS hpd_records_on_lot,
           count(*) FILTER (WHERE record_status = 'ACTIVE' AND lifecycle = 'BUILDING')
               AS active_hpd_buildings_on_lot
    FROM clean.buildings WHERE bbl IS NOT NULL GROUP BY bbl
), linked AS (
    SELECT b.*, p.* EXCLUDE (bbl), l.hpd_records_on_lot, l.active_hpd_buildings_on_lot,
           p.bbl IS NOT NULL AS pluto_matched,
           coalesce(p.buildings_on_lot = 1 AND l.active_hpd_buildings_on_lot = 1
                    AND b.record_status = 'ACTIVE' AND b.lifecycle = 'BUILDING', false)
               AS unit_counts_comparable,
           coalesce(b.record_status = 'ACTIVE' AND b.lifecycle = 'BUILDING'
                    AND b.hpd_units >= 3 AND b.hpd_class_b_rooms = 0
                    AND b.management_program <> 'NYCHA', false) AS candidate_multifamily
    FROM clean.buildings b
    LEFT JOIN clean.pluto p USING (bbl)
    LEFT JOIN lot_counts l USING (bbl)
), compared AS (
    SELECT *,
           CASE WHEN bbl IS NULL THEN 'invalid_hpd_bbl'
                WHEN NOT pluto_matched THEN 'no_pluto_match'
                WHEN NOT unit_counts_comparable THEN 'not_one_building_to_one_lot'
                WHEN hpd_units IS NULL OR hpd_units = 0 THEN 'missing_or_zero_hpd_units'
                WHEN pluto_units IS NULL OR pluto_units = 0 THEN 'missing_or_zero_pluto_units'
                WHEN hpd_units = pluto_units THEN 'agreement'
                ELSE 'disagreement' END AS unit_comparison,
           CASE WHEN unit_counts_comparable THEN hpd_units - pluto_units END AS unit_difference,
           CASE WHEN unit_counts_comparable AND pluto_units > 0
                THEN (hpd_units - pluto_units)::DOUBLE / pluto_units END AS unit_relative_difference
    FROM linked
)
SELECT *,
       -- Conservative provisional rates only. Disagreements keep BOTH original counts.
       CASE WHEN candidate_multifamily AND unit_comparison = 'agreement'
            THEN hpd_units END AS rate_units,
       CASE WHEN candidate_multifamily AND unit_comparison = 'agreement'
            THEN 'HPD and PLUTO agree on a single-building lot'
            ELSE 'withheld pending denominator/cohort review' END AS denominator_policy
FROM compared;

CREATE VIEW audit.event_links AS
SELECT 'complaints' AS source, c.problem_id AS event_id, c.building_id, c.event_month,
       c.in_study, b.building_id IS NOT NULL AS building_matched,
       coalesce(b.pluto_matched, false) AS pluto_matched,
       CASE WHEN c.reported_bbl IS NOT NULL AND b.bbl IS NOT NULL
            THEN c.reported_bbl <> b.bbl END AS bbl_conflict,
       CASE WHEN c.reported_bin IS NOT NULL AND b.bin IS NOT NULL
            THEN c.reported_bin <> b.bin END AS bin_conflict,
       CASE WHEN c.reported_bbl IS NOT NULL AND c.component_bbl IS NOT NULL
            THEN c.reported_bbl <> c.component_bbl END AS source_bbl_conflict
FROM clean.complaints c LEFT JOIN mart.buildings b USING (building_id)
UNION ALL
SELECT 'violations', v.violation_id, v.building_id, v.event_month, v.in_study,
       b.building_id IS NOT NULL, coalesce(b.pluto_matched, false),
       CASE WHEN v.reported_bbl IS NOT NULL AND b.bbl IS NOT NULL
            THEN v.reported_bbl <> b.bbl END,
       CASE WHEN v.reported_bin IS NOT NULL AND b.bin IS NOT NULL
            THEN v.reported_bin <> b.bin END,
       CASE WHEN v.reported_bbl IS NOT NULL AND v.component_bbl IS NOT NULL
            THEN v.reported_bbl <> v.component_bbl END
FROM clean.violations v LEFT JOIN mart.buildings b USING (building_id);

