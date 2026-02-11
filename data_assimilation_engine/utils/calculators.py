"""Base Calculators."""

import logging
from datetime import datetime
from functools import lru_cache

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import xarray as xr
from shapely import MultiPoint, Polygon, voronoi_polygons
from shapely.geometry import Point

from data_assimilation_engine.swe.snotel import SnotelCalculator
from data_assimilation_engine.utils.utils import timing_block

logger = logging.getLogger(__name__)


class Calculator:
    """Base Calculator."""

    def __init__(self, basin_gdf: gpd.GeoDataFrame = None):
        """Initialize the calculator."""
        self.basin_gdf = basin_gdf

    @property
    @lru_cache
    def basin_geometry(self) -> shapely.geometry:
        """Extract a unified basin geometry from a GeoDataFrame.

        Returns
        -------
        shapely.geometry
            (basin_geometry) where:
                - basin_geometry is a shapely geometry representing the entire basin

        """
        # Combine all polygons for basin outline
        try:
            return self.basin_gdf.union_all()
        except AttributeError:
            return self.basin_gdf.unary_union

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Get the bounds of the basin geometry.

        Returns
        -------
        tuple
            (minx, miny, maxx, maxy) for the basin extent

        """
        return self.basin_gdf.total_bounds


class SimCalculator(Calculator):
    """Calculator for simulated data."""

    def __init__(self, basin_gdf: gpd.GeoDataFrame = None, dates: list = None):
        """Initialize the calculator."""
        super().__init__(basin_gdf)
        self.dates = dates

    def extract_data(self, ds: xr.Dataset, date) -> xr.Dataset:
        """Extract values for specified dates from xarray Dataset."""
        ds = ds.rename({val: val.lower() for val in list(ds.data_vars.keys())})
        if not self.check_variable_nc(ds):
            raise ValueError(f"{self.catchment_ids} column names not found")
        if max(self.times) > pd.to_datetime(max(ds.Time.values)):
            raise ValueError(
                f"End date out of range...max: {pd.to_datetime(max(ds.Time.values))}."
            )
        elif min(self.times) < pd.to_datetime(min(ds.Time.values)):
            raise ValueError(
                f"Start date out of range...min: {pd.to_datetime(min(ds.Time.values))}."
            )

        # Use only selected date/times
        mask = ds.Time.isin(self.times)

        return self.convert_units_nc(ds, mask)

    def process_data(self, sim_ds: xr.Dataset, date: str) -> gpd.GeoDataFrame:
        """Process simulated data from NetCDF and geopackage files.

        Args:
            sim_ds: xarray Dataset containing simulated data
            date: str representing the date for data extraction
        """
        basin_gdf = self.basin_gdf.copy()

        catchment_ids = sim_ds.catchments.values
        data = self.extract_data(sim_ds, date)
        # Create a mapping dictionary from catchment IDs to data values
        data_dict = dict(zip(catchment_ids, data.flatten()))

        basin_gdf[self.column] = basin_gdf["divide_id"].map(data_dict).fillna(np.nan)

        return basin_gdf


class ObsCalculator(Calculator, SnotelCalculator):
    """Calculator for Observed data processing."""

    def __init__(
        self, basin_gdf: gpd.GeoDataFrame, ds: xr.Dataset, group_id: str = "divide_id"
    ):
        """Initialize the calculator."""
        super().__init__(basin_gdf)
        self.ds = ds
        self._group_id = group_id

    @property
    @lru_cache
    def group_id(self) -> str:
        """Get the group ID column name."""
        return self._group_id

    @group_id.setter
    def group_id(self, value: str):
        """Set the group ID column name."""
        self._group_id = value

    @property
    @lru_cache
    def _ds_basin_subset(self) -> xr.Dataset:
        """Subset a dataset to the basin extent and prepare for analysis.

        Returns
        -------
        tuple
            (ds_subset, lons, lats) where:
                - ds_subset is the subsetted xarray Dataset

        """
        ds = self.ds.rio.write_crs(self.crs)
        ds = ds.rio.reproject("EPSG:4326")
        ds_subset = ds.rio.clip(self.basin_gdf.geometry, all_touched=True, drop=True)

        ds_subset[self.dataset_name] = self.convert_units(ds_subset)

        ds_subset = ds_subset.rio.write_crs("EPSG:4326")

        return ds_subset

    @property
    def ds_basin_subset(self) -> xr.Dataset:
        """Get the subsetted xarray Dataset for the basin."""
        return self._ds_basin_subset

    @ds_basin_subset.setter
    def ds_basin_subset(self, value: xr.Dataset):
        self._ds_basin_subset = value

    @lru_cache
    def get_lons_lats(self) -> tuple[np.ndarray, np.ndarray]:
        """Get 2D arrays of longitude and latitude values for subsetting."""
        return np.meshgrid(
            self.ds_basin_subset[self.x_dim_name], self.ds_basin_subset[self.y_dim_name]
        )

    @property
    @lru_cache
    def lons(self):
        """Return the longitude values for subsetting."""
        return self.get_lons_lats()[0]

    @property
    @lru_cache
    def lats(self):
        """Return the latitude values for subsetting."""
        return self.get_lons_lats()[1]

    @property
    def long_mask(self):
        """Return the longitude mask for subsetting."""
        return (self.ds[self.y_dim_name] >= self.bounds[0]) & (
            self.ds[self.y_dim_name] <= self.bounds[2]
        )

    @property
    def lat_mask(self):
        """Return the latitude mask for subsetting."""
        return (self.ds[self.x_dim_name] >= self.bounds[1]) & (
            self.ds[self.x_dim_name] <= self.bounds[3]
        )

    @property
    @lru_cache
    def points(self):
        """Convert lat/lon arrays to Shapely Points for spatial operations."""
        return np.array(
            [Point(x, y) for x, y in zip(self.lons.ravel(), self.lats.ravel())]
        )

    @property
    @lru_cache
    def mean_values(self):
        """Calculate mean value for each catchment using area-weighted averaging."""
        return self.fishnet_with_values.groupby(self.group_id).apply(
            lambda x: np.average(x["value"], weights=x["area"])
        )

    @property
    @lru_cache
    def fishnet_overlay(self):
        """Compute Fishnet overlay with basin GeoDataFrame."""
        gdf = gpd.overlay(self.fishnet, self.basin_gdf, how="intersection")
        gdf["area"] = gdf.to_crs(5070).geometry.area
        return gdf

    @property
    @lru_cache
    def fishnet_with_values(self):
        """Compute Fishnet with sampled values."""
        gdf = self.fishnet_overlay.copy()
        gdf["value"] = gdf.apply(self.sample_value, axis=1)
        return gdf

    def sample_value(self, row: pd.Series) -> float:
        """Sample value from dataset at the centroid of a polygon."""
        val = (
            self.ds_basin_subset[self.dataset_name]
            .sel(
                {
                    self.x_dim_name: row.geometry.centroid.x,
                    self.y_dim_name: row.geometry.centroid.y,
                },
                method="nearest",
            )
            .values
        )
        if isinstance(val, float):
            return float(val)
        elif isinstance(val, np.ndarray):
            if val.size == 1:
                try:
                    return float(val[0])
                except IndexError:
                    return float(val)
            else:
                raise ValueError(
                    "Sampled value is an array with more than one element."
                )
        else:
            raise ValueError("Sampled value is not a float or single-element array.")

    @property
    @lru_cache
    def fishnet(self):
        """Compute Fishnet."""
        # create fishnet geodataframe
        mp = MultiPoint(
            [
                (x, y)
                for x in self.ds_basin_subset.x.values
                for y in self.ds_basin_subset.y.values
            ]
        )

        polygons = voronoi_polygons(mp)
        return gpd.GeoDataFrame(
            {"geometry": [Polygon(i) for i in polygons.geoms]},
            crs=self.ds_basin_subset.rio.crs,
            geometry="geometry",
        )

    @property
    @lru_cache
    def calculate_catchment_mean(self):
        """Calculate and return a GeoDataFrame with catchment mean values."""
        with timing_block("Calculating catchment mean values"):
            gdf_with_data = self.basin_gdf.copy()
            gdf_with_data[self.column] = gdf_with_data[self.group_id].map(
                self.mean_values
            )
        return gdf_with_data

    @property
    @lru_cache
    def basin_mask(self) -> np.ndarray:
        """Create a mask for the basin geometry."""
        return np.array(
            [self.basin_geometry.contains(pt) for pt in self.points]
        ).reshape(self.lons.shape)
