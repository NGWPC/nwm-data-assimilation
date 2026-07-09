"""Soil Moisture Timeseries."""

import logging
from functools import lru_cache

import numpy as np
import pandas as pd

from data_assimilation_engine.utils.timeseries import (
    DataParser,
    FileLoader,
    Plotter,
    Processor,
    S3Loader,
    get_options,
)
from data_assimilation_engine.utils.utils import time_function
from data_assimilation_engine.utils.s3_paths import SMAP_CSV_PREFIX, SNOTEL_CSV_PREFIX

logger = logging.getLogger(__name__)


def soil_moisture_ts(args_list=None) -> None:
    """Run soil moisture time series processing.

    Args:
    ----
    args_list : list, optional
        List of command line arguments for programmatic execution

    """
    args = get_options(args_list)
    processor = SoilMoistureProcessor(
        csv_directory=args.csv_directory,
        gpkg_file=args.gpkg_file,
        plot_output=args.plot_output,
        csv_output=args.csv_output,
        direct_s3=args.direct_s3,
    )
    processor.process()


class SoilMoistureProcessor(Processor):
    """Main class for processing and visualizing Soil Moisture data."""

    def __init__(
        self,
        csv_directory: str,
        gpkg_file: str,
        plot_output: str = None,
        csv_output: str = None,
        direct_s3: bool = False,
    ):
        """Initialize Soil Moisture processor with input and output parameters.

        Args:
        ----
        csv_directory : str
            Path to directory containing csv files
        gpkg_file : str
            Path to geopackage file with catchment geometries
        plot_output : str, optional
            Path where plot should be saved
        csv_output : str, optional
            Path where csv data should be saved
        direct_s3 : bool, optional
            Whether to use direct S3 access

        """
        super().__init__(csv_directory, gpkg_file, plot_output, csv_output, direct_s3)
        self.variable = "Soil_Moisture"
        self.sim_col_output = "Simulated_Soil_Moisture"
        self.obs_col_output = "SMAP_Soil_Moisture"

        self.lfl = SoilMoistureFileLoader(csv_directory, self.gpkg_file)
        self.s3l = SoilMoistureS3Loader(self.basin_id, self.direct_s3)
        self.parser = SoilMoistureDataParser(self.lfl.times, self.lfl.ids)
        self.plotter = SoilMoisturePlotter()

    @property
    @lru_cache
    @time_function
    def gage_ts(self) -> dict:
        """Dictionary of SNOTEL timeseries data."""
        return {}


class SoilMoisturePlotter(Plotter):
    """Handles visualization of soil moisture data."""

    def __init__(self):
        """Initialize the SoilMoisturePlotter."""
        super().__init__()
        self.variable_name = "Soil Moisture"
        self.variable_units = "m³/m³"
        self.gage_type = "ISMN"
        self.observed_dataset_name = "SMAP"


class SoilMoistureDataParser(DataParser):
    """Parses soil moisture data from various sources."""

    def __init__(self, times: np.ndarray, catchment_ids: np.ndarray):
        """Initialize the DataParser with column names."""
        self.timestamp_col = "timestamp"
        self.basin_avg_col = "basin_avg_soil_moisture"
        self.variable_name = "sm"
        super().__init__(times, catchment_ids)

    def check_columns(self, df: pd.DataFrame, file_path: str):
        """Check that columns exists."""
        columns = [column for column in df.columns if "sm_profile" in column]
        if len(columns) == 0:
            logger.info(f"{self.variable_name} columns not found in {file_path}")
            return False

        self.columns = columns
        return True

    def convert_units(self, df: pd.DataFrame, mask: pd.DataFrame):
        """Convert Units."""
        return np.average(
            df.loc[mask, self.columns].values, axis=1, weights=self.soil_thickness
        )

    @property
    def depths(self):
        """Get depths from column names."""
        depths = []
        for column in self.columns:
            depths.append(
                float(
                    column.replace("sm_profile_", "").replace("_", ".").replace("m", "")
                )
            )
        return depths

    @property
    def soil_thickness(self):
        """Get soil thickness from column names."""
        sorted_depths = sorted(self.depths, reverse=True) + [0]
        soil_thickness = [
            sorted_depths[i] - sorted_depths[i + 1]
            for i in range(len(sorted_depths) - 1)
            if i + 1 < len(sorted_depths + [0])
        ]
        ordered_soil_thickness = []
        for depth in self.depths:
            idx = sorted_depths.index(depth)
            ordered_soil_thickness.append(soil_thickness[idx])
        return ordered_soil_thickness


class SoilMoistureS3Loader(S3Loader):
    """Handles loading and retrieving soil moisture data from S3."""

    def __init__(self, basin_id: str, direct_s3: bool):
        """Initialize the SoilMoistureS3Loader with basin ID and S3 options."""
        super().__init__(basin_id, direct_s3)
        self.variable_name = "soil_moisture"
        # self.gage_prefix = SNOTEL_CSV_PREFIX
        self.obs_prefix = SMAP_CSV_PREFIX


class SoilMoistureFileLoader(FileLoader):
    """Handles loading and retrieving soil moisture files."""

    def __init__(self, csv_directory: str, gpkg_file: str):
        """Initialize the SoilMoistureFileLoader with the directory containing CSV files."""
        super().__init__(csv_directory, gpkg_file)

    @property
    @lru_cache
    @time_function
    def times(self) -> np.ndarray:
        """Create an array of 01:28:55 timestamps given start and end date.

        Returns:
        -------
        numpy.ndarray
            Array of datetime objects for each 3-hour interval

        """
        # Populate with 3-hourly timesteps from within the start and end
        start_hour = 1 + (3 * round((self.start_date.hour - 1) / 3))  # 01, 04, 07, ...
        end_hour = 1 + (3 * round((self.end_date.hour - 1) / 3))

        if end_hour == 25:
            end_hour = 22
        if start_hour == 25:
            start_hour = 22

        times = np.arange(
            np.datetime64(
                f"{self.start_date.strftime('%Y-%m-%d')} {start_hour:02d}:00:00"
            ),
            np.datetime64(f"{self.end_date.strftime('%Y-%m-%d')} {end_hour:02d}:00:00"),
            # + np.timedelta64(1, "D"),
            np.timedelta64(3, "h"),
        ).astype("datetime64[ns]")
        return times


if __name__ == "__main__":
    soil_moisture_ts()
