"""Simulated Streamflow Loader for precipitation-streamflow plotting"""

import logging
from pathlib import Path

import pandas as pd


logger = logging.getLogger(__name__)


class StreamflowDataLoader:
    """Load and process simulated streamflow"""

    def __init__(self, sim_file: str):
        """Initialize the streamflow data loader"""

        self.sim_file = Path(sim_file)
        self.Q_df = None

    def load_streamflow(self) -> pd.DataFrame:
        """Load streamflow observations from CSV"""
        # This will likely be _output_best_iteration.csv

        try:
            self.Q_df = pd.read_csv(self.sim_file)
            logger.info(f"Loaded streamflow data from {self.sim_file}")

            # Convert time to datetime
            if 'Time' in self.Q_df.columns:
                self.Q_df['Time'] = pd.to_datetime(self.Q_df['Time'])
            else:
                logger.critical("Expected 'Time' column not found in streamflow data")

            # Ensure sim_flow column exists
            if 'sim_flow' not in self.Q_df.columns:
                logger.critical("Expected 'sim_flow' column not in streamflow data")

            return self.Q_df

        except FileNotFoundError:
            logger.critical(f"Streamflow file not found: {self.sim_file}")
        except Exception as e:
            logger.critical(f"Error loading streamflow data: {e}")
            raise
