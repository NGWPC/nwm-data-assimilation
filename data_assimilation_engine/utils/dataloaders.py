"""Data Loaders."""

import logging
import os
from functools import lru_cache
from glob import glob
from pathlib import Path

import fsspec
import geopandas as gpd
import pandas as pd
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
            return xr.open_dataset(netcdf_file)

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

    def __init__(self, gpkg_file: str, csv_directory: str):
        """Initialize the DataLoader with a directory containing CSV files."""
        super().__init__(gpkg_file)
        self.directory = csv_directory

    @staticmethod
    def load_netcdf(netcdf_file: str | Path) -> xr.Dataset:
        """Load a NetCDF file and return the xarray Dataset."""
        with timing_block(f"Loading NetCDF file {netcdf_file}"):
            ds = xr.open_dataset(netcdf_file, engine="h5netcdf")
            ds.load()
            ds.close()
            return ds

    @property
    def output_file(self) -> str:
        """Get the output netcdf file path."""
        return os.path.join(self.directory, "converted_output.nc")

    @property
    @lru_cache
    def csv_files(self):
        """Get all CSV files in the specified directory."""
        pattern = os.path.join(self.directory, "cat-*.csv")
        return glob(pattern)

    def csv_to_netcdf(self) -> str:
        """Convert CSV files in the directory to a NetCDF file."""
        dfs = {}
        for file in self.csv_files:
            df = pd.read_csv(file)
            cat = os.path.splitext(os.path.basename(file))[0]
            df.index = pd.to_datetime(df.Time)
            df.drop(columns=["Time Step", "Time"], inplace=True)

            dfs[cat] = df

        new_ds = xr.concat([df.to_xarray() for df in dfs.values()], dim="catchments")

        new_ds.coords["catchments"] = list(dfs.keys())
        new_ds.to_netcdf(self.output_file, engine="h5netcdf")
        return self.output_file


class ObsDataLoader(DataLoader):
    """Data Loader for Observed data."""

    def path_constructor(self, date: str, s3_mount_point: str, direct_s3: bool) -> str:
        """Construct the S3 path to observed NetCDF file.

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
