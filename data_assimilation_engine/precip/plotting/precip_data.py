"""Precipitation data loader from Ngen output files"""
import logging

import pandas as pd
import numpy as np
import xarray as xr

from data_assimilation_engine.utils.timeseries import DataParser

logger = logging.getLogger(__name__)


class PrecipDataParser(DataParser):
    """Load and process precipitation output data from cat.csv files"""

    def __init__(self, times: np.ndarray, catchment_ids: np.ndarray):
        """Initialize precipitation data loader"""

        super().__init__(times, catchment_ids)
        self.timestamp_col = 'Time'
        self.variable_col = "rainrate"

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

    def parse_precipitation_data_csv(self, csv_files: list) -> np.ndarray:
        """Extract and sum precipitation values across all catchments"""

        # Load data from all catchments
        data = self.parse_simulated_data_csv(csv_files)

        # Sum precipitation across catchments, removing last timestep to align with streamflow
        summed_precip = np.mean(data, axis=1)

        logger.info(f"Summed precipitation across {len(self.catchment_ids)} catchments")
        return summed_precip

    def parse_precipitation_data_nc(self, ds: xr.Dataset) -> np.ndarray:
        """Extract and sum precipitation values across all catchments"""

        # Load data from netcdf
        data = self.parse_simulated_data_nc(ds)

        # Sum precipitation across catchments, removing last timestep to align with streamflow
        summed_precip = np.mean(data, axis=1)

        logger.info(f"Summed precipitation across {len(self.catchment_ids)} catchments")
        return summed_precip
