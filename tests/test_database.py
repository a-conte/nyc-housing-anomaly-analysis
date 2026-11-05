import csv
import gzip
import json

import pytest

from housing.database import verify_snapshot
from housing.download import save_json, sha256
from housing.sources import SOURCES, partitions


@pytest.fixture
def snapshot(tmp_path):
    config = {"study": {"start_year": 2021, "end_year": 2021}}
    save_json(
        tmp_path / "run.json",
        {"complete": True, "contract": {"study": config["study"], "sources": list(SOURCES)}},
    )
    for name, source in SOURCES.items():
        for stage in ("before", "after"):
            save_json(
                tmp_path / "metadata" / f"{name}-{stage}.json",
                {"id": source.dataset_id, "columns": [{"fieldName": c} for c in source.columns]},
            )
        for label, where in partitions(source, 2021, 2021):
            path = tmp_path / "raw" / name / f"{label}.csv.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(path, "wt", newline="") as stream:
                csv.writer(stream).writerow(source.columns)
            save_json(
                tmp_path / "manifests" / f"{name}-{label}.json",
                {
                    "selection": {
                        "dataset_id": source.dataset_id,
                        "columns": list(source.columns),
                        "where": where,
                    },
                    "path": str(path.relative_to(tmp_path)),
                    "rows": 0,
                    "source_count_before": 0,
                    "source_count_after": 0,
                    "queries": [{"rows": 0}],
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                },
            )
    return tmp_path, config


def test_snapshot_verifies_all_expected_partitions_offline(snapshot):
    root, config = snapshot
    _, manifests = verify_snapshot(root, config)
    assert len(manifests) == 6
    assert {m["partition"] for m in manifests} == {"2021", "undated", "all"}


def test_snapshot_rejects_same_size_corruption(snapshot):
    root, config = snapshot
    path = root / "raw/violations/2021.csv.gz"
    content = bytearray(path.read_bytes())
    content[-1] ^= 1
    path.write_bytes(content)
    with pytest.raises(ValueError, match="Checksum mismatch"):
        verify_snapshot(root, config)


def test_snapshot_rejects_invalid_gzip_even_when_checksum_matches(snapshot):
    root, config = snapshot
    path = root / "raw/complaints/2021.csv.gz"
    path.write_bytes(path.read_bytes() + b"invalid trailing gzip member")
    manifest_path = root / "manifests/complaints-2021.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.update(bytes=path.stat().st_size, sha256=sha256(path))
    save_json(manifest_path, manifest)
    with pytest.raises(gzip.BadGzipFile):
        verify_snapshot(root, config)


@pytest.mark.parametrize("field", ["source_count_before", "source_count_after", "queries"])
def test_snapshot_rejects_unreconciled_counts(snapshot, field):
    root, config = snapshot
    path = root / "manifests/violations-2021.json"
    manifest = json.loads(path.read_text())
    manifest[field] = [{"rows": 1}] if field == "queries" else 1
    save_json(path, manifest)
    with pytest.raises(ValueError, match="counts do not reconcile"):
        verify_snapshot(root, config)


def test_snapshot_requires_every_manifest(snapshot):
    root, config = snapshot
    (root / "manifests/violations-undated.json").unlink()
    with pytest.raises(FileNotFoundError):
        verify_snapshot(root, config)


def test_snapshot_rejects_wrong_source_schema(snapshot):
    root, config = snapshot
    path = root / "metadata/buildings-after.json"
    metadata = json.loads(path.read_text())
    metadata["columns"].pop()
    save_json(path, metadata)
    with pytest.raises(ValueError, match="missing source columns"):
        verify_snapshot(root, config)
