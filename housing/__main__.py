"""Run from the repository root: python -m housing {download,load,run}."""

import argparse
import tomllib
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["download", "load", "run"])
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--snapshot", type=Path, default=Path("data/snapshot"))
    parser.add_argument("--database", type=Path, default=Path("data/housing.duckdb"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports/phase2"))
    args = parser.parse_args()
    config = tomllib.loads(args.config.read_text())
    start, end = config["study"]["start_year"], config["study"]["end_year"]
    if not (1900 <= start <= end <= 2100):
        parser.error("Invalid study years")
    if args.command in ("download", "run"):
        from housing.download import download

        download(args.snapshot, config)
    if args.command in ("load", "run"):
        from housing.database import build_database

        build_database(args.snapshot, args.database, args.report_dir, config)


if __name__ == "__main__":
    main()
