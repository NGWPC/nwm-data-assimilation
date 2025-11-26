# """Observed Precipitation Loader"""

# import argparse
# import logging
# from datetime import datetime
# from functools import lru_cache

# import geopandas as gpd
# import matplotlib.pyplot as plt
# import pandas as pd
# import xarray as xr

# from data_assimilation_engine.swe.consts import SWE_END_DATE, SWE_START_DATE
# from data_assimilation_engine.swe.snotel import SnotelDataLoader, SnotelPlotter
# from data_assimilation_engine.utils.calculators import ObsCalculator
# from data_assimilation_engine.utils.dataloaders import ObsDataLoader
# from data_assimilation_engine.utils.plotters import ObservedPlotter
# from data_assimilation_engine.utils.processors import ObsProcessor

# logger = logging.getLogger(__name__)


# class SWEObsDataLoader(ObsDataLoader, SnotelDataLoader):
#     """Data Loader for Observed SWE data."""

#     def __init__(self, gpkg_file: str):
#         """Initialize the SWEObsDataLoader."""
#         self.dataset_name = "Band1"  # Variable name in xarray Dataset
#         self.path_str = (
#             "ngwpc-forcing/snodas_nc/zz_ssmv11034tS__T0001TTNATSdate05HP001.nc"
#         )
#         self._chunk_size = 100  # Default chunk size
#         self.x_dim_name = "lon"  # X dimension name in xarray Dataset
#         self.y_dim_name = "lat"  # Y dimension name in xarray Dataset
#         super().__init__(gpkg_file)

#     def datetime(self, date: str) -> datetime:
#         """Get the datetime object for the specified date."""
#         return datetime.strptime(date, "%Y-%m-%d")

#     @property
#     def chunk_size(self):
#         """Return the chunk size used for loading data."""
#         return self._chunk_size

#     @chunk_size.setter
#     def chunk_size(self, value):
#         """Set the chunk size used for loading data."""
#         self._chunk_size = value

#     @property
#     def obs_start_date(self):
#         """Get the start date of available observations."""
#         return datetime.strptime(SWE_START_DATE, "%Y-%m-%d")

#     @property
#     def obs_end_date(self):
#         """Get the end date of available observations."""
#         return datetime.strptime(SWE_END_DATE, "%Y-%m-%d")


# class SWEObsCalculator(ObsCalculator):
#     """Calculator for Observed SWE data processing."""

#     def __init__(self, basin_gdf: gpd.GeoDataFrame, ds: xr.Dataset):
#         """Initialize the calculator."""
#         super().__init__(basin_gdf, ds)
#         self.column = "mean_swe"  # Column to store computed values in GeoDataFrame
#         self.dataset_name = "Band1"  # Variable name in xarray Dataset
#         self.x_dim_name = "x"  # X dimension name in xarray Dataset
#         self.y_dim_name = "y"  # Y dimension name in xarray Dataset
#         self.crs = "EPSG:4326"  # Coordinate Reference System

#     def convert_units(self, ds: xr.Dataset) -> xr.Dataset:
#         """Convert units of the dataset if necessary."""
#         # Default implementation does nothing
#         return ds[self.dataset_name] / 1000


# class RawSWEObsPlotter(ObservedPlotter, SnotelPlotter):
#     """Class for creating plots of Raw SNODAS SWE data."""

#     def __init__(self, gdf: gpd.GeoDataFrame):
#         """Initialize the RawSWEObsPlotter."""
#         super().__init__(gdf)
#         self.basin_gdf_with_data = None  # To be set externally
#         self.title_str = "Raw SNODAS Snow Water Equivalent\n date - 06z"
#         self.column = "mean_swe"
#         self.color_bar_label = "Snow Water Equivalent (m)"
#         self.cmap = plt.cm.Blues


# class SWEObsPlotter(ObservedPlotter, SnotelPlotter):
#     """Class for creating plots of Observed SWE data."""

#     def __init__(self, gdf: gpd.GeoDataFrame):
#         """Initialize the SWEObsPlotter."""
#         super().__init__(gdf)
#         self.basin_gdf_with_data = None  # To be set externally
#         self.column = "mean_swe"  # Column with computed values
#         self.color_bar_label = "Snow Water Equivalent (m)"
#         self.title_str = "Lumped SNODAS Snow Water Equivalent\n date - 06z"
#         self.cmap = plt.cm.Blues

#     def add_snotel_overlay(self, snotel_data: pd.DataFrame):
#         """Add SNOTEL SWE data as text overlays on a map.

#         Parameters
#         ----------
#         snotel_data : pandas.DataFrame
#             DataFrame with station information and SWE values

#         Returns
#         -------
#         matplotlib.axes.Axes
#             Updated axes with SNOTEL overlay

#         """
#         if snotel_data.empty:
#             return self.ax

#         color = "#990000"

#         if not snotel_data.empty:
#             # Plot all stations
#             self.ax.plot(
#                 snotel_data["longitude"],
#                 snotel_data["latitude"],
#                 "o",
#                 markersize=3,
#                 transform=self.proj,
#                 color=color,
#                 label="SNOTEL Stations (SWE)",
#             )

