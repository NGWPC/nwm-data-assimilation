#!/usr/bin/env python3
"""Validate generated NHF SWE CSVs for multiple gage providers."""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

try:
    from data_assimilation_engine.swe.SNODAS_preprocessing.nhf_gage_list_utils import (
        normalize_domain,
        read_gage_lists,
        safe_file_id,
    )
except ImportError:
    from nhf_gage_list_utils import normalize_domain, read_gage_lists, safe_file_id


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
    file_id: str
    domain: str
    agency: str
    status: str
    file: str
    rows: int = 0
    valid_values: int = 0
    missing_dates: int = 0
    duplicate_dates: int = 0
    sorted: bool = True
    note: str = ""


def validate_one(csv_prefix: str, gage_id: str, domain: str, agency: str, start_date: str, end_date: str, scratch_dir: Path) -> ValidationResult:
    file_id = safe_file_id(gage_id)
    src = f"{csv_prefix.rstrip('/')}/gages-{file_id}_swe.csv"
    local = scratch_dir / f"gages-{file_id}_swe.csv"
    if not copy_from_s3_or_local(src, local):
        return ValidationResult(gage_id, file_id, domain, agency, "missing", src, note="file not found or not readable")

    try:
        df = pd.read_csv(local)
        if "timestamp" not in df.columns or "basin_avg_swe" not in df.columns:
            return ValidationResult(gage_id, file_id, domain, agency, "bad_schema", src, rows=len(df), note=f"columns={list(df.columns)}")
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        if df["timestamp"].isna().all():
            return ValidationResult(gage_id, file_id, domain, agency, "bad_dates", src, rows=len(df), note="all timestamps failed to parse")
        duplicate_dates = int(df["timestamp"].duplicated().sum())
        sorted_flag = bool(df["timestamp"].is_monotonic_increasing)
        df_sorted = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        expected = pd.date_range(start=start_date, end=end_date, freq="D")
        actual = pd.DatetimeIndex(df_sorted["timestamp"].dt.normalize().unique())
        missing_dates = len(expected.difference(actual))
        values = pd.to_numeric(df["basin_avg_swe"], errors="coerce")
        valid_values = int(values.notna().sum())

        if duplicate_dates > 0:
            status = "duplicate_dates"
        elif not sorted_flag:
            status = "unsorted"
        elif missing_dates > 0:
            status = "missing_dates"
        elif valid_values == 0:
            status = "no_valid_values"
        else:
            status = "valid_zero_snow" if values.fillna(0).abs().sum() == 0 else "valid"
        return ValidationResult(gage_id, file_id, domain, agency, status, src, len(df), valid_values, missing_dates, duplicate_dates, sorted_flag, "")
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(gage_id, file_id, domain, agency, "read_error", src, note=repr(exc))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate NHF SWE CSV outputs.")
    parser.add_argument("--csv-prefix", required=True, help="Local or s3:// prefix containing gages-<id>_swe.csv files.")
    parser.add_argument("--gage-list", required=True, nargs="+", help="One or more gage-list files.")
    parser.add_argument("--domains", nargs="+", default=["CONUS", "Alaska", "Hawaii"])
    parser.add_argument("--agencies", nargs="+", default=None, help="Optional agency/provider filter, e.g. USGS ENVCA TXDOT CADWR.")
    parser.add_argument("--default-domain", default="CONUS")
    parser.add_argument("--default-agency", default="")
    parser.add_argument("--enabled-only", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="Optional limit for smoke-test validation.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--report", default="swe_nhf_validation.csv")
    parser.add_argument("--scratch-dir", default="/tmp/swe_nhf_validate")
    args = parser.parse_args()

    domains = {normalize_domain(d) for d in args.domains}
    scratch = Path(args.scratch_dir)
    scratch.mkdir(parents=True, exist_ok=True)

    records = read_gage_lists(
        args.gage_list,
        domains=domains,
        default_domain=args.default_domain,
        default_agency=args.default_agency,
        enabled_only=args.enabled_only,
        limit=args.limit,
    )

    agency_filter = {a.upper() for a in args.agencies} if args.agencies else None

    if agency_filter:
        records = [r for r in records if (r.agency or "").upper() in agency_filter]

    rows = [
        validate_one(
            args.csv_prefix,
            r.gage_id,
            r.domain,
            r.agency,
            args.start_date,
            args.end_date,
            scratch,
        )
        for r in records
    ]

    with open(args.report, "w", newline="", encoding="utf-8") as fp:
        fieldnames = list(asdict(rows[0]).keys()) if rows else ["gage_id", "file_id", "domain", "agency", "status"]
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
    print(f"Wrote validation report: {args.report}")
    if rows:
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        for status, count in sorted(counts.items()):
            print(f"{status}: {count}")


if __name__ == "__main__":
    main()
