#!/usr/bin/env python3
"""Validate generated NHF SWE CSVs."""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import pandas as pd


def is_s3_path(path: str) -> bool:
    return str(path).startswith("s3://")


def copy_from_s3_or_local(src: str, dst: str | Path) -> bool:
    if is_s3_path(src):
        try:
            subprocess.run(["aws", "s3", "cp", src, str(dst), "--only-show-errors"], check=True)
            return True
        except Exception:
            return False
    if os.path.exists(src):
        Path(dst).write_bytes(Path(src).read_bytes())
        return True
    return False


@dataclass
class ValidationResult:
    gage_id: str
    domain: str
    status: str
    file: str
    rows: int = 0
    valid_values: int = 0
    missing_dates: int = 0
    duplicate_dates: int = 0
    sorted: bool = True
    note: str = ""


def validate_one(csv_prefix: str, gage_id: str, domain: str, start_date: str, end_date: str, scratch_dir: Path) -> ValidationResult:
    src = f"{csv_prefix.rstrip('/')}/gages-{gage_id}_swe.csv"
    local = scratch_dir / f"gages-{gage_id}_swe.csv"
    if not copy_from_s3_or_local(src, local):
        return ValidationResult(gage_id, domain, "missing", src, note="file not found or not readable")

    try:
        df = pd.read_csv(local)
        if "timestamp" not in df.columns or "basin_avg_swe" not in df.columns:
            return ValidationResult(gage_id, domain, "bad_schema", src, rows=len(df), note=f"columns={list(df.columns)}")
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        if df["timestamp"].isna().all():
            return ValidationResult(gage_id, domain, "bad_dates", src, rows=len(df), note="all timestamps failed to parse")
        duplicate_dates = int(df["timestamp"].duplicated().sum())
        sorted_flag = bool(df["timestamp"].is_monotonic_increasing)
        df_sorted = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        expected = pd.date_range(start=start_date, end=end_date, freq="D")
        actual = pd.DatetimeIndex(df_sorted["timestamp"].dt.normalize().unique())
        missing_dates = len(expected.difference(actual))
        valid_values = int(pd.to_numeric(df["basin_avg_swe"], errors="coerce").notna().sum())

        if duplicate_dates > 0:
            status = "duplicate_dates"
        elif not sorted_flag:
            status = "unsorted"
        elif missing_dates > 0:
            status = "missing_dates"
        elif valid_values == 0:
            status = "no_valid_values"
        else:
            values = pd.to_numeric(df["basin_avg_swe"], errors="coerce")
            status = "valid_zero_snow" if values.fillna(0).abs().sum() == 0 else "valid"
        return ValidationResult(gage_id, domain, status, src, len(df), valid_values, missing_dates, duplicate_dates, sorted_flag, "")
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(gage_id, domain, "read_error", src, note=repr(exc))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate NHF SWE CSV outputs.")
    parser.add_argument("--csv-prefix", required=True, help="Local or s3:// prefix containing gages-<id>_swe.csv files.")
    parser.add_argument("--gage-list", required=True, help="USGS_gages.txt or equivalent gage list.")
    parser.add_argument("--domains", nargs="+", default=["CONUS", "Alaska", "Hawaii"])
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--report", default="swe_nhf_validation.csv")
    parser.add_argument("--scratch-dir", default="/tmp/swe_nhf_validate")
    args = parser.parse_args()

    domains = set(args.domains)
    scratch = Path(args.scratch_dir)
    scratch.mkdir(parents=True, exist_ok=True)
    rows = []
    with open(args.gage_list, "r", encoding="utf-8") as fp:
        for raw in fp:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.replace(",", " ").split()
            if len(parts) < 2:
                continue
            gage_id, domain = parts[0], parts[1]
            if domain not in domains:
                continue
            rows.append(validate_one(args.csv_prefix, gage_id, domain, args.start_date, args.end_date, scratch))

    with open(args.report, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(asdict(rows[0]).keys()) if rows else ["gage_id", "domain", "status"])
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
    print(f"Wrote validation report: {args.report}")
    if rows:
        counts = {}
        for row in rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        for status, count in sorted(counts.items()):
            print(f"{status}: {count}")


if __name__ == "__main__":
    main()
