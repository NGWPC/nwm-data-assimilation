"""Simulated SWE Mapper."""

import argparse
import os
import time
from pathlib import Path

import cartopy.crs as ccrs
import fsspec
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from ..utility.geo_utils import GeoUtils
from ..utility.plot_utils import PlotUtils
from ..utility.snotel_utils import SnotelCalculator, SnotelDataLoader, SnotelPlotter
from ..utility.swe_minmax import get_minmax


class DataLoader:
    """Data Loader for simulated SWE data."""

    @staticmethod
    def load_netcdf(netcdf_file: str | Path) -> xr.Dataset:
        """Load a NetCDF file and return the xarray Dataset."""
        t0 = time.time()
        sim_ds = xr.open_dataset(netcdf_file)
        print(f"   NetCDF load time: {time.time() - t0:.2f}s")

        return sim_ds

    @staticmethod
    def list_snotel_filenames(
        s3_mount_point: str, snotel_s3_path: str, direct_s3: bool
    ) -> list[str]:
        """List SNOTEL CSV files available in the S3 bucket."""
        return SnotelDataLoader.list_snotel_filenames(
            s3_mount_point, snotel_s3_path, direct_s3
        )

    @staticmethod
    def parse_snotel_filenames(filenames: list[str]) -> gpd.GeoDataFrame:
        """Parse latitude and longitude from SNOTEL filenames and create a GeoDataFrame."""
        return SnotelDataLoader.parse_snotel_filenames(filenames)

    @staticmethod
    def load_snotel_data(
        stations_in_basin: gpd.GeoDataFrame,
        date: str,
        fs: fsspec.AbstractFileSystem,
        s3_mount_point: str,
        snotel_s3_path: str,
    ) -> pd.DataFrame:
        """Load SNOTEL SWE data for stations within the basin for a specific date."""
        return SnotelDataLoader.load_snotel_data(
            stations_in_basin, date, fs, s3_mount_point, snotel_s3_path
        )

    @staticmethod
    def read_geo(gpkg_file: str) -> gpd.GeoDataFrame:
        """Read divides layer from .gpkg file to GeoDataFrame."""
        return GeoUtils.read_geo(gpkg_file)


class Calculator:
    """Calculator for simulated SWE data."""

    @staticmethod
    def process_data(
        sim_ds: xr.Dataset, date_str: str, basin_gdf: gpd.GeoDataFrame
    ) -> gpd.GeoDataFrame:
        """Load and process SWE data from NetCDF and geopackage files.

        Args:
            sim_ds: xarray Dataset containing simulated SWE data
            date_str: Date string from NetCDF time dim (ex: '2015-12-01')
            basin_gdf: GeoDataFrame containing basin geometries

        """
        swe_data = sim_ds.swe.sel(date=date_str).values

        # Create a mapping dictionary from catchment IDs to SWE values
        catchment_ids = sim_ds.catchment.values
        swe_dict = dict(zip(catchment_ids, swe_data))

        # Create catchment ID column and then lookup values from dict
        basin_gdf["catchment_id"] = (
            basin_gdf["divide_id"].str.split("-").str[1].astype(int)
        )
        basin_gdf["mean_swe"] = basin_gdf["catchment_id"].map(swe_dict).fillna(np.nan)
        # print(f"   SWE load/process time: {time.time() - t2:.2f}s")

        return basin_gdf

    @staticmethod
    def get_basin_geometry(
        basin_gdf: gpd.GeoDataFrame,
    ) -> tuple[gpd.GeoSeries, gpd.GeoSeries]:
        """Extract a unified basin geometry and bounds from a GeoDataFrame."""
        return GeoUtils.get_basin_geometry(basin_gdf)

    @staticmethod
    def find_stations_in_basin(
        stations_gdf: gpd.GeoDataFrame, basin_geometry: gpd.GeoSeries
    ) -> gpd.GeoDataFrame:
        """Find SNOTEL stations that fall within the basin geometry."""
        return SnotelCalculator.find_stations_in_basin(stations_gdf, basin_geometry)


