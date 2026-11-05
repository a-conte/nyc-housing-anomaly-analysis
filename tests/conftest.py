import csv
import gzip

import duckdb
import pytest

from housing.database import execute_sql, load_raw
from housing.sources import SOURCES


@pytest.fixture
def audit_db(tmp_path, request):
    def building(key, lot, units, rooms="0"):
        return {
            "buildingid": str(key),
            "boroid": "1",
            "block": "1",
            "lot": str(lot),
            "bin": str(1000000 + key),
            "legalclassa": str(units),
            "legalclassb": rooms,
            "recordstatus": "Active",
            "lifecycle": "Building",
            "managementprogram": "PVT",
            "dobbuildingclass": "TENEMENT",
        }

    def lot(number, units, buildings="1"):
        return {
            "bbl": f"100001{number:04d}.00000000",
            "borocode": "1",
            "block": "1",
            "lot": str(number),
            "unitsres": str(units),
            "numbldgs": buildings,
            "yearbuilt": "1900",
            "version": "test",
        }

    def complaint(problem, complaint, building, date, duplicate="N"):
        return {
            "problem_id": str(problem),
            "complaint_id": str(complaint),
            "building_id": str(building),
            "received_date": date,
            "problem_duplicate_flag": duplicate,
            "major_category": "HEAT/HOT WATER",
            "borough": "MANHATTAN",
            "block": "1",
            "lot": "1",
        }

    def violation(key, building, date, severity):
        return {
            "violationid": str(key),
            "buildingid": str(building),
            "inspectiondate": date,
            "class": severity,
            "boroid": "1",
            "block": "1",
            "lot": "1",
        }

    data = {
        "buildings": [
            building(1, 1, 10),
            building(2, 2, 8),
            building(3, 3, 6),
            building(4, 4, 20),
            building(5, 4, 30),
            building(6, 5, 0),
            building(7, 6, 3, "10"),
            building(8, 7, 4),
        ],
        "pluto": [lot(1, 10), lot(2, 6), lot(3, 6), lot(4, 50, "2"), lot(5, 8), lot(6, 3)],
        "complaints": [
            complaint(1, 10, 1, "2021-01-03T10:00:00", "Y"),
            complaint(2, 10, 1, "2021-01-03T10:00:00"),
            complaint(3, 11, 1, "2021-02-01T10:00:00"),
            complaint(4, 12, 999, "2021-02-02T10:00:00"),
            complaint(5, 13, 2, "2022-01-01T10:00:00"),
            complaint(6, 14, 1, ""),
        ],
        "violations": [
            violation(1, 1, "2021-01-10", "B"),
            violation(2, 1, "2021-01-10", "C"),
            violation(3, 1, "2021-01-10", "I"),
            violation(4, 999, "2021-02-10", "C"),
            violation(5, 1, "2022-01-01", "B"),
            violation(6, 1, "", "B"),
        ],
    }
    # Citywide background records establish source presence in every calendar month.
    for index in range(24):
        date = f"{2021 + index // 12}-{index % 12 + 1:02d}-15T12:00:00"
        data["complaints"].append(complaint(100 + index, 100 + index, 8, date))
        data["violations"].append(violation(100 + index, 8, date, "A"))
    # A conflicting geographic key must NOT move an event off its HPD BuildingID.
    data["complaints"][0]["bbl"] = "1000010012"
    # A source PLUTO record with block 00000 is retained but cannot be joined.
    data["pluto"].append(
        {"bbl": "2000008900.00000000", "borocode": "2", "block": "0", "lot": "8900"}
    )
    if getattr(request, "param", None) == "duplicate_pluto_key":
        data["pluto"].append(data["pluto"][0].copy())
    manifests = []
    for name, rows in data.items():
        source = SOURCES[name]
        grouped = {}
        for row in rows:
            label = (row[source.date][:4] or "undated") if source.date else "all"
            grouped.setdefault(label, []).append(row)
        for label, group in grouped.items():
            path = tmp_path / "raw" / name / f"{label}.csv.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(path, "wt", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=source.columns)
                writer.writeheader()
                writer.writerows(group)
            manifests.append(
                {
                    "source": name,
                    "partition": label,
                    "path": str(path.relative_to(tmp_path)),
                    "rows": len(group),
                }
            )
    connection = duckdb.connect()
    load_raw(connection, tmp_path, manifests, {"study": {"start_year": 2021, "end_year": 2022}})
    execute_sql(connection)
    yield connection
    connection.close()
