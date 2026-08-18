import sys
import os
import json
import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
import dask.array as da
import dask
import time
import math
import re
import shapely
import traceback
from pyproj import CRS
from .DataReader import DataReader
from .utils import (
    NetCDFMetadata,
    get_file_timestep_prefix,
    generate_formatted_timestring_for_naming,
    get_file_timestep_list,
    copy_netcdf_attributes
)
from . import consts

class DataProcessor(DataReader):
    """
    Handles ngen and troute outputs and produces NWM products.
    """
# region DataProcessor init and properties
    def __init__(self, catchment_netcdf_file: str, gpkg_file: str, chunk_size: int = 100) -> None:
        """
        Args:
            catchment_netcdf_file : str
                The absolute or relative path to the ngen output NetCDF file.
            gpkg_file : str
                The absolute or relative path to the geopackage file that was used for ngen run.
            chunk_size : int
                The size to break larger datasets into smaller memory blocks. Defaults to 100

        Attributes:
            _catchment_ds (xr.Dataset): ngen NetCDF dataset
            _gpkg_file (str): full or relative path to geopackage file
            _output_class (str): NWM product class. For example, analysis_assim or  short_range
            _category (str): NWM product category. For example, terrain_rt, land, reservoir
            _domain (str): NWM product domain. For example, conus, hawaii, alaska
            _geo_id (str): Identifier for the geopackage extracted from the file name
            _gpkg_gdf (GeoDataFrame): Geopandas Dataframe for the geopackage divides. 
            _log_file (str): Full or relative path to the log file

        Raises:
            ValueError: If any of the following conditions occur:
                - Geopackage has an empty divides layer
                - Number of catchments in `catchment_netcdf_file` does not match features in `gpkg_file` divides
        """
        super().__init__(catchment_netcdf_file, chunk_size)

        self._catchment_ds: xr.Dataset = self._dataset
        self._gpkg_file = gpkg_file
        self._output_cycle = None
        self._output_class = None
        self._category = None
        self._domain = None
        filename = os.path.basename(gpkg_file)
        self._geo_id = filename.replace(consts.GPKG_FILE_PREFIX, '').replace('.gpkg', '')
        
        nc_catchments = self._catchment_ds[self._catchment_coord].values
        
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
        # To do: Update this with EWTS
        self._original_stdout = sys.stdout
        self._log_file = None

    @property
    def nwm_output_cycle(self):
        return self._output_cycle

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

    @property
    def geo_id(self):
        return self._geo_id

    @nwm_output_cycle.setter
    def nwm_output_cycle(self, value):
        self._output_cycle = value

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

        self._log_file = open(log_file_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = self._log_file

    def set_template_netcdf(self, template_file_path: str):
        """
        Set the template netcdf file to produce NWM products
        """
        self._template_netcdf_ds = xr.open_dataset(template_file_path)

    def set_troute_netcdf(self, troute_outpath: str):
        """
        Set the troute output netcdf file to produce NWM products
        """
        self._troute_netcdf_ds = xr.open_dataset(troute_outpath)

    def set_troute_lakeout_netcdf(self, troute_lakeoutpath: str):
        """
        Set the troute lakeout (waterbody) netcdf file to produce NWM products
        """
        self._troute_lakeout_netcdf_ds = xr.open_dataset(troute_lakeoutpath)

    def _is_new_NHF_schema(self, geopackage_path: str, layer_name: str) -> bool:
        """
        Check the data schema in the geopackage and determine if it is in the new NHF format

        Args:
            geopackage_path : str
                The absolute or relative path to the geopackage file.
            layer_name : str
                The name of the layer in the geopackage file.

        Returns:
            bool
                True/False indicating the presence of the layer in the geopackage.
        """
        layers = gpd.list_layers(geopackage_path)
        tabular_layers = layers[layers[consts.GPKG_GEOMETRY_TYPE_IDENTIFIER].isna()]
        return layer_name.lower() in tabular_layers['name'].tolist()
# endregion

# region Data processing
    def create_template_netcdf_using_config(self, mdata: NetCDFMetadata, template_netcdf_folder: str) -> bool:
        """
        Create a template netcdf file that aligns to a national reference grid defined in the metadata config.
        For gridded NWM products, the output template grid covers the extents of the divides in the geopackage.
        For non-gridded NWM products, the ouptut template contains metadata of the national reference grid with values zeroed.

        Args:
            mdata : utils.NetCDFMetadata
                The instance of the custom class that captures the metadata of NWM products from the config
            template_netcdf_folder : str
                The folder where the template will be saved or retrived from if it exists.

        Returns:
            bool
                Returns True if the template has been generated/identified. Otherwise returns False.
        """
        
        os.makedirs(template_netcdf_folder, exist_ok = True)

        self._output_class = mdata.output_class
        self._category = mdata.category
        self._domain = mdata.domain
        res_x = mdata.resolution_x
        res_y = mdata.resolution_y
        wkt = mdata.crs_wkt
        file_name = mdata.file_path
        x_name = mdata.x_name
        y_name = mdata.y_name

        print(f"--Started creating template netcdf covering geopackage extent for {mdata.output_class}.{mdata.category}.{mdata.domain}")
        
        try:
            start_time = time.perf_counter()
            # Check if the template file already exists for this request
            template_nc_name = self._geo_id + '_' + self._output_class + '_' + self._category + '_' + self._domain + '.nc'
            template_nc_file = os.path.join(template_netcdf_folder, template_nc_name)
            if os.path.isfile(template_nc_file):
                print(f"----Reusing existing template file found here: {template_nc_file}")
                self._template_netcdf_ds = xr.open_dataset(template_nc_file) # assign to class variable.
                return True
            elif mdata.category.startswith('channel_rt') or mdata.category.startswith('reservoir'):  # these are non-gridded products
                ds = xr.open_dataset(file_name)

                # Delete any variable that is in the ignore list. Zero the valid min and max attribute in the time dimension
                ds = ds.drop_vars(consts.NWM_VARS_IGNORE_LIST, errors="ignore")
                time_dim = consts.DIM_TIME
                if time_dim in ds.coords:
                    attrs_to_reset = ['valid_min', 'valid_max']
                    for attr in attrs_to_reset:
                        if attr in ds[time_dim].attrs:
                            ds[time_dim].attrs[attr] = 0

                # Slice all coordinates and variable arrays to zero length and save the template
                dims = list(ds.sizes.keys())
                zero_slices = {dim: slice(0, 0) for dim in dims}
                ds_template = ds.isel(zero_slices)

                # Transfer all the attributes from reference file before creating the template and save as netcdf
                ds_template = copy_netcdf_attributes(ds, ds_template, False, None)
                ds_template.to_netcdf(template_nc_file, engine = "netcdf4")
                print(f"----Template netcdf saved to: {template_nc_file}")
            else: # gridded products - land and terrain_rt
                ds = xr.open_dataset(file_name)
                # To do: Have to figure out a workflow when CRS is "Not Available". This is almost all coastal products
                target_crs = CRS.from_user_input(wkt) 
                
                gdf = self._gpkg_gdf.to_crs(target_crs)
                gdf["geometry"] = gdf["geometry"].make_valid()
                union_geom = shapely.ops.unary_union(gdf.geometry) 
                
                # Get bounding box and snap to origin in the national reference grid
                minx, miny, maxx, maxy = gdf.total_bounds

                snapped_minx = np.floor(minx / res_x) * res_x
                snapped_miny = np.floor(miny / res_y) * res_y
                snapped_maxx = np.ceil(maxx / res_x) * res_x
                snapped_maxy = np.ceil(maxy / res_y) * res_y

                # Filter national grid to a sub-grid within the snapped bounding box using slice
                ds_subset = ds.sortby([x_name, y_name]).sel(
                    {
                        x_name: slice(snapped_minx, snapped_maxx),
                        y_name: slice(snapped_miny, snapped_maxy)
                    }
                )

                # create 1D coordinate arrays for the snapped subset
                x_subset_1D = ds_subset[x_name].values
                y_subset_1D = ds_subset[y_name].values
                xx, yy = np.meshgrid(x_subset_1D, y_subset_1D)

                shapely.prepare(union_geom)
                flat_mask = shapely.intersects_xy(union_geom, xx.ravel(), yy.ravel())
                grid_mask = flat_mask.reshape(len(y_subset_1D), len(x_subset_1D))
                
                mask_da = xr.DataArray(grid_mask,
                    dims=(y_name, x_name),
                    coords={
                        y_name: y_subset_1D,
                        x_name: x_subset_1D
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
                
                # Flattened 2D spatial mask for pixels with valid data
                combined_mask = ds_masked.to_array().notnull()
                dims_to_collapse = [dim for dim in combined_mask.dims if dim not in [x_name, y_name]]
                dataset_mask = combined_mask.any(dim=dims_to_collapse)

                # Extract non-null coordinates along each axis to locate the outer envelope borders
                y_valid = ds_masked[y_name].where(dataset_mask.any(dim=x_name), drop=True)
                x_valid = ds_masked[x_name].where(dataset_mask.any(dim=y_name), drop=True)
                
                if y_valid.size > 0 and x_valid.size > 0:
                    ymin, ymax = y_valid.values.min(), y_valid.values.max()
                    xmin, xmax = x_valid.values.min(), x_valid.values.max()
                    ds_clipped = ds_masked.sel({
                        x_name: slice(xmin, xmax),
                        y_name: slice(ymin, ymax)
                    })
                else:
                    ds_clipped = ds_masked.copy()

                # For land category, we are reducing the snow_layers from 3 (in current product) to 1.
                # We can remove the additional layers and retain the first layer in template
                if consts.DIM_SNOW_LYR in ds_clipped.dims:
                    ds_clipped = ds_clipped.isel(**{consts.DIM_SNOW_LYR: [0]})

                # Set values of NWM variables to zero in the template grid
                nwm_vars = [name for name, var in ds_clipped.data_vars.items() 
                        if var.ndim > 0 and name not in ds_clipped.coords]
                for var in nwm_vars:
                    ds_clipped[var] = ds_clipped[var] * 0
                    if ds_clipped[var].dtype == np.float64:
                        ds_clipped[var] = ds_clipped[var].astype(np.float32)

                # Transfer the attributes before creating the template, compress and save as netcdf
                ds_clipped = copy_netcdf_attributes(ds, ds_clipped, False, None)
                ds_clipped.to_netcdf(template_nc_file, engine = "netcdf4")
                print(f"----Template netcdf saved to: {template_nc_file}")

            self._template_netcdf_ds = xr.open_dataset(template_nc_file) # assign to class variable.
            end_time = time.perf_counter()
            duration_minutes = (end_time - start_time) / 60
            print(f"----Template netcdf created in {duration_minutes:2f} minutes.")
            return True
        except Exception as e:
            self._template_netcdf_ds = None
            print(f"Error in creating template netcdf for {mdata.output_class}.{mdata.category}.{mdata.domain}: {e}")
            print(traceback.format_exc())
            return False

    def produce_nwm_output_product(self, mdata: NetCDFMetadata, output_dir: str, output_cycle_hr: str) -> bool:
        """
        Produces NWM output products for land, terrain, channel and reservoir categories depending on the
        NWM `nwm_output_class`. The product uses the template from `create_template_netcdf_using_config`

        Args:
            mdata : utils.NetCDFMetadata
                The instance of the custom class that captures the metadata of NWM products from the config
            output_dir : str
                The folder where the output product will be saved or overwritten if it exists.
            output_cycle_hr : str
                The hour in a day (0-23) for which the outputs are produced after simulations are run.
        Returns:
            bool
                Returns True if the NWM product has been generated. Otherwise returns False.
        """
        produce_output = False
        is_gridded = True
        ds_modified = self._catchment_ds

        print(f"--Started nwm output product generation for {mdata.output_class}.{mdata.category}.{mdata.domain}")
        try:
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

            cat_class_domain = mdata.output_class + '.' + mdata.category +  '.' + mdata.domain
            if (cat_class_domain in consts.NWM_PRODUCTS_LIST):
                produce_output = True
            if mdata.category.startswith('channel_rt') or mdata.category.startswith('reservoir'):
                is_gridded = False

            product_created = True
            if produce_output and is_gridded:
                # Remove data variables that should not be part of the product.
                # You can remove variables that are in the ignore variables as well.
                target_variables = [var.strip() for var in mdata.nwm_variables.split(",")]
                removed_items = list(set(target_variables).intersection(set(consts.NWM_VARS_IGNORE_LIST))) # for logging
                print(f"----NWM Variables ignored for {mdata.category}: {removed_items}")
                ignore_set = set(consts.NWM_VARS_IGNORE_LIST)
                pruned_variables = [item for item in target_variables if item not in ignore_set]
                variables_to_drop = [var for var in ds_modified.data_vars if var not in pruned_variables and len(ds_modified[var].dims) > 0]
                ds_filtered = ds_modified.drop_vars(variables_to_drop, errors="ignore")

                # Log any variables that are missing in ngen output.
                for var_name in pruned_variables:
                    if var_name in ds_filtered.data_vars:
                        continue # the variable exists in ngen output. We don't need to do anything
                    else:
                        # If not in ngen output
                        print(f"----'{var_name}' is missing in ngen output")

                # Associate catchments to gridded template pixel centroid points
                catchment_grid = self.build_catchment_id_grid(mdata.x_name, mdata.y_name)

                # First check if we have correct number of timesteps in the data.
                # Get the list of hours that needs to be processed for the NWM product.
                hours_list = get_file_timestep_list(mdata.output_cycle, mdata.output_class, 
                                                    mdata.category, mdata.domain, int(output_cycle_hr), True)
                if len(hours_list) == 0:
                    print(f"------No hours identified in simulation times for {self._output_class}.{self._category}")
                    return False

                ngen_timesteps = ds_modified.sizes[consts.DIM_TIME]
                if len(hours_list) > ngen_timesteps:
                    print(f"------Mismatch: {self._output_class}.{self._category} requires {len(hours_list)} timesteps. ngen output has {ngen_timesteps}. Process aborted.")
                    return False
                # Extract only those timeslices that need to be produced
                # for example, hours [3, 6, 9, 12...] correspond to indices [2, 5, 8, 11...]
                target_indices = [hr - 1 for hr in hours_list]
                ds_sliced = ds_filtered.isel(time=target_indices)

                start_time = time.perf_counter()
                # Transfer ngen catchment data to the gridded template and produce a mapped grid
                mapped_grid, grid_index = self.transfer_catchment_data_to_grid(ds_sliced, catchment_grid, mdata.x_name, mdata.y_name)
                end_time = time.perf_counter()
                duration_minutes = (end_time - start_time) / 60
                print(f"----Transfer ngen catchment data to grid: {duration_minutes:.2f} minutes")
                
                # Data validation:
                # Validate if the spatial mapping from catchments to x, y is correct.
                # We will use 2 random catchments and 2 timesteps that have positive variable values
                num_timesteps_validated = 0
                start_time = time.perf_counter()
                mapped_ds_times = mapped_grid[consts.DIM_TIME].values
                for time_index, time_val in enumerate(mapped_ds_times):
                    if time_index > 0 and num_timesteps_validated < 2:
                        positive_variables = self.find_positive_variables(ds_sliced, time_index)
                        if len(positive_variables) > 0:
                            self.data_validation_check(
                                source=ds_sliced,
                                output=mapped_grid,
                                grid_index=grid_index,
                                variables=positive_variables,
                                sample_size=consts.VALIDATION_SAMPLE_SIZE,
                                time_index=time_index,
                                catchments_dim=consts.DIM_CATCHMENTS,
                                time_dim=consts.DIM_TIME
                            )
                            num_timesteps_validated += 1
                end_time = time.perf_counter()
                duration_minutes = (end_time - start_time) / 60
                if num_timesteps_validated > 0:
                        print(f"----Data validation completed for {consts.VALIDATION_SAMPLE_SIZE} random catchments at {num_timesteps_validated} times : {duration_minutes:.2f} minutes")
                else:
                    print(f"----Warning: Variables with positive values were not found in the gridded dataset")

                product_created = self.write_netcdf_per_timestep(mapped_grid, mdata.x_name, mdata.y_name, output_dir, output_cycle_hr)
                if product_created:
                    print(f"----NWM output product generated for {mdata.output_class}.{mdata.category}.{mdata.domain}")
            elif produce_output and not is_gridded:
                product_created = self.produce_channel_reservoir_nwm_product(mdata, output_dir, output_cycle_hr)
                if product_created:
                    print(f"----NWM output product generated for {mdata.output_class}.{mdata.category}.{mdata.domain}")
            else:
                print(f"----Production skipped for {cat_class_domain}. This combination is not specified in the NWM_Products_List.")
            return product_created
        except Exception as e:
            print(f"Error in creating netcdf product for {mdata.output_class}.{mdata.category}.{mdata.domain}: {e}")
            print(traceback.format_exc())
            return False

    def stack_soil_variables(self, var_prefix_list: list[str]) -> xr.Dataset:
        """
        Combines multiple data arrays (soil-related variables) along a new dimension as required for NWM. 
        The stacked dimensions are reordered as required for NWM.

        Args:
            var_prefix_list : list [str]
                The prefix list to identify the outpu variables that needs to be stacked.

        Returns:
            xr.Dataset
                xarray dataset replacing the individual variables with the stacked variable.

        Raises:
            ValueError: If the netcdf does not contain any variables with the prefix.
        """
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
        The x,y coordinates from the template netcdf created in `create_template_netcdf_using_config` 
        is mapped to the catchment IDs in the `catchment_netcdf_file`. 

        Args:
            x_dim_name : str
                The variable that holds the x coordinates in the netcdf template.
            y_dim_name : str
                The variable that holds the y coordinates in the netcdf template.

        Returns:
            xr.DataArray
                xarray data array (y, x) where each cell in the netcdf grid contains a catchment ID.

        Raises:
            RuntimeError if the function crashes during the process.
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
            gdf_poly["geometry"] = gdf_poly["geometry"].make_valid()
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

    def transfer_catchment_data_to_grid(self, ds: xr.Dataset, catchment_grid: xr.DataArray, 
                                        x_dim: str, y_dim: str
    ) -> tuple[xr.Dataset, xr.DataArray]:
        """
        Transfer catchment-indexed variables from a source xarray Dataset
        to a spatial grid defined by the template dataset.

        Args:
            ds : xarray.Dataset
                The netcdf dataset containing the required variables processed and ready to be written to the final product.
            catchment_grid: xr.DataArray
                The grid mapping x, y to catchment ID. This is the output from `build_catchment_id_grid`
            x_dim : str
            The variable that holds the x coordinates in the netcdf template.
            y_dim : str
                The variable that holds the y coordinates in the netcdf template.
            interval : int
                The time interval that needs to be mapped to grid. For example, medium_range is 3, long_range is 24.

        Returns:
            tuple[xr.Dataset, xr.DataArray]
                The dataset represents the grid with all timesteps for NWM product generation.
                The dataarray represents the catchment indices (instead of catchment ID) in each (x,y) for faster processing.

        Raises:
            ValueErrors during diagnostic validation checks after the grid index dataarray is produced.
        """
        ds_data = ds
        time_dim = consts.DIM_TIME
        catchment_dim = consts.DIM_CATCHMENTS
        ds_template = self._template_netcdf_ds

        # Extract only those timeslices that need to be produced
        source_times = ds_data[time_dim].values
        source_times = np.sort(source_times) # ensure chronological order

        # Convert the un-chunked source_ds into a Dask dataset and lazy Dask arrays for RAM optimization
        dask_data_ds = ds_data.chunk({time_dim: 1})

        # Convert grid IDs to indices with catchments
        # Sort catchment_ids for vectorized lookup
        catchment_ids = dask_data_ds[catchment_dim].values
        sort_order = np.argsort(catchment_ids)
        sorted_ids = catchment_ids[sort_order]

        # Perform vectorized lookup
        flat_grid = catchment_grid.values.ravel()
        pos = np.searchsorted(sorted_ids, flat_grid)
        pos_clipped = np.clip(pos, 0, len(sorted_ids) - 1)
        matched = sorted_ids[pos_clipped] == flat_grid

        flat_index = np.where(matched, sort_order[pos_clipped], -1)
        grid_index_values = flat_index.reshape(catchment_grid.shape)

        grid_index = xr.DataArray(
            grid_index_values,
            dims=catchment_grid.dims,
            coords=catchment_grid.coords
        )

        # confirm that grid index is a dataarray
        if not isinstance(grid_index, xr.DataArray): 
            print("----Indexing the catchments grid to indices is not a DataArray")
            raise TypeError(f"grid_index must be an xarray.DataArray")

        # Validate grid_index dimensions
        expected_grid_dims = {y_dim, x_dim}
        if set(grid_index.dims) != expected_grid_dims:
            print(f"----grid_index must have exactly the dimensions "
                f"({y_dim}, {x_dim}). "
                f"Got dimensions: {grid_index.dims}")
            raise ValueError(
                "grid_index must have exactly the dimensions "
                f"({y_dim}, {x_dim}). "
                f"Got dimensions: {grid_index.dims}"
            )

        # Put dimensions in canonical order.
        # Sanity check to confirm that the lat-lon are aligned after masking.
        grid_index = grid_index.transpose(y_dim, x_dim)
        valid_mask = grid_index >= 0
        if not grid_index.coords.equals(valid_mask.coords):
            print("----grid_index and valid_mask coordinates are shifted or some coordinates are lost.")
            raise ValueError("grid_index and valid_mask coordinates do not match.")

        # Mask out the invalid regions
        safe_index = np.where(valid_mask, grid_index, 0).astype(np.int64)
        safe_index_da = xr.DataArray(safe_index, dims=[y_dim, x_dim])
        valid_mask_da = valid_mask.astype(bool)

        variables_to_transfer = [
            name
            for name in ds_template.data_vars
            if (
                name in ds_data.data_vars
                and catchment_dim in ds_data[name].dims
            )
        ]

        # copy the template. Template has single time while the data should have multiple times.
        # we need to retain all. So, dropping time from template and expand as per time in the data
        output = ds_template.copy(deep=False)
        if time_dim in output.dims:
            output = output.drop_dims(time_dim)
        for var_name in output.data_vars:
            if time_dim in ds_template[var_name].dims:
                output[var_name] = output[var_name].expand_dims({time_dim: ds_data[time_dim]})
        output = output.assign_coords({time_dim: ds_data[time_dim]})

        # Map variables to 2D grid
        variables_to_transfer.sort()
        for name in variables_to_transfer:
            source_da = ds_data[name]

            source_non_catchment_dims = [
                dim
                for dim in source_da.dims
                if dim != catchment_dim
            ]

            missing_dims = [
                dim
                for dim in source_non_catchment_dims
                if dim not in ds_template.dims
            ]

            if missing_dims:
                print(f"----Variable {name} contains dimensions "
                    f"{missing_dims} that are not present in the template.")
                raise ValueError(f"Variable {name} contains dimensions "
                    f"{missing_dims} that are not present in the template."
                )
            
            if catchment_dim in source_da.dims:
                mapped_da = dask_data_ds[name].isel({catchment_dim: safe_index_da})
                spatial_chunks = self.chunk_for_netcdf(mapped_da, x_dim, y_dim, True)
                mapped_da = mapped_da.chunk(spatial_chunks)
                
                if catchment_dim in mapped_da.coords:
                    # Remove the catchments dimension if present.
                    mapped_da = mapped_da.drop_vars(catchment_dim)
                    
                # Mask data safely based on dtype
                if np.issubdtype(mapped_da.dtype, np.integer):
                    processed_da = xr.where(valid_mask_da, mapped_da, -9999).astype(mapped_da.dtype)
                else:
                    processed_da = mapped_da.where(valid_mask_da, other=np.nan).astype(mapped_da.dtype) #.astype(np.float32)

                output[name] = processed_da

                # Unify the Dask chunk structure explicitly
                target_chunks = {
                    time_dim: 1,
                    y_dim: spatial_chunks[y_dim],
                    x_dim: spatial_chunks[x_dim],
                }
                # Adjust target chunks if the variable has extra dimensions (like snow layers or soil layers)
                for dim in processed_da.dims:
                    if dim not in target_chunks:
                        dask_chunks = dask_data_ds.chunks.get(dim)
                        if dask_chunks is not None and len(dask_chunks) > 0:
                            target_chunks[dim] = dask_chunks[0]
                        else:
                            target_chunks[dim] = ds_data[dim].size
                output[name] = output[name].chunk(target_chunks)
            else:
                # Check if the variable is a pure scalar (0 dimensions)
                if len(source_da.dims) == 0:
                    # Assign the scalar directly without any chunking modifications
                    output[name] = source_da.copy(deep=False)
                else:
                    # Verify dimensions are compatible.
                    for dim in source_da.dims:
                        if dim not in ds_template.dims:
                            print(f"----Cannot copy variable {name}: dimension "
                                f"{dim} does not exist in template.")
                            raise ValueError(
                                f"Cannot copy variable {name}: dimension "
                                f"{dim} does not exist in template."
                            )
                    # If it has other dimensions (but not time or catchment), copy its lazy dask representation
                    output[name] = dask_data_ds[name].copy(deep=False)

        # Copy all attributes from template
        output = copy_netcdf_attributes(ds_template, output, False, None)

        return output, grid_index

    def chunk_for_netcdf(self, xr_obj: xr.Dataset | xr.DataArray, x_dim: str, y_dim: str, spatial: bool) -> dict[str, int]:
        """
        Apply chunking optimized for faster processing.

        Args:
            xr_obj : xr.Dataset | xr.DataArray
                The netcdf dataset or dataarray that needs to be chunked.
            x_dim : str
                The variable that holds the x coordinates in the netcdf dataset.
            y_dim : str
                The variable that holds the y coordinates in the netcdf dataset.
            spatial : bool
                A boolean variable indicating whether to chunk it for spatial broadcasting
        Returns:
            dict[str, int]
                The chunks dictionary. 
        """
        chunks = {}
        dimensions = xr_obj.sizes if isinstance(xr_obj, xr.Dataset) else xr_obj.dims
        for dim in dimensions:
            if dim == consts.DIM_TIME:
                chunks[consts.DIM_TIME] = 1

            # Based on performance tests, it was best not to chunk along x and y
            # for netcdf writing. However, we need to chunk for spatial mapping.
            elif dim == x_dim:
                if spatial:
                    chunks[x_dim] = consts.NC_SPATIAL_CHUNK_SIZE
                else:
                    chunks[x_dim] = -1
            elif dim == y_dim:
                if spatial:
                    chunks[y_dim] = consts.NC_SPATIAL_CHUNK_SIZE
                else:
                    chunks[y_dim] = -1
            else:
                if spatial:
                    chunks[dim] = -1

        return chunks

    def sort_by_time(self, ds: xr.Dataset, time_dim: str, ascending: bool = True) -> xr.Dataset:
        """
        Sort dataset by datetime time coordinate.

        Args:
            ds : xarray.Dataset
                The netcdf dataset that needs to be sorted along time coordinate.
            time_dim : str
                The name of the time dimension in the netcdf dataset.
            ascending: bool
                A boolean flag that tells whether to sort the data ascending or descending.

        Returns:
            xr.Dataset
                The dataset sorted by time. 
        """
        time_values = ds[time_dim].values
        sort_idx = np.argsort(time_values)
        if not ascending:
            sort_idx = sort_idx[::-1]
        return ds.isel({time_dim: sort_idx})

    def write_netcdf_per_timestep(self, mapped_grid: xr.Dataset, x_dim: str, y_dim: str, 
                                  output_dir: str, output_cycle_hr: str) -> bool:
        """
        Writes one NetCDF per timestep for the various NWM cycle runs. It handles the product file naming as well.
        This is called only for land and terrain_rt NWM products.
        Args:
            mapped_grid : xarray.Dataset
                The netcdf dataset representing the grid with all timesteps for the final NWM product.
            x_dim : str
                The name of the spatial x dimension
            y_dim : str
                The name of the spatial y dimension
            output_dir : str
                The folder where the output product will be saved or overwritten if it exists.
            output_cycle_hr : str
                The hour in a day (0-23) for which the outputs are produced after simulations are run.
        Returns:
            bool
                True if all files have been written successfully. Otherwise False.
        """
        os.makedirs(output_dir, exist_ok=True)
        time_dim = consts.DIM_TIME
        ref_time_dim = consts.DIM_REF_TIME

        if self._output_class.startswith('analysis_assim'):
            # AnA numbers tm00 (most recent) -> tmNN (oldest). Sort by descending
            mapped_grid = self.sort_by_time(mapped_grid, time_dim, False)
        else:
            mapped_grid = self.sort_by_time(mapped_grid, time_dim, True) # sort ascending

        sorted_times = mapped_grid[time_dim].values
        sorted_indices = np.arange(len(sorted_times))

        # Compute min, max and reference time.
        # Get time string values for global attributes
        if self._output_class.startswith('analysis_assim'):
            time_value_min = np.int32(np.datetime64(sorted_times[-1]).astype("datetime64[m]"))
            time_value_max = np.int32(np.datetime64(sorted_times[0]).astype("datetime64[m]"))
            min_time = sorted_times[-1]
        else:
            time_value_min = np.int32(np.datetime64(sorted_times[0]).astype("datetime64[m]"))
            time_value_max = np.int32(np.datetime64(sorted_times[-1]).astype("datetime64[m]"))
            min_time = sorted_times[0]

        valid_time_str = str(min_time).split('.')[0].replace('T', '_')
        ref_time_str = str(min_time - np.timedelta64(1, 'h')).split('.')[0].replace('T', '_')
        reference_time = min_time - np.timedelta64(1, 'h')

        start_time = time.perf_counter()

        # Chunk up the grid
        chunks = self.chunk_for_netcdf(mapped_grid, x_dim, y_dim, False)
        mapped_grid = mapped_grid.chunk(chunks)

        total_files = len(sorted_times)
        for i in range(0, total_files, consts.NC_BATCH_SIZE):
            batch_indices = sorted_indices[i:i + consts.NC_BATCH_SIZE]
            batch_times = sorted_times[i:i + consts.NC_BATCH_SIZE]
            batch_ds = mapped_grid.isel({time_dim: batch_indices})
            batch_ds = batch_ds.load()
            time_encoding = batch_ds[time_dim].encoding.copy()

            for time_step, snapshot_time_val in enumerate(batch_times):
                ds_t = batch_ds.isel({time_dim: [time_step]})
                ds_t[time_dim].encoding.update(time_encoding)
                valid_time_str = str(snapshot_time_val).split('.')[0].replace('T', '_')

                # Add reference_time variable to netcdf
                ref_time_da = xr.DataArray(
                    data = [reference_time],
                    dims = [ref_time_dim],
                    coords = {ref_time_dim: [reference_time]}
                )
                ds_t[ref_time_dim] = ref_time_da

                # Copy all variable attributes and encoding as in the template.
                ds_t = copy_netcdf_attributes(self._template_netcdf_ds, ds_t, True, None)

                # Lastly, update time attributes.
                ds_t[time_dim].attrs["valid_min"] = np.int32(time_value_min)
                ds_t[time_dim].attrs["valid_max"] = np.int32(time_value_max)

                # Copy and update global attribute values as in the template.
                ds_t = self.update_global_attributes(ds_t, valid_time_str, ref_time_str)

                # Output filename and save
                prefix = get_file_timestep_prefix(self._output_class)
                output_time_index = (i + time_step) # set correct timestep value for file name
                sim_time_hr = generate_formatted_timestring_for_naming(output_time_index, self._output_class, self._category)
                if sim_time_hr == 'unknown':
                    print(f"----Formatted timestring for file name not generated for {self._output_class}, {self._category}")
                    return False
                formatted_t = f"{prefix}{sim_time_hr}"
                cycle_hr = output_cycle_hr.zfill(2)
                output_file = os.path.join(output_dir, f"nwm.t{cycle_hr}z.{self._geo_id}.{self._output_class}.{self._category}.{formatted_t}.{self._domain}.nc")
                ds_t.to_netcdf(output_file, engine = 'netcdf4')

        end_time = time.perf_counter()
        duration_minutes = (end_time - start_time) / 60
        print(f"----{self._category} products for each timestep written in: {duration_minutes:.2f} minutes")
        return True

    def produce_channel_reservoir_nwm_product(self, mdata: NetCDFMetadata, output_dir: str, output_cycle_hr: str) -> bool:
        """
        Expands a zeroed NetCDF template and populates it with data for channel_rt and reservoir NWM products.
        
        Args:
            mdata : utils.NetCDFMetadata
                The instance of the custom class that captures the metadata of NWM products from the config
            output_dir : str
                The folder where the output product will be saved or overwritten if it exists.
            output_cycle_hr : str
                The hour in a day (0-23) for which the outputs are produced after simulations are run.
        
        Returns:
            bool
                True if the product has been created successfully. Otherwise False
        Raises:
            ValueError if the required dataset inputs are not being assigned yet.
        """
        if not self._template_netcdf_ds:
            raise ValueError("Template netcdf not set")
        
        if mdata.category == 'channel_rt' and not self._catchment_ds:
            raise ValueError("ngen catchment netcdf not set")
        
        if mdata.category == 'channel_rt' and not self._troute_netcdf_ds:
            raise ValueError("troute output netcdf not set")

        if mdata.category.startswith('reservoir') and self._troute_lakeout_netcdf_ds is None:
            raise ValueError("troute lakeout netcdf not set")

        time_dim = consts.DIM_TIME
        ref_time_dim = consts.DIM_REF_TIME
        feature_id_dim = consts.DIM_FEATURE_ID

        reference_epoch = np.datetime64("1970-01-01T00:00:00") # set reference epoch
        
        if mdata.category.startswith('reservoir'):
            troute_source_ds = self._troute_lakeout_netcdf_ds
        elif mdata.category.startswith('channel_rt'):
            troute_source_ds = self._troute_netcdf_ds
            # troute output has a variable called flow which should be streamflow in the NWM product.
            # adopting to quickly rename the variable in the troute output for now.
            # To do: Have a variables mapping of these outputs with NWM products and do that without hardcoding here
            troute_source_ds = troute_source_ds.rename({"flow": "streamflow"})
        else:
            raise ValueError(f"Unexpected category for channel/reservoir product: {mdata.category}")

        # Check if there are correct number of files in the data. 
        # Get the list of hours that needs to be processed for the NWM product.
        hours_list = get_file_timestep_list(mdata.output_cycle, mdata.output_class, 
                                            mdata.category, mdata.domain, int(output_cycle_hr), True)
        if len(hours_list) == 0:
            print(f"------No hours identified in simulation times for {self._output_class}.{self._category}")
            return False
        troute_timesteps = troute_source_ds.sizes[time_dim]
        if len(hours_list) != troute_timesteps:
            print(f"------Mismatch: {self._output_class}.{self._category} requires {len(hours_list)} timesteps. T-Route output has {troute_timesteps}. Process aborted.")
            return False

        # Extract only those timeslices that need to be produced
        # for example, hours [3, 6, 9, 12...] correspond to indices [2, 5, 8, 11...]
        target_indices = [hr - 1 for hr in hours_list]
        ds_sliced = troute_source_ds.isel(time=target_indices)

        if self._output_class.startswith('analysis_assim'):
            # AnA numbers tm00 (most recent) -> tmNN (oldest). Sort by descending
            ds_sliced = self.sort_by_time(ds_sliced, time_dim, False)
        else:
            ds_sliced = self.sort_by_time(ds_sliced, time_dim, True) # sort ascending

        sorted_times = ds_sliced[time_dim].values

        # Compute min, max and reference time
        # The approach is different from the mapped products because each product uses different way of reporting time.
        # ngen catchment output reports in seconds since reference_epoch.
        # troute output reports in offset seconds since the model initialization time.
        # troute lakeout (waterbody) reports in minutes since reference epoch.
        if self._output_class.startswith('analysis_assim'):
            time_value_min = np.int32((sorted_times[-1] - reference_epoch) / np.timedelta64(1, "m"))
            time_value_max = np.int32((sorted_times[0] - reference_epoch) / np.timedelta64(1, "m"))
            min_time = sorted_times[-1]
        else:
            time_value_min = np.int32((sorted_times[0] - reference_epoch) / np.timedelta64(1, "m"))
            time_value_max = np.int32((sorted_times[-1] - reference_epoch) / np.timedelta64(1, "m"))
            min_time = sorted_times[0]

        # Get reference time for output
        # Get string formatted time for attributes
        ref_time_str = str(min_time - np.timedelta64(1, 'h')).split('.')[0].replace('T', '_')
        ref_time_val = min_time - np.timedelta64(1, 'h') # 60 mins less than the minimum time.

        re_index_args = {
            feature_id_dim: ds_sliced[feature_id_dim].values,
            ref_time_dim: [ref_time_val]
        }

        # Maintain a list of errors/warnings that need to be logged for a product.
        # We will use this to avoid duplicate items in the log.
        log_warnings = []

        # Create one netcdf each for each time step
        start_time = time.perf_counter()

        # If a variable is in the NWM IGNORE list, log it and drop it from the template
        variables_to_drop = [var for var in self._template_netcdf_ds.data_vars if var in consts.NWM_VARS_IGNORE_LIST]
        if len(variables_to_drop) > 0:
            self._template_netcdf_ds = self._template_netcdf_ds.drop_vars(variables_to_drop, errors='ignore')
            print(f"----NWM Variables ignored for {mdata.category}: {variables_to_drop}")

        for time_step, snapshot_time_val in enumerate(sorted_times):
            populated_ds = self._template_netcdf_ds.reindex(**re_index_args, fill_value = np.nan)
            time_args = {time_dim: [snapshot_time_val]}
            populated_ds = populated_ds.assign_coords(**time_args)
            valid_time_str = str(snapshot_time_val).split('.')[0].replace('T', '_')

            # Populate variables defined in the template using the negen output and troute data
            for var_name in self._template_netcdf_ds.variables:
                # leave the dimensions out as they (except time) have already been populated.
                if var_name in self._template_netcdf_ds.dims:
                    continue
                
                # Add reference time value to the output
                if var_name == ref_time_dim:
                    # Assign the scalar or 1D value directly to the pre-allocated template dimension
                    populated_ds[var_name].values = np.array([ref_time_val]).astype(populated_ds[var_name].dtype)
                    continue

                # Confirm if the variable is present both in lakeout and final output
                in_snapshot = var_name in ds_sliced.variables
                in_populated = var_name in populated_ds.variables
                if var_name.lower() == 'qbucket':
                    in_ngenout = var_name in self._catchment_ds.variables
                
                if not in_snapshot and not in_populated:
                    warning_msg = "----" + var_name + " is missing from both troute and output datasets."
                    if warning_msg not in log_warnings:
                        log_warnings.append(warning_msg)
                        print(f"----{var_name} is missing from both troute and output datasets.")
                    continue
                elif not in_snapshot and var_name.lower() != 'qbucket':
                    if self._template_netcdf_ds[var_name].ndim == 0: # Scalar variables not in the data, but in template
                        populated_ds[var_name] = xr.DataArray(self._template_netcdf_ds[var_name].values.item())
                        warning_msg = ("----Found a scalar variable - " + var_name + " that is not in the data, "
                        "but present in the template.Template value has been copied over.")
                        if warning_msg not in log_warnings:
                            log_warnings.append(warning_msg)
                            print(f"----Found a scalar variable - {var_name} that is not in the data, but present in the template.Template value has been copied over.")
                    else:
                        warning_msg = ("----Found a data variable - " + var_name + " that is not in the data, "
                        "but present in the template. It is filled with NaN.")
                        if warning_msg not in log_warnings:
                            log_warnings.append(warning_msg)
                            print(f"----Found a data variable - {var_name} that is not in the data, but present in the template. It is filled with NaN.")
                    continue
                elif not in_populated:
                    warning_msg = "----" + var_name + " is in the template but not found in the output dataset."
                    if warning_msg not in log_warnings:
                        log_warnings.append(warning_msg)
                        print(f"----{var_name} is in the template but not found in the output dataset.")
                    continue
                elif var_name.lower() == 'qbucket' and not in_ngenout:
                    warning_msg = "----" + var_name + " is in the template but not found in the catchment output dataset."
                    if warning_msg not in log_warnings:
                        log_warnings.append(warning_msg)
                        print(f"----{var_name} is in the template but not found in the catchment output dataset.")
                    continue
                
                # Get the time slice data for this variable, if time is one of the dimensions.
                # Otherwise, get the full variable (typically 1D based on feature_id dimension)
                template_var = self._template_netcdf_ds[var_name]
                if var_name.lower() == 'qbucket':
                    # Bug in troute: troute may not have the same catchments as in ngen. 
                    # Temporary measure: We use troute as the authoritative source and reindex ngen variable

                    # ngen uses 'catchments', while troute uses 'feature_id'. So, we rename first.
                    ngen_ds = self._catchment_ds.rename({consts.DIM_CATCHMENTS: feature_id_dim})
                    
                    # get time slice data from ngen catchment output. 
                    # Cast to nanosecond precision to match ngen source values.
                    dt_ns = np.datetime64(snapshot_time_val).astype('datetime64[ns]')
                    source_var = ngen_ds[var_name].sel({consts.DIM_TIME: dt_ns})
                    
                    # Log differences between the two datasets
                    ngen_feature_ids = source_var[feature_id_dim].values
                    troute_feature_ids = ds_sliced[feature_id_dim].values
                    common = np.intersect1d(ngen_feature_ids, troute_feature_ids)
                    only_in_ngen = np.setdiff1d(ngen_feature_ids, troute_feature_ids)
                    only_in_troute = np.setdiff1d(ngen_feature_ids, troute_feature_ids)
                    if len(common) == 0:
                            print("----No matching catchments found between ngen and troute.")
                            raise ValueError("No matching catchments found between ngen and troute.")
                    if len(only_in_ngen) > 0:
                        warning_msg = "----Warning: Missing catchments in troute: " + str(len(only_in_ngen))
                        if warning_msg not in log_warnings:
                            print(f"----Warning: Missing catchments in troute: {len(only_in_ngen)}")
                    if len(only_in_troute) > 0:
                        warning_msg = "----Warning: Missing in ngen output: " + str(len(only_in_troute))
                        if warning_msg not in log_warnings:
                            print(f"----Warning: Missing in ngen output: {len(only_in_troute)}")

                    #reindex ngen variable
                    troute_feature_ids = ds_sliced[feature_id_dim]
                    if feature_id_dim in source_var.dims:
                        if feature_id_dim not in source_var.coords:
                            source_var = source_var.assign_coords(
                                {feature_id_dim: source_var[feature_id_dim]}
                            )
                        source_var = source_var.reindex({feature_id_dim: troute_feature_ids})
                    else:
                        print(f"{var_name} does not have {feature_id_dim} in its dimensions: {source_var.dims}")
                        return False
                else:
                    troute_unsliced_var = ds_sliced[var_name]
                    if time_dim in troute_unsliced_var.dims:
                        # this loop is in descending order of time. but, the source is in ascending order.
                        # recalculate time index.
                        total_timesteps = troute_unsliced_var.sizes[time_dim]
                        inverted_time_index = total_timesteps - 1 - time_step
                        source_var = troute_unsliced_var.isel({time_dim: inverted_time_index})
                    else:
                        source_var = troute_unsliced_var
                
                tgt_shape = populated_ds[var_name].shape
                if source_var.ndim == len(tgt_shape):
                    data_values = source_var.values
                    # Verify the types because the lakeout variables such as inflow and outflow are float
                    # But, they are int in the template. So, we are casting from float to int and fill with 0.
                    if np.issubdtype(template_var.dtype, np.integer):
                        if np.issubdtype(data_values.dtype, np.floating):
                            source_var = source_var.fillna(0).astype(np.int32)
                    populated_ds[var_name] = source_var
                else:
                    print(f"----The dimensions don't match between template ({template_var.dims}) and snapshot ({source_var.dims}) for {var_name}")
                    return False
                
            # Copy all variable attributes and encoding from template
            populated_ds = copy_netcdf_attributes(self._template_netcdf_ds, populated_ds, False, None)

            # Add valid min and max times to the "time" attributes
            populated_ds[time_dim].attrs["valid_min"] = np.int32(time_value_min)
            populated_ds[time_dim].attrs["valid_max"] = np.int32(time_value_max)

            # Copy and update global attribute values as in the template.
            populated_ds = self.update_global_attributes(populated_ds, valid_time_str, ref_time_str)

            # Output filename and save
            os.makedirs(output_dir, exist_ok=True)
            prefix = get_file_timestep_prefix(self._output_class)
            sim_time_hr = generate_formatted_timestring_for_naming(time_step, self._output_class, self._category)
            if sim_time_hr == 'unknown':
                print(f"----Formatted timestring for file name not generated for {self._output_class}, {self._category}")
                return False
            formatted_t = f"{prefix}{sim_time_hr}"
            cycle_hr = output_cycle_hr.zfill(2)
            output_file = os.path.join(output_dir, f"nwm.t{cycle_hr}z.{self._geo_id}.{self._output_class}.{self._category}.{formatted_t}.{self._domain}.nc")
            populated_ds.to_netcdf(output_file, engine = 'netcdf4')

        end_time = time.perf_counter()
        duration_minutes = (end_time - start_time) / 60
        print(f"----{self._category} products for each timestep written in: {duration_minutes:.2f} minutes")
        return True

    def update_global_attributes(self, ds: xr.Dataset, valid_time: str, init_time: str) -> xr.Dataset:
        """
            This updates global attributes for NWM products.
            
            Args:
                ds: xr.Dataset
                    The input xarray Dataset in which the attributes need to be updated.

                valid_time : str
                    The model output valid time 
                
                ref_time : str
                    The model initialization time 
            Returns:
                xarray.Dataset
                    This dataset contains the updated attribute values as per the NWM templates
        """
        ds.attrs.update({'TITLE': 'OUTPUT FROM NWM v4.0'})
        ds.attrs.update({'NWM_version_number': 'v4.0'})
        ds.attrs.update({'model_initialization_time': init_time})
        ds.attrs.update({'model_output_valid_time': valid_time})
        ds.attrs.update({'model_output_type': self._category})
        ds.attrs.update({'model_configuration': self._output_class})
        if self._output_cycle[-1].isdigit(): # update ensemble member number
            ds.attrs.update({'ensemble_member_number': np.int32(self._output_cycle[-1])})
        return ds
# endregion

# region data validation
    def find_positive_variables(self, ds: xr.Dataset, time_index: int) -> list[str]:
        """
        This function identifies variables that have at least one positive value in a netcdf timeslice.
        
        Args:
            ds: xr.Dataset
                The input xarray Dataset in which variables need to be identified.
            time_index: int
                The time index for timeslicing the data in the netcdf.

        Returns:
            list[str]
                The list of variables that have at least one positive value in the timeslice.
        """
        positive_vars = []
        for var in ds.data_vars:
            da = ds[var].isel(time=time_index)
            # Skip non-numeric variables, skip scalar variables
            if not np.issubdtype(da.dtype, np.number) or consts.DIM_CATCHMENTS not in da.dims:
                continue
            has_positive = bool((da > 0).any())
            if has_positive:
                positive_vars.append(var)
        return positive_vars

    def data_validation_check(self, source: xr.Dataset, output: xr.Dataset,
        grid_index: xr.DataArray, variables: list[str], sample_size: int = 5,
        time_index: int = 0, catchments_dim: str = "catchments", time_dim: str = "time"
    ) -> None: 
        """
        Validate catchments-to-grid transformation that is used to produce land and terrain NWM products.

        Checks:
        - mapped catchments only
        - non-zero source values only
        - catchment-to-grid index consistency
        - source vs output grid-cell values
        - numerical values within a low tolerance
        
        Args:
            source: xr.Dataset
                The input xarray Dataset that contains the ngen output data as (time, catchments) arrays.
            output: xr.Dataset
                The mapped spatial xarray Dataset.
            grid_index: xr.DataArray
                The dataarray represents the catchment indices (instead of catchment ID) in each (x,y) for faster processing.
                It is the output from `transfer_catchment_data_to_grid`
            variables: list[str]
                List of variables that needs to be validated. If None, all variables in the source dataset is validated.
            sample_size: int
                Number of catchments that are drawn as a sample to do spot validation checks. Defaults to 10.
            time_index: int
                The time index for timeslicing the data in the netcdf. Defaults to 0
            catchments_dim: str = "catchments"
                The name of the dimension that has catchments information
            time_dim: str = "time"
                The name of the dimension that has time information
        """

        # Get the indices of catchments that are mapped (grid_index >=0)
        mapped_catchment_indices = np.unique(grid_index.values[grid_index.values >= 0])

        for var in variables:
            passed = 0
            failed = 0
            failures = []
            # source_time_index = time_index * interval
            src = source[var].isel({time_dim: time_index})
            dst = output[var].isel({time_dim: time_index})

            # Find non-zero entities
            if catchments_dim in src.dims:
                reduce_dims = [dim for dim in src.dims if dim != catchments_dim]
                active_catchments = ((src > 0).any(dim=reduce_dims))
                nonzero_catchment_indices = np.where(active_catchments.values)[0] # those catchments where non-zero values are found
                if nonzero_catchment_indices.size == 0:
                    print("----------No non-zero values found")
                    continue
                
                # Intersect the mapped and non-zero catchment indices and find the common ones in them.
                # We will use the intersection output to sample catchments for validation.
                validation_catchment_indices = np.intersect1d(mapped_catchment_indices, nonzero_catchment_indices)
                if len(validation_catchment_indices) == 0:
                    print(f"----------No mapped non-zero values for {var}")
                    continue

                sample_catchments_indices = np.random.choice(
                    validation_catchment_indices,
                    size=min(sample_size, len(validation_catchment_indices)),
                    replace=False,
                )

                for catchment_idx in sample_catchments_indices:

                    # Convert catchment ID to grid index
                    # Positional indices and not the catchment values in grid_index
                    catchment = source[catchments_dim].values[catchment_idx]
                    locations = np.argwhere(grid_index.values == catchment_idx)
                    if len(locations) == 0:
                        failures.append(
                            {
                                "catchment": catchment,
                                "reason": "Catchment not found in grid_index",
                            }
                        )
                        continue

                    y, x = locations[0]
                    # Confirm spatial mapping from catchments to X, Y is correct
                    assert grid_index.values[y, x] == catchment_idx

                    src_val = src.isel({catchments_dim: catchment_idx}) # ngen output values                    
                    dst_val = dst.isel({"y": y, "x": x}) # Output grid values

                    try:
                        np.testing.assert_allclose(
                            src_val.values.ravel(),
                            dst_val.values.ravel(),
                            rtol=1e-6,
                            atol=1e-12
                        )
                        passed += 1

                    except AssertionError as e:
                        failed += 1
                        failures.append(
                        {
                            "variable": var,
                            "catchment": catchment,
                            "message": str(e),
                        }
                    )
                # print data validation failures for the variable
                if failed > 0:
                    print(f"------Validation check for {var}: Time index: {time_index}, Sample size of catchments: {sample_size}; Passed = {passed}; Failed = {failed}")
                if len(failures) > 0:
                    print(f"------Data validation failures for {var}: {failures}")
# endregion

    def close_log(self):
        """
        Restores the original terminal output and closes the file.
        """
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
        Close the log file.
        """
        self.close_log()