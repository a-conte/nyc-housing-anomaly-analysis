"""Resumable, counted, hashed extracts from the public Socrata API.

Raw files retain source column names and values. Only the selected columns and event
date window are restricted. No apartment numbers or contact names are requested.
"""

import csv
import gzip
import hashlib
import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import requests

from housing.sources import SOURCES, partitions


def now():
    return datetime.now(UTC).isoformat()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def get(url, settings, params=None):
    headers = {"User-Agent": "nyc-housing-data/0.1 (public research)"}
    if os.environ.get("SOCRATA_APP_TOKEN"):
        headers["X-App-Token"] = os.environ["SOCRATA_APP_TOKEN"]
    for attempt in range(settings["attempts"]):
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=(15, settings["timeout_seconds"]),
            )
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            elif response.status_code >= 400:
                # Invalid queries and permissions are not transient failures.
                raise ValueError(f"HTTP {response.status_code}: {response.text[:500]}")
            return response
        except requests.RequestException as error:
            if attempt + 1 == settings["attempts"]:
                raise
            print(f"retry {url}: {type(error).__name__} ({attempt + 1})", flush=True)
            time.sleep(min(2**attempt, 16))


def check_schema(source, metadata):
    fields = {column["fieldName"] for column in metadata["columns"]}
    missing = set(source.columns) - fields
    if missing:
        raise ValueError(f"{source.dataset_id}: missing source columns {sorted(missing)}")


def get_page(url, settings, params):
    """A slow page can be retried at a smaller size without changing its selection."""
    for attempt in range(settings.get("attempts", 4)):
        try:
            return get(url, {**settings, "attempts": 1}, params)
        except requests.RequestException:
            if attempt + 1 == settings.get("attempts", 4):
                raise
            params["$limit"] = max(1, params["$limit"] // 2)
            print(f"retry smaller page: {url}, limit={params['$limit']}", flush=True)
            time.sleep(min(2**attempt, 16))


def extract_partition(root, name, label, where, settings):
    source = SOURCES[name]
    path = root / "raw" / name / f"{label}.csv.gz"
    manifest_path = root / "manifests" / f"{name}-{label}.json"
    signature = {"dataset_id": source.dataset_id, "columns": list(source.columns), "where": where}
    if manifest_path.exists() and path.exists():
        prior = json.loads(manifest_path.read_text())
        if prior["selection"] != signature or prior["sha256"] != sha256(path):
            raise ValueError(f"Changed selection or corrupted cached extract: {path}")
        print(f"cached {name}/{label}: {prior['rows']:,} rows", flush=True)
        return prior

    started = now()
    count_params = {"$select": "count(*) AS n"}
    if where:
        count_params["$where"] = where
    expected = int(get(source.api + ".json", settings, count_params).json()[0]["n"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    queries, count, last_key = [], 0, None
    # Page in stable primary-key order, avoiding offset drift on the live endpoint.
    # Count reconciliation detects skipped/added records; status updates remain possible.
    with gzip.open(temporary, "wt", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(source.columns)
        while True:
            conditions = [where] if where else []
            if last_key is not None:
                conditions.append(f"{source.key} > {last_key}")
            params = {
                "$select": ",".join(source.columns),
                "$order": source.key,
                "$limit": settings["page_size"],
            }
            if conditions:
                params["$where"] = " AND ".join(f"({c})" for c in conditions)
            response = get_page(source.api + ".csv", settings, params)
            rows = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
            if rows.fieldnames != list(source.columns):
                raise ValueError(f"Unexpected CSV header for {name}: {rows.fieldnames}")
            page_count = 0
            for row in rows:
                key = Decimal(row[source.key])
                if last_key is not None and key <= last_key:
                    raise ValueError(f"Non-unique or unordered {source.key}: {key}")
                last_key = key
                writer.writerow([row[column] for column in source.columns])
                page_count += 1
            queries.append({"url": response.url, "rows": page_count})
            count += page_count
            print(f"download {name}/{label}: {count:,}/{expected:,}", flush=True)
            if page_count < params["$limit"]:
                break
    after = int(get(source.api + ".json", settings, count_params).json()[0]["n"])
    if count != expected or count != after:
        raise ValueError(
            f"Count changed/missing rows in {name}/{label}: "
            f"before={expected}, downloaded={count}, after={after}. Retry this partition."
        )
    temporary.replace(path)
    manifest = {
        "selection": signature,
        "path": str(path.relative_to(root)),
        "started_at": started,
        "completed_at": now(),
        "rows": count,
        "source_count_before": expected,
        "source_count_after": after,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "queries": queries,
    }
    save_json(manifest_path, manifest)
    return manifest


def download(root, config):
    root = Path(root)
    settings = config["download"]
    study = config["study"]
    contract = {"study": study, "sources": list(SOURCES)}
    run_path = root / "run.json"
    if run_path.exists():
        run = json.loads(run_path.read_text())
        if run["contract"] != contract:
            raise ValueError("This snapshot has a different study selection; use a new --snapshot.")
        if run.get("complete"):
            for path in (root / "manifests").glob("*.json"):
                manifest = json.loads(path.read_text())
                if sha256(root / manifest["path"]) != manifest["sha256"]:
                    raise ValueError(f"Corrupted extract: {manifest['path']}")
            print(f"verified cached snapshot: {root}", flush=True)
            return
    else:
        run = {"contract": contract, "started_at": now(), "complete": False}
        save_json(run_path, run)

    for name, source in SOURCES.items():
        metadata = get(source.metadata_url, settings).json()
        check_schema(source, metadata)
        metadata_path = root / "metadata" / f"{name}-before.json"
        if not metadata_path.exists():
            save_json(metadata_path, metadata)

    tasks = [
        (name, label, where)
        for name, source in SOURCES.items()
        for label, where in partitions(source, study["start_year"], study["end_year"])
    ]
    failures = []
    with ThreadPoolExecutor(max_workers=settings["workers"]) as pool:
        futures = [
            pool.submit(extract_partition, root, name, label, where, settings)
            for name, label, where in tasks
        ]
        for future in as_completed(futures):
            try:
                future.result()
            except (requests.RequestException, ValueError, OSError, ArithmeticError) as error:
                failures.append(str(error))
                print(f"partition failed; other extracts continue: {error}", flush=True)
    if failures:
        raise RuntimeError(f"Incomplete snapshot; rerun to resume: {failures}")

    changed = []
    for name, source in SOURCES.items():
        metadata = get(source.metadata_url, settings).json()
        check_schema(source, metadata)
        save_json(root / "metadata" / f"{name}-after.json", metadata)
        original = json.loads((root / "metadata" / f"{name}-before.json").read_text())
        if metadata.get("rowsUpdatedAt") != original.get("rowsUpdatedAt"):
            changed.append(name)
    run.update(complete=True, completed_at=now(), sources_updated_during_extract=changed)
    save_json(run_path, run)
    print(f"snapshot complete: {root}; sources updated during extraction: {changed}", flush=True)
