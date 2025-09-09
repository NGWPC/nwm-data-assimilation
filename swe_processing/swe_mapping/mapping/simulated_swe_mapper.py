"""Simulated SWE Mapper."""

import argparse
import logging
import os
import re
import time
from functools import lru_cache
from pathlib import Path

import cartopy.crs as ccrs
import fsspec
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely
import xarray as xr
from shapely import Point

from ..utility.snotel_utils import SnotelCalculator, SnotelDataLoader, SnotelPlotter
from ..utility.swe_minmax import get_minmax

logger = logging.getLogger(__name__)


class DataLoader:
    """Data Loader for simulated SWE data."""

    @staticmethod
    def load_netcdf(netcdf_file: str | Path) -> xr.Dataset:
        """Load a NetCDF file and return the xarray Dataset."""
        t0 = time.time()
        sim_ds = xr.open_dataset(netcdf_file)
        logger.info(f"   NetCDF load time: {time.time() - t0:.2f}s")

        return sim_ds

    @staticmethod
    def read_geo(gpkg_file: str | Path) -> gpd.GeoDataFrame:
        """Read the 'divides' layer from a geopackage file and ensure geographic CRS.

        Parameters
        ----------
        gpkg_file : str
            Path to the geopackage file

        Returns
        -------
        geopandas.GeoDataFrame
            GeoDataFrame containing the basin divides with geographic CRS

        """
        if not os.path.exists(gpkg_file):
            raise FileNotFoundError(
                f"Geopackage file '{gpkg_file}' not found. Please check the file path."
            )

        basin_gdf = gpd.read_file(gpkg_file, layer="divides")

        if basin_gdf.crs is None or not basin_gdf.crs.is_geographic:
            basin_gdf = basin_gdf.to_crs("EPSG:4326")

        return basin_gdf


class SoilMoistureDataLoader(DataLoader):
    """Data Loader for simulated soil moisture data."""


