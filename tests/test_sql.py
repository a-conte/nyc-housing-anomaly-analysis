import pytest


def test_counts_do_not_multiply_and_severity_stays_separate(audit_db):
    row = audit_db.execute("""
        SELECT complaints, problems, class_b, class_c, hazardous
        FROM mart.building_month WHERE building_id='1' AND event_month='2021-01-01'
    """).fetchone()
    assert row == (1, 2, 1, 1, 2)
    assert audit_db.execute(
        "SELECT class_i FROM mart.violations_monthly WHERE building_id='1' AND event_month='2021-01-01'"
    ).fetchone() == (1,)


def test_zero_event_inventory_and_unmatched_events_are_retained(audit_db):
    assert audit_db.execute(
        "SELECT count(*), sum(complaints), sum(hazardous) FROM mart.building_month WHERE building_id='3'"
    ).fetchone() == (24, 0, 0)
    assert audit_db.execute(
        "SELECT count(*) FROM audit.event_links WHERE in_study AND NOT building_matched"
    ).fetchone() == (2,)
    assert audit_db.execute(
        "SELECT sum(complaints) FROM mart.complaints_monthly WHERE building_id='999'"
    ).fetchone() == (1,)


def test_denominator_disagreements_and_multibuilding_lots(audit_db):
    rows = dict(audit_db.execute("SELECT building_id, rate_units FROM mart.buildings").fetchall())
    assert rows == {
        "1": 10,
        "2": None,
        "3": 6,
        "4": None,
        "5": None,
        "6": None,
        "7": None,
        "8": None,
    }
    assert audit_db.execute(
        "SELECT hpd_units, pluto_units, unit_comparison FROM mart.buildings WHERE building_id='2'"
    ).fetchone() == (8, 6, "disagreement")
    assert audit_db.execute(
        "SELECT hazardous_per_100_units FROM mart.provisional_rates WHERE building_id='1' AND year=2021"
    ).fetchone() == (20.0,)


def test_identifiers_do_not_round_or_accept_placeholders(audit_db):
    assert audit_db.execute(
        "SELECT whole_number('1.5'), valid_bbl('1000010001.00000000'), valid_bbl('0'), valid_bin('1000000'), make_bbl('1', '1', '1')"
    ).fetchone() == (None, "1000010001", None, None, "1000010001")


def test_rolling_metrics_need_a_complete_calendar_window(audit_db):
    assert audit_db.execute(
        "SELECT complaints_12m FROM mart.rolling_activity WHERE building_id='1' AND event_month='2021-11-01'"
    ).fetchone() == (None,)
    assert audit_db.execute(
        "SELECT months_in_window, complaints_12m, hazardous_12m FROM mart.rolling_activity WHERE building_id='1' AND event_month='2021-12-01'"
    ).fetchone() == (12, 2, 2)


def test_undated_events_do_not_enter_outcomes(audit_db):
    assert audit_db.execute("SELECT sum(problems) FROM mart.complaints_monthly").fetchone() == (29,)
    assert audit_db.execute(
        "SELECT sum(violations_all_classes) FROM mart.violations_monthly"
    ).fetchone() == (29,)
    assert audit_db.execute(
        "SELECT sum(missing_primary_date) FROM audit.date_quality"
    ).fetchone() == (2,)


def test_geographic_conflict_is_a_flag_not_an_automatic_rematch(audit_db):
    assert audit_db.execute(
        "SELECT building_id, building_matched, bbl_conflict FROM audit.event_links WHERE source='complaints' AND event_id='1'"
    ).fetchone() == ("1", True, True)


def test_semantic_checks_pass_on_valid_fixture(audit_db):
    assert (
        audit_db.execute(
            "SELECT check_name FROM audit.checks WHERE severity='error' AND failures>0"
        ).fetchall()
        == []
    )


def test_audit_conserves_events_and_explains_cohort_exclusions(audit_db):
    assert audit_db.execute("""
        SELECT source, raw_rows, clean_rows, study_rows, aggregated_study_rows,
               panel_measure, matched_panel_events, panel_events
        FROM audit.row_reconciliation ORDER BY source
    """).fetchall() == [
        ("complaints", 30, 30, 29, 29, "problems", 28, 28),
        ("violations", 30, 30, 29, 29, "Class B/C violations", 3, 3),
    ]
    assert audit_db.execute("""
        SELECT cohort_reason, buildings FROM audit.cohort_exclusions ORDER BY cohort_reason
    """).fetchall() == [
        ("04 fewer than three apartments", 1),
        ("06 Class B rooms present", 1),
        ("09 provisional multifamily candidate", 6),
    ]


def test_invalid_pluto_bbl_is_retained_and_cannot_supply_a_denominator(audit_db):
    assert audit_db.execute("SELECT count(*) FROM raw.pluto").fetchone() == (7,)
    assert audit_db.execute("SELECT count(*) FROM clean.pluto").fetchone() == (7,)
    assert audit_db.execute("SELECT count(*) FROM audit.pluto_unjoinable").fetchone() == (1,)
    assert audit_db.execute("""
        SELECT severity, failures FROM audit.checks
        WHERE check_name='pluto_bbl_missing_or_invalid'
    """).fetchone() == ("warning", 1)
    assert audit_db.execute("""
        SELECT failures FROM audit.checks WHERE check_name='unique_pluto_bbls'
    """).fetchone() == (0,)


@pytest.mark.parametrize("audit_db", ["duplicate_pluto_key"], indirect=True)
def test_duplicate_joinable_pluto_keys_still_block_publication(audit_db):
    assert audit_db.execute("""
        SELECT severity, failures FROM audit.checks WHERE check_name='unique_pluto_bbls'
    """).fetchone() == ("error", 1)
    assert audit_db.execute("""
        SELECT failures FROM audit.checks WHERE check_name='building_join_does_not_multiply'
    """).fetchone() == (1,)


def test_absent_source_month_is_not_a_zero_or_a_full_rolling_window(audit_db):
    audit_db.execute(
        "UPDATE mart.source_months SET complaints_present=false WHERE event_month='2021-06-01'"
    )
    assert audit_db.execute(
        "SELECT complaints FROM mart.building_month WHERE building_id='3' AND event_month='2021-06-01'"
    ).fetchone() == (None,)
    assert audit_db.execute(
        "SELECT complaints_12m FROM mart.rolling_activity WHERE building_id='1' AND event_month='2021-12-01'"
    ).fetchone() == (None,)
