"""Run the ISMN preprocessing pipeline end to end.

Pipeline stages:
1. Parse raw ISMN .stm files and build normalized raw parquet archive
2. Compute station-level top-1m soil moisture products
3. Aggregate station top-1m products to basin-level CSVs

This script is intentionally lightweight and designed for local/dev use first.
"""

from __future__ import annotations

import argparse
import logging
from typing import Optional

import fsspec
import pandas as pd

from data_assimilation_engine.soil_moisture.ISMN_preprocessing.ismn_preprocessor import (
    ISMNPreprocessor,
)
from data_assimilation_engine.soil_moisture.ISMN_preprocessing.ismn_top1m import (
    ISMNTop1MCalculator,
    QCPolicy,
)
from data_assimilation_engine.soil_moisture.ISMN_preprocessing.ismn_basin_timeseries import (
    BasinAggregationConfig,
    ISMNBasinTimeseriesBuilder,
)

from data_assimilation_engine.soil_moisture.ISMN_preprocessing.ismn_download import (
    ISMNDownloader,
)

logger = logging.getLogger(__name__)


def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def discover_parquet_files(fs: fsspec.AbstractFileSystem, source: str) -> list[str]:
    found: list[str] = []

    def _walk(path: str) -> None:
        if fs.isfile(path) and path.lower().endswith(".parquet"):
            found.append(path)
            return
        if not fs.isdir(path):
            return
        for entry in fs.ls(path, detail=True):
            entry_path = entry["name"]
            entry_type = entry["type"]
            if entry_type == "file" and entry_path.lower().endswith(".parquet"):
                found.append(entry_path)
            elif entry_type == "directory":
                _walk(entry_path)

    _walk(source)
    return found


def load_raw_archive(
    raw_archive_root: str,
    fs: Optional[fsspec.AbstractFileSystem] = None,
) -> pd.DataFrame:
    """Load normalized raw archive parquet files into one DataFrame."""
    fs = fs or fsspec.filesystem("file")
    paths = discover_parquet_files(fs, raw_archive_root)
    if not paths:
        raise FileNotFoundError(f"No parquet files found under {raw_archive_root}")

    dfs = []
    for path in paths:
        logger.info("Reading raw archive parquet: %s", path)
        with fs.open(path, "rb") as f:
            dfs.append(pd.read_parquet(f))

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True)


def write_station_top1m_archive(
    station_top1m_df: pd.DataFrame,
    output_root: str,
    fs: Optional[fsspec.AbstractFileSystem] = None,
) -> str:
    """Write station-level top-1m parquet products.

    Output layout:
        {output_root}/ismn_station_top1m/gage_{gage_id}/date={YYYY-MM-DD}/part.parquet
    """
    fs = fs or fsspec.filesystem("file")
    out_root = f"{output_root.rstrip('/')}/ismn_station_top1m"
    fs.makedirs(out_root, exist_ok=True)

    if station_top1m_df.empty:
        raise ValueError("station_top1m_df is empty; nothing to write")

    df = station_top1m_df.copy()
    df["date"] = pd.to_datetime(df["timestamp"], utc=True).dt.strftime("%Y-%m-%d")

    for (gage_id, date), group in df.groupby(["gage_id", "date"], dropna=False):
        out_dir = f"{out_root}/gage_{gage_id}/date={date}"
        fs.makedirs(out_dir, exist_ok=True)
        out_file = f"{out_dir}/part.parquet"

        with fs.open(out_file, "wb") as f:
            group.drop(columns=["date"]).to_parquet(f, index=False)

        logger.info("Wrote station top-1m parquet: %s", out_file)

    return out_root


