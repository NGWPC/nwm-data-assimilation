"""Quick validation script for one ISMN basin product.

Checks:
1. Station index contains the basin/gage
2. Raw archive exists for the basin
3. Station top-1m archive exists for the basin
4. Basin CSV exists and has expected schema
5. Basic summary stats are reasonable

Usage:
    python -m data_assimilation_engine.soil_moisture.ISMN_preprocessing.check_ismn_basin_product \
        --output-root /path/to/output \
        --gage-id 01435000
"""

from __future__ import annotations

import argparse
import logging
from typing import Optional

import fsspec
import pandas as pd

logger = logging.getLogger(__name__)


def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def discover_files(
    fs: fsspec.AbstractFileSystem,
    source: str,
    suffix: str,
) -> list[str]:
    found: list[str] = []

    def _walk(path: str) -> None:
        if fs.isfile(path) and path.lower().endswith(suffix.lower()):
            found.append(path)
            return
        if not fs.isdir(path):
            return
        for entry in fs.ls(path, detail=True):
            entry_path = entry["name"]
            entry_type = entry["type"]
            if entry_type == "file" and entry_path.lower().endswith(suffix.lower()):
                found.append(entry_path)
            elif entry_type == "directory":
                _walk(entry_path)

    _walk(source)
    return found


def load_parquets(
    fs: fsspec.AbstractFileSystem,
    source: str,
) -> pd.DataFrame:
    paths = discover_files(fs, source, ".parquet")
    if not paths:
        return pd.DataFrame()

    dfs = []
    for path in paths:
        with fs.open(path, "rb") as f:
            dfs.append(pd.read_parquet(f))

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True)


def print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def summarize_station_index(
    fs: fsspec.AbstractFileSystem,
    output_root: str,
    gage_id: str,
) -> None:
    print_header("1. Station Index Check")

    station_index_path = f"{output_root.rstrip('/')}/ismn_station_index.parquet"
    if not fs.exists(station_index_path):
        print(f"[FAIL] Missing station index: {station_index_path}")
        return

    with fs.open(station_index_path, "rb") as f:
        df = pd.read_parquet(f)

    basin_df = df[df["gage_id"].astype(str) == str(gage_id)].copy()

    print(f"Station index path: {station_index_path}")
    print(f"Total station index rows: {len(df)}")
    print(f"Rows mapped to gage {gage_id}: {len(basin_df)}")

    if basin_df.empty:
        print(f"[WARN] No stations mapped to gage {gage_id}")
        return

    display_cols = [c for c in ["network", "station", "station_key", "latitude", "longitude"] if c in basin_df.columns]
    print("\nMapped stations (first 10):")
    print(basin_df[display_cols].head(10).to_string(index=False))


def summarize_raw_archive(
    fs: fsspec.AbstractFileSystem,
    output_root: str,
    gage_id: str,
) -> None:
    print_header("2. Raw Archive Check")

    raw_root = f"{output_root.rstrip('/')}/ismn_raw/gage_{gage_id}"
    if not fs.exists(raw_root):
        print(f"[FAIL] Raw archive root missing: {raw_root}")
        return

    df = load_parquets(fs, raw_root)
    print(f"Raw archive root: {raw_root}")
    print(f"Raw archive rows: {len(df)}")

    if df.empty:
        print("[WARN] No raw parquet rows found")
        return

    cols = [c for c in [
        "network", "station", "utc_actual",
        "depth_from_m", "depth_to_m",
        "soil_moisture_m3m3", "ismn_flag", "provider_flag"
    ] if c in df.columns]

    print("\nRaw sample rows:")
    print(df[cols].head(10).to_string(index=False))

    if "soil_moisture_m3m3" in df.columns:
        sm = pd.to_numeric(df["soil_moisture_m3m3"], errors="coerce")
        print("\nRaw soil moisture summary:")
        print(sm.describe().to_string())

    if {"depth_from_m", "depth_to_m"}.issubset(df.columns):
        depth_df = df[["depth_from_m", "depth_to_m"]].drop_duplicates().sort_values(["depth_from_m", "depth_to_m"])
        print("\nDistinct depth intervals (first 20):")
        print(depth_df.head(20).to_string(index=False))