class Plotter:
    """Plotter for simulated SWE data."""

    @staticmethod
    def create_base_plot() -> plt.Axes:
        """Create a base map plot with cartopy projection."""
        return PlotUtils.create_base_plot()

    @staticmethod
    def plot_catchment_boundaries(
        ax: plt.Axes, gdf: gpd.GeoDataFrame, proj
    ) -> plt.Axes:
        """Add catchment boundaries to plot."""
        return PlotUtils.plot_catchment_boundaries(ax, gdf, proj)

    @staticmethod
    def plot_polygon_simulated_swe(
        ax: plt.Axes, gdf: gpd.GeoDataFrame, proj
    ) -> plt.Axes:
        """Plot catchments filled with their simulated (lumped) SWE values."""
        # Set color scale based on min/max values
        # vmin = float(gdf['mean_swe'].min())
        vmin, vmax = get_minmax(gdf["mean_swe"])
        norm = plt.Normalize(vmin=vmin, vmax=vmax)
        cmap = plt.cm.Blues
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)

        for _, row in gdf.iterrows():
            if not np.isnan(row["mean_swe"]):
                ax.add_geometries(
                    [row.geometry],
                    crs=proj,
                    facecolor=cmap(norm(row["mean_swe"])),
                    edgecolor="none",
                )

        ax = Plotter.plot_catchment_boundaries(ax, gdf, proj)
        return ax, sm, vmin, vmax

    @staticmethod
    def set_map_extent(
        ax: plt.Axes, bounds: tuple[float, float, float, float], proj
    ) -> plt.Axes:
        """Set the map extent with appropriate buffers around bounds."""
        return PlotUtils.set_map_extent(ax, bounds, proj)

    @staticmethod
    def add_basin_overlay(
        ax: plt.Axes, basin_geometry: gpd.GeoSeries, proj
    ) -> plt.Axes:
        """Add the basin outline to a map plot."""
        return PlotUtils.add_basin_overlay(ax, basin_geometry, proj)

    @staticmethod
    def add_gridlines(ax: plt.Axes) -> plt.Axes:
        """Add gridlines to a map plot."""
        return PlotUtils.add_gridlines(ax)

    @staticmethod
    def add_colorbar(im: plt.Image, ax: plt.Axes) -> plt.Axes:
        """Add a colorbar to a map plot."""
        return PlotUtils.add_colorbar(im, ax)

    @staticmethod
    def plot_swe_map(
        netcdf_file: str,
        gpkg_file: str,
        date_str: str,
        output_file: str,
        mode: str = "plot",
    ) -> None:
        """Create a map of simulated SWE values by catchment."""
        ds, gdf, basin_geometry, bounds = load_and_process_data(
            netcdf_file, gpkg_file, date_str
        )
        # t1 = time.time()

        # Call plot function
        ax, im, vmin, vmax = plot_polygon_simulated_swe(ax, gdf, proj)

        # Title bar with date

    @staticmethod
    def add_snotel_overlay(ax: plt.Axes, snotel_data: pd.DataFrame, proj):
        """Add SNOTEL SWE data as text overlays on a map."""
        return SnotelPlotter.add_snotel_overlay(ax, snotel_data, proj)

    @staticmethod
    def save_figure(fig, output_file):
        """Save a figure to a file."""
        return PlotUtils.save_figure(fig, output_file)


