"""Compare basin-level ISMN soil moisture against modeled basin-average soil moisture.

This script is meant for quick validation after:
1. ISMN archive creation
2. station top-1m reduction
3. basin CSV generation
4. modeled basin-average generation from NGen catchment outputs

It reads:
- ISMN basin CSV:
    gages-{gage_id}_soil_moisture.csv
    columns: timestamp, basin_avg_soil_moisture

- modeled catchment CSVs from an NGen output directory
  using the existing SoilMoistureFileLoader + SoilMoistureDataParser logic

It reports:
- overlap period
- correlation
- MAE / RMSE / bias
- quick sample table
"""

from __future__ import annotations

import argparse
import logging

import fsspec
import numpy as np
import pandas as pd

from data_assimilation_engine.soil_moisture.timeseries.timeseries import (
    SoilMoistureDataParser,
    SoilMoistureFileLoader,
)

logger = logging.getLogger(__name__)


def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def load_ismn_basin_csv(output_root: str, gage_id: str) -> pd.DataFrame:
    fs = fsspec.filesystem("file")
    path = f"{output_root.rstrip('/')}/ismn_csv/gages-{gage_id}_soil_moisture.csv"
    if not fs.exists(path):
        raise FileNotFoundError(f"ISMN basin CSV not found: {path}")

    with fs.open(path, "r") as f:
        df = pd.read_csv(f)

    expected = {"timestamp", "basin_avg_soil_moisture"}
    missing = expected.difference(df.columns)
    if missing:
        raise ValueError(f"ISMN basin CSV missing columns: {sorted(missing)}")

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["ismn_soil_moisture"] = pd.to_numeric(df["basin_avg_soil_moisture"], errors="coerce")
    df = df.dropna(subset=["timestamp", "ismn_soil_moisture"])
    return df[["timestamp", "ismn_soil_moisture"]].sort_values("timestamp").reset_index(drop=True)


def load_modeled_basin_ts(csv_directory: str, gpkg_file: str) -> pd.DataFrame:
    """Use existing soil-moisture workflow logic to compute modeled basin average."""
    file_loader = SoilMoistureFileLoader(csv_directory, gpkg_file)
    parser = SoilMoistureDataParser(file_loader.times, file_loader.ids)

    sim_df = parser.parse_simulated_data(file_loader.csv_files)
    basin_avg = parser.calculate_basin_average(sim_df, file_loader.catchment_areas)

    out = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(file_loader.times, utc=True),
            "modeled_soil_moisture": basin_avg,
        }
    )
    out = out.dropna(subset=["timestamp", "modeled_soil_moisture"])
    return out.sort_values("timestamp").reset_index(drop=True)


def compute_metrics(df: pd.DataFrame) -> dict:
    x = df["modeled_soil_moisture"].to_numpy(dtype=float)
    y = df["ismn_soil_moisture"].to_numpy(dtype=float)

    diff = x - y
    mae = float(np.mean(np.abs(diff)))
    rmse = float(np.sqrt(np.mean(diff ** 2)))
    bias = float(np.mean(diff))
    corr = float(np.corrcoef(x, y)[0, 1]) if len(df) > 1 else np.nan

    return {
        "n_overlap": int(len(df)),
        "mae": mae,
        "rmse": rmse,
        "bias_model_minus_ismn": bias,
        "correlation": corr,
        "model_mean": float(np.mean(x)),
        "ismn_mean": float(np.mean(y)),
    }


def print_metrics(metrics: dict) -> None:
    print("\n" + "=" * 80)
    print("ISMN vs Modeled Basin Soil Moisture Metrics")
    print("=" * 80)
    for k, v in metrics.items():
        print(f"{k}: {v}")


def print_sample(df: pd.DataFrame, n: int = 10) -> None:
    print("\n" + "=" * 80)
    print(f"Sample overlap rows (first {n})")
    print("=" * 80)
    sample = df.copy()
    sample["abs_diff"] = (sample["modeled_soil_moisture"] - sample["ismn_soil_moisture"]).abs()
    print(sample.head(n).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare ISMN basin CSV against modeled basin-average soil moisture."
    )
    parser.add_argument("--output-root", required=True, help="ISMN pipeline output root")
    parser.add_argument("--gage-id", required=True, help="Target gage/basin id")
    parser.add_argument("--csv-directory", required=True, help="Directory with modeled cat-*.csv files")
    parser.add_argument("--gpkg-file", required=True, help="Basin geopackage used by modeled workflow")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    configure_logging(args.verbose)

    ismn_df = load_ismn_basin_csv(args.output_root, args.gage_id)
    modeled_df = load_modeled_basin_ts(args.csv_directory, args.gpkg_file)

    merged = modeled_df.merge(ismn_df, on="timestamp", how="inner")
    if merged.empty:
        raise ValueError("No overlapping timestamps between modeled and ISMN basin data")

    print("\nOverlap start:", merged["timestamp"].min())
    print("Overlap end:  ", merged["timestamp"].max())
    print("Overlap rows: ", len(merged))

    metrics = compute_metrics(merged)
    print_metrics(metrics)
    print_sample(merged, n=12)


if __name__ == "__main__":
    main()
