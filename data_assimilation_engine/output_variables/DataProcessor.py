import os
import json
import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
import dask.array as da
import time
import fiona
from shapely.geometry import Point
from shapely.ops import unary_union
from shapely import intersects_xy
from pyproj import CRS
from typing import List, Optional
from .DataReader import DataReader


class DataProcessor(DataReader):
    """
    Handles catchment-time NetCDF and grid generation.
    """
    def __init__(self, catchment_output_netcdf_file: str, gpkg_file: str, template_grid_file_name: str, 
                  config_path: str, output_class: str, category: str, domain: str,
                 produce_template: bool, produce_output: bool, chunk_size: int = 100) -> None:
        super().__init__(catchment_output_netcdf_file, chunk_size)

        self.catchment_ds: xr.Dataset = self.dataset
        self.output_variables = list(self.catchment_ds.data_vars)
        # Normalize catchment ids in netcdf with a cat- prefix for consistency.
        self.nc_catchments = self._normalize_catchment_ids(self.catchment_ds[self.catchment_coord].values)

        # Read geopackage, determine schema and "divides" layer
        self.is_new_NHF_schema: bool = self._is_new_NHF_schema(gpkg_file, "reference_flowpaths")
        print (self.is_new_NHF_schema)
        gpkg_gdf = gpd.read_file(gpkg_file, layer="divides")
        if gpkg_gdf.empty:
            raise ValueError("No polygon geometries found in GeoPackage")

        # Check schema and assign catchment ID field.
        if self.is_new_NHF_schema:
            self.catchment_field = "div_id"
        else:
            self.catchment_field = "divide_id"

        # Normalize catchment ids in gpkg with a 'cat-' prefix for consistency.
        gpkg_gdf[self.catchment_field] = self._normalize_catchment_ids(gpkg_gdf[self.catchment_field].values)
        self.gpkg_catchment_list = gpkg_gdf[self.catchment_field].values.tolist()

        # Check if catchments from netcdf and geopackage match
        if set(self.nc_catchments) != set(self.gpkg_catchment_list):
            raise ValueError("There is a mistmatch between catchment IDs in geopackage and netcdf")   

        # Old workflow
        # if produce_template:
        #     self.obsolete_create_template_grid_netcdf_from_geopackage(gpkg_gdf, template_grid_file)
        # self.ds_template_grid = xr.open_dataset(template_grid_file)

        # if produce_output: 
        #     self.grid_points = self.obsolete_build_grid_centroids()
        #     self.obsolete_build_grid_lookup(gpkg_gdf)
        #     output_path = 'sample_data/sample_netcdf/sample_output/final_test' #Change this to command line argument later
        #     start_time = time.perf_counter()
        #     self.obsolete_create_grids_per_timestep_dask(output_path)
        #     end_time = time.perf_counter()
        #     duration_minutes = (end_time - start_time) / 60
        #     print(f"Function execution time: {duration_minutes:.4f} minutes")

        # New workflow
        if produce_template:
            self.create_template_grid_netcdf_using_config(gpkg_gdf, template_grid_file_name,
                                                          config_path, output_class, category, domain)
        self.ds_template_grid = xr.open_dataset(template_grid_file_name)
        print(self.ds_template_grid.rio.crs)
        
        if produce_output:
            # change variable name in the randomvals.nc This is strictly for testing purposes.
            self.catchment_ds = self.catchment_ds.rename({
                'sm_frac_0.4m': 'ACCET',
                'sm_profile_0.1m': 'ACSNOM',
                'sm_profile_0.4m': 'EDIR',
                'sm_profile_1.5m': 'ISNOW',
                'sm_profile_2m': 'QRAIN',
                'SWE_mm': 'QSNOW'
            })
            catchment_grid = self.build_catchment_id_grid(template_grid_file_name, gpkg_gdf, "x", "y") # Change hardcoded values later
            mapped_grid = self.map_catchment_data_to_grid(catchment_grid, "catchments","time") # Change hardcoded values later
            output_dir = 'sample_data/sample_netcdf/sample_output/final_test' #Change this to command line argument later
            start_time = time.perf_counter()
            self.write_netcdf_per_timestep(mapped_grid, output_dir, "time")
            end_time = time.perf_counter()
            duration_minutes = (end_time - start_time) / 60
            print(f"Function execution time: {duration_minutes:.4f} minutes")
            
    def _is_new_NHF_schema(self, geopackage_path: str, layer_name: str) -> bool:
        """
        Check the data schema in the geopackage for the new NHF format
        """
        layers = gpd.list_layers(geopackage_path)
        tabular_layers = layers[layers['geometry_type'].isna()]
        return layer_name.lower() in tabular_layers['name'].tolist()
    
    def _normalize_catchment_ids(self, ids) -> np.ndarray:
        """
        Ensure all IDs are prefixed with 'cat-'. This is necessary when catchments are not prefixed
        with 'cat-' in netcdf and geopackage for consistency. 
        """
        ids_str = ids.astype(str)

        normalized = np.array([
            id_ if id_.startswith("cat-") else f"cat-{id_}"
            for id_ in ids_str
        ])
        return normalized
    
    def _snap_to_grid(self, value: float, origin: float, resolution: int, direction: np.ufunc):
        if direction == np.floor:
            return origin + np.floor((value - origin) / resolution) * resolution
        elif direction == np.ceil:
            return origin + np.ceil((value - origin) / resolution) * resolution
    
    def obsolete_create_template_grid_netcdf_from_geopackage(self, geopackage_gdf: gpd.GeoDataFrame, output_grid_netcdf: str,
                                                    resolution: int, epsg_code: int, origin_x: float,
                                                    origin_y: float) -> None:
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

            snapped_minx = self._snap_to_grid(minx, origin_x, resolution, np.floor)
            snapped_maxx = self._snap_to_grid(maxx, origin_x, resolution, np.ceil)
            snapped_miny = self._snap_to_grid(miny, origin_y, resolution, np.floor)
            snapped_maxy = self._snap_to_grid(maxy, origin_y, resolution, np.ceil)
            
            # Create grid coordinates 
            x_coords = np.arange(snapped_minx, snapped_maxx + resolution, resolution)
            y_coords = np.arange(snapped_miny, snapped_maxy + resolution, resolution)
            
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
    
    def create_template_grid_netcdf_using_config(self, geopackage_gdf: gpd.GeoDataFrame, template_grid_netcdf_path: str,
        config_path: str,
        output_class: str,
        category: str,
        domain: str
    ) -> None:
        """
        Create a template grid aligned to a reference grid defined in config.json.
        The template grid is for the extents in the geopackage (usually basin level).
        """
        # Read config file
        with open(config_path, "r") as f:
            config = json.load(f)

        # Find matching entry
        entry = next((c_item for c_item in config["files"] if 
              c_item["class"] == output_class and 
              c_item["category"] == category and 
              c_item["domain"] == domain), None)
        if entry is None:
            raise ValueError(f"Cannot find a config file entry that matches {output_class}, {category} and {domain}")

        origin_x = entry["origin"]["x"]
        origin_y = entry["origin"]["y"]
        res_x = entry["resolution"]["x"]
        res_y = entry["resolution"]["y"]
        wkt = entry["crs_wkt"]
        file_name = entry["file_path"]
        x_name = entry["location_name"]["x"]
        y_name = entry["location_name"]["y"]

        ds = xr.open_dataset(file_name)
        # To do: Have to figure out a workflow when CRS is "Not Available"
        target_crs = CRS.from_user_input(wkt) 
        
        gdf = geopackage_gdf.to_crs(target_crs)
        geom = unary_union(gdf.geometry) 
        
        # Get bounding box and snap to origin in config
        minx, miny, maxx, maxy = gdf.total_bounds

        snapped_minx = self._snap_to_grid(minx, origin_x, res_x, np.floor)
        snapped_maxx = self._snap_to_grid(maxx, origin_x, res_x, np.ceil)
        snapped_miny = self._snap_to_grid(miny, origin_y, res_y, np.floor)
        snapped_maxy = self._snap_to_grid(maxy, origin_y, res_y, np.ceil)

        ds_subset = ds.sel(
            {
                x_name: slice(snapped_minx, snapped_maxx),
                y_name: slice(snapped_miny, snapped_maxy),
            }
        )
        x_subset = ds_subset[x_name].values
        y_subset = ds_subset[y_name].values
        xx, yy = np.meshgrid(x_subset, y_subset)

        mask = intersects_xy(geom, xx, yy)
        mask_da = xr.DataArray(mask,
            dims=(y_name, x_name),
            coords={
                y_name: ds_subset[y_name],
                x_name: ds_subset[x_name],
            },
        )
        ds_masked = ds_subset.copy()

        for var in ds_subset.data_vars:
            da = ds_subset[var]
            # Only mask numeric variables
            if np.issubdtype(da.dtype, np.number):
                ds_masked[var] = da.where(mask_da)
            else:
                ds_masked[var] = da # Leave non-numeric untouched
        
        # Drop empty rows/cols that are outside of the polygon boundary
        ds_clipped = ds_masked.dropna(dim=y_name, how="all")
        ds_clipped = ds_clipped.dropna(dim=x_name, how="all")

        # Add CRS to clipped grid
        # Since the grid is created from an existing NWM grid,
        # we need to strip out the existing grid_mapping. 
        # It was found that this interferes with rio CRS encoding below.
        for name, var in ds_clipped.variables.items():
            var.attrs.pop("grid_mapping", None)
            var.encoding.pop("grid_mapping", None)

        # Also, remove existing crs variable to avoid duplicate crs definitions
        if "crs" in ds_clipped:
            ds_clipped = ds_clipped.drop_vars("crs")

        # Had to use rio.set_spatial_dims and write_transform for the CRS to stick.
        ds_clipped = ds_clipped.rio.set_spatial_dims(x_dim="x", y_dim="y")
        ds_clipped = ds_clipped.rio.write_crs(target_crs)
        ds_clipped = ds_clipped.rio.write_transform()
        # ds_clipped["crs"] = ([], 0)
        # ds_clipped["crs"].attrs["spatial_ref"] = wkt
        # ds_clipped["crs"].attrs["esri_pe_string"] = wkt
                
        print(ds_clipped.rio.crs)
        # Save
        ds_clipped.to_netcdf(template_grid_netcdf_path)
        print(f"NetCDF template grid written to {template_grid_netcdf_path}")

    def obsolete_build_grid_centroids(self) -> gpd.GeoDataFrame:
        """
        Create GeoDataFrame of grid cell centroids.
        """
        # To do: Replace x, y with the actual x and y names in the netcdf
        x = self.ds_template_grid["x"].values
        y = self.ds_template_grid["y"].values
        xx, yy = np.meshgrid(x, y)
        points = [Point(px, py) for px, py in zip(xx.ravel(), yy.ravel())]
        
        return gpd.GeoDataFrame(
            {"cell_index": np.arange(len(points))},
            geometry=points,
            crs=self.ds_template_grid.rio.crs
        )

    def obsolete_build_grid_lookup(self, catchment_gdf: gpd.GeoDataFrame) -> None:
        """
        Build the grid-to-catchment mapping (vectorized index array).
        Must be called just once before generating grids for every timestep.
        """
        # Spatial join
        # TO DO: Have to determine if there are other methods that are less expensive computationally.

        target_crs = None
        if not ds.rio.crs:
            # Try CF convention (grid_mapping)
            for var in ds.variables:
                if "grid_mapping" in ds[var].attrs:
                    grid_map_var = ds[var].attrs["grid_mapping"]
                    target_crs = ds[grid_map_var].attrs.get("crs_wkt", None)
                    break
            if target_crs is None:
                raise ValueError("CRS not found in NetCDF file.")
            ds = ds.rio.write_crs(target_crs)
        else:
            target_crs = ds.rio.crs

        joined = gpd.sjoin(
            self.grid_points,
            catchment_gdf[[self.catchment_field, "geometry"]],
            how="left",
            predicate="within"
        )

        # Build index map to allow working with integer indices (potentially faster than catchment ID strings)
        catchment_index = {c: i for i, c in enumerate(self.nc_catchments)} #use netcdf list to ensure order of gpkg catchments match with netcdf.
        mapped = joined[self.catchment_field].map(catchment_index)
        grid_to_catchment = mapped.fillna(-1).astype(int).to_numpy()
        self.grid_to_catchment = grid_to_catchment
        print("Grid-to-catchment mapping built!")

    def _obsolete_build_crs_variable(self, ds: xr.Dataset, crs_wkt: str | None = None) -> xr.Dataset:
        """
        Build CF-compliant CRS variable from a template NWM grid.
        Currently, this is not using the template NWM grid. It uses catchment grid instead.
        """

        # Get CRS from template
        crs_obj = CRS.from_user_input(ds.rio.crs)

        # Convert to CF dict
        cf_attrs = crs_obj.to_cf()

        # Create CRS variable
        ds["crs"] = xr.DataArray(0)

        # Assign CF attributes
        ds["crs"].attrs.update(cf_attrs)

        # Add WKT (for QGIS)
        wkt = crs_obj.to_wkt()
        ds["crs"].attrs["spatial_ref"] = wkt
        ds["crs"].attrs["esri_pe_string"] = wkt

        # Add GeoTransform
        x = ds["x"].values
        y = ds["y"].values

        dx = float(x[1] - x[0])
        dy = float(y[1] - y[0])

        xmin = float(x[0] - dx / 2)
        ymax = float(y[-1] + dy / 2)

        ds["crs"].attrs["GeoTransform"] = f"{xmin} {dx} 0 {ymax} 0 {-dy}"

        # Optional (additional metadata)
        ds["crs"].attrs["_CoordinateAxes"] = "y x"
        ds["crs"].attrs["_CoordinateTransformType"] = "Projection"
        ds["crs"].attrs["long_name"] = "CRS definition"

        return ds
    
    def _build_crs_variable(self, ds: xr.Dataset, crs: str) -> xr.Dataset:
        """
        Ensures dataset is fully CF + GDAL compliant with CRS.
        """

        # Write CRS using rioxarray
        ds = ds.rio.write_crs(crs)

        # Build CF-compliant grid_mapping variable
        wkt = crs.to_wkt()

        ds["crs"] = ([], 0)
        ds["crs"].attrs["spatial_ref"] = wkt
        ds["crs"].attrs["esri_pe_string"] = wkt

        # Link all variables to CRS
        for var in ds.data_vars:
            ds[var].attrs["grid_mapping"] = "crs"

        return ds

    def obsolete_create_grids_per_timestep(self, output_dir: str) -> None:
        """
        Generates netcdf grids per timestep for all the variables in the catchments netcdf.
        """
        os.makedirs(output_dir, exist_ok=True)
        n_y = self.ds_grid.dims["y"]
        n_x = self.ds_grid.dims["x"]
        valid_mask = self.grid_to_catchment != -1
        
        # may be a robust approach is not to consider "time". Instead use
        # np.issubdtype(coord.dtype, np.datetime64)?
        time_dim = next(dim for dim in self.catchment_ds.dims if "time" in dim.lower())
        reference_time = np.datetime64('1970-01-01T00:00:00')
        
        for t in self.catchment_ds[time_dim].values:
            print(f"Processing timestep: {t}")
            ds_t = self.catchment_ds.sel({time_dim: t})
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

    def obsolete_create_grids_per_timestep_dask(self, output_dir: str, chunk_size: int = 1000) -> None:
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
        time_dim = next(dim for dim in self.catchment_ds.dims if np.issubdtype(self.catchment_ds[dim].dtype, np.datetime64))
        reference_time = np.datetime64('1970-01-01T00:00:00')
        ds_in = self.catchment_ds.chunk({time_dim: 1})

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

    def build_catchment_id_grid(self, template_nc_path: str, gpkg_gdf: gpd.GeoDataFrame, 
        x_dim: str = "x",
        y_dim: str = "y",
    ) -> xr.DataArray:
        """
        Returns a DataArray (y, x) where each cell in the basin-level grid contains a catchment ID.
        """
        ds = xr.open_dataset(template_nc_path)
        x = ds[x_dim].values
        y = ds[y_dim].values

        # Origin point is assumed to be bottom-left. It may be others too.
        # So, sort the values for consistency
        if x[0] > x[-1]:
            ds = ds.sortby(x_dim)
            x = ds[x_dim].values
        if y[0] > y[-1]:
            ds = ds.sortby(y_dim)
            y = ds[y_dim].values

        # Build centroid points and create geodataframe
        xx, yy = np.meshgrid(x, y)
        df_points = pd.DataFrame({
            "x": xx.ravel(),
            "y": yy.ravel()
        })
        gdf_ncgrid_points = gpd.GeoDataFrame(
            df_points,
            geometry=gpd.points_from_xy(df_points["x"], df_points["y"]),
            crs=ds.rio.crs
        )

        # Spatial join with catchments for grid point to catchment association
        gdf_poly = gpkg_gdf.to_crs(ds.rio.crs)
        joined = gpd.sjoin(
            gdf_ncgrid_points,
            gdf_poly[[self.catchment_field, "geometry"]],
            how="left",
            predicate="within"
        )
        catchment_ids = joined[self.catchment_field].to_numpy()
        catchment_grid = catchment_ids.reshape(len(y), len(x))

        return xr.DataArray(
            catchment_grid,
            dims=(y_dim, x_dim),
            coords={y_dim: y, x_dim: x},
            name="catchment_id"
        )
    
    def map_catchment_data_to_grid(self, catchment_grid: xr.DataArray,
                                   catchment_dim: str = "catchments", time_dim: str = "time"
    ) -> xr.Dataset:
        """
        Assign catchment-based variables onto basin-level grid using catchment_id grid.
        """

        ds_data = self.catchment_ds

        # Convert catchment IDs to index positions
        catchment_ids = ds_data[catchment_dim].values

        # Build mapping: catchment_id -> index
        id_to_index = {cid: i for i, cid in enumerate(catchment_ids)}

        # Convert grid IDs to indices
        grid_index = xr.apply_ufunc(
            np.vectorize(lambda x: id_to_index.get(x, -1)),
            catchment_grid,
            vectorize=True,
            dask="parallelized",
            output_dtypes=[int]
        )

        # Mask invalid cells
        valid_mask = grid_index >= 0

        out_vars = {}

        for var in ds_data.data_vars:
            if catchment_dim not in ds_data[var].dims:
                continue
            data = ds_data[var]
            mapped = data.isel({catchment_dim: grid_index})
            mapped = mapped.where(valid_mask)
            out_vars[var] = mapped

        ds_out = xr.Dataset(out_vars)

        # Attach coordinates from template
        ds_out = ds_out.assign_coords({
            "x": self.ds_template_grid["x"],
            "y": self.ds_template_grid["y"]
        })

        # Add CRS
        ds_out = self._build_crs_variable(ds_out, self.ds_template_grid.rio.crs)

        return ds_out

    def write_netcdf_per_timestep(mapped_grid: xr.Dataset, output_dir: str, time_dim: str = "time") -> None:
        """
        Writes one NetCDF per timestep.
        """
        os.makedirs(output_dir, exist_ok=True)
        reference_time = np.datetime64("1970-01-01T00:00:00")

        for t in mapped_grid[time_dim].values:
            ds_t = mapped_grid.sel({time_dim: t}).copy()
            time_value_min = (t - reference_time) / np.timedelta64(1, "m") # time to CF format
            ds_t = ds_t.expand_dims({time_dim: [time_value_min]})
            ds_t[time_dim].attrs["units"] = "minutes since 1970-01-01 00:00:00 UTC"
            ds_t[time_dim].attrs["standard_name"] = "time"

            # Output filename and save
            t_str = np.datetime_as_string(t, unit='s') 
            formatted_t = t_str.replace('-', '_').replace(':', '_')
            output_file = os.path.join(output_dir, f"new_grid_{formatted_t}.nc")
            ds_t.to_netcdf(output_file)

    def merge_basin_netcdfs(nc_files: list[str], fill_value: float | None = None, check_crs: bool = True
    ) -> xr.Dataset:
        """
        Merge multiple NetCDF subsets.

        Assumes:
        - Same grid resolution
        - Same coordinate system
        - Non-overlapping or safely overlapping regions
        """

        datasets = [xr.open_dataset(f) for f in nc_files]

        # Check CRS and confirm that they are the same for all the netcdf files
        if check_crs:
            crs_list = []
            for ds in datasets:
                if ds.rio.crs:
                    crs_list.append(ds.rio.crs.to_string())
                else:
                    raise ValueError("One dataset missing CRS")
            if len(set(crs_list)) != 1:
                raise ValueError("CRS mismatch between datasets")

        # Use Merge or combine_by_coords to combine the NetCDFs
        ds_combined = xr.combine_by_coords(datasets, combine_attrs="override")

        for dim in ds_combined.dims: 
            ds_combined = ds_combined.sortby(dim) # Sort (for consistency)

        # To do: Alternate approach is to use Merge. Pick one of the two methods after testing.
        # compat='no_conflicts' ensures overlapping non-null values must agree
        #ds_combined = xr.merge(datasets, compat="no_conflicts")

        # --- Optional fill ---
        if fill_value is not None:
            ds_merged = ds_merged.fillna(fill_value)

        return ds_combined