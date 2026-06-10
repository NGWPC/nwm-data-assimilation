import os
import json
import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
import dask.array as da
import time
from shapely.geometry import Point
from shapely.ops import unary_union
from shapely import intersects_xy
from pyproj import CRS
from typing import List, Optional
from .DataReader import DataReader
from . import consts

class DataProcessor(DataReader):
    """
    Handles catchment-time NetCDF and grid generation.
    """
    def __init__(self, catchment_netcdf_file: str, gpkg_file: str,
                  config_path: str, output_class: str | None, category: str | None, 
                  domain: str | None, chunk_size: int = 100) -> None:
        
        super().__init__(catchment_netcdf_file, chunk_size)

        self._catchment_ds: xr.Dataset = self.dataset
        self._gpkg_file = gpkg_file
        self._config_path = config_path
        self._output_class = output_class
        if category in ['channel_rt', 'reservoir', 'total_water']:
            raise ValueError(f"The requested category - {category} - is not a gridded netcdf. This cannot be processed.")
        else:
            self._category = category
            self._domain = domain
        
        # Normalize catchment ids in netcdf with a cat- prefix for consistency.
        nc_catchments = self._normalize_catchment_ids(self._catchment_ds[self.catchment_coord].values)
        
        # Read geopackage, determine schema and "divides" layer
        is_new_NHF_schema: bool = self._is_new_NHF_schema(gpkg_file, "reference_flowpaths")
        gpkg_gdf = gpd.read_file(gpkg_file, layer="divides")
        if gpkg_gdf.empty:
            raise ValueError("No polygon geometries found in GeoPackage")

        # Check schema and assign catchment ID field.
        if is_new_NHF_schema:
            self.catchment_field = "div_id"
        else:
            self.catchment_field = "divide_id"

        # Normalize catchment ids in gpkg with a 'cat-' prefix for consistency.
        gpkg_gdf[self.catchment_field] = self._normalize_catchment_ids(gpkg_gdf[self.catchment_field].values)
        gpkg_catchment_list = gpkg_gdf[self.catchment_field].values.tolist()
        self._gpkg_gdf = gpkg_gdf
        
        # Check if catchments from netcdf and geopackage match
        if set(nc_catchments) != set(gpkg_catchment_list):
            raise ValueError("There is a mistmatch between catchment IDs in geopackage and netcdf")   


    def set_template_grid(self, template_grid_path: str):
        self.ds_template_grid = xr.open_dataset(template_grid_path)

    def _is_new_NHF_schema(self, geopackage_path: str, layer_name: str) -> bool:
        """
        Check the data schema in the geopackage for the new NHF format
        """
        layers = gpd.list_layers(geopackage_path)
        tabular_layers = layers[layers[consts.GPKG_GEOMETRY_TYPE_IDENTIFIER].isna()]
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
    
    def create_template_grid_netcdf_using_config(self, template_grid_netcdf_path: str) -> None:
        """
        Create a template grid aligned to a reference grid defined in config.json.
        The template grid covers the extents in the geopackage (usually basin level).
        """
        # Read config file
        with open(self._config_path, "r") as f:
            config = json.load(f)

        # Find matching entry
        entry = next((c_item for c_item in config["files"] if 
              c_item["class"] == self._output_class and 
              c_item["category"] == self._category and 
              c_item["domain"] == self._domain), None)
        if entry is None:
            raise ValueError(f"Cannot find a config file entry that matches {self._output_class}, {self._category} and {self._domain}")

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

        # Reinforce crs as a scalar variable.
        # This removes the string1 dimension that gets added
        # and creates crs as a string scalar variable.
        crs_attrs = ds_clipped["crs"].attrs
        ds_clipped = ds_clipped.drop_encoding()
        del ds_clipped["crs"]
        ds_clipped["crs"] = xr.DataArray("", dims=())
        ds_clipped["crs"].attrs = crs_attrs

        # Save
        ds_clipped.to_netcdf(template_grid_netcdf_path)
        self.ds_template_grid = xr.open_dataset(template_grid_netcdf_path)

        print(f"NetCDF template grid written to {template_grid_netcdf_path}")

    def produce_nwm_output_grid(self, output_dir: str) -> None:
        # change variable name in the randomvals.nc This is strictly for testing purposes. 
        # The case statements should be removed before going into production.
        cat_class_domain = self._output_class + '_' + self._category +  '_' + self._domain
        match cat_class_domain:
            case "analysis_assim_land_conus":
                # analysis_assim.land.conus
                self._catchment_ds = self._catchment_ds.rename({
                    'sm_frac_0.4m': 'ACCET',
                    'sm_profile_0.1m': 'ACSNOM',
                    'sm_profile_0.4m': 'EDIR',
                    'sm_profile_1.5m': 'ISNOW',
                    'sm_profile_2m': 'QRAIN',
                    'SWE_mm': 'QSNOW'
                })
            case "analysis_assim_terrain_rt_conus" | "medium_range_blend_terrain_rt_conus":
                # analysis_assim.terrain_rt.conus; medium_range_blend.terrain_rt.conus
                self._catchment_ds = self._catchment_ds.drop_vars(["sm_profile_0.4m", "sm_profile_1.5m", "sm_profile_2m", "SWE_mm"])
                self._catchment_ds = self._catchment_ds.rename({
                    'sm_frac_0.4m': 'sfcheadsubrt',
                    'sm_profile_0.1m': 'zwattablrt'
                })
            case "long_range_land_2_conus":
                # long_range.land_2.conus
                self._catchment_ds = self._catchment_ds.rename({
                    'sm_frac_0.4m': 'ACCET',
                    'sm_profile_0.1m': 'UGDRNOFF',
                    'sm_profile_0.4m': 'SOILSAT',
                    'sm_profile_1.5m': 'SFCRNOFF',
                    'sm_profile_2m': 'SOILSAT_TOP',
                    'SWE_mm': 'SNEQV'
                })
            case "medium_range_blend_land_conus": 
                # medium_range_blend.land.conus
                self._catchment_ds = self._catchment_ds.rename({
                    'sm_frac_0.4m': 'FSA',
                    'sm_profile_0.1m': 'FIRA',
                    'sm_profile_0.4m': 'HFX',
                    'sm_profile_1.5m': 'TRAD',
                    'sm_profile_2m': 'LH',
                    'SWE_mm': 'SNEQV'
                })

        catchment_grid = self.build_catchment_id_grid("x", "y") # Change hardcoded values later
        mapped_grid = self.map_catchment_data_to_grid(catchment_grid, consts.DIM_CATCHMENTS)
        
        start_time = time.perf_counter()
        self.write_netcdf_per_timestep(mapped_grid, output_dir, consts.DIM_TIME)
        end_time = time.perf_counter()
        duration_minutes = (end_time - start_time) / 60
        print(f"Function execution time: {duration_minutes:.4f} minutes")

    def build_catchment_id_grid(self, x_dim: str = "x", y_dim: str = "y") -> xr.DataArray:
        """
        Returns a DataArray (y, x) where each cell in the basin-level grid contains a catchment ID.
        """
        ds = self.ds_template_grid
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
        crs = CRS.from_wkt(ds["crs"].attrs["spatial_ref"])
        gdf_ncgrid_points = gpd.GeoDataFrame(
            df_points,
            geometry=gpd.points_from_xy(df_points["x"], df_points["y"]),
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
            dims=(y_dim, x_dim),
            coords={y_dim: y, x_dim: x},
            name="catchment_id"
        )
        # It is important to pass on the CRS info to the functions downstream
        # Attaching the crs wkt as a xr.dataarray attribute
        catchment_id_da.attrs["crs"] = ds["crs"].attrs["spatial_ref"]
        return catchment_id_da
    
    def map_catchment_data_to_grid(self, catchment_grid: xr.DataArray,
                                   catchment_dim: str = consts.DIM_CATCHMENTS
    ) -> xr.Dataset:
        """
        Assign catchment-based variables onto basin-level grid using the catchment_id grid.
        """

        ds_data = self._catchment_ds

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
            "x": self.ds_template_grid["x"],
            "y": self.ds_template_grid["y"]
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
            output_file = os.path.join(output_dir, f"grid_{formatted_t}.nc") # To do: Get this as function argument
            ds_t.to_netcdf(output_file)

