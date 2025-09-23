"""SNODAS Mapper."""

import argparse
import logging
import os
import warnings
from functools import lru_cache

import fsspec
import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from shapely import MultiPoint, Polygon, voronoi_polygons
from shapely.geometry import Point

from utils.utils import Calculator, DataLoader, Plotter, Processor, timing_block

from ..utility.snotel_utils import SnotelCalculator, SnotelDataLoader, SnotelPlotter
from ..utility.swe_minmax import get_minmax

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", module="geopandas")
warnings.filterwarnings("ignore", module="pandas")


class ObsDataLoader(DataLoader):
    """Data Loader for Observed data."""

    def path_constructor(self, date: str, s3_mount_point: str, direct_s3: bool) -> str:
        """Construct the S3 path to SMAP NetCDF file.

        Parameters
        ----------
        date : str
            Date string in format 'YYYY-MM-DD'
        s3_mount_point : str
            S3 mount point for accessing data
        direct_s3 : bool
            Flag indicating whether to access S3 directly

        Returns
        -------
        str
            S3 path to the NetCDF file

        """
        file_date = date.replace("-", "")

        if not direct_s3:
            netcdf_file = f"{s3_mount_point}/{self.path_str}".replace("date", file_date)
            if os.path.exists(netcdf_file):
                return netcdf_file
            else:
                raise FileNotFoundError(f"File not found in local mount: {netcdf_file}")
        else:
            netcdf_file = f"s3://{self.path_str}".replace("date", file_date)
            fs = fsspec.filesystem("s3")
            if fs.exists(netcdf_file):
                return netcdf_file
            else:
                raise FileNotFoundError(f"File not found in S3: {netcdf_file}")

    def load_obs_netcdf(self, netcdf_file: str) -> xr.Dataset:
        """Load NetCDF data from an S3 path with chunking.

        Parameters
        ----------
        netcdf_file : str
            S3 path to the NetCDF file

        Returns
        -------
        xarray.Dataset
            Loaded xarray Dataset containing the data

        """
        # Open the NetCDF file with chunking to optimize performance and memory usage.
        with timing_block(f"Loading {self.dataset_name} NetCDF"):
            with fsspec.open(netcdf_file, mode="rb") as f:
                return xr.open_dataset(
                    f,
                    chunks={
                        "time": 1,
                        self.x_dim_name: self._chunk_size,
                        self.y_dim_name: self._chunk_size,
                    },
                ).load()


class SWEObsDataLoader(ObsDataLoader, SnotelDataLoader):
    """Data Loader for Observed SWE data."""

    def __init__(self):
        """Initialize the SWEObsDataLoader."""
        self.dataset_name = "Band1"  # Variable name in xarray Dataset
        self.path_str = (
            "ngwpc-forcing/snodas_nc/zz_ssmv11034tS__T0001TTNATSdate05HP001.nc"
        )
        self._chunk_size = 100  # Default chunk size
        self.x_dim_name = "lon"  # X dimension name in xarray Dataset
        self.y_dim_name = "lat"  # Y dimension name in xarray Dataset

    @property
    def chunk_size(self):
        """Return the chunk size used for loading data."""
        return self._chunk_size

    @chunk_size.setter
    def chunk_size(self, value):
        """Set the chunk size used for loading data."""
        self._chunk_size = value


class SoilMoistureObsDataLoader(ObsDataLoader):
    """Data Loader for Observed Soil Moisture data."""

    def __init__(self):
        """Initialize the SoilMoistureObsDataLoader."""
        self.dataset_name = "sm_rootzone"  # Variable name in xarray Dataset
        self.path_str = "ngwpc-forcing/smap_nc/SMAP_L4_SM_gph_dateT013000_Vv8010_001.nc"
        self._chunk_size = 100  # Default chunk size
        self.x_dim_name = "x"  # X dimension name in xarray Dataset
        self.y_dim_name = "y"  # Y dimension name in xarray Dataset

    @property
    def chunk_size(self):
        """Return the chunk size used for loading data."""
        return self._chunk_size

    @chunk_size.setter
    def chunk_size(self, value):
        """Set the chunk size used for loading data."""
        self._chunk_size = value


