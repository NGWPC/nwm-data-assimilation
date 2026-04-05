"""Compute station-level top-1m soil moisture from normalized ISMN records."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QCPolicy:
    """Simple QC policy for version 1.

    Adjust accepted flags once the team confirms the exact ISMN/provider semantics.
    """
    accepted_ismn_flags: tuple[str, ...] = ("G", "C", "M", "")  # placeholder
    accepted_provider_flags: tuple[str, ...] = ("G", "C", "M", "")  # placeholder
    allow_null_provider_flag: bool = True


class ISMNTop1MCalculator:
    """Create station-level 0-1m soil moisture time series."""

    def __init__(
        self,
        target_depth_m: float = 1.0,
        min_coverage_fraction: float = 0.50,
        qc_policy: Optional[QCPolicy] = None,
        resample_rule: str = "3h",
        time_offset_hours: int = 1,
    ) -> None:
        self.target_depth_m = target_depth_m
        self.min_coverage_fraction = min_coverage_fraction
        self.qc_policy = qc_policy or QCPolicy()
        self.resample_rule = resample_rule
        self.time_offset_hours = time_offset_hours

    def run(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        """Compute top-1m station soil moisture from normalized raw archive rows."""
        if raw_df.empty:
            return pd.DataFrame(
                columns=[
                    "gage_id",
                    "network",
                    "station",
                    "station_key",
                    "timestamp",
                    "soil_moisture",
                    "valid_thickness_m",
                    "coverage_fraction",
                    "n_layers_used",
                ]
            )

        df = self._prepare(raw_df)
        df = self.filter_qc(df)
        if df.empty:
            return pd.DataFrame()

        grouped = df.groupby(
            ["gage_id", "network", "station", "station_key", "timestamp"],
            dropna=False,
        )

        rows: list[dict] = []
        for _, group in grouped:
            result = self.compute_group(group)
            if result is not None:
                rows.append(result)

        out = pd.DataFrame(rows)
        if out.empty:
            return out

        out = self.align_to_soil_moisture_cycle(out)
        out = self._collapse_duplicate_station_timestamps(out)
        return out.sort_values(["gage_id", "network", "station", "timestamp"]).reset_index(drop=True)

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # Use actual time as the default scientific timestamp.
        df["timestamp"] = pd.to_datetime(df["utc_actual"], errors="coerce", utc=True)
        df["depth_from_m"] = pd.to_numeric(df["depth_from_m"], errors="coerce")
        df["depth_to_m"] = pd.to_numeric(df["depth_to_m"], errors="coerce")
        df["soil_moisture_m3m3"] = pd.to_numeric(df["soil_moisture_m3m3"], errors="coerce")

        df = df.dropna(
            subset=[
                "gage_id",
                "network",
                "station",
                "station_key",
                "timestamp",
                "depth_from_m",
                "depth_to_m",
                "soil_moisture_m3m3",
            ]
        )

        df = df[df["depth_to_m"] >= df["depth_from_m"]]
        df = df[df["soil_moisture_m3m3"].between(0.0, 1.0, inclusive="both")]
        return df

    def filter_qc(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply a simple, configurable QC policy."""
        df = df.copy()

        def normalize_flag(series: pd.Series) -> pd.Series:
            return (
                series.fillna("")
                .astype(str)
                .str.strip()
                .str.upper()
            )

        df["ismn_flag"] = normalize_flag(df.get("ismn_flag", pd.Series(index=df.index, dtype=object)))
        df["provider_flag"] = normalize_flag(df.get("provider_flag", pd.Series(index=df.index, dtype=object)))

        ismn_ok = df["ismn_flag"].isin(self.qc_policy.accepted_ismn_flags)

        if self.qc_policy.allow_null_provider_flag:
            provider_ok = df["provider_flag"].isin(self.qc_policy.accepted_provider_flags) | (df["provider_flag"] == "")
        else:
            provider_ok = df["provider_flag"].isin(self.qc_policy.accepted_provider_flags)

        return df[ismn_ok & provider_ok].copy()

    def compute_group(self, df_group: pd.DataFrame) -> dict | None:
        """Compute one station timestamp top-1m weighted average."""
        overlaps: list[float] = []
        weighted_values: list[float] = []

        for _, row in df_group.iterrows():
            z0 = max(0.0, float(row["depth_from_m"]))
            z1 = min(self.target_depth_m, float(row["depth_to_m"]))
            dz = z1 - z0
            if dz <= 0.0:
                continue

            overlaps.append(dz)
            weighted_values.append(float(row["soil_moisture_m3m3"]) * dz)

        if not overlaps:
            return None

        total_overlap = float(np.sum(overlaps))
        coverage_fraction = total_overlap / self.target_depth_m
        if coverage_fraction < self.min_coverage_fraction:
            return None

        first = df_group.iloc[0]
        return {
            "gage_id": first["gage_id"],
            "network": first["network"],
            "station": first["station"],
            "station_key": first["station_key"],
            "timestamp": first["timestamp"],
            "soil_moisture": float(np.sum(weighted_values) / total_overlap),
            "valid_thickness_m": total_overlap,
            "coverage_fraction": coverage_fraction,
            "n_layers_used": len(overlaps),
        }

    def align_to_soil_moisture_cycle(self, df: pd.DataFrame) -> pd.DataFrame:
        """Snap timestamps to the repo's 01,04,07,... soil moisture cycle."""
        df = df.copy()

        ts = pd.to_datetime(df["timestamp"], utc=True)

        # Shift by the offset so that floor('3h') maps to the 1,4,7,... sequence.
        shifted = ts - pd.to_timedelta(self.time_offset_hours, unit="h")
        snapped = shifted.dt.floor(self.resample_rule) + pd.to_timedelta(self.time_offset_hours, unit="h")

        df["timestamp"] = snapped
        return df

    def _collapse_duplicate_station_timestamps(self, df: pd.DataFrame) -> pd.DataFrame:
        """If multiple raw groups land on the same snapped timestamp, merge them."""
        grouped = df.groupby(
            ["gage_id", "network", "station", "station_key", "timestamp"],
            dropna=False,
            as_index=False,
        ).apply(self._merge_station_timestamp_rows)

        if isinstance(grouped.index, pd.MultiIndex):
            grouped = grouped.reset_index(drop=True)

        return grouped

    @staticmethod
    def _merge_station_timestamp_rows(group: pd.DataFrame) -> pd.Series:
        """Merge duplicate snapped station timestamps using coverage-weighted averaging."""
        weights = group["valid_thickness_m"].to_numpy(dtype=float)
        vals = group["soil_moisture"].to_numpy(dtype=float)

        soil_moisture = np.average(vals, weights=weights) if np.sum(weights) > 0 else np.nan

        first = group.iloc[0]
        return pd.Series(
            {
                "gage_id": first["gage_id"],
                "network": first["network"],
                "station": first["station"],
                "station_key": first["station_key"],
                "timestamp": first["timestamp"],
                "soil_moisture": soil_moisture,
                "valid_thickness_m": float(np.max(group["valid_thickness_m"])),
                "coverage_fraction": float(np.max(group["coverage_fraction"])),
                "n_layers_used": int(np.max(group["n_layers_used"])),
            }
        )