class SWEDataLoader(DataLoader):
    """Data Loader for simulated SWE data."""

    @staticmethod
    def get_s3_filesystem(direct_s3: bool) -> fsspec.AbstractFileSystem:
        """Get the SNOTEL filesystem for S3 access."""
        if direct_s3:
            return fsspec.filesystem("s3")
        else:
            return fsspec.filesystem("local")

    @staticmethod
    def list_snotel_filenames(
        s3_mount_point: str, snotel_s3_path: str, direct_s3: bool
    ) -> tuple:
        """List SNOTEL CSV files available in the S3 bucket.

        Returns
        -------
        list
            List of filenames (strings) of SNOTEL CSV files in the S3 bucket or local mount

        """
        path = snotel_s3_path

        if not direct_s3:
            fs = fsspec.filesystem("local")
            full_path = f"{s3_mount_point}/{path}"
            objects = fs.ls(full_path)
            if not objects:
                raise FileNotFoundError(f"Local snotel files not found at {full_path}")
        else:
            fs = fsspec.filesystem("s3")
            objects = fs.ls(path)
            if not objects:
                raise FileNotFoundError(f"Snotel files not found on S3: {path}")

        filenames = [obj.split("/")[-1] for obj in objects if "/" in obj]

        # Filter out empty strings
        snotel_filenames = [f for f in filenames if f]

        return snotel_filenames

    @staticmethod
    def parse_snotel_filenames(filenames: list) -> gpd.GeoDataFrame:
        """Parse latitude and longitude from SNOTEL filenames and create a GeoDataFrame.

        Parameters
        ----------
        filenames : list
            List of SNOTEL filenames to parse

        Returns
        -------
        geopandas.GeoDataFrame
            GeoDataFrame with columns for station_id, latitude, longitude, filename,
            and geometry (Point objects)

        """
        data = []

        for filename in filenames:
            # Skip if not a CSV file
            if not filename.endswith(".csv"):
                continue

            # Use regex to extract information from the filename
            # Only works with files created by the pre-processor script
            match = re.search(r"(\d+)_LAT_([\d.-]+)_LON_([\d.-]+)\.csv", filename)

            if match:
                station_id = match.group(1)
                latitude = float(match.group(2))
                longitude = float(match.group(3))

                data.append(
                    {
                        "station_id": station_id,
                        "latitude": latitude,
                        "longitude": longitude,
                        "filename": filename,
                        "geometry": Point(longitude, latitude),
                    }
                )

        # Convert to GeoDataFrame for spatial operations
        stations_gdf = gpd.GeoDataFrame(data, geometry="geometry")

        # Converts to EPSG:4326 for the coordinates
        stations_gdf.crs = "EPSG:4326"

        return stations_gdf

    @staticmethod
    def load_snotel_data(
        stations_in_basin: gpd.GeoDataFrame,
        date: str,
        fs,
        s3_mount_point: str,
        snotel_s3_path: str,
    ):
        """Load SNOTEL SWE data for stations within the basin for a specific date.

        Optimized for loading a single timestep.

        Args:
        ----
        stations_in_basin : geopandas.GeoDataFrame
            GeoDataFrame of SNOTEL stations that are within the basin
        date : str
            Date string in format 'YYYY-MM-DD'
        fs : fsspec.AbstractFileSystem
            File system object for accessing S3 or local files
        s3_mount_point : str
            Local mount point for S3 files
        snotel_s3_path : str
            S3 path for SNOTEL data

        Returns:
        -------
        pandas.DataFrame
            DataFrame with station information and SWE values for the specified date

        """
        if stations_in_basin.empty:
            return pd.DataFrame()

        # Initialize a list to store data
        snotel_data_list = []

        path = snotel_s3_path

        if "local" in fs.protocol:
            base_path = f"{s3_mount_point}/{path}"
        elif "s3" in fs.protocol:
            base_path = f"s3://{path}"

        # Process each station in the basin
        for _, station in stations_in_basin.iterrows():
            filename = station["filename"]
            s3_path = f"{base_path}/{filename}"
            try:
                # Open and read the CSV file
                with fs.open(s3_path, "r") as file:
                    df = pd.read_csv(file)
                    # Convert the target date to datetime
                    target_date = pd.to_datetime(date)

                    # Filter for rows where the date matches the target date
                    df["date"] = pd.to_datetime(df["date"])
                    df_filtered = df[df["date"].dt.date == target_date.date()]

                    if not df_filtered.empty:
                        # Get the SWE value for this date
                        swe_value = df_filtered["snotel_swe"].iloc[0]

                        # Create a record with station info and SWE value
                        snotel_data_list.append(
                            {
                                "station_id": station["station_id"],
                                "latitude": station["latitude"],
                                "longitude": station["longitude"],
                                "swe": swe_value,
                            }
                        )
                    else:
                        logger.info(
                            f"No data found for station {station['station_id']} on {date}"
                        )
            except Exception as e:
                logger.info(
                    f"Error loading SNOTEL data for station {station['station_id']}: {e}"
                )

        # Convert list to DataFrame
        snotel_df = pd.DataFrame(snotel_data_list)
        return snotel_df


