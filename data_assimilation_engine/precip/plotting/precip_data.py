"""Precipitation data loader from Ngen output files"""
import logging
from functools import reduce

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
        self.variable_col = "rainrate"

    def check_columns(self, df: pd.DataFrame, file_path: str) -> bool:
        """Check that required columns exist in dataframe"""

        if self.variable_col not in df.columns:
            logger.critical(f"'{self.variable_col}' column not found in {file_path}")
            return False
        return True

    def convert_units(self, df: pd.DataFrame, mask: pd.Series) -> pd.ndarray:
        """Convert precipitation units from m/s to mm/hr"""
        return df.loc[mask, self.variable_col].values * 3600

    def parse_precipitation_data(self, csv_files: list) -> np.ndarray:
        """Extract and sum precipitation values across all catchments"""

        # Load data from all catchments
        data = self.parse_simulated_data(csv_files)

        # Sum precipitation across catchments
        summed_precip = np.sum(data, axis=1)

        logger.info(f"Summed precipitationa across {len(self.catchment_ids)} catchments")
        return summed_precip





        try:
            csv_files = sorted(self.cat_csv_dir.glob("cat*.csv"))
            if not csv_files:
                logger.critical(f"No CSV files found in {self.cat_csv_dir}")
                raise FileNotFoundError(f"No CSV files found in {self.cat_csv_dir}")

            # Load and process each CSV file
            file_list = []
            for ffile in csv_files:
                fdata = pd.read_csv(ffile)

                # Extract time and rainrate
                fdata_copy = fdata[["Time", "rainrate"]].copy()
                fdata_copy["Time"] = pd.to_datetime(fdata_copy["Time"])
                fdata_copy.set_index("Time", inplace=True)
                file_list.append(fdata_copy)

            # Merge all dataframes and sum precipitation
            suffixes = [f"_{id}" for i in range(len(file_list))]
            file_list = [file_list[i].add_suffix(suffixes[i]) for i in range(len(file_list))]

            df_precip = reduce(
                lambda left, right: pd.merge(
                    left, right, left_index=True, right_index=True
                ),
                file_list,
            )

            # Sum rainrate across all catchments and convert from mm/s to mm/hr
            dfp = df_precip.sum(axis=1) * 3600
            dfp.name = "rainrate"
            self.df = dfp.reset_index()

            logger.info(f"Loaded and summed precipitation data from {len(csv_files)} files")
            return self.df
        except Exception as e:
            logger.error(f"Error loading precipitation data: {e}")
            raise
