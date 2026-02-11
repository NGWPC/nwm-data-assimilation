"""Timeseries."""

import argparse
import glob
import logging
import os
import re
import traceback
from functools import lru_cache

import fsspec
import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.dates import DateFormatter, DayLocator

from data_assimilation_engine.utils.dataloaders import DataLoader
from data_assimilation_engine.utils.utils import time_function, timing_block

logger = logging.getLogger(__name__)


class FileLoader(DataLoader):
    """Handles loading and retrieving files."""

    def __init__(
        self, csv_directory_or_netcdf_file: str, gpkg_file: str, netcdf_input: bool
    ):
        """Initialize the FileLoader with the directory containing CSV files."""
        super().__init__(gpkg_file)
        self.csv_directory_or_netcdf_file = csv_directory_or_netcdf_file
        self.netcdf_input = netcdf_input

    @property
    def first_csv_path(self) -> str:
        """Get the path of the first CSV file in the directory."""
        return self.csv_files[0]

    @property
    @lru_cache
    def first_csv_df(self) -> pd.DataFrame:
        """Read the first CSV file to determine date range."""
        df = pd.read_csv(self.first_csv_path)
        df.columns = df.columns.str.lower()
        df["time"] = pd.to_datetime(df["time"])
        return df

    @property
    def start_date(self) -> pd.Timestamp:
        """Get the start date from the first CSV file."""
        if self.netcdf_input:
            return pd.to_datetime(self.sim_ds.Time[0].values)
        else:
            return pd.to_datetime(min(self.first_csv_df["time"]))

    @property
    def end_date(self) -> pd.Timestamp:
        """Get the end date from the first CSV file."""
        if self.netcdf_input:
            return pd.to_datetime(self.sim_ds.Time[-1].values)
        else:
            return pd.to_datetime(max(self.first_csv_df["time"]))

    @property
    @lru_cache
    @time_function
    def csv_files(self) -> list:
        """Create a list of pathnames pointing to ngen csv output files.

        Returns:
        -------
        list
            A list of csv filenames containing simulated datafound in the directory provided

        """
        pattern = os.path.join(self.csv_directory_or_netcdf_file, "cat-*.csv")
        csv_files = glob.glob(pattern)

        if csv_files:
            return csv_files
        else:
            raise Exception(
                f"No csv files found in {self.csv_directory_or_netcdf_file}"
            )

    @property
    @lru_cache
    def ids(self) -> np.ndarray:
        """Extract catchment IDs from filenames.

        Returns:
        -------
        numpy.ndarray
            Array of catchment IDs

        """
        if self.netcdf_input:
            return np.array(
                [cat.replace("cat-", "") for cat in self.sim_ds.catchments.values]
            )
        else:
            # Stop if csv_files is empty
            if not self.csv_files:
                raise ValueError(
                    "No CSV files found in the directory. Processing halted."
                )

            # Same code as convert_swe
            catchment_ids = np.array(
                [
                    int(match.group(1))  # Extract the number safely
                    for f in self.csv_files
                    if (
                        match := re.search(r"cat-(\d+)", os.path.basename(f))
                    )  # Store the match
                ]
            )

            # Stop if csv_files was not empty, but no catchment_ids were parsed
            if len(catchment_ids) == 0:
                raise ValueError(
                    "No valid catchment CSV files found (files must match 'cat-{number}.csv' pattern)."
                )

            return catchment_ids

    @property
    @lru_cache
    def sim_ds(self):
        """Simulated dataset."""
        return xr.open_dataset(self.csv_directory_or_netcdf_file)

    @property
    @lru_cache
    def catchment_gdf(self) -> gpd.GeoDataFrame:
        """Read catchment geometries from geopackage file."""
        if os.path.exists(self.gpkg_file):
            return gpd.read_file(self.gpkg_file, layer="divides")
        else:
            raise FileNotFoundError(f"Geopackage file '{self.gpkg_file}' not found.")

    @property
    @lru_cache
    def catchment_areas(self) -> dict:
        """Read catchment areas from geopackage file.

        Returns:
        -------
        dict
            Mapping of catchment IDs to their areas.

        """
        try:
            # Extract just the catchment numbers from divide_id
            catchment_ids = pd.to_numeric(
                self.catchment_gdf["divide_id"].str.replace("cat-", "", regex=False)
            )

            # Get areas from geometry
            areas = self.catchment_gdf["areasqkm"]

            # Create dictionary with integer keys
            area_dict = dict(zip(catchment_ids, areas))

            return area_dict
        except Exception as e:
            raise ValueError(f"Error reading geopackage file: {e}")


