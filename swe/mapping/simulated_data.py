"""Simulated SWE Mapper."""

import argparse
import logging
from datetime import datetime
from functools import lru_cache

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from swe.snotel import SnotelCalculator, SnotelDataLoader, SnotelPlotter
from utils.calculators import SimCalculator
from utils.converters import Converter
from utils.dataloaders import SimDataLoader
from utils.plotters import SimPlotter
from utils.processors import SimProcessor

logger = logging.getLogger(__name__)


class SWESimDataLoader(SimDataLoader, SnotelDataLoader):
    """Data Loader for simulated SWE data."""


class SWESimCalculator(SimCalculator, SnotelCalculator):
    """Calculator for simulated SWE data."""

    def __init__(self, basin_gdf: gpd.GeoDataFrame = None):
        """Initialize the calculator."""
        super().__init__(basin_gdf)
        self.variable = "swe"
        self.column = "mean_swe"


class SWESimPlotter(SimPlotter, SnotelPlotter):
    """Plotter for simulated SWE data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the plotter with a GeoDataFrame."""
        super().__init__(gdf)
        self.column = "mean_swe"
        self.color_bar_label = "Snow Water Equivalent (m)"
        self.title_str = "Simulated Snow Water Equivalent (SWE)\n date - 06z"
        self.cmap = plt.cm.Blues


class SWESimProcessor(SimProcessor):
    """Processor for simulated SWE data."""

    def __init__(
        self,
        netcdf_file=None,
        gpkg_file=None,
        date=None,
        output_file=None,
        direct_s3=False,
    ):
        """Initialize the processor with input files and parameters."""
        super().__init__(netcdf_file, gpkg_file, date, output_file, direct_s3)
        self.snotel_s3_path = "ngwpc-forcing/snotel_csv"
        self.dl = SWESimDataLoader(self.gpkg_file)
        self.calc = SWESimCalculator(self.basin_gdf)
        self.plotter = SWESimPlotter(self.basin_gdf)

    @property
    @lru_cache
    def snotel_data(self) -> pd.DataFrame | None:
        """Get the SNOTEL SWE data for stations within the basin."""
        if self.stations_in_basin is not None and not self.stations_in_basin.empty:
            return self.dl.load_snotel_data(
                self.stations_in_basin,
                self.date,
                self.snotel_filesystem,
                self.s3_mount_point,
                self.snotel_s3_path,
            )
        return None

    @property
    @lru_cache
    def stations_gdf(self) -> gpd.GeoDataFrame:
        """Get the SNOTEL stations GeoDataFrame."""
        return self.dl.parse_snotel_filenames(self.snotel_filenames)

    @property
    @lru_cache
    def stations_in_basin(self) -> gpd.GeoDataFrame:
        """Get the SNOTEL stations within the basin."""
        return self.calc.find_stations_in_basin(self.stations_gdf, self.basin_geometry)

    def add_station_data(self):
        """Add SNOTEL station data overlay to the plot if available."""
        # Add SNOTEL data overlay if available
        if (
            self.stations_in_basin is not None
            and not self.stations_in_basin.empty
            and self.snotel_data is not None
        ):
            self.plotter.add_snotel_overlay(self.snotel_data)


class SWEConverter(Converter):
    """Convert SWE data from CSV to NetCDF format."""

    def __init__(self, csv_directory: str, dates: list, output_file: str):
        """Initialize the SWEConverter."""
        super().__init__(csv_directory, dates, output_file)
        self.variable_name = "swe"
        self.column1 = "swe_m"
        self.column2 = "swe_mm"

    def convert_units(self, df: pd.DataFrame, mask: pd.DataFrame):
        """Convert Units."""
        if self.column1 in df.columns:
            return df.loc[mask, self.column1].values
        elif self.column2 in df.columns:
            return df.loc[mask, self.column2].values / 1000  # Convert mm to meters

    def check_columns(self, df: pd.DataFrame, file_path: str):
        """Check that columns exists."""
        if self.column1 not in df.columns and self.column2 not in df.columns:
            logger.info(f"{self.variable_name} columns not found in {file_path}")
            return False
        else:
            return True

    @property
    @lru_cache
    def times(self):
        """Get times as datetime objects and add 06z timestamp."""
        return np.array(
            [
                datetime.strptime(f"{date} 06:00:00", "%Y-%m-%d %H:%M:%S")
                for date in self.dates
            ]
        )


def get_options(args_list=None) -> argparse.Namespace:
    """Get command line options for the script."""
    parser = argparse.ArgumentParser()
    parser.add_argument("netcdf_file", type=str, help="Path to NetCDF file")
    parser.add_argument("gpkg_file", type=str, help="Path to geopackage file")
    parser.add_argument("date", type=str, help="Date to plot (ex: '2015-12-01')")
    parser.add_argument(
        "--output_file", type=str, default=None, help="Path where output image is saved"
    )
    parser.add_argument(
        "--direct_s3",
        action="store_true",
        help="Use direct S3 access instead of local mount",
    )
    return parser.parse_args(args_list)


def main(args_list=None) -> None:
    """Run the Simulated SWE processing."""
    args = get_options(args_list)
    processor = SWESimProcessor(
        netcdf_file=args.netcdf_file,
        gpkg_file=args.gpkg_file,
        date=args.date,
        output_file=args.output_file,
        direct_s3=args.direct_s3,
    )
    processor.run()


if __name__ == "__main__":
    main()
