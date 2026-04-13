"""ISMN raw-data preprocessing and archive creation.

This module is intentionally limited to:
- discovering raw .stm files
- parsing valid ISMN records
- normalizing record schema/types
- mapping stations to gages/basins
- writing a raw parquet archive

It does NOT compute top-1m soil moisture or basin-average CSV products.
Those should be handled by downstream derived-product stages.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePath
from typing import Dict, Iterable, Iterator, List, Optional

import fsspec
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ISMNRecord:
    """Normalized raw ISMN record."""

    network: str
    station: str
    station_key: str
    latitude: float
    longitude: float
    elevation_m: float | None
    utc_nominal: pd.Timestamp
    utc_actual: pd.Timestamp
    cse_id: str | None
    depth_from_m: float
    depth_to_m: float
    soil_moisture_m3m3: float
    ismn_flag: str | None
    provider_flag: str | None
    source_file: str
    ingest_time_utc: pd.Timestamp
    gage_id: str | None = None


class ISMNPreprocessor:
    """Create a normalized raw ISMN archive."""

    # Matches:
    # nominal_datetime actual_datetime <11 remaining whitespace-separated fields>
    _ISMN_LINE_PATTERN = re.compile(
        r"^(?P<nominal_datetime>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2})\s+"
        r"(?P<actual_datetime>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2})\s+"
        r"(?P<rest>.*)$"
    )

    def __init__(
        self,
        raw_ismn_source: str,
        gpkg_source: str,
        output_root: str,
        fs: Optional[fsspec.AbstractFileSystem] = None,
        limit_files: int | None = None,
    ) -> None:
        self.raw_ismn_source = raw_ismn_source
        self.gpkg_source = gpkg_source
        self.output_root = output_root.rstrip("/")
        self.fs = fs or fsspec.filesystem("file")
        self.limit_files = limit_files

    def run(self) -> pd.DataFrame:
        """Execute the raw preprocessing workflow.

        Returns a station index DataFrame that includes the assigned gage_id.
        """
        self.fs.makedirs(self.output_root, exist_ok=True)

        raw_files = self.discover_stm_files()
        if not raw_files:
            raise FileNotFoundError(f"No .stm files found under {self.raw_ismn_source}")

        logger.info("Found %d raw ISMN files", len(raw_files))

        station_index = self.build_station_index(raw_files)
        station_index = self.map_stations_to_gages(station_index)
        self.write_station_index(station_index)

        for file_path in raw_files:
            try:
                df = self.parse_stm_file(file_path)
                if df.empty:
                    continue

                df = self.attach_gage_id(df, station_index)
                df = self.normalize_dataframe(df)
                df = df.dropna(subset=["soil_moisture_m3m3", "depth_from_m", "depth_to_m"])

                # Skip records that still cannot be linked to a gage.
                df = df[df["gage_id"].notna()].copy()
                if df.empty:
                    continue

                self.write_raw_archive(df)

            except Exception as exc:
                logger.exception("Failed to process %s: %s", file_path, exc)

        return station_index

    def discover_stm_files(self) -> List[str]:
        """Recursively discover .stm files from a file or directory source."""
        discovered: List[str] = []
        self._discover_stm_files(self.raw_ismn_source, discovered)
        if self.limit_files is not None:
            return discovered[: self.limit_files]
        return discovered

    def _discover_stm_files(self, source: str, out: List[str]) -> None:
        if self.fs.isfile(source) and source.lower().endswith(".stm"):
            out.append(source)
            return

        if not self.fs.isdir(source):
            return

        for entry in self.fs.ls(source, detail=True):
            entry_path = entry["name"]
            entry_type = entry["type"]
            if entry_type == "file" and entry_path.lower().endswith(".stm"):
                out.append(entry_path)
            elif entry_type == "directory":
                self._discover_stm_files(entry_path, out)

    @classmethod
    def normalize_station_name(cls, name: str) -> str:
        """Normalize station name for stable joins."""
        return re.sub(r"[^A-Za-z0-9]+", "", name or "").lower()

    @classmethod
    def make_station_key(cls, network: str, station: str) -> str:
        return f"{cls.normalize_station_name(network)}::{cls.normalize_station_name(station)}"

    @classmethod
    def parse_ismn_line(cls, raw_line: bytes) -> list[str] | None:
        """Parse one raw ISMN line."""
        text_line = raw_line.decode("utf-8", errors="ignore").strip()
        match = cls._ISMN_LINE_PATTERN.match(text_line)
        if not match:
            return None

        rest_fields = match.group("rest").split()
        # Miguel's logic expects 11 fields after the 2 datetime fields.
        if len(rest_fields) != 11:
            return None

        return [match.group("nominal_datetime"), match.group("actual_datetime")] + rest_fields

    @classmethod
    def iter_ismn_records(cls, file_obj: Iterable[bytes]) -> Iterator[list[str]]:
        for raw_line in file_obj:
            parsed = cls.parse_ismn_line(raw_line)
            if parsed is not None:
                yield parsed

    def parse_stm_file(self, file_path: str) -> pd.DataFrame:
        """Parse one .stm file into a normalized DataFrame.

        Expected raw field layout after the 2 datetime columns:
        [cse_id, network, station, lat, lon, elevation,
         depth_from, depth_to, soil_moisture_value, ismn_flag, provider_flag]
        """
        rows: list[dict] = []
        ingest_time_utc = pd.Timestamp.now(tz="UTC")

        with self.fs.open(file_path, "rb") as f:
            for rec in self.iter_ismn_records(f):
                (
                    nominal_datetime,
                    actual_datetime,
                    cse_id,
                    network,
                    station,
                    lat,
                    lon,
                    elevation,
                    depth_from,
                    depth_to,
                    sm_value,
                    ismn_flag,
                    provider_flag,
                ) = rec

                rows.append(
                    {
                        "network": network,
                        "station": station,
                        "station_key": self.make_station_key(network, station),
                        "latitude": lat,
                        "longitude": lon,
                        "elevation_m": elevation,
                        "utc_nominal": nominal_datetime,
                        "utc_actual": actual_datetime,
                        "cse_id": cse_id,
                        "depth_from_m": depth_from,
                        "depth_to_m": depth_to,
                        "soil_moisture_m3m3": sm_value,
                        "ismn_flag": ismn_flag,
                        "provider_flag": provider_flag,
                        "source_file": file_path,
                        "ingest_time_utc": ingest_time_utc,
                    }
                )

        return pd.DataFrame(rows)

    def normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize dtypes and drop impossible values."""
        if df.empty:
            return df

        df = df.copy()

        numeric_cols = [
            "latitude",
            "longitude",
            "elevation_m",
            "depth_from_m",
            "depth_to_m",
            "soil_moisture_m3m3",
        ]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        datetime_cols = ["utc_nominal", "utc_actual", "ingest_time_utc"]
        for col in datetime_cols:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

        # Basic sanity checks
        df = df[df["latitude"].between(-90, 90, inclusive="both")]
        df = df[df["longitude"].between(-180, 180, inclusive="both")]
        df = df[df["depth_from_m"].notna() & df["depth_to_m"].notna()]
        df = df[df["depth_to_m"] >= df["depth_from_m"]]
        df = df[df["soil_moisture_m3m3"].between(0.0, 1.0, inclusive="both")]

        return df

    def build_station_index(self, raw_files: list[str]) -> pd.DataFrame:
        """Build one-row-per-station metadata table from parsed records."""
        station_rows: list[dict] = []

        for file_path in raw_files:
            df = self.parse_stm_file(file_path)
            df = self.normalize_dataframe(df)
            if df.empty:
                continue

            first = df.iloc[0]
            station_rows.append(
                {
                    "network": first["network"],
                    "station": first["station"],
                    "station_key": first["station_key"],
                    "latitude": first["latitude"],
                    "longitude": first["longitude"],
                    "elevation_m": first["elevation_m"],
                    "source_file": file_path,
                }
            )

        station_index = pd.DataFrame(station_rows).drop_duplicates(subset=["station_key"])
        if station_index.empty:
            raise ValueError("No valid station metadata could be extracted from raw ISMN files")

        return station_index

    def map_stations_to_gages(self, station_index: pd.DataFrame) -> pd.DataFrame:
        """Spatially map stations to basin/gage polygons.

        Assumes each geopackage has a filename like gages-<gage_id>.gpkg and contains
        a layer named 'divides'.
        """
        basin_gdfs = self._load_basin_geometries()
        if not basin_gdfs:
            raise FileNotFoundError(f"No geopackages found under {self.gpkg_source}")

        station_gdf = gpd.GeoDataFrame(
            station_index.copy(),
            geometry=gpd.points_from_xy(station_index["longitude"], station_index["latitude"]),
            crs="EPSG:4326",
        )

        mapped_parts: list[pd.DataFrame] = []
        for gage_id, basin_gdf in basin_gdfs.items():
            basin_geom = basin_gdf.unary_union
            inside = station_gdf[station_gdf.geometry.within(basin_geom)].copy()
            if inside.empty:
                continue
            inside["gage_id"] = gage_id
            mapped_parts.append(inside.drop(columns="geometry"))

        if not mapped_parts:
            out = station_index.copy()
            out["gage_id"] = pd.NA
            return out

        mapped = pd.concat(mapped_parts, ignore_index=True)

        # If a station falls in multiple gages, keep first for now and review later.
        mapped = mapped.drop_duplicates(subset=["station_key"], keep="first")

        out = station_index.merge(
            mapped[["station_key", "gage_id"]],
            on="station_key",
            how="left",
        )
        return out

    def _load_basin_geometries(self) -> Dict[str, gpd.GeoDataFrame]:
        basin_gdfs: Dict[str, gpd.GeoDataFrame] = {}

        if self.fs.isfile(self.gpkg_source) and self.gpkg_source.lower().endswith(".gpkg"):
            entries = [{"name": self.gpkg_source, "type": "file"}]
        elif self.fs.isdir(self.gpkg_source):
            entries = self.fs.ls(self.gpkg_source, detail=True)
        else:
            raise FileNotFoundError(f"gpkg source not found: {self.gpkg_source}")

        for entry in entries:
            path = entry["name"]
            if entry["type"] != "file" or not path.lower().endswith(".gpkg"):
                continue

            fname = PurePath(path).name
            gage_id = fname.removeprefix("gages-").removesuffix(".gpkg")
            basin_gdf = gpd.read_file(path, layer="divides")
            if basin_gdf.crs is None:
                basin_gdf = basin_gdf.set_crs("EPSG:4326")
            elif str(basin_gdf.crs).lower() != "epsg:4326":
                basin_gdf = basin_gdf.to_crs("EPSG:4326")

            basin_gdfs[gage_id] = basin_gdf

        return basin_gdfs

    def attach_gage_id(self, df: pd.DataFrame, station_index: pd.DataFrame) -> pd.DataFrame:
        return df.merge(
            station_index[["station_key", "gage_id"]],
            on="station_key",
            how="left",
        )

    def write_station_index(self, station_index: pd.DataFrame) -> None:
        out_path = f"{self.output_root}/ismn_station_index.parquet"
        with self.fs.open(out_path, "wb") as f:
            station_index.to_parquet(f, index=False)

    def write_raw_archive(self, df: pd.DataFrame) -> None:
        """Write normalized raw records partitioned by gage/network/station/date."""
        df = df.copy()
        df["date"] = df["utc_actual"].dt.strftime("%Y-%m-%d")

        group_cols = ["gage_id", "network", "station", "date"]
        for keys, group in df.groupby(group_cols, dropna=False):
            gage_id, network, station, date = keys
            if pd.isna(gage_id):
                continue

            out_dir = (
                f"{self.output_root}/ismn_raw/"
                f"gage_{gage_id}/network={network}/station={station}/date={date}"
            )
            self.fs.makedirs(out_dir, exist_ok=True)
            out_file = f"{out_dir}/part.parquet"
            with self.fs.open(out_file, "wb") as f:
                group.drop(columns=["date"]).to_parquet(f, index=False)
