"""Base Plotters."""

import logging

import cartopy.crs as ccrs
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import shapely
import xarray as xr

from utils.utils import get_minmax

logger = logging.getLogger(__name__)


class Plotter:
    """Base Plotter."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the plotter with a GeoDataFrame."""
        self.gdf = gdf
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


class SimPlotter(Plotter):
    """Plotter for simulated data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the plotter with a GeoDataFrame."""
        super().__init__(gdf)


class ObservedPlotter(Plotter):
    """Plotter for observed data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the plotter with a GeoDataFrame."""
        super().__init__(gdf)

    def plot_raw_data_polygon(
        self, fishnet_with_values: gpd.GeoDataFrame, ds_basin_subset: xr.Dataset
    ):
        """Plot raw data values with the basin boundary."""
        for _, row in fishnet_with_values.iterrows():
            if not np.isnan(row["value"]):
                self.ax.add_geometries(
                    [row.geometry],
                    crs=self.proj,
                    # facecolor="none",
                    facecolor=self.scalar_mappable.to_rgba(row["value"]),
                    edgecolor="none",
                )

    def plot_raw_data_raster(self, ds_basin_subset: xr.Dataset) -> None:
        """Plot raw data values with the basin boundary."""
        # Compute min/max values for colormap scaling
        self.vmin, self.vmax = get_minmax(
            ds_basin_subset.compute(), self.vmin, self.vmax
        )

        scalar_mappable = ds_basin_subset.plot(
            ax=self.ax,
            vmin=self.vmin,
            vmax=self.vmax,
            cmap=self.cmap,
            add_colorbar=False,
        )
        return scalar_mappable