class SimSWEProcessor:
    """Processor for simulated SWE data."""

    def __init__(
        self,
        netcdf_file=None,
        gpkg_file=None,
        date=None,
        output_file=None,
        mode=None,
        direct_s3=False,
    ):
        """Initialize the processor with input files and parameters."""
        # Initialize input parameters
        self.netcdf_file = netcdf_file
        self.gpkg_file = gpkg_file
        self.date = date
        self.output_file = output_file
        self.mode = mode
        self.direct_s3 = direct_s3

        # Initialize data attributes
        self.basin_gdf = None
        self.swe_gdf = None
        self.bounds = None
        self.basin_geometry = None
        self.sim_ds = None

        # Initialize plot attributes
        self.vmin = None
        self.vmax = None
        self.sim_fig = None
        self.sim_ax = None
        self.sim_im = None
        self.proj = None
        self.ext = None

        # Initialize SNOTEL-related attributes
        self.snotel_filenames = None
        self.stations_gdf = None
        self.stations_in_basin = None
        self.snotel_data = None
        self.snotel_filesystem = None
        self.snotel_s3_path = None
        self.s3_mount_point = None

    def run(self) -> None:
        """Run the SWE processing workflow."""
        self.setup_data()
        self.process_data()
        self.plot_swe()

    def setup_data(self) -> None:
        """Set up the data for processing."""
        self.snotel_s3_path = "ngwpc-forcing/snotel_csv"
        self.s3_mount_point = os.getenv(
            "S3_MOUNT_POINT", os.path.join(os.path.expanduser("~"), "s3")
        )
        self.basin_gdf = DataLoader.read_geo(self.gpkg_file)
        self.sim_ds = DataLoader.load_netcdf(self.netcdf_file)
        self.basin_geometry, self.bounds = Calculator.get_basin_geometry(self.basin_gdf)

        # For SNOTEL data
        self.snotel_filenames, self.snotel_filesystem = (
            DataLoader.list_snotel_filenames(
                self.s3_mount_point, self.snotel_s3_path, self.direct_s3
            )
        )
        self.stations_gdf = DataLoader.parse_snotel_filenames(self.snotel_filenames)
        self.stations_in_basin = Calculator.find_stations_in_basin(
            self.stations_gdf, self.basin_geometry
        )

        # Load SNOTEL data if stations exist in basin
        if not self.stations_in_basin.empty:
            self.snotel_data = DataLoader.load_snotel_data(
                self.stations_in_basin,
                self.date,
                self.snotel_filesystem,
                self.s3_mount_point,
                self.snotel_s3_path,
            )

    def process_data(self) -> None:
        """Process the data for SWE mapping."""
        self.swe_gdf = Calculator.process_data(self.sim_ds, self.date, self.basin_gdf)

    def plot_swe(self):
        """Plot the simulated SWE data."""
        if self.mode == "scan":
            return get_minmax(self.swe_gdf["mean_swe"])
        self.sim_fig, self.sim_ax, self.proj = Plotter.create_base_plot()
        self.ext = Plotter.set_map_extent(self.sim_ax, self.bounds, self.proj)
        self.sim_ax, self.sim_im, self.vmin, self.vmax = (
            Plotter.plot_polygon_simulated_swe(self.sim_ax, self.swe_gdf, self.proj)
        )
        self.sim_ax = Plotter.add_basin_overlay(
            self.sim_ax, self.basin_geometry, self.proj
        )
        cbar = Plotter.add_colorbar(self.sim_im, self.sim_ax)
        plt.title(f"Simulated Snow Water Equivalent (SWE)\n {self.date} - 06z")
        gl = Plotter.add_gridlines(self.sim_ax)
        # Add SNOTEL data overlay if available
        if (
            self.stations_in_basin is not None
            and not self.stations_in_basin.empty
            and self.snotel_data is not None
        ):
            self.sim_ax = Plotter.add_snotel_overlay(
                self.sim_ax, self.snotel_data, self.proj
            )
        if self.output_file is not None:
            Plotter.save_figure(self.sim_fig, self.output_file)


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
        "--mode",
        type=str,
        default="plot",
        choices=["plot", "scan"],
        help="Operation mode: 'plot' or 'scan'",
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
    processor = SimSWEProcessor(
        netcdf_file=args.netcdf_file,
        gpkg_file=args.gpkg_file,
        date=args.date,
        output_file=args.output_file,
        mode=args.mode,
        direct_s3=args.direct_s3,
    )
    processor.run()


if __name__ == "__main__":
    main()
