"""Build basin-level ISMN top-1m soil moisture CSV products.

This module reads station-level top-1m soil moisture time series and produces
one CSV per basin/gage using the contract expected by the soil moisture
timeseries workflow:

    gages-{basin_id}_soil_moisture.csv

with columns:
    - timestamp
    - basin_avg_soil_moisture

Optional metadata products can also be written for debugging/UI support.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import fsspec
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BasinAggregationConfig:
    """Configuration for basin aggregation."""
    min_station_count: int = 1
    min_station_coverage_fraction: float = 0.0
    aggregation_method: str = "mean"  # supported: mean, thickness_weighted
    write_metadata: bool = True


class ISMNBasinTimeseriesBuilder:
    """Aggregate station-level ISMN top-1m soil moisture to basin CSVs."""

    def __init__(
        self,
        station_top1m_source: str,
        output_root: str,
        fs: Optional[fsspec.AbstractFileSystem] = None,
        config: Optional[BasinAggregationConfig] = None,
    ) -> None:
        self.station_top1m_source = station_top1m_source.rstrip("/")
        self.output_root = output_root.rstrip("/")
        self.fs = fs or fsspec.filesystem("file")
        self.config = config or BasinAggregationConfig()

    def run(self) -> pd.DataFrame:
        """Build all basin-level CSV products.

        Returns a summary DataFrame listing what was written.
        """
        station_df = self.load_station_top1m()
        if station_df.empty:
            raise ValueError("No station-level top-1m ISMN data found")

        station_df = self.prepare_station_df(station_df)
        basin_df, meta_df = self.aggregate_to_basin(station_df)

        self.write_basin_csvs(basin_df)

        if self.config.write_metadata and not meta_df.empty:
            self.write_metadata_csvs(meta_df)

        summary = self.build_summary(basin_df, meta_df)
        self.write_summary(summary)
        return summary

    def load_station_top1m(self) -> pd.DataFrame:
        """Load station-level top-1m parquet data.

        This loader supports:
        - a directory containing parquet files
        - a single parquet file
        """
        paths = self.discover_parquet_files(self.station_top1m_source)
        if not paths:
            raise FileNotFoundError(
                f"No parquet files found under {self.station_top1m_source}"
            )

        dfs = []
        for path in paths:
            try:
                with self.fs.open(path, "rb") as f:
                    dfs.append(pd.read_parquet(f))
            except Exception as exc:
                logger.exception("Failed to read %s: %s", path, exc)

        if not dfs:
            return pd.DataFrame()

        return pd.concat(dfs, ignore_index=True)

    def discover_parquet_files(self, source: str) -> list[str]:
        """Recursively discover parquet files."""
        found: list[str] = []
        self._discover_parquet_files(source, found)
        return found

    def _discover_parquet_files(self, source: str, found: list[str]) -> None:
        if self.fs.isfile(source) and source.lower().endswith(".parquet"):
            found.append(source)
            return

        if not self.fs.isdir(source):
            return

        for entry in self.fs.ls(source, detail=True):
            entry_path = entry["name"]
            entry_type = entry["type"]
            if entry_type == "file" and entry_path.lower().endswith(".parquet"):
                found.append(entry_path)
            elif entry_type == "directory":
                self._discover_parquet_files(entry_path, found)

    def prepare_station_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize expected columns and apply basic filtering.

        Important:
        - true integrated rows still use coverage_fraction filtering
        - single_depth_proxy rows are allowed through even when their
          coverage_fraction is 0.0
        """
        required_cols = {
            "gage_id",
            "network",
            "station",
            "station_key",
            "timestamp",
            "soil_moisture",
            "valid_thickness_m",
            "coverage_fraction",
            "n_layers_used",
        }
        missing = required_cols.difference(df.columns)
        if missing:
            raise ValueError(
                f"Station top-1m data missing required columns: {sorted(missing)}"
            )

        df = df.copy()

        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df["soil_moisture"] = pd.to_numeric(df["soil_moisture"], errors="coerce")
        df["valid_thickness_m"] = pd.to_numeric(df["valid_thickness_m"], errors="coerce")
        df["coverage_fraction"] = pd.to_numeric(df["coverage_fraction"], errors="coerce")
        df["n_layers_used"] = pd.to_numeric(df["n_layers_used"], errors="coerce")

        if "method_used" not in df.columns:
            df["method_used"] = "unknown"
        else:
            df["method_used"] = (
                df["method_used"]
                .fillna("unknown")
                .astype(str)
                .str.strip()
            )

        if "num_depths" not in df.columns:
            df["num_depths"] = 1
        else:
            df["num_depths"] = pd.to_numeric(df["num_depths"], errors="coerce").fillna(1).astype(int)

        df = df.dropna(subset=["gage_id", "timestamp", "soil_moisture"])
        df = df[df["soil_moisture"].between(0.0, 1.0, inclusive="both")]

        if self.config.min_station_coverage_fraction > 0.0:
            proxy_mask = df["method_used"] == "single_depth_proxy"
            coverage_mask = df["coverage_fraction"] >= self.config.min_station_coverage_fraction
            df = df[proxy_mask | coverage_mask].copy()

        return df

    def aggregate_to_basin(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Aggregate station-level rows to basin-level time series.

        Proxy rows are allowed to contribute to the basin average, but metadata
        for coverage/thickness should only reflect truly integrated rows.
        """
        basin_rows: list[dict] = []
        meta_rows: list[dict] = []

        grouped = df.groupby(["gage_id", "timestamp"], dropna=False)

        for (gage_id, timestamp), group in grouped:
            station_count = int(group["station_key"].nunique())
            if station_count < self.config.min_station_count:
                continue

            basin_value = self.aggregate_group(group)
            if basin_value is None or np.isnan(basin_value):
                continue

            real_mask = group["method_used"] != "single_depth_proxy"
            proxy_station_count = int((group["method_used"] == "single_depth_proxy").sum())
            integrated_station_count = int(real_mask.sum())

            if real_mask.any():
                mean_station_coverage_fraction = float(group.loc[real_mask, "coverage_fraction"].mean())
                min_station_coverage_fraction = float(group.loc[real_mask, "coverage_fraction"].min())
                max_station_coverage_fraction = float(group.loc[real_mask, "coverage_fraction"].max())
                mean_valid_thickness_m = float(group.loc[real_mask, "valid_thickness_m"].mean())
            else:
                mean_station_coverage_fraction = 0.0
                min_station_coverage_fraction = 0.0
                max_station_coverage_fraction = 0.0
                mean_valid_thickness_m = 0.0

            basin_rows.append(
                {
                    "gage_id": str(gage_id),
                    "timestamp": timestamp,
                    "basin_avg_soil_moisture": basin_value,
                }
            )

            meta_rows.append(
                {
                    "gage_id": str(gage_id),
                    "timestamp": timestamp,
                    "station_count": station_count,
                    "proxy_station_count": proxy_station_count,
                    "integrated_station_count": integrated_station_count,
                    "stations_used": ";".join(sorted(group["station_key"].astype(str).unique())),
                    "mean_station_coverage_fraction": mean_station_coverage_fraction,
                    "min_station_coverage_fraction": min_station_coverage_fraction,
                    "max_station_coverage_fraction": max_station_coverage_fraction,
                    "mean_valid_thickness_m": mean_valid_thickness_m,
                    "methods_used": ";".join(sorted(group["method_used"].astype(str).unique())),
                }
            )

        basin_df = pd.DataFrame(basin_rows)
        meta_df = pd.DataFrame(meta_rows)

        if not basin_df.empty:
            basin_df = basin_df.sort_values(["gage_id", "timestamp"]).reset_index(drop=True)

        if not meta_df.empty:
            meta_df = meta_df.sort_values(["gage_id", "timestamp"]).reset_index(drop=True)

        return basin_df, meta_df

    def aggregate_group(self, group: pd.DataFrame) -> float | None:
        """Aggregate one basin/timestamp station group."""
        method = self.config.aggregation_method.lower()

        if method == "mean":
            return float(group["soil_moisture"].mean())

        if method == "thickness_weighted":
            weights = group["valid_thickness_m"].to_numpy(dtype=float)
            values = group["soil_moisture"].to_numpy(dtype=float)
            if np.sum(weights) <= 0:
                return None
            return float(np.average(values, weights=weights))

        raise ValueError(
            f"Unsupported aggregation_method={self.config.aggregation_method!r}. "
            f"Supported: 'mean', 'thickness_weighted'"
        )

    def write_basin_csvs(self, basin_df: pd.DataFrame) -> None:
        """Write one CSV per gage following the engine contract."""
        if basin_df.empty:
            logger.warning("No basin rows to write")
            return

        out_dir = f"{self.output_root}/ismn_csv"
        self.fs.makedirs(out_dir, exist_ok=True)

        for gage_id, group in basin_df.groupby("gage_id", dropna=False):
            out_file = f"{out_dir}/gages-{gage_id}_soil_moisture.csv"

            output = group[["timestamp", "basin_avg_soil_moisture"]].copy()
            output["timestamp"] = pd.to_datetime(output["timestamp"], utc=True)
            # Keep ISO-like UTC timestamp strings for consistency.
            output["timestamp"] = output["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S%z")

            with self.fs.open(out_file, "w") as f:
                output.to_csv(f, index=False)

            logger.info("Wrote basin ISMN CSV: %s", out_file)

    def write_metadata_csvs(self, meta_df: pd.DataFrame) -> None:
        """Write optional per-basin metadata CSVs."""
        if meta_df.empty:
            return

        out_dir = f"{self.output_root}/ismn_csv_metadata"
        self.fs.makedirs(out_dir, exist_ok=True)

        for gage_id, group in meta_df.groupby("gage_id", dropna=False):
            out_file = f"{out_dir}/gages-{gage_id}_soil_moisture_metadata.csv"

            output = group.copy()
            output["timestamp"] = pd.to_datetime(output["timestamp"], utc=True)
            output["timestamp"] = output["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S%z")

            with self.fs.open(out_file, "w") as f:
                output.to_csv(f, index=False)

            logger.info("Wrote basin ISMN metadata CSV: %s", out_file)

    def build_summary(self, basin_df: pd.DataFrame, meta_df: pd.DataFrame) -> pd.DataFrame:
        """Build a simple run summary."""
        if basin_df.empty:
            return pd.DataFrame(
                columns=[
                    "gage_id",
                    "n_timestamps",
                    "start_time",
                    "end_time",
                    "mean_basin_soil_moisture",
                ]
            )

        summary = (
            basin_df.groupby("gage_id", dropna=False)
            .agg(
                n_timestamps=("timestamp", "count"),
                start_time=("timestamp", "min"),
                end_time=("timestamp", "max"),
                mean_basin_soil_moisture=("basin_avg_soil_moisture", "mean"),
            )
            .reset_index()
        )

        if not meta_df.empty:
            meta_summary = (
                meta_df.groupby("gage_id", dropna=False)
                .agg(
                    mean_station_count=("station_count", "mean"),
                    mean_proxy_station_count=("proxy_station_count", "mean"),
                    mean_integrated_station_count=("integrated_station_count", "mean"),
                    mean_station_coverage_fraction=("mean_station_coverage_fraction", "mean"),
                )
                .reset_index()
            )
            summary = summary.merge(meta_summary, on="gage_id", how="left")

        return summary

    def write_summary(self, summary: pd.DataFrame) -> None:
        """Write run summary CSV."""
        out_file = f"{self.output_root}/ismn_basin_summary.csv"
        with self.fs.open(out_file, "w") as f:
            summary.to_csv(f, index=False)
        logger.info("Wrote ISMN basin summary: %s", out_file)
