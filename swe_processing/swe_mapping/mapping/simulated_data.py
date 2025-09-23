"""Simulated SWE Mapper."""

import argparse
import logging
import time
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr

from utils.utils import Calculator, DataLoader, Plotter, Processor

from ..utility.snotel_utils import SnotelCalculator, SnotelDataLoader, SnotelPlotter

logger = logging.getLogger(__name__)


class SimDataLoader(DataLoader):
    """Data Loader for simulated SWE data."""

    @staticmethod
    def load_netcdf(netcdf_file: str | Path) -> xr.Dataset:
        """Load a NetCDF file and return the xarray Dataset."""
        t0 = time.time()
        sim_ds = xr.open_dataset(netcdf_file)
        logger.info(f"   NetCDF load time: {time.time() - t0:.2f}s")

        return sim_ds


class SoilMoistureSimDataLoader(SimDataLoader):
    """Data Loader for simulated soil moisture data."""


class SWESimDataLoader(SimDataLoader, SnotelDataLoader):
    """Data Loader for simulated SWE data."""


class SimCalculator(Calculator):
    """Calculator for simulated data."""

    def __init__(self, basin_gdf: gpd.GeoDataFrame = None):
        """Initialize the calculator."""
        super().__init__(basin_gdf)

    def process_data(self, sim_ds: xr.Dataset, date_str: str) -> gpd.GeoDataFrame:
        """Process simulated data from NetCDF and geopackage files.

        Args:
            sim_ds: xarray Dataset containing simulated data
            date_str: Date string from NetCDF time dim (ex: '2015-12-01')

        """
        basin_gdf = self.basin_gdf.copy()
        data = sim_ds[self.variable].sel(date=date_str).values

        # Create a mapping dictionary from catchment IDs to data values
        catchment_ids = sim_ds.catchment.values
        data_dict = dict(zip(catchment_ids, data))

        # Create catchment ID column and then lookup values from dict
        basin_gdf["catchment_id"] = (
            basin_gdf["divide_id"].str.split("-").str[1].astype(int)
        )
        basin_gdf[self.column] = basin_gdf["catchment_id"].map(data_dict).fillna(np.nan)

        return basin_gdf


class SWESimCalculator(SimCalculator, SnotelCalculator):
    """Calculator for simulated SWE data."""

    def __init__(self, basin_gdf: gpd.GeoDataFrame = None):
        """Initialize the calculator."""
        super().__init__(basin_gdf)
        self.variable = "swe"
        self.column = "mean_swe"


class SoilMoistureSimCalculator(SimCalculator):
    """Calculator for simulated soil moisture data."""

    def __init__(self, basin_gdf: gpd.GeoDataFrame = None):
        """Initialize the calculator."""
        super().__init__(basin_gdf)
        self.variable = "sm"
        self.column = "mean_sm"


class SimPlotter(Plotter):
    """Plotter for simulated data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the plotter with a GeoDataFrame."""
        super().__init__(gdf)


class SoilMoistureSimPlotter(SimPlotter):
    """Plotter for simulated soil moisture data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the plotter with a GeoDataFrame."""
        super().__init__(gdf)
        self.column = "mean_sm"
        self.color_bar_label = "Soil Moisture"
        self.title_str = "Simulated Soil Moisture (SM)\n date - 06z"


class SWESimPlotter(SimPlotter, SnotelPlotter):
    """Plotter for simulated SWE data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the plotter with a GeoDataFrame."""
        super().__init__(gdf)
        self.column = "mean_swe"
        self.color_bar_label = "Snow Water Equivalent (m)"
        self.title_str = "Simulated Snow Water Equivalent (SWE)\n date - 06z"


class SimProcessor(Processor):
    """Processor for simulated data."""

    def __init__(
        self,
        netcdf_file=None,
        gpkg_file=None,
        date=None,
        output_file=None,
        direct_s3=False,
    ):
        """Initialize the processor with input files and parameters."""
        # Initialize input parameters
        super().__init__(gpkg_file, date, output_file, direct_s3)

        self.netcdf_file = netcdf_file

    def run(self) -> None:
        """Run the processing workflow."""
        self.plot_simulated_data()

    @property
    @lru_cache
    def sim_ds(self) -> xr.Dataset:
        """Get the simulated xarray Dataset."""
        return self.dl.load_netcdf(self.netcdf_file)

    @property
    @lru_cache
    def basin_gdf_with_data(self) -> gpd.GeoDataFrame:
        """Processed gdf of the simulated data for mapping."""
        basin_gdf_with_data = self.calc.process_data(self.sim_ds, self.date)
        self.plotter.basin_gdf_with_data = basin_gdf_with_data
        return basin_gdf_with_data

    def scan(self) -> tuple[float, float]:
        """Scan the simulated data for min/max SWE values."""
        return self.get_minmax(self.basin_gdf_with_data["mean_swe"])

    def plot_simulated_data(self):
        """Plot the simulated data."""
        self.plotter.plot_choropleth_map()
        self.plotter.plot_catchment_boundaries()

        self.plotter.add_basin_overlay(self.basin_geometry)
        self.plotter.set_map_extent()
        self.plotter.add_colorbar()
        self.plotter.add_gridlines()
        self.plotter.add_title(self.date)
        # self.add_station_data()

        if self.output_file is not None:
            self.plotter.save_figure(self.output_file)


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

        self.dl = SWESimDataLoader()
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
        self.dl = SoilMoistureSimDataLoader()

        self.dl = SoilMoistureSimDataLoader()
        self.calc = SoilMoistureSimCalculator(self.basin_gdf)
        self.plotter = SoilMoistureSimPlotter(self.basin_gdf)


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
    """Run the SWE processing."""
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
