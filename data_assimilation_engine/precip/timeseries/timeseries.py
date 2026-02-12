""""Precip Timeseries."""
import logging
from functools import lru_cache
from pathlib import Path
import argparse
import pandas as pd
import numpy as np
import xarray as xr

from data_assimilation_engine.utils.timeseries import (
    DataParser,
    FileLoader
)
from data_assimilation_engine.utils.utils import time_function

logger = logging.getLogger(__name__)


class PrecipDataParser(DataParser):
    """Load and process precipitation output data from cat.csv files"""

    def __init__(self, times: np.ndarray, catchment_ids: np.ndarray):
        """Initialize precipitation data loader"""

        self.timestamp_col = 'Time'
        self.variable_col = "rainrate"
        super().__init__(times, catchment_ids)

    def check_columns(self, df: pd.DataFrame, file_path: str) -> bool:
        """Check that required columns exist in dataframe"""

        if self.variable_col not in df.columns:
            logger.critical(f"'{self.variable_col}' column not found in {file_path}")
            return False
        return True

    def check_variable_nc(self, ds: xr.Dataset) -> bool:
        """Check that variable exists in netcdf dataset"""
        if self.variable_col not in ds.data_vars.keys():
            logger.info(f"'{self.variable_col}' variable not found in dataset")
            return False
        return True

    def convert_units(self, df: pd.DataFrame, mask: pd.Series) -> np.ndarray:
        """Convert precipitation units from m/s to mm/hr"""
        return df.loc[mask, self.variable_col].values * 3600

    def convert_units_nc(self, df: pd.DataFrame, mask: pd.Series) -> np.ndarray:
        """Convert precipitation units from m/s to mm/hr for netcdf"""
        return df[self.variable_col].where(mask, drop=True).values * 3600


class PrecipFileLoader(FileLoader):
    """"Handles loading and retrieving precipitation output files"""
    def __init__(self, csv_directory_or_netcdf_file: str, netcdf_input: bool):
        """Initialize the SWEFileLoader with the directory containing CSV or netcdf files."""
        super().__init__(csv_directory_or_netcdf_file, gpkg_file=None, netcdf_input=netcdf_input)

    @property
    @lru_cache
    @time_function
    def times(self) -> np.ndarray:
        """Create an array of timestamps from the first CSV file or netcdf"""
        if self.netcdf_input:
            return self.sim_ds['Time'].values
        else:
            times = pd.to_datetime(self.first_csv_df['time']).values
            return times


class PrecipProcessor:
    """Main class for processing and saving precipitation data"""

    def __init__(
        self,
        csv_directory_or_netcdf_file: str,
        csv_output: str,
    ):
        """Initialize precipitation processor

        Args:
        ----
        csv_directory_or_netcdf_file : str
            Path to directory containing csv files or a netcdf file
        csv_output : str
            Path where csv data should be saved
        netcdf_input: bool
            Whether input is a netcdf file
        """
        self.csv_directory_or_netcdf_file = csv_directory_or_netcdf_file
        self.csv_output = Path(csv_output)

        input_path = Path(self.csv_directory_or_netcdf_file)
        self.netcdf_input = input_path.is_file() and input_path.suffix == '.nc'

        self.lfl = PrecipFileLoader(csv_directory_or_netcdf_file, self.netcdf_input)
        self.parser = PrecipDataParser(self.lfl.times, self.lfl.ids)

    @property
    @lru_cache
    @time_function
    def basin_avg_precip(self) -> np.ndarray:
        """Array of basin averaged precipitation"""
        if self.netcdf_input:
            precip = self.parser.parse_simulated_data_nc(self.lfl.sim_ds)
        else:
            precip = self.parser.parse_simulated_data_csv(self.lfl.csv_files)
        avg = np.nanmean(precip, axis=1)
        logger.info(f"Computed basin-averaged precipitation from {len(self.lfl.ids)} catchments")
        return avg

    @time_function
    def save_to_csv(self) -> None:
        """Save basin-averaged precipitation to CSV file"""
        try:
            df = pd.DataFrame({'timestamp': self.lfl.times, 'precip_mm_hr': self.basin_avg_precip})
            df.to_csv(self.csv_output, index=False)
            logger.info(f"Precipitation timeseries saved to {self.csv_output}")
        except Exception as e:
            logger.error(f"Error saving precipitation timeseries to CSV: {e}")
            raise

    def process(self) -> None:
        """Run precip timeseries processes"""
        self.save_to_csv()


def precip_ts(args_list=None):
    """
    Args:
    ----
    args_list : list, optional
        List of command line arguments for programmatic execution

    """
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_directory_or_netcdf_file", type=str, help="Path to directory containing csv files or netcdf_file")
    parser.add_argument("csv_output", type=str, help="Path output csv file")
    args = parser.parse_args(args_list)

    processor = PrecipProcessor(
        csv_directory_or_netcdf_file=args.csv_directory_or_netcdf_file,
        csv_output=args.csv_output,
    )
    processor.process()


if __name__ == "__main__":
    precip_ts()
