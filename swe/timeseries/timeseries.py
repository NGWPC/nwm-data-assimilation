"""SWE Timeseries."""

import logging
from functools import lru_cache

import geopandas as gpd
import numpy as np
import pandas as pd

from swe.snotel import (
    SnotelCalculator,
    SnotelDataLoader,
)
from utils.time_series import (
    DataParser,
    FileLoader,
    Plotter,
    Processor,
    S3Loader,
    get_options,
)
from utils.utils import time_function

logger = logging.getLogger(__name__)


class SWEPlotter(Plotter):
    """Handles visualization of SWE data."""

    def __init__(self):
        """Initialize the SWEPlotter."""
        super().__init__()
        self.variable_name = "SWE"
        self.variable_units = "m"
        self.gage_type = "SNOTEL"
        self.observed_dataset_name = "SNODAS"


class SWEDataParser(DataParser):
    """Parses SWE data from various sources."""

    def __init__(self, times: np.ndarray, catchment_ids: np.ndarray):
        """Initialize the DataParser with column names."""
        self.timestamp_col = "timestamp"
        self.basin_avg_col = "basin_avg_swe"
        self.column1 = "swe_m"
        self.column2 = "swe_mm"
        super().__init__(times, catchment_ids)

    def convert_units(self, df: pd.DataFrame, mask: pd.DataFrame):
        """Convert Units."""
        if self.column1 in df.columns:
            return df.loc[mask, self.column1].values
        elif self.column2 in df.columns:
            return df.loc[mask, self.column2].values / 1000  # Convert mm to meters

    def check_columns(self, df: pd.DataFrame, file_path: str):
        """Check that columns exists."""
        if self.column1 not in df.columns and self.column2 not in df.columns:
            logger.info(f"{self.variable_name} columns not found in {file_path}")
            return False
        else:
            return True


class SWES3Loader(S3Loader):
    """Handles loading and retrieving SWE data from S3."""

    def __init__(self, basin_id: str, direct_s3: bool):
        """Initialize the SWESLoader with basin ID and S3 options."""
        super().__init__(basin_id, direct_s3)
        self.variable_name = "swe"
        self.gage_prefix = "ngwpc-forcing/snotel_csv"
        self.obs_prefix = "ngwpc-forcing/snodas_csv"


class SWEFileLoader(FileLoader):
    """Handles loading and retrieving SWE files."""

    def __init__(self, csv_directory: str, gpkg_file: str):
        """Initialize the SWEFileLoader with the directory containing CSV files."""
        super().__init__(csv_directory, gpkg_file)

    @property
    @lru_cache
    @time_function
    def times(self) -> np.ndarray:
        """Create an array of 06z timestamps given start and end date.

        Returns:
        -------
        numpy.ndarray
            Array of 06z datetime objects for each day

        """
        # Populate with 06z timesteps from within the start and end
        times = np.arange(
            self.start_date, np.datetime64(self.end_date), np.timedelta64(1, "D")
        ).astype("datetime64[ns]")
        times = times + np.timedelta64(6, "h")

        return times


class SWEProcessor(Processor):
    """Main class for processing and visualizing SWE data."""

    def __init__(
        self,
        csv_directory: str,
        gpkg_file: str,
        plot_output: str = None,
        csv_output: str = None,
        direct_s3: bool = False,
    ):
        """Initialize SWE processor with input and output parameters.

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
        self.variable = "SWE"
        self.sim_col_output = "Simulated_SWE"
        self.obs_col_output = "SNODAS_SWE"
        self.gage_col_output = "SNOTEL_station_id_SWE"
        self.lfl = SWEFileLoader(csv_directory, self.gpkg_file)
        self.s3l = SWES3Loader(self.basin_id, self.direct_s3)
        self.parser = SWEDataParser(self.lfl.times, self.lfl.ids)
        self.plotter = SWEPlotter()

        self.gage_dl = SnotelDataLoader()
        self.gage_calc = SnotelCalculator()

    @property
    @lru_cache
    @time_function
    def stations_in_basin(self) -> gpd.GeoDataFrame:
        """GeoDataFrame of stations within the basin."""
        return self.gage_calc.find_stations_in_basin(
            self.stations_gdf, self.basin_geometry
        )

    @property
    @lru_cache
    @time_function
    def gage_df(self) -> pd.DataFrame:
        """DataFrame of SNOTEL gage metadata."""
        return self.gage_dl.get_snotel_timeseries(
            self.lfl.times,
            self.stations_in_basin,
            self.snotel_filesystem,
            self.s3l.s3_mount_point,
            self.s3l.gage_prefix,
        )

    @property
    @lru_cache
    @time_function
    def gage_ts(self) -> dict:
        """Dictionary of SNOTEL timeseries data."""
        return self.gage_dl.extract_snotel_timeseries(self.gage_df, self.lfl.times)

    @property
    @lru_cache
    def snotel_filenames(self) -> list:
        """List of SNOTEL CSV filenames from S3."""
        return self.gage_dl.list_snotel_filenames(
            self.s3l.s3_mount_point, self.s3l.gage_prefix, self.direct_s3
        )

    @property
    @lru_cache
    def snotel_filesystem(self):
        """Filesystem object for accessing SNOTEL data."""
        return self.gage_dl.get_s3_filesystem(self.direct_s3)

    @property
    @lru_cache
    def stations_gdf(self) -> gpd.GeoDataFrame:
        """GeoDataFrame of SNOTEL station locations."""
        return self.gage_dl.parse_snotel_filenames(self.snotel_filenames)


def swe_ts(args_list=None) -> None:
    """Run SWE time series processing.

    Args:
    ----
    args_list : list, optional
        List of command line arguments for programmatic execution

    """
    args = get_options(args_list)
    processor = SWEProcessor(
        csv_directory=args.csv_directory,
        gpkg_file=args.gpkg_file,
        plot_output=args.plot_output,
        csv_output=args.csv_output,
        direct_s3=args.direct_s3,
    )
    processor.process()


if __name__ == "__main__":
    swe_ts()
