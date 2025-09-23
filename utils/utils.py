import logging
import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from time import time

import cartopy.crs as ccrs
import fsspec
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import shapely
import xarray as xr

from swe_processing.swe_mapping.utility.swe_minmax import get_minmax

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@contextmanager
def timing_block(step_str: str):
    """Context manager for timing code execution.

    Args:
        step_str: Description of the step being timed.

    """
    start = time()
    yield
    end = time()
    logger.info(f"  Execution time for {step_str}: {end - start} seconds")


class DataLoader:
    """Base Data Loader."""

    @staticmethod
    def load_netcdf(netcdf_file: str | Path) -> xr.Dataset:
        """Load a NetCDF file and return the xarray Dataset."""
        with timing_block(f"Loading NetCDF file {netcdf_file}"):
            sim_ds = xr.open_dataset(netcdf_file)

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


class Calculator:
    """Base Calculator."""

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


class Plotter:
    """Base Plotter."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the plotter with a GeoDataFrame."""
        self.gdf = gdf
        self.cmap = plt.cm.Blues
        self._create_base_plot()

        self._min = np.nan
        self._max = np.nan

    def _create_base_plot(self) -> tuple:
        """Create a base map plot with cartopy projection."""
        self.fig, self.ax = plt.subplots(
            figsize=(15, 10), subplot_kw={"projection": self.proj}
        )

    def plot_choropleth_map(self):
        """Plot catchments filled with their values."""
        for _, row in self.basin_gdf_with_data.iterrows():
            if not np.isnan(row[self.column]):
                self.ax.add_geometries(
                    [row.geometry],
                    crs=self.proj,
                    facecolor=self.scalar_mappable.to_rgba(row[self.column]),
                    edgecolor="none",
                )

    def add_title(self, date_str: str):
        """Add a title to the plot."""
        self.ax.set_title(self.title_str.replace("date", date_str))

    @property
    def proj(self):
        """Get the cartopy projection (PlateCarree)."""
        return ccrs.PlateCarree()

    @property
    def vmin(self):
        """Get the global minimum value for color scale."""
        if np.isnan(self.basin_gdf_with_data[self.column]).all():
            logger.warning(
                "current_data contains only NaNs, skipping min/max calculation."
            )
            return np.nan  # or some default value
        else:
            return np.nanmin(
                self.basin_gdf_with_data[self.column].to_list() + [self._min]
            )

    @property
    def vmax(self):
        """Get the global maximum value for color scale."""
        if np.isnan(self.basin_gdf_with_data[self.column]).all():
            logger.warning(
                "current_data contains only NaNs, skipping min/max calculation."
            )
            return np.nan
        else:
            return np.nanmax(
                self.basin_gdf_with_data[self.column].to_list() + [self._max]
            )

    @vmin.setter
    def vmin(self, value: float):
        """Set the global minimum value for color scale."""
        self._min = value

    @vmax.setter
    def vmax(self, value: float):
        """Set the global maximum value for color scale."""
        self._max = value

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

    def save_figure(self, output_file: str):
        """Save a figure to a file.

        Parameters
        ----------
        output_file : str
            Path where the figure should be saved

        """
        logging.debug(f"Saving figure to {output_file}")
        self.fig.savefig(output_file, dpi=300, bbox_inches="tight")
        # self.fig.close()
        # self.fig.clf()

    def add_colorbar(self, scalar_mappable: None | plt.cm.ScalarMappable = None):
        """Add a colorbar to a map plot.

        Parameters
        ----------
        scalar_mappable : matplotlib.cm.ScalarMappable, optional
            ScalarMappable object for color scaling

        Returns
        -------
        matplotlib.colorbar.Colorbar
            Colorbar object

        """
        # Plot colorbar based on settings in plot functions
        if scalar_mappable is None:
            scalar_mappable = self.scalar_mappable
        cbar = self.fig.colorbar(self.scalar_mappable, ax=self.ax, pad=0.02)
        cbar.set_label(self.color_bar_label, fontsize=10)
        return cbar


class Processor:
    """Base Processor."""

    def __init__(
        self,
        gpkg_file=None,
        date=None,
        output_file=None,
        direct_s3=False,
    ):
        """Initialize the processor with input files and parameters."""
        # Initialize input parameters
        self.gpkg_file = gpkg_file
        self.date = date
        self.output_file = output_file
        self.direct_s3 = direct_s3

    def get_minmax(
        self, current_data: np.ndarray, vmin: float, vmax: float
    ) -> tuple[float, float]:
        """Update the global min/max with current data.

        Returns:
            The current global values

        """
        if np.isnan(current_data).all():
            logger.warning(
                "current_data contains only NaNs, skipping min/max calculation."
            )
            current_min = np.nan  # or some default value
            current_max = np.nan
        else:
            current_min = np.nanmin(current_data)
            current_max = np.nanmax(current_data)

        vmin = min(vmin, current_min)
        vmax = max(vmax, current_max)

        return vmin, vmax

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

    def scan(self) -> tuple[float, float]:
        """Scan the simulated data for min/max values."""
        return get_minmax(self.basin_gdf_with_data[self.column])