#             # Add text labels iteratively
#             for _, station in snotel_data.iterrows():
#                 swe_value = f"{station['swe']:.2f}"
#                 self.ax.text(
#                     station["longitude"] + 0.0005,
#                     station["latitude"] - 0.0005,
#                     swe_value,
#                     fontsize=11,
#                     ha="left",
#                     va="top",
#                     transform=self.proj,
#                     fontweight="bold",
#                     color=color,
#                 )
#             # Add the legend to the plot, using the specified label
#             self.ax.legend(
#                 loc="upper right",
#                 fontsize=10,
#                 framealpha=0.5,
#                 bbox_to_anchor=(1.25, 1.05),
#             )


# class SWEObsProcessor(ObsProcessor):
#     """Processor for Observed SWE data mapping and visualization."""

#     def __init__(
#         self,
#         date=None,
#         gpkg_file=None,
#         output_file_raw=None,
#         output_file_lumped=None,
#         direct_s3=False,
#     ):
#         """Initialize the SWE Observed Processor."""
#         self._date = date
#         super().__init__(gpkg_file, output_file_raw, output_file_lumped, direct_s3)
#         self.snotel_s3_path = "ngwpc-forcing/snotel_csv"
#         self.column = "mean_swe"

#         self.dl = SWEObsDataLoader(self.gpkg_file)
#         self.calc = SWEObsCalculator(self.basin_gdf, self.obs_ds)
#         self.raw_plotter = RawSWEObsPlotter(self.basin_gdf)
#         self.lumped_plotter = SWEObsPlotter(self.basin_gdf)

#     @property
#     def date(self) -> str:
#         """Get the date string."""
#         return self._date

#     def check_datetime(self, date: str) -> bool:
#         """Check if the specified date is within available observation range."""
#         try:
#             dt = datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
#         except ValueError:
#             try:
#                 dt = datetime.strptime(date, "%Y-%m-%d")
#             except ValueError:
#                 raise ValueError(
#                     f"time data '{date}' does not match format '%Y-%m-%d %H:%M:%S' nor '%Y-%m-%d'"
#                 )

#         if dt < self.dl.obs_start_date:
#             return False
#         elif dt > self.dl.obs_end_date:
#             return False
#         return True

#     @property
#     @lru_cache
#     def snotel_data(self) -> pd.DataFrame | None:
#         """Get the SNOTEL SWE data for stations within the basin."""
#         if self.stations_in_basin is not None and not self.stations_in_basin.empty:
#             return self.dl.load_snotel_data(
#                 self.stations_in_basin,
#                 self.date,
#                 self.snotel_filesystem,
#                 self.s3_mount_point,
#                 self.snotel_s3_path,
#             )

#     @property
#     @lru_cache
#     def stations_gdf(self) -> gpd.GeoDataFrame:
#         """Get the SNOTEL stations GeoDataFrame."""
#         return self.dl.parse_snotel_filenames(self.snotel_filenames)

#     @property
#     @lru_cache
#     def stations_in_basin(self) -> gpd.GeoDataFrame:
#         """Get the SNOTEL stations within the basin."""
#         return self.calc.find_stations_in_basin(self.stations_gdf, self.basin_geometry)

#     def add_station_data(self):
#         """Add SNOTEL station data overlay to the plot if available."""
#         # Add SNOTEL data overlay if available
#         if (
#             self.stations_in_basin is not None
#             and not self.stations_in_basin.empty
#             and self.snotel_data is not None
#         ):
#             self.raw_plotter.add_snotel_overlay(self.snotel_data)
#             self.lumped_plotter.add_snotel_overlay(self.snotel_data)


# def get_options(args_list=None) -> argparse.Namespace:
#     """Parse command-line arguments.

#     Args:
#         args_list : list, optional
#         List of arguments to parse (defaults to command line arguments)

#     Returns:
#     -------
#     argparse.Namespace
#         Namespace containing the parsed arguments

#     """
#     parser = argparse.ArgumentParser()
#     parser.add_argument("date", type=str, help="Date of SNODAS data to map.")
#     parser.add_argument("gpkg_file", type=str, help="Path to geopackage file.")
#     parser.add_argument(
#         "output_file_raw",
#         type=str,
#         help="Path where raw visualization output is saved.",
#     )
#     parser.add_argument(
#         "output_file_lumped",
#         type=str,
#         help="Path where catchment-averaged output is saved.",
#     )
#     parser.add_argument(
#         "--direct_s3",
#         action="store_true",
#         help="Use direct S3 access instead of local mount",
#     )
#     args_list = list(args_list)
#     return parser.parse_args(args_list)


# def main(args_list=None) -> None:
#     """Run the Observed SWE processor.

#     Args:
#     ----
#     args_list : list, optional
#         List of arguments to parse (defaults to command line arguments)

#     """
#     args = get_options(args_list)

#     # Create, then run, a processor instance
#     processor = SWEObsProcessor(
#         date=args.date,
#         gpkg_file=args.gpkg_file,
#         output_file_raw=args.output_file_raw,
#         output_file_lumped=args.output_file_lumped,
#         direct_s3=args.direct_s3,
#     )

#     processor.run()


# if __name__ == "__main__":
#     main()
