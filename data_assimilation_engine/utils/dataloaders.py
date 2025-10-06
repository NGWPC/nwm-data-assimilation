"""Data Loaders."""

import logging
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import fsspec
import geopandas as gpd
import xarray as xr

from data_assimilation_engine.utils.utils import timing_block

logger = logging.getLogger(__name__)


class DataLoader:
    """Base Data Loader."""

    def __init__(self, gpkg_file: str):
        """Initialize the DataLoader with a geopackage file path."""
        self.gpkg_file = gpkg_file

    @staticmethod
    def load_netcdf(netcdf_file: str | Path) -> xr.Dataset:
        """Load a NetCDF file and return the xarray Dataset."""
        with timing_block(f"Loading NetCDF file {netcdf_file}"):
            sim_ds = xr.open_dataset(netcdf_file)

        return sim_ds

    @property
    @lru_cache
    def basin_gdf(self) -> gpd.GeoDataFrame:
        """Read the 'divides' layer from a geopackage file and ensure geographic CRS.

        Returns
        -------
        geopandas.GeoDataFrame
            GeoDataFrame containing the basin divides with geographic CRS

        """
        if not os.path.exists(self.gpkg_file):
            raise FileNotFoundError(
                f"Geopackage file '{self.gpkg_file}' not found. Please check the file path."
            )

        basin_gdf = gpd.read_file(self.gpkg_file, layer="divides")

        if basin_gdf.crs is None or not basin_gdf.crs.is_geographic:
            basin_gdf = basin_gdf.to_crs("EPSG:4326")

        return basin_gdf


class SimDataLoader(DataLoader):
    """Data Loader for simulated SWE data."""

    @staticmethod
    def load_netcdf(netcdf_file: str | Path) -> xr.Dataset:
        """Load a NetCDF file and return the xarray Dataset."""
        with timing_block(f"Loading NetCDF file {netcdf_file}"):
            return xr.open_dataset(netcdf_file)


class ObsDataLoader(DataLoader):
    """Data Loader for Observed data."""

    def path_constructor(self, date: str, s3_mount_point: str, direct_s3: bool) -> str:
        """Construct the S3 path to SMAP NetCDF file.

        Parameters
        ----------
        date : str
            Date string in format 'YYYY-MM-DD'
        s3_mount_point : str
            S3 mount point for accessing data
        direct_s3 : bool
            Flag indicating whether to access S3 directly

        Returns
        -------
        str
            S3 path to the NetCDF file

        """
        file_date = self.datetime(date).strftime("%Y%m%d")
        hour = self.datetime(date).hour

        if not direct_s3:
            netcdf_file = f"{s3_mount_point}/{self.path_str}".replace(
                "date", file_date
            ).replace("hour", f"{hour:02d}")
            if os.path.exists(netcdf_file):
                return netcdf_file
            else:
                raise FileNotFoundError(f"File not found in local mount: {netcdf_file}")
        else:
            netcdf_file = f"s3://{self.path_str}".replace("date", file_date).replace(
                "hour", f"{hour:02d}"
            )
            fs = fsspec.filesystem("s3")
            if fs.exists(netcdf_file):
                return netcdf_file
            else:
                raise FileNotFoundError(f"File not found in S3: {netcdf_file}")

    def load_obs_netcdf(self, netcdf_file: str) -> xr.Dataset:
        """Load NetCDF data from an S3 path with chunking.

        Parameters
        ----------
        netcdf_file : str
            S3 path to the NetCDF file

        Returns
        -------
        xarray.Dataset
            Loaded xarray Dataset containing the data

        """
        # Open the NetCDF file with chunking to optimize performance and memory usage.
        with timing_block(f"Loading {self.dataset_name} NetCDF"):
            with fsspec.open(netcdf_file, mode="rb") as f:
                return xr.open_dataset(
                    f,
                    chunks={
                        "time": 1,
                        self.x_dim_name: self._chunk_size,
                        self.y_dim_name: self._chunk_size,
                    },
                ).load()