class ObsCalculator(Calculator, SnotelCalculator):
    """Calculator for Observed data processing."""

    def __init__(self, basin_gdf: gpd.GeoDataFrame, ds: xr.Dataset):
        """Initialize the calculator."""
        super().__init__(basin_gdf)
        self.ds = ds

    @property
    @lru_cache
    def ds_basin_subset(self) -> xr.Dataset:
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

    # @property
    # @lru_cache
    # def mean_values(
    #     self,
    # ) -> list[float]:
    #     """Calculate mean value for each catchment.

    #     Returns
    #     -------
    #     list[float]
    #         List of mean values for each catchment

    #     """
    #     mean_values = []
    #     for _, row in self.basin_gdf.iterrows():
    #         # Mask for each catchment using Shapely `contains`
    #         mask = np.array([row.geometry.contains(pt) for pt in self.points]).reshape(
    #             self.lons.shape
    #         )

    #         # Extract SWE data for catchment and compute mean
    #         catchment_data = self.ds_basin_subset[self.dataset_name].where(mask)
    #         mean_swe = float(catchment_data.mean().compute())
    #         mean_values.append(mean_swe)
    #     return mean_values

    @property
    @lru_cache
    def mean_values(self):
        """Calculate mean value for each catchment using area-weighted averaging."""
        return self.fishnet_with_values.groupby("divide_id").apply(
            lambda x: np.average(x["value"], weights=x["area"])
        )

    @property
    @lru_cache
    def fishnet_with_values(self):
        """Compute Fishnet with sampled values."""
        gdf = gpd.overlay(self.fishnet, self.basin_gdf, how="intersection")
        gdf["area"] = gdf.to_crs(5070).geometry.area
        gdf["value"] = gdf.apply(self.sample_value, axis=1)
        return gdf

    def sample_value(self, row: pd.Series) -> float:
        """Sample value from dataset at the centroid of a polygon."""
        return float(
            self.ds_basin_subset[self.dataset_name].sel(
                {
                    self.x_dim_name: row.geometry.centroid.x,
                    self.y_dim_name: row.geometry.centroid.y,
                },
                method="nearest",
            )
        )

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
            gdf_with_swe = self.basin_gdf.copy()
            gdf_with_swe[self.column] = gdf_with_swe["divide_id"].map(self.mean_values)
        return gdf_with_swe

    @property
    @lru_cache
    def basin_mask(self) -> np.ndarray:
        """Create a mask for the basin geometry."""
        return np.array(
            [self.basin_geometry.contains(pt) for pt in self.points]
        ).reshape(self.lons.shape)

    # @property
    # @lru_cache
    # def ds_to_plot(self) -> xr.Dataset:
    #     """Get the dataset to plot for the specified date."""
    #     # Mask invalid values & apply basin mask
    #     # data = (
    #     #     self.ds_basin_subset[self.dataset_name]
    #     #     .where(self.ds_basin_subset[self.dataset_name] != -9999)
    #     #     .where(self.basin_mask)
    #     # )
    #     # data = data.rio.write_crs(self.crs)
    #     return self.ds_basin_subset[self.dataset_name]


class SWEObsCalculator(ObsCalculator):
    """Calculator for Observed SWE data processing."""

    def __init__(self, basin_gdf: gpd.GeoDataFrame, ds: xr.Dataset):
        """Initialize the calculator."""
        super().__init__(basin_gdf, ds)
        self.column = "mean_swe"  # Column to store computed values in GeoDataFrame
        self.dataset_name = "Band1"  # Variable name in xarray Dataset
        self.x_dim_name = "x"  # X dimension name in xarray Dataset
        self.y_dim_name = "y"  # Y dimension name in xarray Dataset
        self.crs = "EPSG:4326"  # Coordinate Reference System

    def convert_units(self, ds: xr.Dataset) -> xr.Dataset:
        """Convert units of the dataset if necessary."""
        # Default implementation does nothing
        return ds[self.dataset_name] / 1000


class SoilMoistureObsCalculator(ObsCalculator):
    """Calculator for Observed Soil Moisture data processing."""

    def __init__(self, basin_gdf: gpd.GeoDataFrame = None, ds: xr.Dataset = None):
        """Initialize the calculator."""
        super().__init__(basin_gdf, ds)
        self.column = "mean_sm"  # Column to store computed values in GeoDataFrame
        self.dataset_name = "sm_rootzone"  # Variable name in xarray Dataset
        self.x_dim_name = "x"  # X dimension name in xarray Dataset
        self.y_dim_name = "y"  # Y dimension name in xarray Dataset
        self.crs = "EPSG:6933"  # Coordinate Reference System

    def convert_units(self, ds: xr.Dataset) -> xr.Dataset:
        """Convert units of the dataset if necessary."""
        # Default implementation does nothing
        return ds[self.dataset_name]


