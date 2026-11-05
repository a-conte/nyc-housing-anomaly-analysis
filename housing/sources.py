"""The four inspected official sources and the columns needed for this project."""

from dataclasses import dataclass

BASE_URL = "https://data.cityofnewyork.us"


@dataclass(frozen=True)
class Source:
    dataset_id: str
    key: str
    columns: tuple[str, ...]
    date: str | None = None

    @property
    def api(self):
        return f"{BASE_URL}/resource/{self.dataset_id}"

    @property
    def metadata_url(self):
        return f"{BASE_URL}/api/views/{self.dataset_id}.json"


SOURCES = {
    "complaints": Source(
        "ygpa-z7cr",
        "problem_id",
        (
            "problem_id",
            "complaint_id",
            "building_id",
            "received_date",
            "borough",
            "block",
            "lot",
            "bin",
            "bbl",
            "major_category",
            "minor_category",
            "problem_code",
            "unit_type",
            "type",
            "problem_duplicate_flag",
            "complaint_status",
            "complaint_status_date",
            "problem_status",
            "problem_status_date",
        ),
        "received_date",
    ),
    "violations": Source(
        "wvxf-dwi5",
        "violationid",
        (
            "violationid",
            "buildingid",
            "boroid",
            "block",
            "lot",
            "bin",
            "bbl",
            "class",
            "inspectiondate",
            "approveddate",
            "novissueddate",
            "ordernumber",
            "novid",
            "violationstatus",
            "currentstatus",
            "currentstatusdate",
            "originalcorrectbydate",
            "newcorrectbydate",
            "certifieddate",
        ),
        "inspectiondate",
    ),
    "buildings": Source(
        "kj4p-ruqc",
        "buildingid",
        (
            "buildingid",
            "boroid",
            "block",
            "lot",
            "bin",
            "communityboard",
            "dobbuildingclass",
            "legalstories",
            "legalclassa",
            "legalclassb",
            "managementprogram",
            "lifecycle",
            "recordstatus",
        ),
    ),
    "pluto": Source(
        "64uk-42ks",
        "bbl",
        (
            "bbl",
            "borough",
            "borocode",
            "block",
            "lot",
            "unitsres",
            "unitstotal",
            "numbldgs",
            "numfloors",
            "yearbuilt",
            "yearalter1",
            "yearalter2",
            "bldgclass",
            "landuse",
            "resarea",
            "bldgarea",
            "cd",
            "bct2020",
            "condono",
            "version",
        ),
    ),
}


def partitions(source, start, end):
    if source.date is None:
        return [("all", None)]
    annual = [
        (
            str(year),
            (
                f"{source.date} >= '{year}-01-01T00:00:00' AND "
                f"{source.date} < '{year + 1}-01-01T00:00:00'"
            ),
        )
        for year in range(start, end + 1)
    ]
    # Undated events cannot be assigned to the study window. Keep them for an audit only.
    return annual + [("undated", f"{source.date} IS NULL")]