def summarize_station_top1m(
    fs: fsspec.AbstractFileSystem,
    output_root: str,
    gage_id: str,
) -> None:
    print_header("3. Station Top-1m Check")

    top1m_root = f"{output_root.rstrip('/')}/ismn_station_top1m/gage_{gage_id}"
    if not fs.exists(top1m_root):
        print(f"[FAIL] Station top-1m archive root missing: {top1m_root}")
        return

    df = load_parquets(fs, top1m_root)
    print(f"Station top-1m root: {top1m_root}")
    print(f"Station top-1m rows: {len(df)}")

    if df.empty:
        print("[WARN] No station top-1m parquet rows found")
        return

    cols = [c for c in [
        "network", "station", "timestamp",
        "soil_moisture", "valid_thickness_m",
        "coverage_fraction", "n_layers_used"
    ] if c in df.columns]

    print("\nStation top-1m sample rows:")
    print(df[cols].head(10).to_string(index=False))

    if "soil_moisture" in df.columns:
        sm = pd.to_numeric(df["soil_moisture"], errors="coerce")
        print("\nStation top-1m soil moisture summary:")
        print(sm.describe().to_string())

    if "coverage_fraction" in df.columns:
        cov = pd.to_numeric(df["coverage_fraction"], errors="coerce")
        print("\nCoverage fraction summary:")
        print(cov.describe().to_string())

    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        print("\nTime range:")
        print(f"Start: {ts.min()}")
        print(f"End:   {ts.max()}")

    if {"station_key", "timestamp"}.issubset(df.columns):
        dup_count = df.duplicated(subset=["station_key", "timestamp"]).sum()
        print(f"\nDuplicate station/timestamp rows: {dup_count}")


def summarize_basin_csv(
    fs: fsspec.AbstractFileSystem,
    output_root: str,
    gage_id: str,
) -> None:
    print_header("4. Basin CSV Check")

    basin_csv = f"{output_root.rstrip('/')}/ismn_csv/gages-{gage_id}_soil_moisture.csv"
    if not fs.exists(basin_csv):
        print(f"[FAIL] Missing basin CSV: {basin_csv}")
        return

    with fs.open(basin_csv, "r") as f:
        df = pd.read_csv(f)

    print(f"Basin CSV path: {basin_csv}")
    print(f"Basin CSV rows: {len(df)}")
    print(f"Columns: {list(df.columns)}")

    expected_cols = ["timestamp", "basin_avg_soil_moisture"]
    if list(df.columns) != expected_cols:
        print(f"[WARN] Expected columns {expected_cols}, got {list(df.columns)}")
    else:
        print("[PASS] Basin CSV schema matches expected contract")

    if df.empty:
        print("[WARN] Basin CSV is empty")
        return

    print("\nBasin CSV sample rows:")
    print(df.head(10).to_string(index=False))

    ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    sm = pd.to_numeric(df["basin_avg_soil_moisture"], errors="coerce")

    print("\nBasin time range:")
    print(f"Start: {ts.min()}")
    print(f"End:   {ts.max()}")

    print("\nBasin soil moisture summary:")
    print(sm.describe().to_string())

    bad = (~sm.between(0.0, 1.0, inclusive="both")).sum()
    print(f"\nValues outside [0, 1]: {int(bad)}")