class ObservedPlotter(Plotter):
    """Plotter for observed data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the plotter with a GeoDataFrame."""
        super().__init__(gdf)

    def plot_raw_data_polygon(
        self, fishnet_with_values: gpd.GeoDataFrame, ds_basin_subset: xr.Dataset
    ):
        """Plot raw data values with the basin boundary."""
        for _, row in fishnet_with_values.iterrows():
            if not np.isnan(row["value"]):
                self.ax.add_geometries(
                    [row.geometry],
                    crs=self.proj,
                    # facecolor="none",
                    facecolor=self.scalar_mappable.to_rgba(row["value"]),
                    edgecolor="none",
                )

    def plot_raw_data_raster(self, ds_basin_subset: xr.Dataset) -> None:
        """Plot raw data values with the basin boundary."""
        # Compute min/max values for colormap scaling
        self.vmin, self.vmax = get_minmax(
            ds_basin_subset.compute(), self.vmin, self.vmax
        )

        scalar_mappable = ds_basin_subset.plot(
            ax=self.ax,
            vmin=self.vmin,
            vmax=self.vmax,
            cmap=self.cmap,
            add_colorbar=False,
        )
        return scalar_mappable


class RawSWEObsPlotter(ObservedPlotter, SnotelPlotter):
    """Class for creating plots of Raw SNODAS SWE data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the RawSWEObsPlotter."""
        super().__init__(gdf)
        self.basin_gdf_with_data = None  # To be set externally
        self.title_str = "Raw SNODAS Snow Water Equivalent\n date - 06z"
        self.column = "mean_swe"
        self.color_bar_label = "Snow Water Equivalent (m)"


class SWEObsPlotter(ObservedPlotter, SnotelPlotter):
    """Class for creating plots of Observed SWE data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the SWEObsPlotter."""
        super().__init__(gdf)
        self.basin_gdf_with_data = None  # To be set externally
        self.column = "mean_swe"  # Column with computed values
        self.color_bar_label = "Snow Water Equivalent (m)"
        self.title_str = "Lumped SNODAS Snow Water Equivalent\n date - 06z"

    def add_snotel_overlay(self, snotel_data: pd.DataFrame):
        """Add SNOTEL SWE data as text overlays on a map.

        Parameters
        ----------
        snotel_data : pandas.DataFrame
            DataFrame with station information and SWE values

        Returns
        -------
        matplotlib.axes.Axes
            Updated axes with SNOTEL overlay

        """
        if snotel_data.empty:
            return self.ax

        color = "#990000"

        if not snotel_data.empty:
            # Plot all stations
            self.ax.plot(
                snotel_data["longitude"],
                snotel_data["latitude"],
                "o",
                markersize=3,
                transform=self.proj,
                color=color,
                label="SNOTEL Stations (SWE)",
            )

            # Add text labels iteratively
            for _, station in snotel_data.iterrows():
                swe_value = f"{station['swe']:.2f}"
                self.ax.text(
                    station["longitude"] + 0.0005,
                    station["latitude"] - 0.0005,
                    swe_value,
                    fontsize=11,
                    ha="left",
                    va="top",
                    transform=self.proj,
                    fontweight="bold",
                    color=color,
                )
            # Add the legend to the plot, using the specified label
            self.ax.legend(
                loc="upper right",
                fontsize=10,
                framealpha=0.5,
                bbox_to_anchor=(1.25, 1.05),
            )


class RawSoilMoistureObsPlotter(ObservedPlotter):
    """Class for creating plots of Raw Soil Moisture data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the RawSoilMoistureObsPlotter."""
        super().__init__(gdf)
        self.title_str = "Raw SMAP Soil Moisture\n date - 06z"
        self.color_bar_label = "Soil Moisture (m³/m³)"


class SoilMoistureObsPlotter(ObservedPlotter):
    """Class for creating plots of Observed Soil Moisture data."""

    def __init__(self, gdf: gpd.GeoDataFrame):
        """Initialize the SoilMoistureObsPlotter."""
        super().__init__(gdf)
        self.basin_gdf_with_data = None  # To be set externally
        self.column = "mean_sm"  # Column with computed values
        self.title_str = "Lumped SMAP Soil Moisture\n date - 06z"
        self.color_bar_label = "Soil Moisture (m³/m³)"


