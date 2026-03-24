import os
import geopandas as gpd
import numpy as np
import xarray as xr
import dask.array as da
import time
from shapely.geometry import Point
from pyproj import CRS
from typing import List, Optional
from .DataReader import DataReader


class DataProcessor(DataReader):
    """
    Handles catchment-time NetCDF and grid generation.
    """
    def __init__(self, netcdf_file: str, gpkg_file: str, template_grid_file: str,
                 produce_template: bool, produce_output: bool, chunk_size: int = 100) -> None:
        super().__init__(netcdf_file, chunk_size)

        self.dimensions: List[str] = []
        self.output_variables: List[str] = []
        self.catchments: np.ndarray
        self.times: np.ndarray

        self.input_ds: xr.Dataset = self.dataset

        self.output_variables = list(self.input_ds.data_vars)

        # Read geopackage "divides" layer
        gpkg_gdf = gpd.read_file(gpkg_file, layer="divides")
        self.catchment_field = "divide_id"

        if gpkg_gdf.empty:
            raise ValueError("No polygon geometries found in GeoPackage")

        if produce_template:
            self.create_template_grid_netcdf_from_geopackage(gpkg_gdf, template_grid_file)
        self.ds_grid = xr.open_dataset(template_grid_file)
        # explicitly set CRS to CONUS. 
        # TO DO: Read an existing NWM grid file for CRS info 
        self.ds_grid = self.ds_grid.rio.write_crs("EPSG:5070") 

        if produce_output:
            self.grid_points = self.build_grid_centroids()
            self.build_grid_lookup(gpkg_gdf)
            output_path = 'sample_data/sample_netcdf/sample_output/final_test' #Change this to command line argument later
            start_time = time.perf_counter()
            self.create_grids_per_timestep_dask(output_path)
            end_time = time.perf_counter()
            duration_minutes = (end_time - start_time) / 60
            print(f"Function execution time: {duration_minutes:.4f} minutes")
            
    def create_template_grid_netcdf_from_geopackage(self, geopackage_gdf: gpd.GeoDataFrame, output_grid_netcdf: str,
                                                    resolution: int = 1000, epsg_code: int = 5070) -> None:
        """
        Create a NetCDF grid with 1 km x 1 km resolution 
        covering the extent of catchment polygons.

        Default CRS: EPSG:5070 (NAD83 / Conus Albers, meters)
        """

        if os.path.exists(output_grid_netcdf) == False:
            target_crs = CRS.from_epsg(epsg_code)
            gdf = geopackage_gdf.to_crs(target_crs)

            # Get bounding box
            minx, miny, maxx, maxy = gdf.total_bounds
            
            # Create grid coordinates and default to zero for the data
            x_coords = np.arange(minx, maxx + resolution, resolution)
            y_coords = np.arange(miny, maxy + resolution, resolution)
            grid_data = np.zeros((len(y_coords), len(x_coords)))

            ds = xr.Dataset(
                coords={
                    "x": ("x", x_coords),
                    "y": ("y", y_coords)
                }
            )
            # Coordinate metadata
            ds["x"].attrs["standard_name"] = "projection_x_coordinate"
            ds["x"].attrs["units"] = "m"

            ds["y"].attrs["standard_name"] = "projection_y_coordinate"
            ds["y"].attrs["units"] = "m"

            # Write CRS.
            ds.rio.write_crs("EPSG:5070", inplace=True)

            # Without the following line the grid was not lining up with the catchments
            # Set the X and Y as spatial dims for rioxarray
            ds.rio.set_spatial_dims(x_dim="x", y_dim="y", inplace=True)

            # Save
            ds.to_netcdf(output_grid_netcdf)
            print(f"NetCDF template grid written to {output_grid_netcdf}")
    
    def build_grid_centroids(self) -> gpd.GeoDataFrame:
        """
        Create GeoDataFrame of grid cell centroids.
        """
        x = self.ds_grid["x"].values
        y = self.ds_grid["y"].values
        xx, yy = np.meshgrid(x, y)
        points = [Point(px, py) for px, py in zip(xx.ravel(), yy.ravel())]
        
        return gpd.GeoDataFrame(
            {"cell_index": np.arange(len(points))},
            geometry=points,
            crs=self.ds_grid.rio.crs
        )

    def build_grid_lookup(self, catchment_gdf: gpd.GeoDataFrame) -> None:
        """
        Build the grid-to-catchment mapping (vectorized index array).
        Must be called just once before generating grids for every timestep.
        """
        self.catchment_list: List[str] = catchment_gdf[self.catchment_field].values.tolist()

        # Spatial join
        # TO DO: Have to determine if there are other methods that are less expensive computationally.
        joined = gpd.sjoin(
            self.grid_points,
            catchment_gdf[[self.catchment_field, "geometry"]],
            how="left",
            predicate="within"
        )

        # Build index map to allow working with integer indices (potentially faster than catchment ID strings)
        catchment_index = {c: i for i, c in enumerate(self.catchment_list)}
        mapped = joined[self.catchment_field].map(catchment_index)
        grid_to_catchment = mapped.fillna(-1).astype(int).to_numpy()
        self.grid_to_catchment = grid_to_catchment
        print("Grid-to-catchment mapping built!")

    def _build_crs_variable(self, ds_out: xr.Dataset) -> xr.Dataset:
        """
        Build CF-compliant CRS variable from a template NWM grid.
        Currently, this is not using the template NWM grid. It uses catchment grid instead.
        """

        # Get CRS from template
        crs_obj = CRS.from_user_input(self.ds_grid.rio.crs)

        # Convert to CF dict
        cf_attrs = crs_obj.to_cf()

        # Create CRS variable
        ds_out["crs"] = xr.DataArray(0)

        # Assign CF attributes
        ds_out["crs"].attrs.update(cf_attrs)

        # Add WKT (for QGIS)
        wkt = crs_obj.to_wkt()
        ds_out["crs"].attrs["spatial_ref"] = wkt
        ds_out["crs"].attrs["esri_pe_string"] = wkt

        # Add GeoTransform
        x = ds_out["x"].values
        y = ds_out["y"].values

        dx = float(x[1] - x[0])
        dy = float(y[1] - y[0])

        xmin = float(x[0] - dx / 2)
        ymax = float(y[-1] + dy / 2)

        ds_out["crs"].attrs["GeoTransform"] = f"{xmin} {dx} 0 {ymax} 0 {-dy}"

        # Optional (additional metadata)
        ds_out["crs"].attrs["_CoordinateAxes"] = "y x"
        ds_out["crs"].attrs["_CoordinateTransformType"] = "Projection"
        ds_out["crs"].attrs["long_name"] = "CRS definition"

        return ds_out

    def create_grids_per_timestep(self, output_dir: str) -> None:
        """
        Generates netcdf grids per timestep for all the variables in the catchments netcdf.
        """
        os.makedirs(output_dir, exist_ok=True)
        n_y = self.ds_grid.dims["y"]
        n_x = self.ds_grid.dims["x"]
        valid_mask = self.grid_to_catchment != -1
        grid_index_2d = self.grid_to_catchment.reshape(n_y, n_x)
        self.output_variables = list(self.input_ds.data_vars)

        # may be a robust approach is not to consider "time". Instead use
        # np.issubdtype(coord.dtype, np.datetime64)?
        time_dim = next(dim for dim in self.input_ds.dims if "time" in dim.lower())
        reference_time = np.datetime64('1970-01-01T00:00:00')
        
        for t in self.input_ds[time_dim].values:
            print(f"Processing timestep: {t}")
            ds_t = self.input_ds.sel({time_dim: t})
            ds_out = self.ds_grid.copy(deep=True)
            
            time_value_min = (t - reference_time) / np.timedelta64(1, 'm')
            ds_out = ds_out.assign_coords({time_dim: [time_value_min]})
            ds_out[time_dim].attrs["units"] = "minutes since 1970-01-01 00:00:00 UTC"
            ds_out[time_dim].attrs["standard_name"] = "time"
            ds_out = self._build_crs_variable(ds_out)

            # spatial_ref variable gets added somewhere. 
            # To Do: Need to find this later. a quick fix for now is to delete, if exists.
            if "spatial_ref" in ds_out.variables:
                ds_out = ds_out.drop_vars("spatial_ref")

            # Loop over all variables dynamically
            for var in self.output_variables:
                print(f"  Processing variable: {var}")
                values_1d = ds_t[var].values # Get catchment values (1D)
                flat_grid = np.full(self.grid_to_catchment.shape, np.nan) # Prepare flat grid
                flat_grid[valid_mask] = values_1d[self.grid_to_catchment[valid_mask]] # Assign values using lookup
                grid_2d = flat_grid.reshape(n_y, n_x) # Reshape to 2D
                ds_out[var] = (("time", "y", "x"), grid_2d[np.newaxis, :, :]) # Add to output dataset
                ds_out[var].attrs["grid_mapping"] = "crs" # Ensure the variable references CRS

            # Output filename and save
            t_str = np.datetime_as_string(t, unit='s') 
            formatted_t = t_str.replace('-', '_').replace(':', '_')
            output_file = os.path.join(output_dir, f"grid_{formatted_t}.nc")
            ds_out.to_netcdf(output_file)

    def create_grids_per_timestep_dask(self, output_dir: str, chunk_size: int = 1000) -> None:
        """
        Generates netcdf grids per timestep for all the variables in the catchments netcdf.
        """

        os.makedirs(output_dir, exist_ok=True)

        # Dimensions
        n_y = self.ds_grid.dims["y"]
        n_x = self.ds_grid.dims["x"]
        n_cells = n_y * n_x

        # Mask for valid cells
        valid_mask = self.grid_to_catchment != -1

        # Convert to Dask arrays
        grid_to_catchment_da = da.from_array(self.grid_to_catchment, chunks=chunk_size)
        valid_mask_da = da.from_array(valid_mask, chunks=chunk_size)

        # Rechunk by time dimension as we are processing one timestep at a time
        time_dim = next(dim for dim in self.input_ds.dims if np.issubdtype(self.input_ds[dim].dtype, np.datetime64))
        reference_time = np.datetime64('1970-01-01T00:00:00')
        ds_in = self.input_ds.chunk({time_dim: 1})

        for t in ds_in[time_dim].values:
            print(f"Processing timestep: {t}")

            ds_t = ds_in.sel({time_dim: t})
            ds_out = self.ds_grid.copy(deep=True)
            time_value_min = (t - reference_time) / np.timedelta64(1, 'm')
            ds_out = ds_out.assign_coords({time_dim: [time_value_min]})
            ds_out = self._build_crs_variable(ds_out)

            # spatial_ref variable gets added somewhere. 
            # To Do: Need to find this later. a quick fix for now is to delete, if exists.
            if "spatial_ref" in ds_out.variables:
                ds_out = ds_out.drop_vars("spatial_ref")

            for var in ds_in.data_vars:
                print(f"  Processing variable: {var}")

                values_1d = ds_t[var].data # (catchment,) → Dask array

                # Convert to Dask array if needed
                if not isinstance(values_1d, da.Array):
                    values_1d = da.from_array(values_1d, chunks=values_1d.shape)
                
                flat_grid = da.full((n_cells,), np.nan, chunks=chunk_size)
                assigned = da.where(
                    valid_mask_da,
                    values_1d[grid_to_catchment_da],
                    np.nan
                )
                
                grid_2d = assigned.reshape((n_y, n_x))
                grid_3d = grid_2d[None, :, :]  # (time=1, y, x)
                ds_out[var] = (("time", "y", "x"), grid_3d)
                ds_out[var].attrs = ds_in[var].attrs
                ds_out[var].attrs["grid_mapping"] = "crs" #"spatial_ref"

            ds_out[time_dim].attrs["units"] = "minutes since 1970-01-01 00:00:00 UTC"
            ds_out[time_dim].attrs["standard_name"] = "time"

            # Output file  and save
            t_str = np.datetime_as_string(t, unit='s') 
            formatted_t = t_str.replace('-', '_').replace(':', '_')
            output_file = os.path.join(output_dir, f"grid_{formatted_t}.nc")
            ds_out.to_netcdf(output_file)