    -- Preserve source strings in raw.*; normalize explicitly in clean.*.
    -- DuckDB casts fractional strings to rounded integers: reject fractions first.
    CREATE MACRO whole_number(value) AS
        CASE WHEN regexp_full_match(trim(value::VARCHAR), '[0-9]+([.]0+)?')
            THEN try_cast(value AS BIGINT) END;
    CREATE MACRO positive_id(value) AS
        CASE WHEN whole_number(value) > 0 THEN whole_number(value)::VARCHAR END;
    CREATE MACRO valid_bbl(value) AS
        CASE WHEN regexp_full_match(positive_id(value), '[1-5][0-9]{9}')
                AND substr(positive_id(value), 2, 5) <> '00000'
                AND right(positive_id(value), 4) <> '0000'
            THEN positive_id(value) END;
    CREATE MACRO valid_bin(value) AS
        CASE WHEN regexp_full_match(positive_id(value), '[1-5][0-9]{6}')
                AND right(positive_id(value), 6) <> '000000'
            THEN positive_id(value) END;
    CREATE MACRO make_bbl(borough, block, lot) AS
        CASE WHEN whole_number(borough) BETWEEN 1 AND 5
                AND whole_number(block) BETWEEN 1 AND 99999
                AND whole_number(lot) BETWEEN 1 AND 9999
            THEN whole_number(borough)::VARCHAR || lpad(whole_number(block)::VARCHAR, 5, '0')
                || lpad(whole_number(lot)::VARCHAR, 4, '0') END;
    CREATE MACRO borough_number(value) AS
        CASE upper(trim(value)) WHEN 'MANHATTAN' THEN 1 WHEN 'BRONX' THEN 2
            WHEN 'BROOKLYN' THEN 3 WHEN 'QUEENS' THEN 4 WHEN 'STATEN ISLAND' THEN 5 END;

    CREATE TABLE clean.buildings AS
    SELECT positive_id(buildingid) AS building_id,
        whole_number(boroid) AS borough_id,
        make_bbl(boroid, block, lot) AS bbl,
        valid_bin(bin) AS bin,
        whole_number(communityboard) AS community_board,
        dobbuildingclass AS building_class,
        whole_number(legalstories) AS stories,
        whole_number(legalclassa) AS hpd_units,
        whole_number(legalclassb) AS hpd_class_b_rooms,
        upper(trim(managementprogram)) AS management_program,
        upper(trim(lifecycle)) AS lifecycle,
        upper(trim(recordstatus)) AS record_status
    FROM raw.buildings;

    CREATE TABLE clean.pluto AS
    SELECT valid_bbl(bbl) AS bbl, make_bbl(borocode, block, lot) AS component_bbl,
        whole_number(unitsres) AS pluto_units,
        whole_number(unitstotal) AS total_units,
        whole_number(numbldgs) AS buildings_on_lot,
        try_cast(numfloors AS DOUBLE) AS tallest_building_floors,
        CASE WHEN whole_number(yearbuilt) BETWEEN 1600 AND year(current_date)
                THEN whole_number(yearbuilt) END AS year_built,
        whole_number(yearalter1) AS year_altered_1,
        whole_number(yearalter2) AS year_altered_2,
        bldgclass AS pluto_building_class,
        whole_number(landuse) AS land_use,
        try_cast(resarea AS DOUBLE) AS residential_area,
        try_cast(bldgarea AS DOUBLE) AS building_area,
        whole_number(cd) AS community_district,
        bct2020 AS census_tract_2020, whole_number(condono) AS condominium_number,
        version AS pluto_version
    FROM raw.pluto;

    CREATE TABLE clean.complaints AS
    SELECT positive_id(problem_id) AS problem_id, positive_id(complaint_id) AS complaint_id,
        positive_id(building_id) AS building_id,
        try_cast(received_date AS TIMESTAMP) AS received_at,
        date_trunc('month', try_cast(received_date AS TIMESTAMP))::DATE AS event_month,
        valid_bbl(bbl) AS reported_bbl,
        make_bbl(borough_number(borough), block, lot) AS component_bbl,
        valid_bin(bin) AS reported_bin,
        upper(trim(major_category)) AS major_category,
        minor_category, problem_code, unit_type, type AS problem_type,
        upper(trim(problem_duplicate_flag)) AS duplicate_flag,
        complaint_status, problem_status,
        try_cast(complaint_status_date AS TIMESTAMP) AS complaint_status_at,
        try_cast(problem_status_date AS TIMESTAMP) AS problem_status_at,
        _partition,
        coalesce(try_cast(received_date AS TIMESTAMP) >= start_date
                    AND try_cast(received_date AS TIMESTAMP) < end_date, false) AS in_study
    FROM raw.complaints CROSS JOIN run_config;

    CREATE TABLE clean.violations AS
    SELECT positive_id(violationid) AS violation_id, positive_id(buildingid) AS building_id,
        upper(trim(class)) AS violation_class,
        try_cast(inspectiondate AS TIMESTAMP) AS inspected_at,
        date_trunc('month', try_cast(inspectiondate AS TIMESTAMP))::DATE AS event_month,
        try_cast(approveddate AS TIMESTAMP) AS approved_at,
        try_cast(novissueddate AS TIMESTAMP) AS notice_issued_at,
        valid_bbl(bbl) AS reported_bbl, make_bbl(boroid, block, lot) AS component_bbl,
        valid_bin(bin) AS reported_bin,
        ordernumber AS order_number, positive_id(novid) AS notice_id,
        violationstatus AS violation_status, currentstatus AS current_status,
        try_cast(currentstatusdate AS TIMESTAMP) AS current_status_at,
        try_cast(originalcorrectbydate AS TIMESTAMP) AS original_correct_by,
        try_cast(newcorrectbydate AS TIMESTAMP) AS new_correct_by,
        try_cast(certifieddate AS TIMESTAMP) AS certified_at,
        _partition,
        coalesce(try_cast(inspectiondate AS TIMESTAMP) >= start_date
                    AND try_cast(inspectiondate AS TIMESTAMP) < end_date, false) AS in_study
    FROM raw.violations CROSS JOIN run_config;

