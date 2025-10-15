"""Simulated Soil Moisture Mapper."""

import argparse
import logging
from datetime import datetime
from functools import lru_cache

import geopandas as gpd
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

from data_assimilation_engine.utils.calculators import SimCalculator
from data_assimilation_engine.utils.converters import Converter
from data_assimilation_engine.utils.dataloaders import SimDataLoader
from data_assimilation_engine.utils.plotters import SimPlotter
from data_assimilation_engine.utils.processors import SimProcessor

logger = logging.getLogger(__name__)


class SoilMoistureSimDataLoader(SimDataLoader):
    """Data Loader for simulated soil moisture data."""


class SoilMoistureSimCalculator(SimCalculator):
    """Calculator for simulated soil moisture data."""

    def __init__(self, basin_gdf: gpd.GeoDataFrame = None):
        """Initialize the calculator."""
        super().__init__(basin_gdf)
        self.variable = "sm"
        self.column = "mean_sm"


class SoilMoistureSimPlotter(SimPlotter):
    """Plotter for simulated soil moisture data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the plotter with a GeoDataFrame."""
        super().__init__(gdf)
        self.column = "mean_sm"
        self.color_bar_label = "Soil Moisture (m³/m³)"
        self.title_str = "Simulated Soil Moisture (SM)\n date"

    @property
    def cmap(self):
        """Create a custom colormap for soil moisture visualization."""
        colors_for_gradient = [
            "firebrick",
            "darkred",
            "navajowhite",
            "yellow",
            "lightgrey",
            "skyblue",
            "lightblue",
            "cornflowerblue",
            "darkblue",
        ]

        # Create the LinearSegmentedColormap
        return mcolors.LinearSegmentedColormap.from_list(
            name="my_gradient_cmap",
            colors=colors_for_gradient,
            N=256,  # Number of color levels (higher N for smoother gradient)
        )


class SoilMoistureSimProcessor(SimProcessor):
    """Processor for simulated soil moisture data."""

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
        self.dl = SoilMoistureSimDataLoader(self.gpkg_file)
        self.calc = SoilMoistureSimCalculator(self.basin_gdf)
        self.plotter = SoilMoistureSimPlotter(self.basin_gdf)


class SoilMoistureConverter(Converter):
    """Convert soil moisture data from CSV to NetCDF format."""

    def __init__(self, csv_directory: str, dates: list, output_file: str):
        """Initialize the SoilMoistureConverter."""
        super().__init__(csv_directory, dates, output_file)
        self.variable_name = "sm"

    def convert_units(self, df: pd.DataFrame, mask: pd.DataFrame):
        """Convert Units."""
        return df.loc[mask, self.column1].values

    def check_columns(self, df: pd.DataFrame, file_path: str):
        """Check that columns exists."""
        columns = [column for column in df.columns if "sm_profile" in column]
        if len(columns) == 0:
            logger.info(f"{self.variable_name} columns not found in {file_path}")
            return False

        elif len(columns) > 1:
            logger.info(
                f"Too many ({len(columns)}) {self.variable_name} columns found in {file_path}"
            )
            return False
        else:
            self.column1 = columns[0]
            return True

    @property
    @lru_cache
    def times(self):
        """Get times as datetime objects and add timestamp."""
        try:
            times = np.array(
                [datetime.strptime(date, "%Y-%m-%d %H:%M:%S") for date in self.dates]
            )
        except ValueError:
            times = np.array(
                [datetime.strptime(date, "%Y-%m-%d") for date in self.dates]
            )
        return times


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
    """Run the simulated soil moisture processing."""
    args = get_options(args_list)
    processor = SoilMoistureSimProcessor(
        netcdf_file=args.netcdf_file,
        gpkg_file=args.gpkg_file,
        date=args.date,
        output_file=args.output_file,
        direct_s3=args.direct_s3,
    )
    processor.run()


if __name__ == "__main__":
    main()
