"""Recreate the lost SNODAS NetCDF-to-gage SWE CSV workflow.

This script is intentionally close to Matt's unfinished ``swe_gage.py`` and the
SMAP gage averaging pattern, but fixes the SWE-specific issues needed for the
CONUS/CADWR/ENVCA backfill story:

* SNODAS is daily, not 3-hourly.
* S3 NetCDFs are downloaded to local scratch before xarray reads them.
* The final year is always written.
* Per-gage CSVs are written without mutating the source dataframe.
* Output CSVs are sorted and one row per daily SNODAS file.
* A manifest records missing NetCDFs, no-overlap/no-valid-pixel cases, and files written.

Expected output CSV contract used by the existing SWE time-series code:

    timestamp,basin_avg_swe
    2009-12-09 00:00:00,0.123

SNODAS Band1 values are assumed to be millimeters unless ``--source-units m`` is passed.
The default writes meters because the downstream SWE workflow expects meters.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

import fsspec
import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr

# Required because the code uses the xarray .rio accessor.
import rioxarray  # noqa: F401
from dotenv import find_dotenv, load_dotenv
from shapely import MultiPoint, Polygon, voronoi_polygons

try:
    from data_assimilation_engine.utils.utils import time_function, timing_block
except Exception:  # pragma: no cover - lets this script run standalone during backfill.
    from contextlib import contextmanager

    def time_function(func):
        return func

    @contextmanager
    def timing_block(label: str):
        print(label)
        yield

load_dotenv(find_dotenv())


class BasinAverageProcessor:
    """Processor for calculating gage/catchment-average SWE from SNODAS grids."""

    def __init__(
        self,
        gage_gpkg_file_directory: str,
        output_directory: str,
        start_date: str,
        end_date: str,
        domain: str = "CONUS",
        snodas_nc_prefix: str = "s3://ngwpc-forcing/snodas_nc_v4",
        scratch_dir: str = "/tmp/snodas_swe_backfill",
        dataset_name: str = "Band1",
        source_units: str = "mm",
        output_units: str = "m",
        gage_ids: Optional[Iterable[str]] = None,
        overwrite: bool = False,
        manifest_file: Optional[str] = None,
    ):
        self.gage_gpkg_file_directory = gage_gpkg_file_directory
        self.output_directory = output_directory
        self.start_date = start_date
        self.end_date = end_date
        self.domain = domain
        self.snodas_nc_prefix = snodas_nc_prefix.rstrip("/")
        self.scratch_dir = Path(scratch_dir)
        self.dataset_name = dataset_name
        self.source_units = source_units
        self.output_units = output_units
        self.only_gage_ids = {str(g) for g in gage_ids} if gage_ids else None
        self.overwrite = overwrite
        self.manifest_file = manifest_file

        self.group_id = "gage_id"
        self.column = "basin_avg_swe"
        self.x_dim_name = "lon"
        self.y_dim_name = "lat"
        self._data = None
        self.crs = "EPSG:4326"
        self.manifest_records: list[dict] = []

    def s3_key(self, date: datetime) -> str:
        """Generate the S3/local path for one daily SNODAS NetCDF file."""
        filename = f"zz_ssmv11034tS__T0001TTNATS{date.strftime('%Y%m%d05')}HP001.nc"
        return f"{self.snodas_nc_prefix}/{filename}"

    @property
    @lru_cache
    def times(self):
        """Daily SNODAS dates. End date is inclusive for backfill convenience."""
        return list(pd.date_range(self.start_date, self.end_date, freq="D"))

    @property
    @lru_cache
    def gage_ids(self):
        return self.gage_gdf[self.group_id].unique().tolist()

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

    def _convert_units(self, values):
        """Convert SNODAS values to the output CSV units."""
        values = values.astype("float64")
        # Common SNODAS no-data values after GDAL conversion are large negatives.
        values = values.where(values > -9000)
        if self.source_units == self.output_units:
            return values
        if self.source_units == "mm" and self.output_units == "m":
            return values / 1000.0
        if self.source_units == "m" and self.output_units == "mm":
            return values * 1000.0
        raise ValueError(f"Unsupported unit conversion: {self.source_units} -> {self.output_units}")

    def _localize_dataset(self, key: str, date: datetime) -> Optional[Path]:
        """Return a local NetCDF path, downloading from S3 if needed."""
        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        local_file = self.scratch_dir / Path(key).name

        if key.startswith("s3://"):
            fs = fsspec.filesystem("s3")
            if not fs.exists(key):
                self._record(date, status="missing_netcdf", snodas_key=key)
                return None
            fs.get(key, str(local_file))
            return local_file

        path = Path(key)
        if not path.exists():
            self._record(date, status="missing_netcdf", snodas_key=key)
            return None
        if path.resolve() == local_file.resolve():
            return path
        shutil.copy2(path, local_file)
        return local_file

    def _record(self, date, status: str, **kwargs):
        row = {
            "domain": self.domain,
            "date": pd.Timestamp(date).strftime("%Y-%m-%d") if date is not None else "",
            "status": status,
        }
        row.update(kwargs)
        self.manifest_records.append(row)

    def _reset_spatial_cache(self):
        """Clear geometry caches that depend on the current SNODAS grid subset."""
        for attr in ("fishnet", "fishnet_overlay", "x_coords", "y_coords"):
            try:
                getattr(type(self), attr).fget.cache_clear()
            except Exception:
                pass

    @time_function
    def process(self):
        """Process all daily SNODAS grids and write one CSV per gage."""
        if not self.gage_ids:
            raise RuntimeError(f"No gage geopackages found in {self.gage_gpkg_file_directory}")

        results = []
        for time in self.times:
            dt_time = pd.Timestamp(time).to_pydatetime()
            key = self.s3_key(dt_time)
            with timing_block(f"processing SNODAS SWE: {dt_time:%Y-%m-%d}"):
                local_nc = self._localize_dataset(key, dt_time)
                if local_nc is None:
                    continue

                try:
                    ds = xr.open_dataset(local_nc, engine="h5netcdf")
                except Exception:
                    ds = xr.open_dataset(local_nc)

                if self.dataset_name not in ds:
                    self._record(
                        dt_time,
                        status="missing_variable",
                        snodas_key=key,
                        variable=self.dataset_name,
                    )
                    continue

                try:
                    data = ds.sel(
                        lon=slice(self.bounds[0], self.bounds[2]),
                        lat=slice(self.bounds[3], self.bounds[1]),
                    ).load()
                except Exception as exc:
                    self._record(dt_time, status="subset_failed", snodas_key=key, error=str(exc))
                    continue

                if data[self.dataset_name].size == 0:
                    self._record(dt_time, status="no_grid_overlap", snodas_key=key)
                    continue

                data[self.dataset_name] = self._convert_units(data[self.dataset_name])
                self.data = data.rio.write_crs(self.crs)
                self._reset_spatial_cache()

                try:
                    means = self.mean_values
                except Exception as exc:
                    self._record(dt_time, status="zonal_mean_failed", snodas_key=key, error=str(exc))
                    continue

                for gage_id in self.gage_ids:
                    value = means.get(gage_id, np.nan)
                    if pd.isna(value):
                        self._record(
                            dt_time,
                            status="no_valid_pixels_for_gage",
                            gage_id=gage_id,
                            snodas_key=key,
                        )
                    results.append(
                        {"timestamp": pd.Timestamp(dt_time), self.group_id: gage_id, self.column: value}
                    )

                self._record(
                    dt_time,
                    status="processed",
                    snodas_key=key,
                    gage_count=len(self.gage_ids),
                )

        if not results:
            self.write_manifest()
            raise RuntimeError("No SWE records were produced. Check manifest for missing data/coverage.")

        df = pd.DataFrame(results)
        self.write_csvs(df)
        self.write_manifest()

    @property
    def mean_values(self):
        valid = self.fishnet_with_values.dropna(subset=["value", "area"])
        if valid.empty:
            return pd.Series(dtype="float64")
        return valid.groupby(self.group_id).apply(
            lambda x: np.average(x["value"], weights=x["area"])
            if np.isfinite(x["area"]).any() and x["area"].sum() > 0
            else np.nan
        )

    @property
    def fishnet_with_values(self):
        gdf = self.fishnet_overlay.copy()
        gdf["value"] = (
            self.data[self.dataset_name]
            .sel(lon=self.x_coords, lat=self.y_coords, method="nearest")
            .values
        )
        return gdf

    @property
    @lru_cache
    def x_coords(self):
        return xr.DataArray(self.fishnet_overlay.centroid.x)

    @property
    @lru_cache
    def y_coords(self):
        return xr.DataArray(self.fishnet_overlay.centroid.y)

    @property
    @lru_cache
    @time_function
    def fishnet_overlay(self):
        gdf = gpd.overlay(self.fishnet, self.gage_gdf, how="intersection")
        if gdf.empty:
            return gdf.assign(area=pd.Series(dtype="float64"))
        gdf["area"] = gdf.to_crs(5070).geometry.area
        return gdf

    @property
    @lru_cache
    def fishnet(self):
        lon = self.data.lon.values
        lat = self.data.lat.values
        if len(lon) == 0 or len(lat) == 0:
            return gpd.GeoDataFrame({"geometry": []}, crs=self.crs, geometry="geometry")
        mp = MultiPoint([(x, y) for x in lon for y in lat])
        polygons = voronoi_polygons(mp)
        return gpd.GeoDataFrame(
            {"geometry": [Polygon(i) for i in polygons.geoms]},
            crs=self.data.rio.crs,
            geometry="geometry",
        )

    @property
    @lru_cache
    def gage_files(self):
        files = sorted(glob.glob(f"{self.gage_gpkg_file_directory}/*.gpkg"))
        if self.only_gage_ids is None:
            return files
        selected = []
        for file in files:
            gage_id = str(Path(file).stem).replace("gages-", "")
            if gage_id in self.only_gage_ids:
                selected.append(file)
        missing = sorted(self.only_gage_ids.difference({str(Path(f).stem).replace("gages-", "") for f in selected}))
        for gage_id in missing:
            self._record(None, status="missing_gpkg", gage_id=gage_id)
        return selected

    @property
    @lru_cache
    def gage_gdf(self):
        gdfs = []
        for file in self.gage_files:
            gdf = gpd.read_file(file, layer="divides")
            gdf[self.group_id] = str(Path(file).stem).replace("gages-", "")
            gdfs.append(gdf)
        if not gdfs:
            return gpd.GeoDataFrame({self.group_id: [], "geometry": []}, crs=self.crs)
        return pd.concat(gdfs, ignore_index=True).to_crs(self.crs)

    @property
    @lru_cache
    def bounds(self):
        return self.gage_gdf.to_crs(self.crs).total_bounds

    def _write_local_or_s3(self, local_file: Path, target: str):
        if target.startswith("s3://"):
            fs = fsspec.filesystem("s3")
            fs.put(str(local_file), target)
        else:
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_file, target)

    def write_csvs(self, df: pd.DataFrame):
        """Write one sorted CSV per gage using the expected downstream schema."""
        tmp_out = self.scratch_dir / "csv_out"
        tmp_out.mkdir(parents=True, exist_ok=True)

        for gage_id, gdf in df.groupby(self.group_id):
            out_name = f"gages-{gage_id}_swe.csv"
            target = f"{self.output_directory.rstrip('/')}/{out_name}"
            if (not self.overwrite) and (not target.startswith("s3://")) and Path(target).exists():
                self._record(None, status="skipped_existing_csv", gage_id=gage_id, output=target)
                continue

            out_df = (
                gdf[["timestamp", self.column]]
                .drop_duplicates(subset=["timestamp"], keep="last")
                .sort_values("timestamp")
            )
            local_file = tmp_out / out_name
            out_df.to_csv(local_file, index=False, date_format="%Y-%m-%d %H:%M:%S")
            self._write_local_or_s3(local_file, target)
            self._record(None, status="wrote_csv", gage_id=gage_id, output=target, rows=len(out_df))

    def write_manifest(self):
        if not self.manifest_file:
            return
        manifest = pd.DataFrame(self.manifest_records)
        Path(self.manifest_file).parent.mkdir(parents=True, exist_ok=True)
        manifest.to_csv(self.manifest_file, index=False)


def main(
    gage_gpkg_file_directory: str,
    output_directory: str,
    start_date: str,
    end_date: str,
    domain: str = "CONUS",
    snodas_nc_prefix: str = "s3://ngwpc-forcing/snodas_nc_v4",
    scratch_dir: str = "/tmp/snodas_swe_backfill",
    dataset_name: str = "Band1",
    source_units: str = "mm",
    output_units: str = "m",
    gage_ids: Optional[Iterable[str]] = None,
    overwrite: bool = False,
    manifest_file: Optional[str] = None,
):
    processor = BasinAverageProcessor(
        gage_gpkg_file_directory=gage_gpkg_file_directory,
        output_directory=output_directory,
        start_date=start_date,
        end_date=end_date,
        domain=domain,
        snodas_nc_prefix=snodas_nc_prefix,
        scratch_dir=scratch_dir,
        dataset_name=dataset_name,
        source_units=source_units,
        output_units=output_units,
        gage_ids=gage_ids,
        overwrite=overwrite,
        manifest_file=manifest_file,
    )
    processor.process()


def parse_args():
    parser = argparse.ArgumentParser(description="Compute gage-average SWE from daily SNODAS NetCDF files.")
    parser.add_argument("--gage-gpkg-dir", required=True, help="Directory containing gages-<gage_id>.gpkg files.")
    parser.add_argument("--output-dir", required=True, help="Local or s3:// directory for gages-<gage_id>_swe.csv files.")
    parser.add_argument("--start-date", required=True, help="Inclusive start date, YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="Inclusive end date, YYYY-MM-DD.")
    parser.add_argument("--domain", default="CONUS", help="Domain label for manifest, e.g. CONUS, CADWR, ENVCA.")
    parser.add_argument("--snodas-nc-prefix", default="s3://ngwpc-forcing/snodas_nc_v4")
    parser.add_argument("--scratch-dir", default="/tmp/snodas_swe_backfill")
    parser.add_argument("--dataset-name", default="Band1")
    parser.add_argument("--source-units", default="mm", choices=["mm", "m"])
    parser.add_argument("--output-units", default="m", choices=["mm", "m"])
    parser.add_argument("--gage-ids", nargs="*", default=None, help="Optional subset of gage IDs to process.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--manifest-file", default="snodas_swe_backfill_manifest.csv")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(
        gage_gpkg_file_directory=args.gage_gpkg_dir,
        output_directory=args.output_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        domain=args.domain,
        snodas_nc_prefix=args.snodas_nc_prefix,
        scratch_dir=args.scratch_dir,
        dataset_name=args.dataset_name,
        source_units=args.source_units,
        output_units=args.output_units,
        gage_ids=args.gage_ids,
        overwrite=args.overwrite,
        manifest_file=args.manifest_file,
    )
