#!/usr/bin/env python3
"""
Aggregate daily SNODAS SWE NetCDF grids to NHF gage polygons.

This is the NHF-oriented version of the recreated Kyle SWE aggregation workflow.
It accepts Icefabric/MSWM-style files named gauge_<gage>.gpkg and older SWE-style
files named gages-<gage>.gpkg.

Output per gage:
    gages-<gage>_swe.csv
with columns:
    timestamp,basin_avg_swe

Notes:
  * SNODAS SWE product 1034 is commonly stored as Band1 in the converted NetCDFs.
  * Source units are usually millimeters; output defaults to meters to match existing SWE CSV convention.
  * This script downloads S3 NetCDFs to local scratch before opening because direct xarray+h5 reads from S3 have been unreliable in this workflow.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Iterable, List, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import box

try:
    import rioxarray  # noqa: F401 - activates .rio accessor
except Exception:  # noqa: BLE001
    rioxarray = None


@dataclass
class GageResult:
    gage_id: str
    domain: str
    status: str
    output_file: str
    rows: int = 0
    valid_values: int = 0
    note: str = ""


def parse_gage_id(path: str | Path) -> str:
    stem = Path(path).stem
    for prefix in ("gages-", "gauge_", "gage_"):
        if stem.startswith(prefix):
            return stem.replace(prefix, "", 1)
    match = re.search(r"(\d{7,15})", stem)
    if match:
        return match.group(1)
    raise ValueError(f"Cannot parse gage id from file name: {path}")


def date_range_daily(start_date: str, end_date: str) -> list[datetime]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    days = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def is_s3_path(path: str) -> bool:
    return str(path).startswith("s3://")


def s3_to_bucket_key(s3_path: str) -> tuple[str, str]:
    no_scheme = s3_path.replace("s3://", "", 1)
    bucket, key = no_scheme.split("/", 1)
    return bucket, key


def run_cmd(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)

def copy_from_s3_or_local(src: str, dst: str | Path) -> bool:
    dst = str(dst)

    if is_s3_path(src):
        ls_cmd = ["aws", "s3", "ls", src]
        cp_cmd = ["aws", "s3", "cp", src, dst, "--only-show-errors"]

        if os.environ.get("AWS_REQUEST_PAYER", "").lower() in ("1", "true", "requester"):
            ls_cmd.extend(["--request-payer", "requester"])
            cp_cmd.extend(["--request-payer", "requester"])

        ls = subprocess.run(ls_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if ls.returncode != 0:
            err = (ls.stderr or "").strip()
            if any(x in err for x in ("ExpiredToken", "InvalidToken", "AccessDenied", "Bad Request")):
                raise RuntimeError(f"S3 access/auth failure while checking {src}: {err}")
            return False

        cp = subprocess.run(cp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if cp.returncode < 0:
            raise RuntimeError(
                f"AWS CLI crashed while downloading {src}: returncode={cp.returncode}; "
                f"stderr={(cp.stderr or '').strip()}"
            )

        if cp.returncode != 0:
            err = (cp.stderr or "").strip()
            if any(x in err for x in ("ExpiredToken", "InvalidToken", "AccessDenied", "Bad Request")):
                raise RuntimeError(f"S3 access/auth failure while downloading {src}: {err}")
            print(f"WARNING: failed to download SNODAS file: {src}; {err}")
            return False

        return Path(dst).exists() and Path(dst).stat().st_size > 0

    if os.path.exists(src):
        shutil.copyfile(src, dst)
        return True

    return False

def build_snodas_candidates(prefix: str, date: datetime) -> list[str]:
    prefix = prefix.rstrip("/")
    ymdh = date.strftime("%Y%m%d05")

    # snodas_nc_v4 path used by Matt's draft script.
    names = [
        f"zz_ssmv11034tS__T0001TTNATS{ymdh}HP001.nc",

        # Older README/example pattern without the extra 'v'.
        f"zz_ssm11034tS__T0001TTNATS{ymdh}HP001.nc",
    ]

    return [f"{prefix}/{name}" for name in names]

def output_exists(path: str) -> bool:
    if is_s3_path(path):
        cmd = ["aws", "s3", "ls", path]
        if os.environ.get("AWS_REQUEST_PAYER", "").lower() in ("1", "true", "requester"):
            cmd.extend(["--request-payer", "requester"])
        return subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0

    return Path(path).exists()

def copy_to_s3_or_local(src: str | Path, dst: str) -> None:
    src = str(src)
    if is_s3_path(dst):
        run_cmd(["aws", "s3", "cp", src, dst, "--only-show-errors"])
    else:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

def find_coord_names(ds: xr.Dataset) -> tuple[str, str]:
    candidates = [
        ("lon", "lat"),
        ("longitude", "latitude"),
        ("x", "y"),
    ]
    for x_name, y_name in candidates:
        if x_name in ds.coords and y_name in ds.coords:
            return x_name, y_name
        if x_name in ds.dims and y_name in ds.dims:
            return x_name, y_name
    raise ValueError(f"Could not identify x/y coordinate names. coords={list(ds.coords)} dims={list(ds.dims)}")


def choose_dataset_name(ds: xr.Dataset, requested: Optional[str]) -> str:
    if requested:
        if requested not in ds.data_vars:
            raise ValueError(f"Requested dataset variable '{requested}' not found. Available: {list(ds.data_vars)}")
        return requested
    if "Band1" in ds.data_vars:
        return "Band1"
    if "swe" in ds.data_vars:
        return "swe"
    if len(ds.data_vars) == 1:
        return list(ds.data_vars)[0]
    raise ValueError(f"Could not infer SWE variable. Available variables: {list(ds.data_vars)}")


def convert_units(values: np.ndarray, source_units: str, output_units: str) -> np.ndarray:
    arr = values.astype(float)
    if source_units == output_units:
        return arr
    if source_units == "mm" and output_units == "m":
        return arr / 1000.0
    if source_units == "m" and output_units == "mm":
        return arr * 1000.0
    raise ValueError(f"Unsupported unit conversion: {source_units} -> {output_units}")


def safe_weighted_average(values: np.ndarray, weights: np.ndarray) -> float:
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not np.any(valid):
        return float("nan")
    return float(np.average(values[valid], weights=weights[valid]))


class SNODASNHFGageProcessor:
    def __init__(
        self,
        gage_gpkg_dir: str,
        output_dir: str,
        start_date: str,
        end_date: str,
        domain: str,
        snodas_nc_prefix: str,
        scratch_dir: str,
        dataset_name: Optional[str] = "Band1",
        source_units: str = "mm",
        output_units: str = "m",
        gage_ids: Optional[list[str]] = None,
        overwrite: bool = False,
        manifest_file: str = "swe_nhf_manifest.csv",
    ) -> None:
        self.gage_gpkg_dir = Path(gage_gpkg_dir)
        self.output_dir = output_dir.rstrip("/")
        self.start_date = start_date
        self.end_date = end_date
        self.domain = domain
        self.snodas_nc_prefix = snodas_nc_prefix.rstrip("/")
        self.scratch_dir = Path(scratch_dir)
        self.dataset_name = dataset_name
        self.source_units = source_units
        self.output_units = output_units
        self.gage_ids = set(gage_ids) if gage_ids else None
        self.overwrite = overwrite
        self.manifest_file = manifest_file
        self.scratch_dir.mkdir(parents=True, exist_ok=True)

    @cached_property
    def dates(self) -> list[datetime]:
        return date_range_daily(self.start_date, self.end_date)

    @cached_property
    def gage_files(self) -> list[Path]:
        patterns = ["gages-*.gpkg", "gauge_*.gpkg", "gage_*.gpkg", "*.gpkg"]
        files: list[Path] = []
        for pattern in patterns:
            files.extend(sorted(self.gage_gpkg_dir.glob(pattern)))
        unique = []
        seen = set()
        for fp in files:
            if fp in seen:
                continue
            seen.add(fp)
            try:
                gid = parse_gage_id(fp)
            except ValueError:
                continue
            if self.gage_ids and gid not in self.gage_ids:
                continue
            unique.append(fp)
        return unique

    def output_file_for_gage(self, gage_id: str) -> str:
        name = f"gages-{gage_id}_swe.csv"
        return f"{self.output_dir}/{name}" if is_s3_path(self.output_dir) else str(Path(self.output_dir) / name)

    def local_output_file_for_gage(self, gage_id: str) -> Path:
        return self.scratch_dir / "outputs" / f"gages-{gage_id}_swe.csv"

    def download_snodas(self, date: datetime) -> Optional[Path]:
        local_dir = self.scratch_dir / "snodas_nc"
        local_dir.mkdir(parents=True, exist_ok=True)

        for source in build_snodas_candidates(self.snodas_nc_prefix, date):
            local = local_dir / Path(source).name

            if local.exists() and local.stat().st_size > 0:
                return local

            ok = copy_from_s3_or_local(source, local)
            if ok and local.exists() and local.stat().st_size > 0:
                return local

        return None

    def read_gage_geometry(self, gpkg_file: Path) -> gpd.GeoDataFrame:
        try:
            gdf = gpd.read_file(gpkg_file, layer="divides")
        except Exception as exc:
            raise RuntimeError(f"failed to read divides layer from {gpkg_file}: {exc}") from exc
        if gdf.empty:
            raise RuntimeError(f"divides layer is empty: {gpkg_file}")
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        return gdf.to_crs("EPSG:4326")

    def process_one_gage(self, gpkg_file: Path) -> GageResult:
        gage_id = parse_gage_id(gpkg_file)
        dest_file = self.output_file_for_gage(gage_id)
        local_output = self.local_output_file_for_gage(gage_id)
        local_output.parent.mkdir(parents=True, exist_ok=True)

        if not self.overwrite and output_exists(dest_file):
            return GageResult(
                gage_id,
                self.domain,
                "exists",
                dest_file,
                note="output already exists; use --overwrite to regenerate",
            )

        try:
            gage_gdf = self.read_gage_geometry(gpkg_file)
            bounds = gage_gdf.total_bounds
            geom_union = (
                gage_gdf.union_all()
                if hasattr(gage_gdf, "union_all")
                else gage_gdf.unary_union
            )

            rows = []
            missing_nc = 0
            no_overlap = 0
            failed_days = 0

            for day_index, date in enumerate(self.dates, start=1):
                if day_index == 1 or day_index % 30 == 0 or day_index == len(self.dates):
                    print(
                        f"    {gage_id}: processing day {day_index}/{len(self.dates)} "
                        f"({date:%Y-%m-%d})",
                        flush=True,
                    )

                local_nc = None
                delete_local_nc = False

                try:
                    local_nc = self.download_snodas(date)

                    if local_nc is None:
                        missing_nc += 1
                        rows.append({
                            "timestamp": (date + pd.Timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
                            "basin_avg_swe": np.nan,
                        })
                        continue

                    if is_s3_path(self.snodas_nc_prefix):
                        delete_local_nc = True

                    with xr.open_dataset(local_nc) as ds:
                        var_name = choose_dataset_name(ds, self.dataset_name)
                        x_name, y_name = find_coord_names(ds)

                        xvals = ds[x_name].values
                        yvals = ds[y_name].values

                        x_slice = (
                            slice(bounds[0], bounds[2])
                            if xvals[0] <= xvals[-1]
                            else slice(bounds[2], bounds[0])
                        )
                        y_slice = (
                            slice(bounds[1], bounds[3])
                            if yvals[0] <= yvals[-1]
                            else slice(bounds[3], bounds[1])
                        )

                        subset = ds.sel({x_name: x_slice, y_name: y_slice})

                        if subset.sizes.get(x_name, 0) == 0 or subset.sizes.get(y_name, 0) == 0:
                            no_overlap += 1
                            rows.append({
                                "timestamp": (date + pd.Timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
                                "basin_avg_swe": np.nan,
                            })
                            continue

                        da = subset[var_name]
                        values = da.values

                        if values.ndim > 2:
                            values = np.squeeze(values)

                        values = convert_units(
                            np.asarray(values),
                            self.source_units,
                            self.output_units,
                        )

                        xs = subset[x_name].values
                        ys = subset[y_name].values

                        if len(xs) < 1 or len(ys) < 1:
                            no_overlap += 1
                            rows.append({
                                "timestamp": (date + pd.Timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
                                "basin_avg_swe": np.nan,
                            })
                            continue

                        dx = float(np.nanmedian(np.abs(np.diff(xs)))) if len(xs) > 1 else 0.01
                        dy = float(np.nanmedian(np.abs(np.diff(ys)))) if len(ys) > 1 else 0.01

                        records = []
                        dims = da.squeeze().dims

                        for iy, y in enumerate(ys):
                            for ix, x in enumerate(xs):
                                if len(dims) != 2:
                                    continue

                                if dims[0] == y_name and dims[1] == x_name:
                                    value = values[iy, ix]
                                elif dims[0] == x_name and dims[1] == y_name:
                                    value = values[ix, iy]
                                else:
                                    value = values[iy, ix]

                                cell = box(
                                    float(x) - dx / 2,
                                    float(y) - dy / 2,
                                    float(x) + dx / 2,
                                    float(y) + dy / 2,
                                )

                                if not cell.intersects(geom_union):
                                    continue

                                inter = cell.intersection(geom_union)
                                if inter.is_empty:
                                    continue

                                records.append((float(value), float(inter.area)))

                        if not records:
                            no_overlap += 1
                            mean_swe = np.nan
                        else:
                            vals = np.array([r[0] for r in records], dtype=float)
                            weights = np.array([r[1] for r in records], dtype=float)
                            mean_swe = safe_weighted_average(vals, weights)

                        rows.append({
                            "timestamp": (date + pd.Timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
                            "basin_avg_swe": mean_swe,
                        })

                except Exception as exc:
                    msg = repr(exc)

                    # Fatal infrastructure/auth errors should stop this gage immediately.
                    if (
                        "S3 access/auth failure" in msg
                        or "AWS CLI crashed" in msg
                        or "ExpiredToken" in msg
                        or "InvalidToken" in msg
                        or "AccessDenied" in msg
                        or "Bad Request" in msg
                    ):
                        raise RuntimeError(
                            f"fatal download/S3 failure for {gage_id} on {date:%Y-%m-%d}: {exc}"
                        ) from exc

                    failed_days += 1
                    rows.append({
                        "timestamp": (date + pd.Timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
                        "basin_avg_swe": np.nan,
                    })
                    print(f"WARNING: failed processing {gage_id} {date:%Y-%m-%d}: {exc}", flush=True)

                finally:
                    if delete_local_nc and local_nc is not None:
                        try:
                            Path(local_nc).unlink(missing_ok=True)
                        except Exception:
                            pass

            df = pd.DataFrame(rows)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
            df.to_csv(local_output, index=False, date_format="%Y-%m-%d %H:%M:%S")

            valid_values = int(df["basin_avg_swe"].notna().sum())

            if valid_values == 0:
                note = (
                    f"missing_nc_days={missing_nc}; "
                    f"no_overlap_days={no_overlap}; "
                    f"failed_days={failed_days}; "
                    f"local_output={local_output}"
                )
                return GageResult(
                    gage_id,
                    self.domain,
                    "invalid_no_valid_values_not_uploaded",
                    dest_file,
                    len(df),
                    valid_values,
                    note,
                )

            upload_failed = False
            upload_error = ""

            try:
                copy_to_s3_or_local(local_output, dest_file)
            except Exception as exc:
                upload_failed = True
                upload_error = repr(exc)

            status = "partial" if (missing_nc > 0 or no_overlap > 0 or failed_days > 0) else "processed"
            note = (
                f"missing_nc_days={missing_nc}; "
                f"no_overlap_days={no_overlap}; "
                f"failed_days={failed_days}; "
                f"local_output={local_output}"
            )

            if upload_failed:
                status = "upload_failed"
                note = f"{note}; upload_error={upload_error}"

            return GageResult(
                gage_id,
                self.domain,
                status,
                dest_file,
                len(df),
                valid_values,
                note,
            )

        except Exception as exc:
            return GageResult(
                gage_id,
                self.domain,
                "failed",
                dest_file,
                0,
                0,
                repr(exc),
            )

    def write_manifest(self, results: Iterable[GageResult]) -> None:
        rows = list(results)
        with open(self.manifest_file, "w", newline="", encoding="utf-8") as fp:
            fieldnames = list(asdict(rows[0]).keys()) if rows else ["gage_id", "domain", "status", "output_file", "rows", "valid_values", "note"]
            writer = csv.DictWriter(fp, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(asdict(row))

    def process(self) -> list[GageResult]:
        if not self.gage_files:
            raise RuntimeError(f"No gage geopackages found in {self.gage_gpkg_dir}")
        results = []
        for i, gpkg in enumerate(self.gage_files, start=1):
            print(f"[{i}/{len(self.gage_files)}] processing {gpkg.name}")
            result = self.process_one_gage(gpkg)
            print(f"  {result.status}: {result.output_file} ({result.valid_values}/{result.rows} valid)")
            results.append(result)

            # Keep scratch small between gages.
            snodas_cache = self.scratch_dir / "snodas_nc"
            if snodas_cache.exists():
                shutil.rmtree(snodas_cache, ignore_errors=True)

        self.write_manifest(results)
        print(f"Wrote manifest: {self.manifest_file}")
        return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate SNODAS SWE to NHF gage polygons.")
    parser.add_argument("--gage-gpkg-dir", required=True, help="Directory containing gauge_<gage>.gpkg or gages-<gage>.gpkg files.")
    parser.add_argument("--output-dir", required=True, help="Local directory or s3:// prefix for output SWE CSV files.")
    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD inclusive.")
    parser.add_argument("--end-date", required=True, help="End date YYYY-MM-DD inclusive.")
    parser.add_argument("--domain", required=True, help="Domain label, e.g. CONUS, Alaska, Hawaii.")
    parser.add_argument("--snodas-nc-prefix", required=True, help="Local or s3:// prefix containing daily SNODAS NetCDFs.")
    parser.add_argument("--scratch-dir", default="/tmp/snodas_swe_nhf", help="Scratch directory for downloaded NetCDFs and local CSVs.")
    parser.add_argument("--dataset-name", default="Band1", help="SWE variable name in NetCDF. Use empty string to infer.")
    parser.add_argument("--source-units", choices=["mm", "m"], default="mm", help="Units of NetCDF SWE values.")
    parser.add_argument("--output-units", choices=["mm", "m"], default="m", help="Units for output basin_avg_swe.")
    parser.add_argument("--gage-ids", nargs="*", default=None, help="Optional subset of gage IDs to process.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing local outputs.")
    parser.add_argument("--manifest-file", default="swe_nhf_manifest.csv", help="Output manifest CSV.")
    args = parser.parse_args()

    processor = SNODASNHFGageProcessor(
        gage_gpkg_dir=args.gage_gpkg_dir,
        output_dir=args.output_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        domain=args.domain,
        snodas_nc_prefix=args.snodas_nc_prefix,
        scratch_dir=args.scratch_dir,
        dataset_name=args.dataset_name or None,
        source_units=args.source_units,
        output_units=args.output_units,
        gage_ids=args.gage_ids,
        overwrite=args.overwrite,
        manifest_file=args.manifest_file,
    )
    processor.process()


if __name__ == "__main__":
    main()