class Calculator:
    """Calculator for simulated data."""

    def __init__(self, basin_gdf: gpd.GeoDataFrame = None):
        """Initialize the calculator."""
        self.basin_gdf = basin_gdf

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

    @property
    @lru_cache
    def basin_geometry(self) -> shapely.geometry:
        """Extract a unified basin geometry from a GeoDataFrame.

        Returns
        -------
        shapely.geometry
            (basin_geometry) where:
                - basin_geometry is a shapely geometry representing the entire basin

        """
        # Combine all polygons for basin outline
        try:
            return self.basin_gdf.union_all()
        except AttributeError:
            return self.basin_gdf.unary_union

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Get the bounds of the basin geometry.

        Returns
        -------
        tuple
            (minx, miny, maxx, maxy) for the basin extent

        """
        return self.basin_gdf.total_bounds


class SWECalculator(Calculator):
    """Calculator for simulated SWE data."""

    def __init__(self, gdf: gpd.GeoDataFrame = None):
        """Initialize the calculator."""
        super().__init__(gdf)
        self.variable = "swe"
        self.column = "mean_swe"

    @staticmethod
    def find_stations_in_basin(
        stations_gdf: gpd.GeoDataFrame, basin_geometry: shapely.geometry
    ) -> gpd.GeoDataFrame:
        """Find SNOTEL stations that fall within the basin geometry.

        Parameters
        ----------
        stations_gdf : geopandas.GeoDataFrame
            GeoDataFrame containing SNOTEL station information
        basin_geometry : shapely.geometry
            Basin geometry to use for filtering stations

        Returns
        -------
        geopandas.GeoDataFrame
            Filtered GeoDataFrame containing only stations within the basin

        """
        # Ensure CRS match between stations and basin geometry
        if hasattr(basin_geometry, "crs") and basin_geometry.crs != stations_gdf.crs:
            stations_gdf = stations_gdf.to_crs(basin_geometry.crs)

        # Filter stations within the basin
        stations_in_basin = stations_gdf[stations_gdf.intersects(basin_geometry)]

        if not stations_in_basin["station_id"].empty:
            station_return = []
            for stations in stations_in_basin["station_id"]:
                station_return.append(stations)
            logger.info(
                f"{len(station_return)} SNOTEL stations found in basin: {station_return}"
            )

        return stations_in_basin


class SoilMoistureCalculator(Calculator):
    """Calculator for simulated soil moisture data."""

    def __init__(self):
        """Initialize the calculator."""
        super().__init__()
        self.variable = "sm"
        self.column = "mean_sm"


class Plotter:
    """Plotter for simulated SWE data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the plotter with a GeoDataFrame."""
        self.gdf = gdf
        self.cmap = plt.cm.Blues
        self._create_base_plot()

    def _create_base_plot(self) -> tuple:
        """Create a base map plot with cartopy projection."""
        self.fig, self.ax = plt.subplots(
            figsize=(15, 10), subplot_kw={"projection": self.proj}
        )

    @property
    def proj(self):
        """Get the cartopy projection (PlateCarree)."""
        return ccrs.PlateCarree()

    @property
    def vmin(self):
        """Get the global minimum value for color scale."""
        if np.isnan(self.simulated_gdf["mean_swe"]).all():
            logger.warning(
                "current_data contains only NaNs, skipping min/max calculation."
            )
            return np.nan  # or some default value
        else:
            return np.nanmin(self.simulated_gdf["mean_swe"])

    @property
    def vmax(self):
        """Get the global maximum value for color scale."""
        if np.isnan(self.simulated_gdf["mean_swe"]).all():
            logger.warning(
                "current_data contains only NaNs, skipping min/max calculation."
            )
            return np.nan
        else:
            return np.nanmax(self.simulated_gdf["mean_swe"])

    @property
    def norm(self):
        """Get the normalization for color scale."""
        return plt.Normalize(vmin=self.vmin, vmax=self.vmax)

    @property
    def scalar_mappable(self):
        """Get the ScalarMappable for color scale."""
        return plt.cm.ScalarMappable(cmap=self.cmap, norm=self.norm)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Get the basin bounds."""
        return self.gdf.total_bounds  # (minx, miny, maxx, maxy)

    @property
    def map_extent(self) -> list[float]:
        """Set the map extent with appropriate buffers around bounds."""
        # Set the extent using dynamic vertical and horizontal buffers
        buff_v = abs(self.bounds[2] - self.bounds[0]) * 0.01
        buff_h = abs(self.bounds[3] - self.bounds[1]) * 0.01
        return [
            self.bounds[0] - buff_v,
            self.bounds[2] + buff_v,
            self.bounds[1] - buff_h,
            self.bounds[3] + buff_h,
        ]

    def set_map_extent(self):
        """Set the map extent with appropriate buffers around bounds."""
        self.ax.set_extent(self.map_extent, crs=self.proj)

    def add_basin_overlay(self, basin_geometry: shapely.geometry):
        """Add the basin outline to a map plot.

        Parameters
        ----------
        basin_geometry : shapely.geometry
            Basin geometry to add as outline

        """
        # Overlay basin outline
        self.ax.add_geometries(
            [basin_geometry],
            crs=self.proj,
            facecolor="none",
            edgecolor="red",
            linewidth=1.5,
        )

    def plot_catchment_boundaries(self):
        """Add catchment boundaries to a map plot."""
        # Iterate over polygons in the dataframe, drawing boundaries
        for _, row in self.gdf.iterrows():
            self.ax.add_geometries(
                [row.geometry],
                crs=self.proj,
                facecolor="none",
                edgecolor="black",
                linewidth=0.5,
                alpha=0.5,
            )

    def add_gridlines(self):
        """Add gridlines to a map plot.

        Returns
        -------
        cartopy.mpl.gridliner.Gridliner
            Gridliner object for the added gridlines

        """
        # Add gridlines
        gl = self.ax.gridlines(
            draw_labels=True, linewidth=0.5, color="gray", alpha=0.5, linestyle="--"
        )
        gl.top_labels = False
        gl.right_labels = False
        return gl

    def plot_polygon_simulated(self):
        """Plot catchments filled with their simulated (lumped) values."""
        for _, row in self.simulated_gdf.iterrows():
            if not np.isnan(row[self.column]):
                self.ax.add_geometries(
                    [row.geometry],
                    crs=self.proj,
                    facecolor=self.scalar_mappable.to_rgba(row[self.column]),
                    edgecolor="none",
                )

        self.plot_catchment_boundaries()

    def save_figure(self, output_file: str):
        """Save a figure to a file.

        Parameters
        ----------
        output_file : str
            Path where the figure should be saved

        """
        plt.savefig(output_file, dpi=300, bbox_inches="tight")
        plt.close(self.fig)

    def add_colorbar(self):
        """Add a colorbar to a map plot.

        Returns
        -------
        matplotlib.colorbar.Colorbar
            Colorbar object

        """
        # Plot colorbar based on settings in plot functions
        cbar = plt.colorbar(self.scalar_mappable, ax=self.ax, pad=0.02)
        cbar.set_label(self.color_bar_label, fontsize=10)
        return cbar


