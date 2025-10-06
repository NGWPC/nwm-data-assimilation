"""Observed Soil Moisture Mapper."""

import argparse
import logging
from datetime import datetime
from functools import lru_cache

import geopandas as gpd
import matplotlib.colors as mcolors
import pandas as pd
import xarray as xr

from data_assimilation_engine.utils.calculators import ObsCalculator
from data_assimilation_engine.utils.dataloaders import ObsDataLoader
from data_assimilation_engine.utils.plotters import ObservedPlotter
from data_assimilation_engine.utils.processors import ObsProcessor

logger = logging.getLogger(__name__)


class SoilMoistureObsDataLoader(ObsDataLoader):
    """Data Loader for Observed Soil Moisture data."""

    def __init__(self, gpkg_file: str):
        """Initialize the SoilMoistureObsDataLoader."""
        self.dataset_name = "sm_rootzone"  # Variable name in xarray Dataset
        self.path_str = (
            "ngwpc-forcing/smap_nc/SMAP_L4_SM_gph_dateThour3000_Vv8010_001.nc"
        )
        self._chunk_size = 100  # Default chunk size
        self.x_dim_name = "x"  # X dimension name in xarray Dataset
        self.y_dim_name = "y"  # Y dimension name in xarray Dataset
        super().__init__(gpkg_file)

    @property
    def chunk_size(self):
        """Return the chunk size used for loading data."""
        return self._chunk_size

    @chunk_size.setter
    def chunk_size(self, value):
        """Set the chunk size used for loading data."""
        self._chunk_size = value

    def datetime(self, date: str):
        """Get the datetime object for the specified date."""
        return datetime.strptime(date, "%Y-%m-%d %H:%M:%S")


class SoilMoistureObsCalculator(ObsCalculator):
    """Calculator for Observed Soil Moisture data processing."""

    def __init__(self, basin_gdf: gpd.GeoDataFrame = None, ds: xr.Dataset = None):
        """Initialize the calculator."""
        super().__init__(basin_gdf, ds)
        self.column = "mean_sm"  # Column to store computed values in GeoDataFrame
        self.dataset_name = "sm_rootzone"  # Variable name in xarray Dataset
        self.x_dim_name = "x"  # X dimension name in xarray Dataset
        self.y_dim_name = "y"  # Y dimension name in xarray Dataset
        self.crs = "EPSG:6933"  # Coordinate Reference System

    def convert_units(self, ds: xr.Dataset) -> xr.Dataset:
        """Convert units of the dataset if necessary."""
        # Default implementation does nothing
        return ds[self.dataset_name]


class RawSoilMoistureObsPlotter(ObservedPlotter):
    """Class for creating plots of Raw Soil Moisture data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the RawSoilMoistureObsPlotter."""
        super().__init__(gdf)
        self.basin_gdf_with_data = None  # To be set externally
        self.title_str = "Raw SMAP Soil Moisture\n date - 06z"
        self.color_bar_label = "Soil Moisture (m³/m³)"
        self.column = "mean_sm"  # Column with computed values

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


class SoilMoistureObsPlotter(ObservedPlotter):
    """Class for creating plots of Observed Soil Moisture data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the SoilMoistureObsPlotter."""
        super().__init__(gdf)
        self.basin_gdf_with_data = None  # To be set externally
        self.column = "mean_sm"  # Column with computed values
        self.title_str = "Lumped SMAP Soil Moisture\n date - 06z"
        self.color_bar_label = "Soil Moisture (m³/m³)"

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


class SoilMoistureObsProcessor(ObsProcessor):
    """Processor for Observed Soil Moisture data mapping and visualization."""

    def __init__(
        self,
        date: str,
        gpkg_file: str,
        output_file_raw: str,
        output_file_lumped: str,
        direct_s3=False,
    ):
        """Initialize the Soil Moisture Observed Processor."""
        super().__init__(
            date, gpkg_file, output_file_raw, output_file_lumped, direct_s3
        )
        # self.snotel_s3_path = "ngwpc-forcing/snotel_csv"
        self.column = "mean_sm"

        self.dl = SoilMoistureObsDataLoader(self.gpkg_file)
        self.calc = SoilMoistureObsCalculator(self.basin_gdf, self.obs_ds)
        self.raw_plotter = RawSoilMoistureObsPlotter(self.basin_gdf)
        self.lumped_plotter = SoilMoistureObsPlotter(self.basin_gdf)

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
            self.raw_plotter.add_snotel_overlay(self.snotel_data)
            self.lumped_plotter.add_snotel_overlay(self.snotel_data)


def get_options(args_list=None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        args_list : list, optional
        List of arguments to parse (defaults to command line arguments)

    Returns:
    -------
    argparse.Namespace
        Namespace containing the parsed arguments

    """
    parser = argparse.ArgumentParser()
    parser.add_argument("date", type=str, help="Date of SNODAS data to map.")
    parser.add_argument("gpkg_file", type=str, help="Path to geopackage file.")
    parser.add_argument(
        "output_file_raw",
        type=str,
        help="Path where raw visualization output is saved.",
    )
    parser.add_argument(
        "output_file_lumped",
        type=str,
        help="Path where catchment-averaged output is saved.",
    )
    parser.add_argument(
        "--direct_s3",
        action="store_true",
        help="Use direct S3 access instead of local mount",
    )
    args_list = list(args_list)
    return parser.parse_args(args_list)


def main(args_list=None) -> None:
    """Run the Observed Soil Moisture processor.

    Args:
    ----
    args_list : list, optional
        List of arguments to parse (defaults to command line arguments)

    """
    args = get_options(args_list)

    # Create, then run, a processor instance
    processor = SoilMoistureObsProcessor(
        date=args.date,
        gpkg_file=args.gpkg_file,
        output_file_raw=args.output_file_raw,
        output_file_lumped=args.output_file_lumped,
        direct_s3=args.direct_s3,
    )

    processor.run()


if __name__ == "__main__":
    main()
