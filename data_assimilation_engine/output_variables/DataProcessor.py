import os
import geopandas as gpd
import numpy as np
import xarray as xr
import rioxarray
from shapely.geometry import Point
#import fiona
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

        # Read geopackage. Had to specify "divides" because the default layer 
        # in the geopackage was not the catchments
        gpkg_gdf = gpd.read_file(gpkg_file, layer="divides")
        self.catchment_field = "divide_id"

        # Keep only polygon geometries. Once we fix the above with pulling all layers, this becomes necessary.
        gpkg_gdf = gpkg_gdf[gpkg_gdf.geom_type.isin(["Polygon", "MultiPolygon"])]

        if gpkg_gdf.empty:
            raise ValueError("No polygon geometries found in GeoPackage")

        if produce_template:
            self.create_template_grid_netcdf_from_geopackage(gpkg_gdf, template_grid_file)
        self.ds_grid = xr.open_dataset(template_grid_file)
        self.ds_grid = self.ds_grid.rio.write_crs("EPSG:5070") #had to explicitly write this info for spatial join later.

        if produce_output:
            self.grid_points = self.build_grid_centroids()
            self.build_grid_lookup(gpkg_gdf)
            output_path = 'sample_data/sample_netcdf/sample_output/final_test'
            self.create_grids_per_timestep(output_path)
            
    def create_template_grid_netcdf_from_geopackage(self, geopackage_gdf: gpd.GeoDataFrame, output_grid_netcdf: str,
                                                    resolution: int = 1000, epsg_code: int = 5070) -> None:
        """
        Create a NetCDF grid in Lambert Conformal Conic CRS with
        1 km x 1 km resolution covering the extent of catchment polygons.

        Default CRS: EPSG:5070 (NAD83 / Conus Albers, meters)
        You may change to another LCC EPSG if needed.
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
                {
                    "grid": (("y", "x"), grid_data)
                },
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

            # Write CRS. Had to use rioxarray. Trials with pyproj CRS weren't successful.
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
        Must be called once before generating grids.
        """

        self.catchment_list: List[str] = catchment_gdf[self.catchment_field].values.tolist()

        # Spatial join
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

        # valid_indices = np.where(grid_to_catchment != -1)[0]
        # for idx in valid_indices[:10]:
        #     print(f"Index: {idx}, Value: {grid_to_catchment[idx]}")
        print("Grid-to-catchment mapping built!")

    def create_grids_per_timestep(self, output_dir: str) -> None:
        os.makedirs(output_dir, exist_ok=True)

        n_y = self.ds_grid.dims["y"]
        n_x = self.ds_grid.dims["x"]

        # mask for valid cells
        valid_mask = self.grid_to_catchment != -1

        # reshape index lookup to 2D grid
        grid_index_2d = self.grid_to_catchment.reshape(n_y, n_x)

        self.output_variables = list(self.input_ds.data_vars)

        time_dim = next(dim for dim in self.input_ds.dims if "time" in dim.lower())
        reference_time = np.datetime64('1970-01-01T00:00:00')
        counter = 0

        for t in self.input_ds[time_dim].values:
            if counter <= 2:
                print(f"Processing timestep: {t}")

                # Select timestep
                ds_t = self.input_ds.sel({time_dim: t})

                # Copy template grid
                ds_out = self.ds_grid.copy(deep=True)

                # Convert time value to minutes in NWM grid
                time_value_min = (t - reference_time) / np.timedelta64(1, 'm')

                ds_out = ds_out.expand_dims({time_dim: [time_value_min]})

                ds_out[time_dim].attrs["units"] = "minutes since 1970-01-01 00:00:00 UTC"
                ds_out[time_dim].attrs["standard_name"] = "time"
                # time_encoding = {
                #     time_dim: {
                #         "units": "minutes since 1970-01-01 00:00:00",
                #         "calendar": "proleptic_gregorian"
                #     }
                # }

                ds_out.rio.set_spatial_dims(x_dim="x", y_dim="y", inplace=True)
                

                # Loop over all variables dynamically
                for var in self.output_variables:
                    print(f"  Processing variable: {var}")

                    # Get catchment values (1D)
                    values_1d = ds_t[var].values

                    # Prepare flat grid
                    flat_grid = np.full(self.grid_to_catchment.shape, np.nan)

                    # Assign values using lookup
                    flat_grid[valid_mask] = values_1d[self.grid_to_catchment[valid_mask]]

                    # Reshape to 2D
                    grid_2d = flat_grid.reshape(n_y, n_x)

                    # Add to output dataset
                    #ds_out[var] = (("y", "x"), grid_2d)
                    ds_out[var] = (("time", "y", "x"), grid_2d[np.newaxis, :, :])

                    # Ensure the variable references CRS
                    ds_out[var].attrs["grid_mapping"] = "spatial_ref"

                # Output filename
                t_str = np.datetime_as_string(t, unit='s') 
                formatted_t = t_str.replace('-', '_').replace(':', '_')
                output_file = os.path.join(output_dir, f"grid_{formatted_t}.nc")

                # Save
                ds_out.rio.write_crs(self.ds_grid.rio.crs, inplace=True) #add CRS to output file
                ds_out.to_netcdf(output_file)
                counter += 1
