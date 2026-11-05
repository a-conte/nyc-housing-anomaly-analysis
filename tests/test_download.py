import csv
import io
from types import SimpleNamespace

import pytest
import requests

from housing import download
from housing.sources import SOURCES, partitions


def response(rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=SOURCES["buildings"].columns)
    writer.writeheader()
    writer.writerows(rows)
    return SimpleNamespace(content=stream.getvalue().encode(), url="https://example.test/query")


def test_keyset_pagination_reconciliation_and_verified_resume(tmp_path, monkeypatch):
    calls = []

    def get(url, settings, params=None):
        calls.append(params)
        if params["$select"] == "count(*) AS n":
            return SimpleNamespace(json=lambda: [{"n": "3"}])
        if "$where" not in params:
            return response([{"buildingid": "1"}, {"buildingid": "2"}])
        assert params["$where"] == "(buildingid > 2)"
        return response([{"buildingid": "3"}])

    monkeypatch.setattr(download, "get", get)
    settings = {"page_size": 2}
    result = download.extract_partition(tmp_path, "buildings", "all", None, settings)
    assert result["rows"] == 3
    assert len(result["queries"]) == 2
    count = len(calls)
    assert download.extract_partition(tmp_path, "buildings", "all", None, settings) == result
    assert len(calls) == count
    (tmp_path / result["path"]).write_bytes(b"corruption")
    with pytest.raises(ValueError, match="corrupted"):
        download.extract_partition(tmp_path, "buildings", "all", None, settings)


def test_truncated_download_is_not_marked_complete(tmp_path, monkeypatch):
    def get(url, settings, params=None):
        if params["$select"] == "count(*) AS n":
            return SimpleNamespace(json=lambda: [{"n": "4"}])
        return response([{"buildingid": "1"}])

    monkeypatch.setattr(download, "get", get)
    with pytest.raises(ValueError, match="Count changed/missing"):
        download.extract_partition(tmp_path, "buildings", "all", None, {"page_size": 2})
    assert not (tmp_path / "manifests/buildings-all.json").exists()
    assert not (tmp_path / "raw/buildings/all.csv.gz").exists()


def test_date_boundaries_and_undated_audit_partition():
    selected = partitions(SOURCES["complaints"], 2023, 2024)
    assert [label for label, _ in selected] == ["2023", "2024", "undated"]
    assert "< '2025-01-01T00:00:00'" in selected[1][1]
    assert selected[-1][1] == "received_date IS NULL"


def test_schema_drift_is_explicit():
    with pytest.raises(ValueError, match="missing source columns"):
        download.check_schema(SOURCES["buildings"], {"columns": [{"fieldName": "buildingid"}]})


def test_smaller_page_retry_does_not_truncate_the_partition(tmp_path, monkeypatch):
    def get(url, settings, params=None):
        if params["$select"] == "count(*) AS n":
            return SimpleNamespace(json=lambda: [{"n": "4"}])
        if "$where" not in params:
            if params["$limit"] == 4:
                raise requests.ReadTimeout("simulated slow page")
            assert params["$limit"] == 2
            return response([{"buildingid": "1"}, {"buildingid": "2"}])
        assert params["$where"] == "(buildingid > 2)"
        return response([{"buildingid": "3"}, {"buildingid": "4"}])

    monkeypatch.setattr(download, "get", get)
    monkeypatch.setattr(download.time, "sleep", lambda seconds: None)
    result = download.extract_partition(tmp_path, "buildings", "all", None, {"page_size": 4})
    assert result["rows"] == 4
    assert [query["rows"] for query in result["queries"]] == [2, 2]
