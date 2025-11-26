"""Precipitation and streamflow plotting"""

import argparse
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from data_assimilation_engine.precip.plotting.precip_data import PrecipDataLoader
from data_assimilation_engine.precip.plotting.streamflow_data import StreamflowDataLoader
from data_assimilation_engine.utils.timeseries import FileLoader, Plotter

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
load_dotenv()


class PrecipPlotter(Plotter):
    """Plotter for precipitation and streamflow time series comparison"""

    def __init__(self, gdf=None):
        """Initialize precipitation plotter"""
        super().__init__()
        self.variable_name = "Precipitation & Streamflow"
        self.variable_units = "mm/h & m3/s"

    def plot_precip_streamflow(
            self,
            times: np.ndarray,
            streamflow: np.ndarray,
            precipitation: np.ndarray,
            title: Optional[str] = None,
    ) -> tuple:
        fig, ax = plt.subplots(figsize=(12, 6))

        # Plot streamflow on primary y-axis
        ax.plot(
            times,
            streamflow,
            "b.-",
            markersize=4,
            linewidth=1.5,
            label="Simulated Streamflow (m3/s)",
        )
        ax.set_xlabel("Date", fontsize=12)
        ax.set_ylabel("Streamflow (m3/s)", fontsize=12, color="b")
        ax.tick_params(axis="y", labelcolor="b")

        # Create secondary y-axis for precipitation
        ax2 = ax.twinx()
        ax2.plot(
            times,
            precipitation,
            "r^-",
            markersize=4,
            alpha=0.7,
            label="Precipitation (mm/hr)",
        )
        ax2.set_ylabel("Precipitation (mm/hr)", fontsize=12, color="r")
        ax2.tick_params(axis="y", labelcolor="r")
        ax2.invert_yaxis()

        if title is not None:
            ax.set_title(title, fontsize=14, pad=15)

        # COmbined legend
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, loc="upper_left", frameon=False)

        return fig, ax