class S3Loader:
    """Handles operations related to S3 storage."""

    def __init__(self, basin_id: str, direct_s3: bool):
        """Initialize the S3Loader with optional S3 client."""
        self.basin_id = basin_id
        self.direct_s3 = direct_s3

    @property
    def s3_mount_point(self) -> str:
        """Get the S3 mount point from environment variable or default path."""
        return os.getenv("S3_MOUNT_POINT", os.path.join(os.path.expanduser("~"), "s3"))

    @property
    @lru_cache
    def obs_path(self) -> tuple[str, str]:
        """Parse/construct observed data s3 path from gpkg filename."""
        # Construct the path using the numeric part and s3 options
        if not self.direct_s3:
            fs = fsspec.filesystem("local")
            s3_path = f"{self.s3_mount_point}/{self.obs_prefix}/gages-{self.basin_id}_{self.variable_name}.csv"
            if fs.exists(s3_path):
                return s3_path
            else:
                raise FileNotFoundError(f"Could not find local csv file: {s3_path}")
        else:
            fs = fsspec.filesystem("s3")
            s3_uri = (
                f"s3://{self.obs_prefix}/gages-{self.basin_id}_{self.variable_name}.csv"
            )
            if fs.exists(s3_uri):
                return s3_uri
            else:
                raise FileNotFoundError(f"Could not find S3 csv file: {s3_uri}")

    @property
    @lru_cache
    @time_function
    def obs_df(self) -> pd.DataFrame:
        """Read a CSV file from an S3 bucket.

        Returns:
        -------
        pandas.DataFrame
            DataFrame containing the CSV data

        """
        try:
            # Use fsspec to open the file
            with fsspec.open(self.obs_path) as f:
                df = pd.read_csv(f)

            return df

        except Exception as e:
            logger.info(f"Error reading S3 file {self.obs_path}: {e}")
            return None


