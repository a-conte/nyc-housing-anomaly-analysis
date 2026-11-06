from housing.phase3 import build


def prepare(con):
    con.execute(
        "UPDATE mart.buildings SET residential_area=100, year_built=1900, year_altered_1=0, year_altered_2=0"
    )


def test_cohort_denominators_zeros_and_reproducibility(audit_db):
    prepare(audit_db)
    build(audit_db)
    rows = audit_db.execute(
        "SELECT building_id,selected_units,complaints,class_b,class_c FROM analytical.features ORDER BY building_id"
    ).fetchall()
    assert ("1", 10, 2, 2, 1) in rows
    assert ("2", 8, 1, 0, 0) in rows  # HPD/PLUTO disagreement retained, no imputation.
    assert ("3", 6, 0, 0, 0) in rows
    assert not any(row[0] in ("6", "7", "8") for row in rows)
    assert audit_db.execute(
        "SELECT complaints_per_100_unit_years FROM analytical.features WHERE building_id='1'"
    ).fetchone() == (10.0,)
    build(audit_db)
    assert (
        audit_db.execute(
            "SELECT building_id,selected_units,complaints,class_b,class_c FROM analytical.features ORDER BY building_id"
        ).fetchall()
        == rows
    )


def test_unknown_history_shared_identifiers_and_unavailable_month(audit_db):
    prepare(audit_db)
    audit_db.execute("UPDATE mart.buildings SET year_built=NULL WHERE building_id='1'")
    audit_db.execute("UPDATE clean.buildings SET bin='1000002' WHERE building_id='3'")
    build(audit_db)
    assert audit_db.execute(
        "SELECT eligibility_step FROM analytical.eligibility WHERE building_id='1'"
    ).fetchone() == (5,)
    assert audit_db.execute(
        "SELECT eligibility_step FROM analytical.eligibility WHERE building_id='2'"
    ).fetchone() == (4,)
    audit_db.execute(
        "UPDATE mart.source_months SET complaints_present=false WHERE event_month='2021-06-01'"
    )
    build(audit_db)
    assert audit_db.execute("SELECT count(*) FROM analytical.features").fetchone() == (0,)
