"""Rebuild Phase 3 only: python -m housing.phase3. No source downloads."""

import runpy

import duckdb

from housing.database import PROJECT, export_csv, markdown_table
from housing.download import now, save_json, sha256

SQL = PROJECT / "sql/phase3/features.sql"


def build(connection):
    connection.execute(SQL.read_text())
    assert (
        connection.execute(
            "SELECT count(*)-count(DISTINCT building_id) FROM analytical.features"
        ).fetchone()[0]
        == 0
    )
    assert (
        connection.execute(
            "SELECT count(*) FROM analytical.features WHERE selected_units<3 OR hazardous<>class_b+class_c OR eligibility_step<>8"
        ).fetchone()[0]
        == 0
    )
    assert (
        connection.execute(
            "SELECT count(*) FROM analytical.annual WHERE NOT source_coverage_present OR calendar_months<>12"
        ).fetchone()[0]
        == 0
    )


def main():
    report = PROJECT / "reports/phase3"
    report.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(PROJECT / "data/housing.duckdb")) as con:
        con.execute("BEGIN")
        try:
            build(con)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        for name in ("exclusions", "denominator_review"):
            export_csv(con, f"SELECT * FROM analytical.{name} ORDER BY ALL", report / f"{name}.csv")
        rows = con.execute(
            "SELECT * FROM analytical.exclusions ORDER BY eligibility_step"
        ).fetchall()
        totals = con.execute(
            "SELECT count(*),sum(complaints),sum(class_b),sum(class_c),count(*) FILTER(WHERE complaints=0 AND hazardous=0) FROM analytical.features"
        ).fetchone()
        (report / "coverage.md").write_text(
            markdown_table(["Step", "Buildings", "Complaints", "B", "C"], rows)
            + "\n\nRetained buildings, complaints, B, C, zero complaint/B-C buildings: "
            + str(totals)
            + "\n"
        )
        save_json(
            report / "provenance.json",
            {
                "generated_at": now(),
                "sql_sha256": sha256(SQL),
                "phase2_provenance_sha256": sha256(PROJECT / "reports/phase2/provenance.json"),
                "duckdb_version": duckdb.__version__,
            },
        )
        print(totals)
    runpy.run_module("housing.phase3_review", run_name="__main__")


if __name__ == "__main__":
    main()