class ObsProcessor(Processor):
    """Processor for Observed data mapping and visualization."""

    def __init__(
        self,
        date=None,
        gpkg_file=None,
        output_file_raw=None,
        output_file_lumped=None,
        direct_s3=False,
    ):
        """Initialize the Observed Processor.

        Args:
        ----
        date : str, optional
            Date string in format 'YYYY-MM-DD'
        gpkg_file : str, optional
            Path to geopackage file with basin/catchment boundaries
        output_file_raw : str, optional
            Path where raw SWE visualization will be saved
        output_file_lumped : str, optional
            Path where catchment-averaged visualization will be saved
        direct_s3 : bool, optional
            Whether to access S3 directly or via mounted filesystem

        """
        super().__init__(gpkg_file=gpkg_file, date=date, direct_s3=direct_s3)

        self.output_file_raw = output_file_raw
        self.output_file_lumped = output_file_lumped

    @property
    @lru_cache
    def obs_file(self) -> str | None:
        """Get the observed data file path."""
        return self.dl.path_constructor(self.date, self.s3_mount_point, self.direct_s3)

    @property
    @lru_cache
    def obs_ds(self) -> xr.Dataset | None:
        """Get the observed dataset."""
        return self.dl.load_obs_netcdf(self.obs_file)

    def run(self, vmin: float, vmax: float) -> None:
        """Run the complete observed data processing pipeline."""
        logging.debug(f"Initial vmin: {vmin}, vmax: {vmax}")
        self.set_vmin_vmax(vmin, vmax)
        self.basin_gdf_with_data
        self.process_raw()
        self.process_lumped()

    def process_raw(self) -> None:
        """Process and plot raw SNODAS data."""
        self.raw_plotter.set_map_extent()

        # scalar_mappable = self.raw_plotter.plot_raw_data_raster(
        #     self.calc.ds_basin_subset[self.calc.dataset_name]
        # )

        self.raw_plotter.plot_raw_data_polygon(
            self.calc.fishnet_with_values,
            self.calc.ds_basin_subset[self.calc.dataset_name],
        )
        self.raw_plotter.plot_catchment_boundaries()
        self.raw_plotter.add_basin_overlay(self.basin_geometry)

        self.raw_plotter.add_colorbar()
        self.raw_plotter.add_gridlines()
        self.raw_plotter.add_title(self.date)
        # self.add_station_data()

        if self.output_file_raw is not None:
            self.raw_plotter.save_figure(self.output_file_raw)

    def set_vmin_vmax(self, vmin: float, vmax: float):
        """Set the global vmin and vmax using current data."""
        self.vmin, self.vmax = self.get_minmax(
            self.calc.fishnet_with_values["value"], vmin, vmax
        )
        self.raw_plotter.vmin = self.vmin
        self.raw_plotter.vmax = self.vmax
        self.lumped_plotter.vmin = self.vmin
        self.lumped_plotter.vmax = self.vmax

    @property
    @lru_cache
    def basin_gdf_with_data(self) -> gpd.GeoDataFrame:
        """Get the basin GeoDataFrame with computed catchment mean values."""
        self.lumped_plotter.basin_gdf_with_data = self.calc.calculate_catchment_mean
        self.raw_plotter.basin_gdf_with_data = self.calc.calculate_catchment_mean
        return self.calc.calculate_catchment_mean

    def process_lumped(self) -> None:
        """Process and plot catchment-averaged data."""
        self.lumped_plotter.plot_choropleth_map()
        self.lumped_plotter.plot_catchment_boundaries()
        self.lumped_plotter.add_basin_overlay(self.basin_geometry)
        self.lumped_plotter.set_map_extent()
        self.lumped_plotter.add_colorbar()
        self.lumped_plotter.add_gridlines()
        self.lumped_plotter.add_title(self.date)
        # self.add_station_data()

        if self.output_file_lumped is not None:
            self.lumped_plotter.save_figure(self.output_file_lumped)


class SWEObsProcessor(ObsProcessor):
    """Processor for Observed SWE data mapping and visualization."""

    def __init__(
        self,
        date=None,
        gpkg_file=None,
        output_file_raw=None,
        output_file_lumped=None,
        direct_s3=False,
    ):
        """Initialize the SWE Observed Processor."""
        super().__init__(
            date, gpkg_file, output_file_raw, output_file_lumped, direct_s3
        )
        self.snotel_s3_path = "ngwpc-forcing/snotel_csv"
        self.column = "mean_swe"

        self.dl = SWEObsDataLoader()
        self.calc = SWEObsCalculator(self.basin_gdf, self.obs_ds)
        self.raw_plotter = RawSWEObsPlotter(self.basin_gdf)
        self.lumped_plotter = SWEObsPlotter(self.basin_gdf)

    @property
    @lru_cache
    def snotel_data(self) -> pd.DataFrame | None:
        """Get the SNOTEL SWE data for stations within the basin."""
        if self.stations_in_basin is not None and not self.stations_in_basin.empty:
            return self.dl.load_snotel_data(
                self.stations_in_basin,
                self.date,
                self.snotel_filesystem,
                self.s3_mount_point,
                self.snotel_s3_path,
            )

    @property
    @lru_cache
    def stations_gdf(self) -> gpd.GeoDataFrame:
        """Get the SNOTEL stations GeoDataFrame."""
        return self.dl.parse_snotel_filenames(self.snotel_filenames)

    @property
    @lru_cache
    def stations_in_basin(self) -> gpd.GeoDataFrame:
        """Get the SNOTEL stations within the basin."""
        return self.calc.find_stations_in_basin(self.stations_gdf, self.basin_geometry)

    def add_station_data(self):
        """Add SNOTEL station data overlay to the plot if available."""
        # Add SNOTEL data overlay if available
        if (
            self.stations_in_basin is not None
            and not self.stations_in_basin.empty
            and self.snotel_data is not None
        ):
            self.raw_plotter.add_snotel_overlay(self.snotel_data)
            self.lumped_plotter.add_snotel_overlay(self.snotel_data)


