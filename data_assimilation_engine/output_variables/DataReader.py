import fsspec
import xarray as xr
import numpy as np
from . import consts

class DataReader:
    """
    Handles reading ngen catchment netcdf output for further data processing.
    """
    def __init__(self, netcdf_file: str, chunk_size: int = 100) -> None:
        """
        Args:
            netcdf_file : str
                The absolute or relative path to the ngen output NetCDF file.
            chunk_size : int
                The size to break larger datasets into smaller memory blocks. Defaults to 100

        Attributes:
            _netcdf_file (str): full or relative path to ngen NetCDF output.
            _chunk_size (int): chunk size for reading netcdf data.
            _dataset (xr.Dataset): ngen NetCDF xarray Dataset
            __catchment_dim (str): Name of the catchment dimension
            _catchment_coord (str): Name of the catchment coordinate variable


        Raises:

        """
        self._netcdf_file: str = netcdf_file
        self._chunk_size: int = chunk_size
        self._dataset: xr.Dataset = self._load_dataset()
        self._catchment_dim, self._catchment_coord = self._infer_catchment()

    def _load_dataset(self) -> xr.Dataset:
        """
        Load NetCDF using fsspec with chunking.

        Returns:
            xr.Dataset
                The xarray dataset of the netcdf file being read.
        """
        with fsspec.open(self._netcdf_file, mode="rb") as f:
            ds: xr.Dataset = xr.open_dataset(
                f,
                chunks={
                    consts.DIM_TIME: 1,
                    consts.DIM_CATCHMENTS: self._chunk_size
                }
            )
            return ds.load()
        
    def _infer_catchment(self) -> tuple[str, str]:
        """
        Read NetCDF and find long integer type coordinate for catchment.
        
        Returns:
            tuple[str, str]
                A tuple containing catchment dimension name and catchmetn coordinate variable name
        """
        ds = self._dataset

        # Find coordinate with IDs
        for coord_name in ds.coords:
            coord = ds[coord_name]
            if coord.dtype.kind in {"i", "u"} and coord.dtype.itemsize == 8 and coord.ndim == 1: #assumes catchments are the only long type.
                return coord.dims[0], coord_name

        raise ValueError("Could not find catchment IDs")