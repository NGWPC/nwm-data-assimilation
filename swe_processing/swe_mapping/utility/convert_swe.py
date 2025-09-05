"""Convert SWE."""

import argparse
import glob
import logging
import os
import re
from datetime import datetime
from functools import lru_cache

import numpy as np
import pandas as pd
import xarray as xr

logger = logging.getLogger(__name__)


class Converter:
    """Base class for converters."""

    def __init__(self, csv_directory: str, dates: list, output_file: str):
        """Initialize the converter with command line arguments."""
        self.directory = csv_directory
        self.dates = dates
        self.output_file = output_file

    @property
    @lru_cache
    def times(self):
        """Get times as datetime objects and add 06z timestamp."""
        return np.array(
            [
                datetime.strptime(f"{date} 06:00:00", "%Y-%m-%d %H:%M:%S")
                for date in self.dates
            ]
        )

    @property
    @lru_cache
    def csv_files(self):
        """Get all CSV files in the specified directory."""
        pattern = os.path.join(self.directory, "cat-*.csv")
        return glob.glob(pattern)

    @property
    @lru_cache
    def catchment_ids(self):
        """Get catchment IDs from filenames."""
        return np.array(
            [
                int(match.group(1))  # Extract the number safely
                for f in self.csv_files
                if (
                    match := re.search(r"cat-(\d+)", os.path.basename(f))
                )  # Store the match
            ]
        )

    def read_values_from_dir(self) -> tuple:
        """Extract 06Z values for specified dates from all catchments.

        Returns:
                - data: 2D numpy array (time x catchment) of swe values

        """
        # Extract catchment IDs from filenames
        if not self.csv_files:
            raise Exception(f"No CSV files found in {self.directory}")

        if self.catchment_ids.size == 0:
            raise Exception(
                f"No valid catchment files found in {self.directory}: {self.csv_files}"
            )

        logger.info(f"catchment_ids: {self.catchment_ids}")

        # Initialize data array - 2d (times, ids)
        data = np.full((len(self.times), len(self.catchment_ids)), np.nan)

        missing_data = False
        # Parse values from each file
        for idx, file_path in enumerate(self.csv_files):
            try:
                df = pd.read_csv(file_path)
                # Use lower() to make case-insensitive
                df.columns = df.columns.str.lower()
                if not self.check_columns(df, file_path):
                    missing_data = True
                    continue

                # Use only selected date/times
                df["time"] = pd.to_datetime(df["time"])
                mask = df["time"].isin(self.times)
                if not mask.any():
                    continue

                # Extract and store values
                data[:, idx] = self.convert_units(df, mask)

            except Exception as e:
                logger.info(f"Error processing {file_path}: {e}")
                continue

        # Check if any files were missing SWE data
        if missing_data:
            raise Exception("One or more files were missing SWE data.")

        return data

    def write_to_netcdf(
        self, catchment_ids: np.ndarray, times: np.ndarray, data: np.ndarray
    ) -> None:
        """Write the extracted values to a NetCDF file with dates as strings."""
        # Use xarray to construct the dataset for writing
        ds = xr.Dataset(
            data_vars={self.variable_name: (["date", "catchment"], data)},
            coords={
                "date": [t.strftime("%Y-%m-%d") for t in times],
                "catchment": catchment_ids,
            },
        )

        # write to netcdf output file
        ds.to_netcdf(self.output_file)


class SWEConverter(Converter):
    """Convert SWE data from CSV to NetCDF format."""

    def __init__(self, csv_directory: str, dates: list, output_file: str):
        """Initialize the SWEConverter."""
        super().__init__(csv_directory, dates, output_file)
        self.variable_name = "swe"
        self.column1 = "swe_m"
        self.column2 = "swe_mm"

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


class SoilMoistureConverter(Converter):
    """Convert soil moisture data from CSV to NetCDF format."""

    def __init__(self, csv_directory: str, dates: list, output_file: str):
        """Initialize the SoilMoistureConverter."""
        super().__init__(csv_directory, dates, output_file)
        self.variable_name = "sm"
        self.column1 = "sm"

    def convert_units(self, df: pd.DataFrame, mask: pd.DataFrame):
        """Convert Units."""
        return df.loc[mask, self.column1].values

    def check_columns(self, df: pd.DataFrame, file_path: str):
        """Check that columns exists."""
        columns = [column for column in df.columns if "sm_profile" in column]
        if len(columns) == 0:
            logger.info(f"{self.variable_name} columns not found in {file_path}")
            return False

        elif len(columns) > 1:
            logger.info(
                f"Too many ({len(columns)}) {self.variable_name} columns found in {file_path}"
            )
            return False
        else:
            return True


def get_options(args_list=None) -> argparse.Namespace:
    """Read and pass in command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "csv_directory", type=str, help="Path that contains csv ngen files."
    )
    parser.add_argument(
        "dates", nargs="+", help="Dates to process ex: '2015-12-01' '2015-12-02'"
    )
    parser.add_argument("output_file", type=str, help="Desired path for output file.")
    return parser.parse_args(args_list)


def main(args_list=None) -> None:
    """Convert data from CSV to NetCDF format."""
    args = get_options(args_list)
    converter = SWEConverter(args)
    data = converter.read_values_from_dir()
    logger.info(f"Converted {len(converter.catchment_ids)} catchments")

    converter.write_to_netcdf(converter.catchment_ids, converter.times, data)


if __name__ == "__main__":
    main()