def run_pipeline(
    raw_ismn_source: str,
    gpkg_source: str,
    output_root: str,
    min_station_coverage_fraction: float = 0.5,
    min_basin_station_count: int = 1,
    basin_aggregation_method: str = "mean",
    target_depth_m: float = 1.0,
    limit_files: int | None = None,
    verbose: bool = False,
    download_first: bool = False,
    staged_raw_dir: str | None = None,
) -> None:
    configure_logging(verbose=verbose)

    if download_first:
        if not staged_raw_dir:
            staged_raw_dir = f"{output_root.rstrip('/')}/raw_ismn_staging"

        logger.info("Stage 0: Downloading/staging raw ISMN files")
        downloader = ISMNDownloader(
            remote_source=raw_ismn_source,
            local_output_dir=staged_raw_dir,
            overwrite=False,
            limit_files=limit_files,
        )
        result = downloader.run()
        logger.info(
            "Download result: discovered=%d copied=%d skipped=%d",
            result.discovered_files,
            result.copied_files,
            result.skipped_files,
        )

        # After staging, downstream preprocessing should read local staged files.
        raw_ismn_source = staged_raw_dir



    fs = fsspec.filesystem("file")

    logger.info("Starting ISMN pipeline")
    logger.info("Raw source: %s", raw_ismn_source)
    logger.info("GPKG source: %s", gpkg_source)
    logger.info("Output root: %s", output_root)

    # ------------------------------------------------------------------
    # Stage 1: Raw normalization and archive creation
    # ------------------------------------------------------------------
    logger.info("Stage 1: Building normalized raw archive")
    preprocessor = ISMNPreprocessor(
        raw_ismn_source=raw_ismn_source,
        gpkg_source=gpkg_source,
        output_root=output_root,
        fs=fs,
        limit_files=limit_files,
    )
    station_index = preprocessor.run()
    logger.info("Station index rows: %d", len(station_index))

    raw_archive_root = f"{output_root.rstrip('/')}/ismn_raw"

    # ------------------------------------------------------------------
    # Stage 2: Station-level top-1m soil moisture
    # ------------------------------------------------------------------
    logger.info("Stage 2: Computing station-level top-%sm soil moisture", target_depth_m)

    raw_df = load_raw_archive(raw_archive_root=raw_archive_root, fs=fs)
    logger.info("Normalized raw archive rows: %d", len(raw_df))

    qc_policy = QCPolicy()
    top1m_calculator = ISMNTop1MCalculator(
        target_depth_m=target_depth_m,
        min_coverage_fraction=min_station_coverage_fraction,
        qc_policy=qc_policy,
    )
    station_top1m_df = top1m_calculator.run(raw_df)
    logger.info("Station top-1m rows: %d", len(station_top1m_df))

    if station_top1m_df.empty:
        raise ValueError("No station-level top-1m products were generated")

    station_top1m_root = write_station_top1m_archive(
        station_top1m_df=station_top1m_df,
        output_root=output_root,
        fs=fs,
    )

    # ------------------------------------------------------------------
    # Stage 3: Basin-level CSV products
    # ------------------------------------------------------------------
    logger.info("Stage 3: Building basin-level ISMN CSVs")

    basin_builder = ISMNBasinTimeseriesBuilder(
        station_top1m_source=station_top1m_root,
        output_root=output_root,
        fs=fs,
        config=BasinAggregationConfig(
            min_station_count=min_basin_station_count,
            min_station_coverage_fraction=min_station_coverage_fraction,
            aggregation_method=basin_aggregation_method,
            write_metadata=True,
        ),
    )
    summary_df = basin_builder.run()
    logger.info("Basin summary rows: %d", len(summary_df))

    logger.info("ISMN pipeline complete")
    logger.info("Products written under: %s", output_root)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the ISMN preprocessing pipeline end to end."
    )
    parser.add_argument(
        "--raw-ismn-source",
        required=True,
        help="Directory or file containing raw ISMN .stm files",
    )
    parser.add_argument(
        "--gpkg-source",
        required=True,
        help="Directory or geopackage file used to map stations to gages/basins",
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="Root output directory for parquet/CSV archive products",
    )
    parser.add_argument(
        "--target-depth-m",
        type=float,
        default=1.0,
        help="Target depth in meters for top-layer average soil moisture",
    )
    parser.add_argument(
        "--min-station-coverage-fraction",
        type=float,
        default=0.5,
        help="Minimum required vertical coverage fraction at station level",
    )
    parser.add_argument(
        "--min-basin-station-count",
        type=int,
        default=1,
        help="Minimum number of valid stations required per basin timestamp",
    )
    parser.add_argument(
        "--basin-aggregation-method",
        choices=["mean", "thickness_weighted"],
        default="mean",
        help="How to aggregate station values to the basin level",
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        default=None,
        help="Optional limit on number of raw .stm files to ingest for testing",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--download-first",
        action="store_true",
        help="Download/sync raw ISMN files to a local staging directory before preprocessing",
    )
    parser.add_argument(
        "--staged-raw-dir",
        default=None,
        help="Local directory for staged raw ISMN files when --download-first is used",
    )

    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    run_pipeline(
        raw_ismn_source=args.raw_ismn_source,
        gpkg_source=args.gpkg_source,
        output_root=args.output_root,
        min_station_coverage_fraction=args.min_station_coverage_fraction,
        min_basin_station_count=args.min_basin_station_count,
        basin_aggregation_method=args.basin_aggregation_method,
        target_depth_m=args.target_depth_m,
        limit_files=args.limit_files,
        verbose=args.verbose,
        download_first=args.download_first,
        staged_raw_dir=args.staged_raw_dir,
    )


if __name__ == "__main__":
    main()
