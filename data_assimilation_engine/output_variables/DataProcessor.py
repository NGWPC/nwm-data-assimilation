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
            self._catchment_field = consts.NHF_DIV_ID
        else:
            self._catchment_field = consts.NONNHF_DIV_ID

        gpkg_catchment_list = gpkg_gdf[self._catchment_field].values.tolist()
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

    def set_template_netcdf(self, template_grid_path: str):
        self._template_netcdf_ds = xr.open_dataset(template_grid_path)

    def set_troute_netcdf(self, troute_outpath: str):
        self._troute_netcdf_ds = xr.open_dataset(troute_outpath)

    def set_troute_lakeout_netcdf(self, troute_lakeoutpath: str):
        self._troute_lakeout_netcdf_ds = xr.open_dataset(troute_lakeoutpath)

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
    
    def create_template_netcdf_using_config(self, mdata: NetCDFMetadata, template_netcdf_folder: str) -> None:
        """
        Create a template grid aligned to a reference grid defined in config.json.
        The output template grid covers the extents of the divides in the geopackage.
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
        elif mdata.category in ['channel_rt', 'reservoir']: # indicates that it is non-geospatial. For example, channel_rt
            ds = xr.open_dataset(file_name)

            # Delete any variable that is in the ignore list. Zero the valid min and max attribute in the time dimension
            ds = ds.drop_vars(consts.NWM_VARS_IGNORE_LIST, errors="ignore")
            if consts.DIM_TIME in ds.coords:
                attrs_to_reset = ['valid_min', 'valid_max']
                for attr in attrs_to_reset:
                    if attr in ds[consts.DIM_TIME].attrs:
                        ds[consts.DIM_TIME].attrs[attr] = 0

            # Slice all coordinates and variable arrays to zero length.
            dims = list(ds.sizes.keys())
            zero_slices = {dim: slice(0, 0) for dim in dims}
            ds_template = ds.isel(zero_slices)

            # Save to nc file
            ds_template.to_netcdf(template_nc_file)
        else:
            ds = xr.open_dataset(file_name)
            # To do: Have to figure out a workflow when CRS is "Not Available"
            target_crs = CRS.from_user_input(wkt) 
            
            gdf = self._gpkg_gdf.to_crs(target_crs)
            geom = unary_union(gdf.geometry) 
            
            # Get bounding box and snap to origin in the national reference grid
            minx, miny, maxx, maxy = gdf.total_bounds

            snapped_minx = self._snap_to_grid(minx, origin_x, res_x, np.floor)
            snapped_maxx = self._snap_to_grid(maxx, origin_x, res_x, np.ceil)
            snapped_miny = self._snap_to_grid(miny, origin_y, res_y, np.floor)
            snapped_maxy = self._snap_to_grid(maxy, origin_y, res_y, np.ceil)

            # Filter national grid to a sub-grid within the snapped bounding box
            # 1. Determine if the national grid Y-coordinate counts upwards or downwards
            y_dir = 1 if ds[y_name].values[1] > ds[y_name].values[0] else -1

            # 2. Slice dynamically based on the direction of the reference grid
            if y_dir == 1:
                y_slice = slice(snapped_miny, snapped_maxy) # South to North
            else:
                y_slice = slice(snapped_maxy, snapped_miny) # North to South

            # 3. Perform your selection using the verified slice orientation
            ds_subset = ds.sel(
                {
                    x_name: slice(snapped_minx, snapped_maxx),
                    y_name: y_slice #slice(snapped_miny, snapped_maxy),
                }
            )
            x_subset = ds_subset[x_name].values
            y_subset = ds_subset[y_name].values
            xx, yy = np.meshgrid(x_subset, y_subset)

            flat_mask = intersects_xy(geom, xx.ravel(), yy.ravel())
            grid_mask = flat_mask.reshape(ds_subset[y_name].size, ds_subset[x_name].size)
            mask_da = xr.DataArray(grid_mask,
                dims=(y_name, x_name),
                coords={
                    y_name: ds_subset[y_name].values,
                    x_name: ds_subset[x_name].values
                }
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

        self._template_netcdf_ds = xr.open_dataset(template_nc_file)
        print(f"NetCDF template grid written to {template_nc_file}")

    def produce_nwm_output_product(self, mdata: NetCDFMetadata, output_dir: str) -> None:
        produce_output = False
        is_gridded = True
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
        ds_filtered = ds_modified.drop_vars(variables_to_drop, errors="ignore")
        
        cat_class_domain = mdata.output_class + '.' + mdata.category +  '.' + mdata.domain
        
        for var_name in pruned_variables:
            if var_name in ds_filtered.data_vars:
                continue # the variable exists in ngen output. We don't need to do anything
            else:
                # If not in 
                print(f"----'{var_name}' is missing in ngen output")
        
        if (cat_class_domain in consts.NWM_PRODUCTS_LIST):
            produce_output = True
        if mdata.category in ['channel_rt', 'reservoir']:
            is_gridded = False

        print(f"----Produce output: {produce_output} and Gridded: {is_gridded}")

        if produce_output and is_gridded:
            catchment_grid = self.build_catchment_id_grid(mdata.x_name, mdata.y_name)
            mapped_grid = self.map_catchment_data_to_grid(ds_filtered, catchment_grid, consts.DIM_CATCHMENTS, mdata.x_name, mdata.y_name)
            
            start_time = time.perf_counter()
            self.write_netcdf_per_timestep(mapped_grid, output_dir, consts.DIM_TIME)
            end_time = time.perf_counter()
            duration_minutes = (end_time - start_time) / 60
            print(f"----Function execution time: {duration_minutes:.2f} minutes")
        elif produce_output and not is_gridded:
            self.produce_channel_reservoir_nwm_product(mdata, output_dir)
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
            ds = self._template_netcdf_ds
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
                gdf_poly[[self._catchment_field, "geometry"]],
                how="left",
                predicate="within"
            )
            catchment_ids = joined[self._catchment_field].to_numpy()
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
            x_dim_name: self._template_netcdf_ds[x_dim_name],
            y_dim_name: self._template_netcdf_ds[y_dim_name]
        })

        # Add CRS info from template grid
        crs_attrs = self._template_netcdf_ds["crs"].attrs.copy()
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
        reference_epoch = np.datetime64("1970-01-01T00:00:00")

        for t in mapped_grid[time_dim].values:
            ds_t = mapped_grid.sel({time_dim: t}).copy()
            time_value_mins = (t - reference_epoch) / np.timedelta64(1, "m") # time to CF format
            ds_t = ds_t.expand_dims({time_dim: [time_value_mins]})
            ds_t[time_dim].attrs["units"] = "minutes since 1970-01-01 00:00:00 UTC"
            ds_t[time_dim].attrs["standard_name"] = "time"

            # Rebuild CRS info and mapping.
            if "crs" in ds_t:
                ds_t = ds_t.drop_vars("crs")
            ds_t["crs"] = xr.DataArray(0, dims=())
            ds_t["crs"].attrs = mapped_grid["crs"].attrs.copy()
            for var in ds_t.data_vars:
                if not var == "crs":
                    ds_t[var].attrs["grid_mapping"] = "crs"

            # Add reference_time variable and attributes to netcdf
            # To do: Replace this with the actual time when the model simulations were run.
            ds_t[consts.DIM_REF_TIME] = xr.DataArray(
                data=time_value_mins.astype("int32"),
                dims=()
            )
            ds_t[consts.DIM_REF_TIME].attrs = {
                "long_name": "model initialization time",
                "standard_name": "forecast_reference_time",
                "units": "minutes since 1970-01-01 00:00:00 UTC"
            }

            # Output filename and save
            t_str = np.datetime_as_string(t, unit='s') 
            formatted_t = t_str.replace('-', '_').replace(':', '_')
            output_file = os.path.join(output_dir, f"nwm.{self._geo_id}.{self._output_class}.{self._category}.{self._domain}.{formatted_t}.nc")
            ds_t.to_netcdf(output_file)

    def produce_channel_reservoir_nwm_product(self, mdata: NetCDFMetadata, output_dir: str):
        """
        Expands a zeroed NetCDF template and populates it with data from a single
        time snapshot, including remapping misnamed variables.
        """
        if not self._template_netcdf_ds:
            raise ValueError("Template netcdf not set")
        
        if mdata.category == 'channel_rt' and not self._catchment_ds:
            raise ValueError("ngen catchment netcdf not set")
        
        if mdata.category == 'channel_rt' and not self._troute_netcdf_ds:
            raise ValueError("troute output netcdf not set")

        if mdata.category == 'reservoir' and not self._troute_lakeout_netcdf_ds:
            raise ValueError("troute lakeout netcdf not set")
        
        if mdata.category =='channel_rt':
            # Extract the last time from ngen catchment output and use that as the timeslice
            # To do: Need to update this for the correct time snapshot.
            last_time_1 = self._troute_netcdf_ds.coords[consts.DIM_TIME].values[-1]
            output_snapshot_1 = self._troute_netcdf_ds.sel(time=slice(last_time_1, last_time_1))
            last_time_2 = self._catchment_ds.coords[consts.DIM_TIME].values[-1]
            output_snapshot_2 = self._catchment_ds.sel(time=slice(last_time_2, last_time_2))

            # For testing, since the last time snapshot doesn't align in the two datasets
            # we align the troute output to the ngen output
            output_snapshot_1 = output_snapshot_1.assign_coords(time=output_snapshot_2.coords[consts.DIM_TIME].values)

            # Replace any misnamed variable and also filter based on the required variables
            var_mapping={'flow': 'streamflow'}
            output_snapshot_1 = output_snapshot_1.rename(**var_mapping)
            variables_to_keep = ['feature_id', 'time', 'streamflow', 'nudge', 'velocity']
            ds_filtered_1 = output_snapshot_1[variables_to_keep]
        
            # rename catchments to feature_id and filter required variables
            dim_mapping={'catchments': 'feature_id'}
            output_snapshot_2 = output_snapshot_2.rename(**dim_mapping)
            variables_to_keep = ['feature_id', 'time', 'qBucket']
            ds_filtered_2 = output_snapshot_2[variables_to_keep]
            
            # Merge the two filtered datasets together
            merged_snapshot = xr.merge([ds_filtered_1, ds_filtered_2], join='outer', combine_attrs = 'override')
            snapshot_time = merged_snapshot.coords[consts.DIM_TIME].values
        else:
            merged_snapshot = self._troute_lakeout_netcdf_ds
            snapshot_time = merged_snapshot.coords[consts.DIM_REF_TIME].values
        
        
        # Extract the feature_ids
        feature_ids = merged_snapshot.coords[consts.DIM_FEATURE_ID].values
        feature_ids_da = xr.DataArray(feature_ids, dims=[consts.DIM_FEATURE_ID])

        # Time calculations for reference time and time dimension/variable.
        # To do: Set up for testing. Update this if-else block for production
        if mdata.category == 'channel_rt':
            timesteps = self._catchment_ds.coords[consts.DIM_TIME].values
            min_time = np.min(timesteps)
            max_time = np.max(timesteps)
        else:
            ref_time = np.atleast_1d(snapshot_time)[0].astype('datetime64[m]')
            min_time = ref_time + 60 #mins
            max_time = ref_time + 180 #mins

        # Extract the unique coordinates from the snapshot for output
        reference_epoch = np.datetime64("1970-01-01T00:00:00")
        snapshot_time_array = snapshot_time.astype('datetime64[m]') #we need minutes to perform timedelta
        snapshot_time_val = np.int32((snapshot_time_array[0] - reference_epoch) / np.timedelta64(1, "m")) # time to CF format
        time_value_min = np.int32((min_time - reference_epoch) / np.timedelta64(1, "m")) # time to CF format
        time_value_max = np.int32((max_time - reference_epoch) / np.timedelta64(1, "m")) # time to CF format
        if mdata.category == 'channel_rt':
            time_da = xr.DataArray([snapshot_time_val], dims=[consts.DIM_TIME])
        else:
            time_da = xr.DataArray([time_value_max], dims=[consts.DIM_TIME])
        # print(f"Min time: {min_time}; Max time: {max_time}")
        # print(f"Min value time: {time_value_min}; Max value time: {time_value_max}")

        # reference_time variable and attributes to netcdf
        # To do: Replace this with the actual time when the model simulations were run.
        if mdata.category == 'channel_rt':
            ref_time_val = time_value_max.astype("int32")
        else:
            ref_time_val = np.int32((min_time - 60 - reference_epoch) / np.timedelta64(1, "m")) # time to CF format
        
        ref_time_da = xr.DataArray(data=[ref_time_val], dims=[consts.DIM_REF_TIME])
        
        # Create empty dataset with the merged snapshot values
        data_coords={
            consts.DIM_TIME: time_da,
            consts.DIM_FEATURE_ID: feature_ids_da,
            consts.DIM_REF_TIME: ref_time_da
        }
        data_vars_dict = {}
        for var_name, var_obj in self._template_netcdf_ds.data_vars.items():
            # shape tuple based on dimensions
            if len(var_obj.dims) == 0: # scalar variables
                var_shape = ()
            else:
                var_shape = tuple(len(data_coords[d]) for d in var_obj.dims)
            # Construct empty array with the exact dimensions, type and attributes in the template
            data_vars_dict[var_name] = (var_obj.dims, np.empty(var_shape, dtype=var_obj.dtype), var_obj.attrs)

        populated_ds = xr.Dataset(data_vars = data_vars_dict, coords = data_coords)

        # Copy all global attributes from template
        populated_ds.attrs.update(self._template_netcdf_ds.attrs)

        # Populate variables defined in the template using the snapshot data
        for var_name in self._template_netcdf_ds.variables:
            # leave the dimensions out as they have already been populated.
            if var_name in self._template_netcdf_ds.dims:
                continue
            
            # Confirm if the variable is present both in snapshot and final output
            in_snapshot = var_name in merged_snapshot.variables
            in_populated = var_name in populated_ds.variables
            
            if not in_snapshot and not in_populated:
                print(f"{var_name} is missing from both snapshot and output datasets.")
                continue
            elif not in_snapshot:
                print(f"{var_name} is in the template but not found in the snapshot dataset.")
                continue
            elif not in_populated:
                print(f"{var_name} is in the template but not found in the output dataset.")
                continue

            if var_name in merged_snapshot.variables:
                print(f"----Processing variable: {var_name}")
                out_var = merged_snapshot[var_name]
                template_var = self._template_netcdf_ds[var_name]
                # raw_values = np.squeeze(out_var.values)
                # populated_ds[var_name] = xr.DataArray(raw_values, dims=[consts.DIM_FEATURE_ID]) #, attrs=var_attrs)
                if out_var.ndim == template_var.ndim:
                    print(f"----Dimensions match for variable {var_name}")
                    print(f"----Source   - Shape: {out_var.shape} | Dtype: {out_var.dtype}")
                    print(f"----Template - Shape: {template_var.shape} | Dtype: {template_var.dtype}")
        
                    # Check if shapes are fully identical
                    if out_var.shape != template_var.shape:
                        print(f"----SHAPE MISMATCH: Cannot copy {out_var.shape} into {template_var.shape}!")
                        # Optional: print a preview of the source values
                        # print("----Source values preview:", out_var.values) 
                    # -----------------------
                    # if dtypes are different between template and the snapshot,
                    # we need to do appropriate casting. This loop does only from float to int.
                    data_values = out_var.values
                    if np.issubdtype(template_var.dtype, np.integer):
                        if np.issubdtype(extracted_values.dtype, np.floating):
                            data_values = np.nan_to_num(data_values, nan=0)
                            # Use np.array().astype() to ensure scalars cast works as well.
                            extracted_values = np.array(extracted_values).astype(template_var.dtype)
                    
                    populated_ds[var_name].values = data_values # populate the values.
                else:
                    print(f"----The dimensions don't match between template ({template_var.dims}) and snapshot ({out_var.dims}) for {var_name}")
            else:
                if self._template_netcdf_ds[var_name].ndim == 0: #Scalar variables not in the data, but in template
                    populated_ds[var_name] = xr.DataArray(self._template_netcdf_ds[var_name].values.item()) #, attrs=var_attrs)
                    print(f"----Found a scalar variable {var_name} that is not in the data, but present in the template.Template value has been copied over.")
                else:
                    # Allocate a 1D zero array sized exactly to the number of catchments/feature IDs
                    # This is just a fallback option
                    # shape = (len(feature_ids),)
                    # populated_ds[var_name] = xr.DataArray(np.zeros(shape), dims=[consts.DIM_FEATURE_ID]) #, attrs=var_attrs)
                    print(f"----Found a data variable {var_name} that is not in the data, but present in the template.It has been ignored.")
        
        # Transfer all other attributes from template
        for var_name in self._template_netcdf_ds.variables:
            if var_name in populated_ds.variables:
                populated_ds[var_name].attrs.update(self._template_netcdf_ds[var_name].attrs)
                populated_ds[var_name].encoding.update(self._template_netcdf_ds[var_name].encoding)
        
                # Prevent overwriting conflicts by clearing 'units' and calendar
                populated_ds[var_name].attrs.pop('units', None)
                populated_ds[var_name].attrs.pop('calendar', None)

                # Copy Fill and missing values from the template DS
                has_missing = 'missing_value' in self._template_netcdf_ds[var_name].encoding
                has_fill = '_FillValue' in self._template_netcdf_ds[var_name].encoding
                if  has_missing and has_fill:
                    tgt_value = self._template_netcdf_ds[var_name].encoding['missing_value']
                    populated_ds[var_name].encoding['missing_value'] = tgt_value
                    populated_ds[var_name].encoding['_FillValue'] = tgt_value
                elif has_missing and not has_fill:
                    tgt_value = self._template_netcdf_ds[var_name].encoding['missing_value']
                    populated_ds[var_name].encoding['missing_value'] = tgt_value
                    populated_ds[var_name].encoding['_FillValue'] = None # set it to None.
                elif has_fill and not has_missing:
                    tgt_value = self._template_netcdf_ds[var_name].encoding['_FillValue']
                    populated_ds[var_name].encoding['_FillValue'] = tgt_value
                    populated_ds[var_name].encoding['missing_value'] = None
        
        # Add valid min and max times to the "time" attributes and specify units for all time related variables
        populated_ds[consts.DIM_TIME].attrs["valid_min"] = time_value_min
        populated_ds[consts.DIM_TIME].attrs["valid_max"] = time_value_max
        populated_ds[consts.DIM_TIME].attrs['units'] = "minutes since 1970-01-01 00:00:00"

        # Manually assign units and encoding for reference time. 
        # Without this it was encoding as nanoseconds since 1970-01-01
        populated_ds[consts.DIM_REF_TIME].attrs['units'] = "minutes since 1970-01-01 00:00:00"


        # Output filename and save
        os.makedirs(output_dir, exist_ok=True)
        datetime_obj = np.datetime64(int(time_value_max), "m")
        t_str = np.datetime_as_string(datetime_obj, unit='m') 
        formatted_t = t_str.replace('-', '_').replace(':', '_')
        output_file = os.path.join(output_dir, f"nwm.{self._geo_id}.{self._output_class}.{self._category}.{self._domain}.{formatted_t}.nc")
        populated_ds.to_netcdf(output_file)

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