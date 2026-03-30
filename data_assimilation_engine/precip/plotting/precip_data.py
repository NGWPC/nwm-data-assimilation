"""Precipitation data loader from Ngen output files"""
import logging

import pandas as pd
import numpy as np

from data_assimilation_engine.utils.timeseries import DataParser

logger = logging.getLogger(__name__)


class PrecipDataParser(DataParser):
    """Load and process precipitation output data from cat.csv files"""

    def __init__(self, times: np.ndarray, catchment_ids: np.ndarray):
        """Initialize precipitation data loader"""

        super().__init__(times, catchment_ids)
        self.timestamp_col = 'Time'
        self.variable_col = "rainmelt"

    def check_columns(self, df: pd.DataFrame, file_path: str) -> bool:
        """Check that required columns exist in dataframe"""

        if self.variable_col not in df.columns:
            logger.critical(f"'{self.variable_col}' column not found in {file_path}")
            return False
        return True

    def parse_precipitation_data(self, csv_files: list) -> np.ndarray:
        """Extract and sum precipitation values across all catchments"""

        # Load data from all catchments
        data = self.parse_simulated_data(csv_files)

        # Sum precipitation across catchments, removing last timestep to align with streamflow
        summed_precip = np.mean(data, axis=1)

        logger.info(f"Summed precipitation and melt across {len(self.catchment_ids)} catchments")
        return summed_precip
