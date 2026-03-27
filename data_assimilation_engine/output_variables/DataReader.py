import fsspec
import xarray as xr
import numpy as np


class DataReader:
    def __init__(self, netcdf_file: str, chunk_size: int = 100) -> None:
        self.netcdf_file: str = netcdf_file
        self.chunk_size: int = chunk_size
        self.dataset: xr.Dataset = self._load_dataset()
        self.catchment_dim, self.catchment_coord = self._infer_catchment()

    def _load_dataset(self) -> xr.Dataset:
        """Load NetCDF using fsspec with chunking."""
        with fsspec.open(self.netcdf_file, mode="rb") as f:
            ds: xr.Dataset = xr.open_dataset(
                f,
                chunks={
                    "time": 1,
                    "catchment": self.chunk_size
                }
            )
            return ds.load()
        
    def _infer_catchment(self):
        """Read NetCDF and find string type coordinate for catchment."""
        ds = self.dataset

        # Find coordinate with IDs
        for coord_name in ds.coords:
            coord = ds[coord_name]
            if coord.dtype.kind in {"U", "S", "O"} and coord.ndim == 1: #assumes catchments are string type.
                return coord.dims[0], coord_name

        raise ValueError("Could not find catchment IDs")
    
    def assign_random_values(self, output_file: str) -> None:
        """
        Assign random values between 1 and 10 to all data variables.
        This function can be deleted once we address the catchment netcdf writing issue.
        """

        with fsspec.open(self.netcdf_file, mode="rb") as f:
            ds = xr.open_dataset(f)

        for var_name in ds.data_vars:
            print(f"Assigning random values to {var_name}")
            random_values = np.random.uniform(
                1.0, 10.0, size=ds[var_name].shape
            )
            ds[var_name].values = random_values

        ds.to_netcdf(output_file)
        print(f"Saved updated dataset to {output_file}")