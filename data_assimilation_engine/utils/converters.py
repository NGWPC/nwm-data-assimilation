"""Base Data Converter."""

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
        # if missing_data:
        #     raise Exception("One or more files were missing simulated data.")

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
        if os.path.exists(self.output_file):
            os.remove(self.output_file)
        ds.to_netcdf(self.output_file, engine="h5netcdf")
