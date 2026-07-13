import sys
import os
import json
import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
import dask.array as da
import time
import math
import re
from shapely.geometry import Point
from shapely.ops import unary_union
from shapely import intersects_xy
from pyproj import CRS
from typing import List, Optional
from .DataReader import DataReader
from .utils import NetCDFMetadata
from . import consts

class DataProcessor(DataReader):
    """
    Handles catchment-time NetCDF and grid generation.
    """
    def __init__(self, catchment_netcdf_file: str, gpkg_file: str, chunk_size: int = 100) -> None:
        
        super().__init__(catchment_netcdf_file, chunk_size)

        self._catchment_ds: xr.Dataset = self.dataset
        self._gpkg_file = gpkg_file
        filename = os.path.basename(gpkg_file)
        self._geo_id = filename.replace(consts.GPKG_FILE_PREFIX, '').replace('.gpkg', '')
        
        nc_catchments = self._catchment_ds[self.catchment_coord].values
        
        # Read geopackage, determine schema and "divides" layer
        is_new_NHF_schema: bool = self._is_new_NHF_schema(gpkg_file, consts.NHF_REF_OBJECT)
        gpkg_gdf = gpd.read_file(gpkg_file, layer=consts.GPKG_DIVIDES_LYR)
        if gpkg_gdf.empty:
            raise ValueError("No polygon geometries found in GeoPackage")

        # Check schema and assign catchment ID field.
        if is_new_NHF_schema:
            self.catchment_field = consts.NHF_DIV_ID
        else:
            self.catchment_field = consts.NONNHF_DIV_ID

        gpkg_catchment_list = gpkg_gdf[self.catchment_field].values.tolist()
        self._gpkg_gdf = gpkg_gdf
        
        # Check if catchments from netcdf and geopackage match
        if set(nc_catchments) != set(gpkg_catchment_list):
            raise ValueError("There is a mistmatch between catchment IDs in geopackage and netcdf")
        
        # Set log file which will be redirect to stdout.
        # Only for testing
        self._original_stdout = sys.stdout
        self._log_file = None

    @property
    def nwm_output_class(self):
        return self._output_class
    
    @property
    def nwm_category(self):
        return self._category
    
    @property
    def nwm_domain(self):
        return self._domain
    
    @property
    def log_file(self):
        return self._log_file

    @nwm_output_class.setter
    def nwm_output_class(self, value):
        self._output_class = value
    
    @nwm_category.setter
    def nwm_category(self, value):
        self._category = value

    @nwm_domain.setter
    def nwm_domain(self, value):
        self._domain = value

    @log_file.setter
    def log_file(self, log_file_path: str):
        self.close_log()
        if log_file_path is None:
            return

        log_folder = os.path.dirname(log_file_path)
        if log_folder:
            os.makedirs(log_folder, exist_ok=True)

        self._log_file = open(log_file_path, "w", encoding="utf-8")
        sys.stdout = self._log_file

    def set_template_grid(self, template_grid_path: str):
        self.ds_template_grid = xr.open_dataset(template_grid_path)

    def _is_new_NHF_schema(self, geopackage_path: str, layer_name: str) -> bool:
        """
        Check the data schema in the geopackage for the new NHF format
        """
        layers = gpd.list_layers(geopackage_path)
        tabular_layers = layers[layers[consts.GPKG_GEOMETRY_TYPE_IDENTIFIER].isna()]
        return layer_name.lower() in tabular_layers['name'].tolist()
    
    def _snap_to_grid(self, value: float, origin: float, resolution: int, direction: np.ufunc):
        if direction == np.floor:
            return origin + np.floor((value - origin) / resolution) * resolution
        elif direction == np.ceil:
            return origin + np.ceil((value - origin) / resolution) * resolution
    
    def create_template_grid_netcdf_using_config(self, mdata: NetCDFMetadata, template_netcdf_folder: str) -> None:
        """
        Create a template grid aligned to a reference grid defined in config.json.
        The template grid covers the extents in the geopackage (usually basin level).
        """

        os.makedirs(template_netcdf_folder, exist_ok = True)

        self._output_class = mdata.output_class
        self._category = mdata.category
        self._domain = mdata.domain
        origin_x = mdata.origin_x
        origin_y = mdata.origin_y
        res_x = mdata.resolution_x
        res_y = mdata.resolution_y
        wkt = mdata.crs_wkt
        file_name = mdata.file_path
        x_name = mdata.x_name
        y_name = mdata.y_name

        # Check if the template file already exists for this request
        template_nc_name = self._geo_id + '_' + self._output_class + '_' + self._category + '_' + self._domain + '.nc'
        template_nc_file = os.path.join(template_netcdf_folder, template_nc_name)
        if os.path.isfile(template_nc_file):
            print(f"----Reusing existing template file in local for {self._output_class}, {self._category}, {self._domain}")
        else:
            ds = xr.open_dataset(file_name)
            # To do: Have to figure out a workflow when CRS is "Not Available"
            target_crs = CRS.from_user_input(wkt) 
            
            gdf = self._gpkg_gdf.to_crs(target_crs)
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

            # Set values of NWM variables to zero in the template grid
            nwm_vars = [name for name, var in ds_clipped.data_vars.items() 
                       if var.ndim > 0 and name not in ds_clipped.coords]
            for var in nwm_vars:
                ds_clipped[var] = ds_clipped[var] * 0

            # Create crs as a scalar variable.
            crs_attrs = ds_clipped["crs"].attrs
            ds_clipped = ds_clipped.drop_encoding()
            del ds_clipped["crs"]
            ds_clipped["crs"] = xr.DataArray("", dims=())
            ds_clipped["crs"].attrs = crs_attrs

            # Save to nc file
            ds_clipped.to_netcdf(template_nc_file)
            print(f"NetCDF template grid written to {template_nc_file}")
        
        self.ds_template_grid = xr.open_dataset(template_nc_file)

    def produce_nwm_output_grid(self, mdata: NetCDFMetadata, output_dir: str) -> None:
        produce_output = False
        ds_modified = self._catchment_ds

        # if the output needs to have SOIL_M or SOIL_T, we need to
        # stack the ngen output into the layers.
        var_prefix_list = []
        if 'SOIL_M' in mdata.nwm_variables:
            var_prefix_list.append('SOIL_M_')
        if 'SOIL_T' in mdata.nwm_variables:
            var_prefix_list.append('SOIL_T_')
            
        if len(var_prefix_list) > 0:
            ds_modified = self.stack_soil_variables(var_prefix_list)
        
        # if the output needs to have SNLIQ (snow layer liquid water), we need to expand 
        # dimensions to include a snow layer. It is assumed to be of length=1
        if 'SNLIQ' in mdata.nwm_variables:
            expanded_var = ds_modified['SNLIQ'].expand_dims(dim = consts.DIM_SNOW_LYR)
            expanded_var = expanded_var.transpose(consts.DIM_TIME, consts.DIM_SNOW_LYR, consts.DIM_CATCHMENTS)
            ds_modified['SNLIQ'] = expanded_var

        # Remove data variables that should not be part of the product.
        # You can remove variables that are in the ignore variables as well.
        target_variables = [var.strip() for var in mdata.nwm_variables.split(",")]
        removed_items = list(set(target_variables).intersection(set(consts.NWM_VARS_IGNORE_LIST))) # for logging
        print(f"----Variables ignored: {removed_items}")
        ignore_set = set(consts.NWM_VARS_IGNORE_LIST)
        pruned_variables = [item for item in target_variables if item not in ignore_set]
        variables_to_drop = [var for var in ds_modified.data_vars if var not in pruned_variables and len(ds_modified[var].dims) > 0]
        ds_filtered = ds_modified.drop_vars(variables_to_drop)
        
        cat_class_domain = mdata.output_class + '.' + mdata.category +  '.' + mdata.domain
        
        for var_name in pruned_variables:
            if var_name in ds_filtered.data_vars:
                continue # the variable exists in ngen output. We don't need to do anything
            else:
                print(f"----'{var_name}' is missing in ngen output")
        
        if (cat_class_domain in consts.NWM_PRODUCTS_LIST):
            produce_output = True

        if produce_output:
            catchment_grid = self.build_catchment_id_grid(mdata.x_name, mdata.y_name)
            mapped_grid = self.map_catchment_data_to_grid(ds_filtered, catchment_grid, consts.DIM_CATCHMENTS, mdata.x_name, mdata.y_name)
            
            start_time = time.perf_counter()
            self.write_netcdf_per_timestep(mapped_grid, output_dir, consts.DIM_TIME)
            end_time = time.perf_counter()
            duration_minutes = (end_time - start_time) / 60
            print(f"----Function execution time: {duration_minutes:.2f} minutes")
        else:
            print(f"----Production skipped for {cat_class_domain}")

    def stack_soil_variables(self, var_prefix_list: List[str]) -> xr.Dataset:
        stacked_ds = self._catchment_ds.copy()
        for var_prefix in var_prefix_list:
            matching_vars = [var for var in stacked_ds.data_vars if var.startswith(var_prefix)]
            if not matching_vars:
                raise ValueError(f"ngen output netcdf has no variables found matching the prefix '{var_prefix}'")

            var_val_dict = {}
            for var in stacked_ds.data_vars:
                if var in matching_vars:
                    soil_depth = var[len(var_prefix) :]
                    depth_num = re.search(r"\d*\.\d+|\d+", soil_depth)
                    var_val_dict[var] = float(depth_num.group()) if depth_num else 0.0

            sorted_vars = sorted(var_val_dict.keys(), key = lambda k: var_val_dict[k])
            arrays_for_stack = [stacked_ds[v].rename(var_prefix.strip("_")) for v in sorted_vars]
            stacked_var = xr.concat(arrays_for_stack, dim = consts.DIM_SOIL_LYR)
            stacked_var = stacked_var.transpose(consts.DIM_TIME, consts.DIM_SOIL_LYR, consts.DIM_CATCHMENTS)
            stacked_ds[var_prefix.strip("_")] = stacked_var
            stacked_ds = stacked_ds.drop_vars(matching_vars)
        return stacked_ds
    


    def build_catchment_id_grid(self, x_dim_name: str, y_dim_name: str) -> xr.DataArray:
        """
        Returns a DataArray (y, x) where each cell in the basin-level grid contains a catchment ID.
        """
        try:
            ds = self.ds_template_grid
            x = ds[x_dim_name].values
            y = ds[y_dim_name].values

            # Origin point is assumed to be bottom-left. It may be others too.
            # So, sort the values for consistency
            if x[0] > x[-1]:
                ds = ds.sortby(x_dim_name)
                x = ds[x_dim_name].values
            if y[0] > y[-1]:
                ds = ds.sortby(y_dim_name)
                y = ds[y_dim_name].values

            # Build centroid points and create geodataframe
            xx, yy = np.meshgrid(x, y)
            df_points = pd.DataFrame({
                x_dim_name: xx.ravel(),
                y_dim_name: yy.ravel()
            })
            crs = CRS.from_wkt(ds["crs"].attrs["spatial_ref"])
            gdf_ncgrid_points = gpd.GeoDataFrame(
                df_points,
                geometry=gpd.points_from_xy(df_points[x_dim_name], df_points[y_dim_name]),
                crs=crs
            )

            # Spatial join with catchments for grid point to catchment association
            # To do: Using sjoin here. For larger areas, we may need to revisit if computing efficiency drops.
            gdf_poly = self._gpkg_gdf.to_crs(crs)
            joined = gpd.sjoin(
                gdf_ncgrid_points,
                gdf_poly[[self.catchment_field, "geometry"]],
                how="left",
                predicate="within"
            )
            catchment_ids = joined[self.catchment_field].to_numpy()
            catchment_grid = catchment_ids.reshape(len(y), len(x))

            catchment_id_da = xr.DataArray(
                catchment_grid,
                dims=(y_dim_name, x_dim_name),
                coords={y_dim_name: y, x_dim_name: x},
                name="catchment_id"
            )
            # It is important to pass on the CRS info to the functions downstream
            # Attaching the crs wkt as a xr.dataarray attribute
            catchment_id_da.attrs["crs"] = ds["crs"].attrs["spatial_ref"]
        except Exception as e:
            raise RuntimeError(f"Error in building catchment grid: {e}") from e
        
        return catchment_id_da
    
    def map_catchment_data_to_grid(self, ds: xr.Dataset, catchment_grid: xr.DataArray, catchment_dim: str, 
                                   x_dim_name: str, y_dim_name: str 
                                    
    ) -> xr.Dataset:
        """
        Assign catchment-based variables onto basin-level grid using the catchment_id grid.
        """

        ds_data = ds

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

        valid_mask = grid_index >= 0 # Mask invalid cells
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
            x_dim_name: self.ds_template_grid[x_dim_name],
            y_dim_name: self.ds_template_grid[y_dim_name]
        })

        # Add CRS info from template grid
        crs_attrs = self.ds_template_grid["crs"].attrs.copy()
        ds_out["crs"] = xr.DataArray(data=0,dims=())
        ds_out["crs"].attrs = crs_attrs

        # Link all variables to CRS
        for var in ds_out.data_vars:
            ds_out[var].attrs["grid_mapping"] = "crs"

        return ds_out

    def write_netcdf_per_timestep(self, mapped_grid: xr.Dataset, output_dir: str, time_dim: str = "time") -> None:
        """
        Writes one NetCDF per timestep.
        """
        os.makedirs(output_dir, exist_ok=True)
        reference_time = np.datetime64("1970-01-01T00:00:00")

        for t in mapped_grid[time_dim].values:
            ds_t = mapped_grid.sel({time_dim: t}).copy()
            time_value_mins = (t - reference_time) / np.timedelta64(1, "m") # time to CF format
            ds_t = ds_t.expand_dims({time_dim: [time_value_mins]})
            ds_t[time_dim].attrs["units"] = "minutes since 1970-01-01 00:00:00 UTC"
            ds_t[time_dim].attrs["standard_name"] = "time"

            # Rebuild CRS info and mapping.
            # This is required to avoid crs variable getting timesliced. crs(time=1)
            if "crs" in ds_t:
                ds_t = ds_t.drop_vars("crs")
            ds_t["crs"] = xr.DataArray(0, dims=())
            ds_t["crs"].attrs = mapped_grid["crs"].attrs.copy()
            for var in ds_t.data_vars:
                if not var == "crs":
                    ds_t[var].attrs["grid_mapping"] = "crs"

            # Add reference_time variable and attributes to netcdf
            # To do: Replace this with the actual time when the model simulations were run.
            ds_t["reference_time"] = xr.DataArray(
                data=time_value_mins.astype("int32"),
                dims=()
            )
            ds_t["reference_time"].attrs = {
                "long_name": "model initialization time",
                "standard_name": "forecast_reference_time",
                "units": "minutes since 1970-01-01 00:00:00 UTC"
            }

            # Output filename and save
            t_str = np.datetime_as_string(t, unit='s') 
            formatted_t = t_str.replace('-', '_').replace(':', '_')
            output_file = os.path.join(output_dir, f"nwm.{self._geo_id}.{self._output_class}.{self._category}.{self._domain}.{formatted_t}.nc") # To do: Get this as function argument
            ds_t.to_netcdf(output_file)

    def close_log(self):
        """Restores the original terminal output and closes the file."""
        original_stream = getattr(self, "_original_stdout", sys.stdout)
        if sys.stdout != original_stream:
            sys.stdout = original_stream

        log_file_obj = getattr(self, "_log_file", None)
        if log_file_obj and not log_file_obj.closed:
            log_file_obj.flush()
            log_file_obj.close()
            
        # Reset the private attribute safely
        if hasattr(self, "_log_file"):
            self._log_file = None

    def __del__(self):
        """
        Close the log file if the script ends unexpectedly.
        """
        self.close_log()