class DataParser:
    """Handles parsing and processing of data."""

    def __init__(self, times: np.ndarray, catchment_ids: np.ndarray):
        """Initialize the DataParser."""
        self.times = times
        self.catchment_ids = catchment_ids

    def parse_obs_dataframe(self, obs_df: pd.DataFrame) -> np.ndarray:
        """Extract observed data values for specified dates.

        Args:
        ----
        obs_df : pandas.DataFrame
            DataFrame containing observed  data

        Returns:
        -------
        numpy.ndarray
            1D numpy array of basin-averaged SWE values corresponding to the provided times

        """
        try:
            # Ensure timestamp column is datetime
            if not pd.api.types.is_datetime64_any_dtype(obs_df[self.timestamp_col]):
                obs_df[self.timestamp_col] = pd.to_datetime(obs_df[self.timestamp_col])

            # Sort data by timestamp to ensure proper time ordering
            obs_df = obs_df.sort_values(self.timestamp_col)

            # Initialize an array for the basin average values
            obs_data = np.full(len(set(self.times)), np.nan)
            obs_df[self.timestamp_col] = pd.to_datetime(
                obs_df[self.timestamp_col].dt.strftime("%Y-%m-%d %H:00:00")
            )
            # Create a mask for the dates we want to extract
            mask = obs_df[self.timestamp_col].isin(self.times)

            if not mask.any():
                logger.info(
                    "Warning: No matching timestamps within date range found in dataframe"
                )
                return obs_data

            # Extract the filtered data
            filtered_df = obs_df[mask].copy()

            # Create a dictionary for quick lookup of SWE values by timestamp
            obs_data_dict = dict(
                zip(filtered_df[self.timestamp_col], filtered_df[self.basin_avg_col])
            )

            # Populate the basin_avg_data array with values from the dictionary
            for i, t in enumerate(self.times):
                if not isinstance(t, pd.Timestamp):
                    t_timestamp = pd.to_datetime(t)
                else:
                    t_timestamp = t
                if t_timestamp in obs_data_dict:
                    obs_data[i] = obs_data_dict[t_timestamp]

            return obs_data

        except Exception as e:
            logger.info(f"Error processing basin average data from dataframe: {e}")
            logger.info(traceback.format_exc())
            return np.full(len(self.times), np.nan)

    def parse_simulated_data_csv(self, csv_files: list) -> np.ndarray:
        """Extract values for specified dates from all catchments.

        Args:
        ----
        csv_files : list
            List of CSV file paths

        Returns:
        -------
        numpy.ndarray
            2D numpy array (time x catchment) of values

        """
        # Initialize data array - 2d (times, ids)
        data = np.full((len(self.times), len(self.catchment_ids)), np.nan)

        critical_error = False

        for idx, file_path in enumerate(csv_files):
            try:
                df = pd.read_csv(file_path)
                # Use lower() to make headers case-independent
                df.columns = df.columns.str.lower()
                if not self.check_columns(df, file_path):
                    raise ValueError(f"{self.catchment_ids} column names not found")

                df["time"] = pd.to_datetime(df["time"])

                # Check date range - these are critical errors we want to exit on
                if max(self.times) > max(df["time"]):
                    raise ValueError(f"End date out of range...max: {max(df['time'])}.")
                elif min(self.times) < min(df["time"]):
                    raise ValueError(
                        f"Start date out of range...min: {min(df['time'])}."
                    )

                # Use only selected date/times
                mask = df["time"].isin(self.times)
                if not mask.any():
                    continue

                data[:, idx] = self.convert_units(df, mask)

            except ValueError as ve:
                # For ValueError, set flag and break loop
                logger.info(f"Critical error with {file_path}: {ve}")
                break

            except Exception as e:
                logger.info(f"Error processing {file_path}: {e}")
                continue

        return data

    def parse_simulated_data_nc(self, ds: xr.Dataset) -> pd.DataFrame:
        """Extract values for specified dates from xarray Dataset."""
        ds = ds.rename({val: val.lower() for val in list(ds.data_vars.keys())})
        if not self.check_variable_nc(ds):
            raise ValueError(f"{self.catchment_ids} column names not found")
        if max(self.times) > max(ds.Time):
            raise ValueError(f"End date out of range...max: {max(ds.Time)}.")
        elif min(self.times) < min(ds.Time):
            raise ValueError(f"Start date out of range...min: {min(ds.Time)}.")

        # Use only selected date/times
        mask = ds.Time.isin(self.times)

        return self.convert_units_nc(ds, mask)


class Analyzer:
    """Analyzes simulated data across catchments."""

    @staticmethod
    def calculate_basin_average(
        data: np.ndarray, catchment_ids: np.ndarray, areas: dict
    ) -> np.ndarray:
        """Calculate area-weighted basin average simulated data.

        Args:
            data (numpy.ndarray): 2D array of simulated values (time x catchment)
            catchment_ids (numpy.ndarray): Array of catchment IDs
            areas (dict): Dictionary mapping catchment IDs to areas

        Returns:
        -------
        numpy.ndarray

        """
        # Convert catchment_ids to integers if they aren't already
        catchment_ids = np.array([int(cid) for cid in catchment_ids])

        try:
            # Create an array of area values for each catchment
            weights = np.array([areas[int(cid)] for cid in catchment_ids])
            try:
                return np.average(data, weights=weights, axis=0)
            except Exception as e:
                return np.average(data, weights=weights, axis=1)

        except KeyError as e:
            logger.info(f"Error: Cannot find area for catchment {e}")
            logger.info(f"Catchment ID type: {type(e.args[0])}")
            logger.info(f"Area dictionary key type: {type(list(areas.keys())[0])}")
            raise


