"""Validate generated SNODAS SWE gage CSVs.

This script catches the exact issues reported for the preprocessed SNODAS CSVs:
missing files, non-daily spacing, unsorted timestamps, duplicates, and missing values.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import fsspec
import pandas as pd


def read_csv(path: str) -> pd.DataFrame | None:
    try:
        if path.startswith("s3://"):
            fs = fsspec.filesystem("s3")
            if not fs.exists(path):
                return None
            with fs.open(path, "rb") as f:
                return pd.read_csv(f)
        if not Path(path).exists():
            return None
        return pd.read_csv(path)
    except Exception as exc:
        return pd.DataFrame({"__read_error__": [str(exc)]})


def validate_one(csv_prefix: str, gage_id: str, start_date: str, end_date: str) -> dict:
    path = f"{csv_prefix.rstrip('/')}/gages-{gage_id}_swe.csv"
    row = {"gage_id": gage_id, "csv_path": path}
    df = read_csv(path)
    if df is None:
        row.update({"status": "missing_csv", "rows": 0})
        return row
    if "__read_error__" in df.columns:
        row.update({"status": "read_error", "error": df["__read_error__"].iloc[0]})
        return row

    timestamp_col = "timestamp" if "timestamp" in df.columns else df.columns[0]
    value_col = "basin_avg_swe" if "basin_avg_swe" in df.columns else None
    if value_col is None:
        row.update({"status": "missing_basin_avg_swe_column", "columns": ",".join(df.columns)})
        return row

    times = pd.to_datetime(df[timestamp_col], errors="coerce")
    valid_times = times.dropna()
    expected = pd.date_range(start_date, end_date, freq="D")
    normalized = pd.DatetimeIndex(valid_times.dt.normalize().unique()).sort_values()
    missing_dates = expected.difference(normalized)
    extra_dates = normalized.difference(expected)
    duplicate_dates = int(valid_times.dt.normalize().duplicated().sum())
    sorted_ok = valid_times.is_monotonic_increasing
    null_values = int(df[value_col].isna().sum())

    if len(valid_times) == 0:
        status = "no_valid_timestamps"
    elif len(missing_dates) > 0 or duplicate_dates > 0 or not sorted_ok:
        status = "invalid_needs_recompute"
    else:
        status = "valid"

    row.update(
        {
            "status": status,
            "rows": len(df),
            "valid_timestamps": len(valid_times),
            "expected_days": len(expected),
            "first_timestamp": str(valid_times.min()) if len(valid_times) else "",
            "last_timestamp": str(valid_times.max()) if len(valid_times) else "",
            "missing_date_count": len(missing_dates),
            "duplicate_date_count": duplicate_dates,
            "extra_date_count": len(extra_dates),
            "is_sorted": bool(sorted_ok),
            "null_value_count": null_values,
            "missing_dates_sample": ";".join(d.strftime("%Y-%m-%d") for d in missing_dates[:20]),
        }
    )
    return row


def main(csv_prefix: str, gage_ids: list[str], start_date: str, end_date: str, report: str):
    rows = [validate_one(csv_prefix, str(g), start_date, end_date) for g in gage_ids]
    out = pd.DataFrame(rows)
    out.to_csv(report, index=False)
    print(f"Wrote validation report: {report}")
    print(out["status"].value_counts(dropna=False).to_string())


def parse_args():
    parser = argparse.ArgumentParser(description="Validate SNODAS gage SWE CSV completeness.")
    parser.add_argument("--csv-prefix", required=True, help="Local or s3:// directory containing gages-<gage_id>_swe.csv")
    parser.add_argument("--gage-ids", nargs="+", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--report", default="swe_csv_validation.csv")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(args.csv_prefix, args.gage_ids, args.start_date, args.end_date, args.report)