class SoilMoistureObsProcessor(ObsProcessor):
    """Processor for Observed Soil Moisture data mapping and visualization."""

    def __init__(
        self,
        date: str,
        gpkg_file: str,
        output_file_raw: str,
        output_file_lumped: str,
        direct_s3=False,
    ):
        """Initialize the Soil Moisture Observed Processor."""
        super().__init__(
            date, gpkg_file, output_file_raw, output_file_lumped, direct_s3
        )
        # self.snotel_s3_path = "ngwpc-forcing/snotel_csv"
        self.column = "mean_sm"

        self.dl = SoilMoistureObsDataLoader()
        self.calc = SoilMoistureObsCalculator(self.basin_gdf, self.obs_ds)
        self.raw_plotter = SoilMoistureObsPlotter(self.basin_gdf)
        self.lumped_plotter = SoilMoistureObsPlotter(self.basin_gdf)

    @property
    @lru_cache
    def snotel_data(self) -> pd.DataFrame | None:
        """Get the SNOTEL SWE data for stations within the basin."""
        if self.stations_in_basin is not None and not self.stations_in_basin.empty:
            return self.dl.load_snotel_data(
                self.stations_in_basin,
                self.date,
                self.snotel_filesystem,
                self.s3_mount_point,
                self.snotel_s3_path,
            )

    @property
    @lru_cache
    def stations_gdf(self) -> gpd.GeoDataFrame:
        """Get the SNOTEL stations GeoDataFrame."""
        return self.dl.parse_snotel_filenames(self.snotel_filenames)

    @property
    @lru_cache
    def stations_in_basin(self) -> gpd.GeoDataFrame:
        """Get the SNOTEL stations within the basin."""
        return self.calc.find_stations_in_basin(self.stations_gdf, self.basin_geometry)

    def add_station_data(self):
        """Add SNOTEL station data overlay to the plot if available."""
        # Add SNOTEL data overlay if available
        if (
            self.stations_in_basin is not None
            and not self.stations_in_basin.empty
            and self.snotel_data is not None
        ):
            self.raw_plotter.add_snotel_overlay(self.snotel_data)
            self.lumped_plotter.add_snotel_overlay(self.snotel_data)


def get_options(args_list=None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        args_list : list, optional
        List of arguments to parse (defaults to command line arguments)

    Returns:
    -------
    argparse.Namespace
        Namespace containing the parsed arguments

    """
    parser = argparse.ArgumentParser()
    parser.add_argument("date", type=str, help="Date of SNODAS data to map.")
    parser.add_argument("gpkg_file", type=str, help="Path to geopackage file.")
    parser.add_argument(
        "output_file_raw",
        type=str,
        help="Path where raw visualization output is saved.",
    )
    parser.add_argument(
        "output_file_lumped",
        type=str,
        help="Path where catchment-averaged output is saved.",
    )
    parser.add_argument(
        "--direct_s3",
        action="store_true",
        help="Use direct S3 access instead of local mount",
    )
    args_list = list(args_list)
    return parser.parse_args(args_list)


def main(args_list=None) -> None:
    """Run the SNODAS processor.

    Args:
    ----
    args_list : list, optional
        List of arguments to parse (defaults to command line arguments)

    """
    args = get_options(args_list)

    # Create, then run, a processor instance
    processor = SWEObsProcessor(
        date=args.date,
        gpkg_file=args.gpkg_file,
        output_file_raw=args.output_file_raw,
        output_file_lumped=args.output_file_lumped,
        direct_s3=args.direct_s3,
    )

    processor.run()


if __name__ == "__main__":
    main()
