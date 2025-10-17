"""Base Data Processors."""

import logging
import os
from functools import lru_cache

import fsspec
import geopandas as gpd
import numpy as np
import xarray as xr

from data_assimilation_engine.utils.utils import get_minmax

logger = logging.getLogger(__name__)


class Processor:
    """Base Processor."""

    def __init__(
        self,
        gpkg_file=None,
        output_file=None,
        direct_s3=False,
    ):
        """Initialize the processor with input files and parameters."""
        # Initialize input parameters
        self.gpkg_file = gpkg_file
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
        basin_gdf = self.dl.basin_gdf.copy()
        basin_gdf[self.column] = np.nan
        return basin_gdf

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


class SimProcessor(Processor):
    """Processor for simulated data."""

    def __init__(
        self,
        netcdf_file=None,
        gpkg_file=None,
        output_file=None,
        direct_s3=False,
    ):
        """Initialize the processor with input files and parameters."""
        # Initialize input parameters
        super().__init__(gpkg_file, output_file, direct_s3)

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
        """Scan the simulated data for min/max values."""
        return self.get_minmax(self.basin_gdf_with_data[self.column])

    def plot_simulated_data(self):
        """Plot the simulated data."""
        self.plotter.plot_choropleth_map()
        self.plotter.plot_catchment_boundaries()

        self.plotter.add_basin_overlay(self.basin_geometry)
        self.plotter.set_map_extent()
        self.plotter.add_colorbar()
        self.plotter.add_gridlines()
        self.plotter.add_title(self.date)
        self.add_station_data()

        if self.output_file is not None:
            self.plotter.save_figure(self.output_file)


class ObsProcessor(Processor):
    """Processor for Observed data mapping and visualization."""

    def __init__(
        self,
        gpkg_file=None,
        output_file_raw=None,
        output_file_lumped=None,
        direct_s3=False,
    ):
        """Initialize the Observed Processor.

        Args:
        ----
        gpkg_file : str, optional
            Path to geopackage file with basin/catchment boundaries
        output_file_raw : str, optional
            Path where raw SWE visualization will be saved
        output_file_lumped : str, optional
            Path where catchment-averaged visualization will be saved
        direct_s3 : bool, optional
            Whether to access S3 directly or via mounted filesystem

        """
        super().__init__(gpkg_file=gpkg_file, direct_s3=direct_s3)

        self.output_file_raw = output_file_raw
        self.output_file_lumped = output_file_lumped

    @property
    @lru_cache
    def obs_file(self) -> str | None:
        """Get the observed data file path."""
        return self.dl.path_constructor(self.date, self.s3_mount_point, self.direct_s3)

    @property
    @lru_cache
    def obs_ds(self) -> xr.Dataset | None:
        """Get the observed dataset."""
        if self.check_datetime(self.date):
            return self.dl.load_obs_netcdf(self.obs_file)

    def run(self, vmin: float, vmax: float) -> None:
        """Run the complete observed data processing pipeline."""
        logging.debug(f"Initial vmin: {vmin}, vmax: {vmax}")
        self.set_vmin_vmax(vmin, vmax)
        self.basin_gdf_with_data
        self.process_raw()
        self.process_lumped()

    def process_raw(self) -> None:
        """Process and plot raw SNODAS data."""
        self.raw_plotter.set_map_extent()

        # scalar_mappable = self.raw_plotter.plot_raw_data_raster(
        #     self.calc.ds_basin_subset[self.calc.dataset_name]
        # )
        if self.check_datetime(self.date):
            self.raw_plotter.plot_raw_data_polygon(
                self.calc.fishnet_with_values,
                self.calc.ds_basin_subset[self.calc.dataset_name],
            )
        self.raw_plotter.plot_catchment_boundaries()
        self.raw_plotter.add_basin_overlay(self.basin_geometry)

        self.raw_plotter.add_colorbar()
        self.raw_plotter.add_gridlines()
        self.raw_plotter.add_title(self.date)
        self.add_station_data()

        if self.output_file_raw is not None:
            self.raw_plotter.save_figure(self.output_file_raw)

    def set_vmin_vmax(self, vmin: float, vmax: float):
        """Set the global vmin and vmax using current data."""
        if self.check_datetime(self.date):
            self.vmin, self.vmax = self.get_minmax(
                self.calc.fishnet_with_values["value"], vmin, vmax
            )
        else:
            self.vmin = vmin
            self.vmax = vmax

        self.raw_plotter.vmin = self.vmin
        self.raw_plotter.vmax = self.vmax
        self.lumped_plotter.vmin = self.vmin
        self.lumped_plotter.vmax = self.vmax

    @property
    @lru_cache
    def basin_gdf_with_data(self) -> gpd.GeoDataFrame:
        """Get the basin GeoDataFrame with computed catchment mean values."""
        if self.check_datetime(self.date):
            self.lumped_plotter.basin_gdf_with_data = self.calc.calculate_catchment_mean
            self.raw_plotter.basin_gdf_with_data = self.calc.calculate_catchment_mean
            return self.calc.calculate_catchment_mean
        else:
            self.lumped_plotter.basin_gdf_with_data = self.basin_gdf
            self.raw_plotter.basin_gdf_with_data = self.basin_gdf
            return self.basin_gdf

    def process_lumped(self) -> None:
        """Process and plot catchment-averaged data."""
        self.lumped_plotter.plot_choropleth_map()
        self.lumped_plotter.plot_catchment_boundaries()
        self.lumped_plotter.add_basin_overlay(self.basin_geometry)
        self.lumped_plotter.set_map_extent()
        self.lumped_plotter.add_colorbar()
        self.lumped_plotter.add_gridlines()
        self.lumped_plotter.add_title(self.date)
        # self.add_station_data()

        if self.output_file_lumped is not None:
            self.lumped_plotter.save_figure(self.output_file_lumped)