class Plotter:
    """Handles visualization of SWE data."""

    def __init__(
        self,
    ):
        """Initialize the Plotter."""
        pass

    @staticmethod
    def add_grids(ax: matplotlib.axes.Axes):
        """Add grid lines to the plot.

        Args:
        ----
        ax : matplotlib.axes.Axes
            The axes object to add grid lines to

        """
        ax.grid(True, which="major", linestyle="--", alpha=0.8, color="darkgray")
        ax.grid(True, which="minor", linestyle=":", alpha=0.4, color="gray")

    def titles_labels(self, ax: matplotlib.axes.Axes, basin_id: int) -> None:
        """Add title and axis labels.

        Args:
        ----
        ax : matplotlib.axes.Axes
            The axes object to add title and labels to
        basin_id : int
            The ID of the basin being analyzed

        """
        ax.set_title(
            f"Basin Average {self.variable_name} Comparison (Basin {basin_id})",
            fontsize=14,
            pad=15,
        )
        ax.set_xlabel("Date", fontsize=12)
        ax.set_ylabel(f"{self.variable_name} ({self.variable_units})", fontsize=12)

    @staticmethod
    def get_x_intervals(times: np.ndarray) -> tuple:
        """Determine x-axis intervals and labels based on time span.

        Args:
        ----
        times : numpy.ndarray
            Array of datetime objects

        Returns:
        -------
        tuple
            (x_major_interval, x_minor_interval, date_fmt)

        """
        # Calculate date range for dynamic interval
        time_range = np.ptp(times).astype("timedelta64[D]").item().days

        target_major_ticks = 15

        # Calculate major interval and round to whole days
        raw_major_interval = time_range / target_major_ticks
        x_major_interval = max(1, round(raw_major_interval))

        # Set minor interval to half the major interval
        x_minor_interval = max(1, x_major_interval // 2)

        # Determine date format based on the overall time range
        if time_range <= 60:  # Up to 2 months
            date_fmt = "%Y-%m-%d"
        else:
            date_fmt = "%Y-%m"

        return x_major_interval, x_minor_interval, date_fmt

    def calculate_y_lims(
        self,
        simulated_avg: np.ndarray,
        observed_avg: np.ndarray,
        gage_data: dict = None,
    ) -> tuple:
        """Calculate y-axis limits for the plot.

        Args:
        ----
        simulated_avg : numpy.ndarray
            Array of simulated basin averaged values
        observed_avg : numpy.ndarray
            Array of observed basin average values
        gage_data : dict, optional
            Dictionary of station data

        Returns:
        -------
        tuple
            (y_lim_min, y_lim_max, y_range)

        """
        # Calculate y-axis range for dynamic intervals
        if np.isnan(simulated_avg).all():
            sim_y_max, sim_y_min = np.nan, np.nan
        else:
            sim_y_min, sim_y_max = np.nanmin(simulated_avg), np.nanmax(simulated_avg)
        observed_y_min, observed_y_max = (
            np.nanmin(observed_avg),
            np.nanmax(observed_avg),
        )

        y_min = np.nanmin([sim_y_min, observed_y_min])
        y_max = np.nanmax([sim_y_max, observed_y_max])

        # Include gage data in the y-axis range if available
        if gage_data:
            for station_id, data in gage_data.items():
                gage_y_min = np.nanmin(data[self.variable_name.lower()])
                gage_y_max = np.nanmax(data[self.variable_name.lower()])
                y_min = np.nanmin([y_min, gage_y_min])
                y_max = np.nanmax([y_max, gage_y_max])

        y_range = y_max - y_min

        # Add a small buffer to the y-axis limits
        y_buffer = y_range * 0.025
        y_lim_min = np.nanmax([0, y_min - y_buffer])
        y_lim_max = y_max + y_buffer

        return y_lim_min, y_lim_max, y_range

    @staticmethod
    def get_y_intervals(y_range: float) -> tuple:
        """Set y intervals based on the range of values.

        Args:
        ----
        y_range : float
            Range in values between y_min and y_max

        Returns:
        -------
        tuple
            (y_major_interval, y_minor_interval, y_format)

        """
        # Target number of major ticks
        target_major_ticks = 10

        # Calculate the major interval to get 10 ticks
        y_major_interval = y_range / target_major_ticks

        # Find the appropriate magnitude (0.001, 0.01, 0.1, etc.)
        magnitude = 10 ** np.floor(np.log10(y_major_interval))

        if magnitude == 0.001:
            y_format = "%.3f"
        elif magnitude == 0.01:
            y_format = "%.2f"
        elif magnitude == 0.1:
            y_format = "%.1f"
        else:
            y_format = "%.0f"

        # Round to increments of the magnitude to make prettier intervals
        if y_major_interval / magnitude <= 1:
            y_major_interval = magnitude
        elif y_major_interval / magnitude <= 2:
            y_major_interval = 2 * magnitude
        elif y_major_interval / magnitude <= 5:
            y_major_interval = 5 * magnitude
        else:
            y_major_interval = 10 * magnitude

        # Set minor interval to half the major interval
        y_minor_interval = y_major_interval / 2

        return y_major_interval, y_minor_interval, y_format

    @staticmethod
    def customize_x_axis(
        ax: plt.Axes, x_major_interval: int, x_minor_interval: int, date_fmt: str
    ) -> None:
        """Apply x-axis formatting.

        Args:
        ----
        ax : matplotlib.axes.Axes
            The axes object to customize
        x_major_interval : int
            Interval for major tick marks
        x_minor_interval : int
            Interval for minor tick marks
        date_fmt : str
            Date format string for tick labels

        """
        ax.xaxis.set_major_formatter(DateFormatter(date_fmt))
        ax.xaxis.set_minor_locator(DayLocator(interval=x_minor_interval))
        ax.xaxis.set_major_locator(DayLocator(interval=x_major_interval))
        ax.tick_params(rotation=45)

    @staticmethod
    def customize_y_axis(
        ax: plt.Axes,
        y_major_interval: float,
        y_minor_interval: float,
        y_lim_min: float,
        y_lim_max: float,
        y_format: str,
    ) -> None:
        """Apply y-axis formatting.

        Args:
        ----
        ax : matplotlib.axes.Axes
            The axes object to customize
        y_major_interval : float
            Interval for major tick marks
        y_minor_interval : float
            Interval for minor tick marks
        y_lim_min : float
            Lower limit for y-axis
        y_lim_max : float
            Upper limit for y-axis
        y_format : str
            Decimal format for y-axis labels

        """
        ax.yaxis.set_major_formatter(plt.FormatStrFormatter(y_format))
        ax.yaxis.set_major_locator(plt.MultipleLocator(y_major_interval))
        ax.yaxis.set_minor_locator(plt.MultipleLocator(y_minor_interval))
        ax.set_ylim(y_lim_min, y_lim_max)

    def plot_basin_average(
        self,
        times: np.ndarray,
        simulated_avg: np.ndarray,
        observed_avg: np.ndarray,
        gage_ts: dict = None,
    ) -> tuple:
        """Create time series plot of basin-averaged SWE.

        Args:
        ----
        times : numpy.ndarray
            Array of datetime objects
        simulated_avg : numpy.ndarray
            Array of simulated basin-averaged SWE values
        observed_avg : numpy.ndarray
            Array of observed basin-averaged SWE values
        gage_ts : dict, optional
            Dictionary of gage station data

        Returns:
        -------
        tuple
            (fig, ax) - Figure and axis objects

        """
        # Initialize figure and axis
        fig, ax = plt.subplots(figsize=(10, 6))

        # Plot data
        ax.plot(
            times,
            simulated_avg,
            "b.-",
            markersize=5,
            linewidth=1.5,
            label=f"Simulated {self.variable_name}",
        )
        ax.plot(
            times,
            observed_avg,
            "g^-",
            markersize=4,
            linewidth=1.5,
            alpha=0.5,
            label=f"{self.observed_dataset_name} {self.variable_name}",
        )

        # Add gage data if available
        if gage_ts:
            cmap = plt.cm.tab10

            for i, (station_id, data) in enumerate(gage_ts.items()):
                color = cmap(i % 30)
                ax.plot(
                    times,
                    data["swe"],
                    "o-",
                    markersize=3,
                    linewidth=1,
                    alpha=0.7,
                    color=color,
                    label=f"{self.gage_type} {station_id}",
                )

        ax.legend()

        return fig, ax

    @staticmethod
    def finalize_plot(fig: plt.Figure, output_path: str) -> None:
        """Save the plot to file.

        Args:
        ----
        fig : matplotlib.figure.Figure
            The figure object to save
        output_path : str
            Path where the plot should be saved

        """
        # Adjust layout to prevent label cutoff
        fig.tight_layout()
        # Save plot
        fig.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close()


class Processor:
    """Main class for processing and visualizing SWE data."""

    def __init__(
        self,
        csv_directory_or_netcdf_file=None,
        gpkg_file=None,
        plot_output=None,
        csv_output=None,
        direct_s3=False,
    ):
        """Initialize SWE processor with input and output parameters.

        Args:
        ----
        csv_directory_or_netcdf_file : str, optional
            Path to directory containing csv files or a netcdf file
        gpkg_file : str, optional
            Path to geopackage file with catchment geometries
        plot_output : str, optional
            Path where plot should be saved
        csv_output : str, optional
            Path where csv data should be saved
        direct_s3 : bool, optional
            Whether to use direct S3 access

        """
        self.csv_directory_or_netcdf_file = csv_directory_or_netcdf_file  # local
        self.gpkg_file = gpkg_file  # local
        self.plot_output = plot_output
        self.csv_output = csv_output
        self.direct_s3 = direct_s3

        self.analyzer = Analyzer()

    @property
    def netcdf_input(self) -> bool:
        """Determine if the input is a netCDF file based on the path."""
        if os.path.isdir(self.csv_directory_or_netcdf_file):
            return False
        elif os.path.isfile(
            self.csv_directory_or_netcdf_file
        ) and self.csv_directory_or_netcdf_file.endswith(".nc"):
            return True
        else:
            raise ValueError(
                f"Unexpected input path: must be a directory or a .nc file. Received {self.csv_directory_or_netcdf_file}"
            )

    @property
    @lru_cache
    def times(self) -> np.ndarray:
        """Array of timestamps."""
        return self.lfl.times

    @property
    @lru_cache
    def ids(self) -> np.ndarray:
        """Catchment ids."""
        return self.lfl.ids

    @property
    def gpkg_basename(self) -> str:
        """Extract the filename from the geopackage path."""
        return os.path.basename(self.gpkg_file)

    @property
    def gpkg_filename(self) -> str:
        """Extract the filename from the geopackage path."""
        return self.gpkg_basename.split(".")[0]

    @property
    def basin_id(self) -> str:
        """Extract the basin ID from the geopackage filename."""
        # return re.search(r"(\d+)", self.gpkg_filename).group(1)
        return os.path.basename(self.gpkg_file).split(".")[0].split("_")[-1]

    @property
    @lru_cache
    def simulated_data(self) -> np.ndarray:
        """2D array of simulated data (time x catchment)."""
        if self.netcdf_input:
            return self.parser.parse_simulated_data_nc(self.lfl.sim_ds)
        else:
            return self.parser.parse_simulated_data_csv(
                self.lfl.csv_files,
            )

    @property
    @lru_cache
    @time_function
    def obs_avg(self) -> pd.DataFrame:
        """DataFrame of observed basin-averaged data."""
        return self.parser.parse_obs_dataframe(self.s3l.obs_df)

    @property
    @lru_cache
    def areas(self) -> dict:
        """Dictionary of catchment areas."""
        return self.lfl.catchment_areas

    @property
    @lru_cache
    def basin_gdf(self) -> gpd.GeoDataFrame:
        """GeoDataFrame of basin geometry."""
        return self.lfl.basin_gdf

    @property
    @lru_cache
    def basin_geometry(self):
        """Geometry of the basin."""
        return self.basin_gdf.union_all()

    @property
    @lru_cache
    @time_function
    def simulated_avg(self) -> np.ndarray:
        """1D array of area-weighted basin-averaged simulated data."""
        return self.analyzer.calculate_basin_average(
            self.simulated_data, self.ids, self.areas
        )

    @time_function
    def prepare_visualization(self) -> None:
        """Calculate parameters for visualization."""
        (self.y_lim_min, self.y_lim_max, self.y_range) = self.plotter.calculate_y_lims(
            self.simulated_avg, self.obs_avg, self.gage_ts
        )
        (self.x_major_interval, self.x_minor_interval, self.date_fmt) = (
            self.plotter.get_x_intervals(self.times)
        )
        (self.y_major_interval, self.y_minor_interval, self.y_format) = (
            self.plotter.get_y_intervals(self.y_range)
        )

    @time_function
    def create_plot(self) -> None:
        """Create and save the plot."""
        fig, ax = self.plotter.plot_basin_average(
            self.times, self.simulated_avg, self.obs_avg, self.gage_ts
        )
        self.plotter.customize_x_axis(
            ax, self.x_major_interval, self.x_minor_interval, self.date_fmt
        )
        self.plotter.customize_y_axis(
            ax,
            self.y_major_interval,
            self.y_minor_interval,
            self.y_lim_min,
            self.y_lim_max,
            self.y_format,
        )
        self.plotter.add_grids(ax)
        self.plotter.titles_labels(ax, self.basin_id)
        self.plotter.finalize_plot(fig, self.plot_output)
        logger.info(
            f"Basin average {self.variable} data plot saved to {self.plot_output}"
        )

    @property
    def data_dict(self) -> dict:
        """Create a dictionary of the data for saving to CSV."""
        data_dict = {
            "timestamp": self.times,
            self.sim_col_output: self.simulated_avg,
            self.obs_col_output: self.obs_avg,
        }

        # Add gage data if available
        if self.gage_ts:
            for station_id, station_data in self.gage_ts.items():
                data_dict[self.gage_col_output.replace("station_id", station_id)] = (
                    station_data[self.variable.lower()]
                )

        return data_dict

    @time_function
    def save_basin_avg_to_csv(self) -> None:
        """Save basin average varaiable data to csv file."""
        if self.csv_output is None or self.simulated_avg is None or self.times is None:
            return
        try:
            # Create DataFrame and save to CSV
            df = pd.DataFrame(self.data_dict)
            df.to_csv(self.csv_output, index=False)
            logger.info(
                f"Basin average {self.variable} data table saved to {self.csv_output}"
            )
        except Exception as e:
            logger.info(f"Error saving data to CSV: {e}")

    @time_function
    def process(self) -> None:
        """Run the processing pipeline."""
        with timing_block(f"Total {self.variable} Processing Time"):
            # Export data to csv if csv_output is provided
            if self.csv_output:
                self.save_basin_avg_to_csv()

            # Generate visualization if plot_output is provided
            if self.plot_output:
                self.prepare_visualization()
                self.create_plot()


def get_options(args_list=None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
    ----
    args_list : list, optional
        List of command line arguments for programmatic execution

    Returns:
    -------
    argparse.Namespace
        Parsed arguments from command line or list

    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "csv_directory_or_netcdf_file",
        type=str,
        help="Path that contains ngen csv files or a netcdf file.",
    )
    parser.add_argument(
        "gpkg_file",
        type=str,
        help="Path to geopackage file containing catchment geometries.",
    )
    parser.add_argument(
        "--plot_output",
        type=str,
        default=None,
        help="Optional output path for the simulated SWE time series PNG file.",
    )
    parser.add_argument(
        "--csv_output",
        type=str,
        default=None,
        help="Optional output path for the basin average SWE data CSV file.",
    )
    parser.add_argument(
        "--direct_s3",
        action="store_true",
        help="Use direct S3 access incsv_directorystead of local mount",
    )

    if args_list is not None:
        return parser.parse_args(args_list)
    else:
        return parser.parse_args()