class SoilMoisturePlotter(Plotter):
    """Plotter for simulated soil moisture data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the plotter with a GeoDataFrame."""
        super().__init__(gdf)
        self.column = "mean_sm"
        self.color_bar_label = "Soil Moisture"

    def add_title(self, date_str: str):
        """Add a title to the plot."""
        plt.title(f"Simulated Soil Moisture (SM)\n {date_str} - 06z")


class SimProcessor:
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
        self.netcdf_file = netcdf_file
        self.gpkg_file = gpkg_file
        self.date = date
        self.output_file = output_file
        self.direct_s3 = direct_s3

    def run(self) -> None:
        """Run the processing workflow."""
        # self.setup_data()
        # self.process_data()
        self.plot_simulated_data()

    @property
    def s3_mount_point(self) -> str:
        """Get the S3 mount point from environment variable or default path."""
        return os.getenv("S3_MOUNT_POINT", os.path.join(os.path.expanduser("~"), "s3"))

    @property
    @lru_cache
    def basin_gdf(self) -> gpd.GeoDataFrame:
        """Get the basin GeoDataFrame."""
        return self.dl.read_geo(self.gpkg_file)

    @property
    @lru_cache
    def sim_ds(self) -> xr.Dataset:
        """Get the simulated xarray Dataset."""
        return self.dl.load_netcdf(self.netcdf_file)

    @property
    @lru_cache
    def basin_geometry(self) -> gpd.GeoSeries:
        """Get the basin geometry."""
        return self.calc.basin_geometry

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Get the basin bounds."""
        return self.calc.bounds(self.basin_gdf)

    @property
    @lru_cache
    def snotel_filenames(self) -> list[str]:
        """Get the list of SNOTEL filenames."""
        return self.dl.list_snotel_filenames(
            self.s3_mount_point, self.snotel_s3_path, self.direct_s3
        )

    @property
    @lru_cache
    def snotel_filesystem(self) -> fsspec.AbstractFileSystem | None:
        """Get the SNOTEL filesystem for S3 access."""
        return self.dl.get_s3_filesystem(self.direct_s3)

    @property
    @lru_cache
    def simulated_gdf(self) -> gpd.GeoDataFrame:
        """Processed gdf of the simulated data for mapping."""
        simulated_gdf = self.calc.process_data(self.sim_ds, self.date)
        self.plotter.simulated_gdf = simulated_gdf
        return simulated_gdf

    def scan(self) -> tuple[float, float]:
        """Scan the simulated data for min/max SWE values."""
        return get_minmax(self.simulated_gdf["mean_swe"])

    def plot_simulated_data(self):
        """Plot the simulated data."""
        self.plotter.plot_polygon_simulated()

        self.plotter.add_basin_overlay(self.basin_geometry)
        self.plotter.set_map_extent()
        self.plotter.add_colorbar()
        self.plotter.add_gridlines()
        self.plotter.add_title(self.date)
        self.add_station_data()

        if self.output_file is not None:
            self.plotter.save_figure(self.output_file)


class SWEPlotter(Plotter):
    """Plotter for simulated SWE data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the plotter with a GeoDataFrame."""
        super().__init__(gdf)
        self.column = "mean_swe"
        self.color_bar_label = "Snow Water Equivalent (m)"

    def add_title(self, date_str: str):
        """Add a title to the plot."""
        plt.title(f"Simulated Snow Water Equivalent (SWE)\n {date_str} - 06z")

    def add_snotel_overlay(self, snotel_data: pd.DataFrame):
        """Add SNOTEL SWE data as text overlays on a map.

        Parameters
        ----------
        snotel_data : pandas.DataFrame
            DataFrame with station information and SWE values

        Returns
        -------
        matplotlib.axes.Axes
            Updated axes with SNOTEL overlay

        """
        if snotel_data.empty:
            return self.ax

        color = "#990000"

        if not snotel_data.empty:
            # Plot all stations
            self.ax.plot(
                snotel_data["longitude"],
                snotel_data["latitude"],
                "o",
                markersize=3,
                transform=self.proj,
                color=color,
                label="SNOTEL Stations (SWE)",
            )

            # Add text labels iteratively
            for _, station in snotel_data.iterrows():
                swe_value = f"{station['swe']:.2f}"
                self.ax.text(
                    station["longitude"] + 0.0005,
                    station["latitude"] - 0.0005,
                    swe_value,
                    fontsize=11,
                    ha="left",
                    va="top",
                    transform=self.proj,
                    fontweight="bold",
                    color=color,
                )
            # Add the legend to the plot, using the specified label
            self.ax.legend(
                loc="upper right",
                fontsize=10,
                framealpha=0.5,
                bbox_to_anchor=(1.25, 1.05),
            )


class SimSWEProcessor(SimProcessor):
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

        self.dl = SWEDataLoader()
        self.calc = SWECalculator(self.basin_gdf)
        self.plotter = SWEPlotter(self.basin_gdf)

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

    def add_station_data(self):
        """Add SNOTEL station data overlay to the plot if available."""
        # Add SNOTEL data overlay if available
        if (
            self.stations_in_basin is not None
            and not self.stations_in_basin.empty
            and self.snotel_data is not None
        ):
            self.plotter.add_snotel_overlay(self.snotel_data)


class SimSoilMoistureProcessor(SimProcessor):
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
        self.dl = SoilMoistureDataLoader()


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
    processor = SimSWEProcessor(
        netcdf_file=args.netcdf_file,
        gpkg_file=args.gpkg_file,
        date=args.date,
        output_file=args.output_file,
        direct_s3=args.direct_s3,
    )
    processor.run()


if __name__ == "__main__":
    main()