def summarize_metadata_csv(
    fs: fsspec.AbstractFileSystem,
    output_root: str,
    gage_id: str,
) -> None:
    print_header("5. Basin Metadata CSV Check")

    meta_csv = f"{output_root.rstrip('/')}/ismn_csv_metadata/gages-{gage_id}_soil_moisture_metadata.csv"
    if not fs.exists(meta_csv):
        print(f"[WARN] Metadata CSV not found: {meta_csv}")
        return

    with fs.open(meta_csv, "r") as f:
        df = pd.read_csv(f)

    print(f"Metadata CSV path: {meta_csv}")
    print(f"Metadata rows: {len(df)}")
    print(f"Columns: {list(df.columns)}")

    if df.empty:
        print("[WARN] Metadata CSV is empty")
        return

    print("\nMetadata sample rows:")
    print(df.head(10).to_string(index=False))

    if "station_count" in df.columns:
        station_count = pd.to_numeric(df["station_count"], errors="coerce")
        print("\nStation count summary:")
        print(station_count.describe().to_string())

    if "mean_station_coverage_fraction" in df.columns:
        cov = pd.to_numeric(df["mean_station_coverage_fraction"], errors="coerce")
        print("\nMean station coverage fraction summary:")
        print(cov.describe().to_string())


def summarize_basin_against_station_top1m(
    fs: fsspec.AbstractFileSystem,
    output_root: str,
    gage_id: str,
) -> None:
    print_header("6. Consistency Check: Basin CSV vs Station Top-1m")

    top1m_root = f"{output_root.rstrip('/')}/ismn_station_top1m/gage_{gage_id}"
    basin_csv = f"{output_root.rstrip('/')}/ismn_csv/gages-{gage_id}_soil_moisture.csv"

    if not fs.exists(top1m_root):
        print(f"[WARN] Missing station top-1m root: {top1m_root}")
        return
    if not fs.exists(basin_csv):
        print(f"[WARN] Missing basin CSV: {basin_csv}")
        return

    station_df = load_parquets(fs, top1m_root)
    if station_df.empty:
        print("[WARN] No station top-1m rows found")
        return

    with fs.open(basin_csv, "r") as f:
        basin_df = pd.read_csv(f)

    station_df["timestamp"] = pd.to_datetime(station_df["timestamp"], errors="coerce", utc=True)
    station_df["soil_moisture"] = pd.to_numeric(station_df["soil_moisture"], errors="coerce")
    basin_df["timestamp"] = pd.to_datetime(basin_df["timestamp"], errors="coerce", utc=True)
    basin_df["basin_avg_soil_moisture"] = pd.to_numeric(basin_df["basin_avg_soil_moisture"], errors="coerce")

    mean_station = (
        station_df.groupby("timestamp", dropna=False)["soil_moisture"]
        .mean()
        .reset_index()
        .rename(columns={"soil_moisture": "station_mean"})
    )

    merged = basin_df.merge(mean_station, on="timestamp", how="inner")
    print(f"Merged timestamps: {len(merged)}")

    if merged.empty:
        print("[WARN] No overlapping timestamps between station top-1m and basin CSV")
        return

    merged["abs_diff"] = (merged["basin_avg_soil_moisture"] - merged["station_mean"]).abs()

    print("\nConsistency sample:")
    print(
        merged[
            ["timestamp", "basin_avg_soil_moisture", "station_mean", "abs_diff"]
        ].head(10).to_string(index=False)
    )

    print("\nAbsolute difference summary:")
    print(merged["abs_diff"].describe().to_string())

    print(
        "\nNote: if basin aggregation is set to simple mean and there is no extra filtering "
        "between station top-1m and basin CSV creation, these values should usually match closely."
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check one ISMN basin product end to end."
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="Pipeline output root directory",
    )
    parser.add_argument(
        "--gage-id",
        required=True,
        help="Target gage/basin id to inspect",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    configure_logging(verbose=args.verbose)
    fs = fsspec.filesystem("file")

    summarize_station_index(fs, args.output_root, args.gage_id)
    summarize_raw_archive(fs, args.output_root, args.gage_id)
    summarize_station_top1m(fs, args.output_root, args.gage_id)
    summarize_basin_csv(fs, args.output_root, args.gage_id)
    summarize_metadata_csv(fs, args.output_root, args.gage_id)
    summarize_basin_against_station_top1m(fs, args.output_root, args.gage_id)


if __name__ == "__main__":
    main()
