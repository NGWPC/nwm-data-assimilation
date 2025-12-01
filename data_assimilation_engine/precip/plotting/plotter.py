"""Precipitation and streamflow plotting"""

import argparse
import logging
import math
from pathlib import Path
from typing import Optional, Union

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from data_assimilation_engine.precip.plotting.precip_data import PrecipDataParser
from data_assimilation_engine.precip.plotting.streamflow_data import StreamflowDataLoader
from data_assimilation_engine.utils.timeseries import FileLoader, Plotter

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
load_dotenv()


class PrecipPlotter(Plotter):
    """Plotter for precipitation and streamflow time series comparison"""

    def __init__(self):
        """Initialize precipitation plotter"""
        super().__init__()

    def plot_precip_streamflow(
            self,
            times: np.ndarray,
            streamflow: np.ndarray,
            precip: np.ndarray,
            title: Optional[str] = None,
    ) -> tuple:
        fig, ax = plt.subplots(figsize=(12, 6), dpi=120, tight_layout=True)

        # Handle Dataframe with multiple columns
        if isinstance(streamflow, pd.DataFrame):
            colnames = streamflow.columns.tolist()
            colors = ["black", "blue", "orange", "tab:green", "tab:cyan"]
            for i, col in enumerate(colnames):

                # Plot streamflow on primary y-axis
                ax.plot(
                    times,
                    streamflow[col],
                    color=colors[i % len(colors)],
                    linewidth=0.8,
                    label=col,
                )

        ax.set_xlabel("Date", fontsize=15)
        ax.set_ylabel(r"$\mathsf{Streamflow}\ (\mathsf{m^3}/\mathsf{s})$", fontsize=15)
        ax.tick_params(axis="y", labelcolor="black")

        # Calculate precipitation y axis intervals
        maxp = math.ceil(np.nanmax(precip))
        if maxp > 500:
            yint2 = 100
        elif maxp > 200 and maxp <= 500:
            yint2 = 80
        elif maxp > 100 and maxp <= 200:
            yint2 = 50
        elif maxp > 50 and maxp <= 100:
            yint2 = 20
        elif maxp > 10 and maxp <= 50:
            yint2 = 5
        else:
            yint2 = 2
        ytk2 = range(0, 5 * maxp + yint2, yint2)
        label2 = [x if x < maxp + yint2 else "" for x in ytk2]

        for label in ax.get_xticklabels(which="major"):
            label.set(rotation=30, horizontalalignment="right")

        # Create secondary y-axis for precipitation
        ax2 = ax.twinx()
        ax2.plot(
            times,
            precip,
            "purple",
            linewidth=0.8,
            label="Total Precipitation (mm/h)",
        )
        ax2.set_ylabel("Total Precipitation (mm/h)", color="black", fontsize=14)
        ax2.set_ylim(ax2.get_ylim()[::-1])
        ax2.tick_params(axis="y")
        ax2.set_yticks(ytk2)
        ax2.set_yticklabels(label2)

        if title is not None:
            ax.set_title(title, fontsize=14, pad=15)

        ax.grid(True, color="0.8", linewidth=0.4)

        # Combined legend
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax.get_legend_handles_labels()

        seen = set()
        unique_lines = []
        unique_labels = []
        for line, label in zip(lines1 + lines2, labels1 + labels2):
            if label not in seen:
                unique_lines.append(line)
                unique_labels.append(label)
                seen.add(label)

        ax.legend(unique_lines, unique_labels, loc="center left", frameon=False)

        return fig, ax


class PrecipStreamflowProcessor:
    """Main processor for precipitation-streamflow plotting"""

    def __init__(
        self,
        valid_best_file: Union[str, Path],
        valid_control_file: Union[str, Path],
        precip_dir: Union[str, Path],
        output_plot: Union[str, Path],
        title: str
    ):
        self.valid_best_file = Path(valid_best_file)
        self.valid_control_file = Path(valid_control_file)
        self.precip_dir = Path(precip_dir)
        self.output_plot = Path(output_plot)
        self.title = title

        # Initialize data loaders
        self.file_loader = FileLoader(precip_dir, None)
        self.precip_parser = PrecipDataParser(self.file_loader.first_csv_df['time'].values, self.file_loader.ids)
        self.plotter = PrecipPlotter()

    def load_data(self) -> tuple:
        """Load streamflow and precip data"""

        # Load valid_best streamflow
        streamflow_loader_best = StreamflowDataLoader(self.valid_best_file)
        df_best = streamflow_loader_best.load_streamflow()
        df_best = df_best.rename(columns={"sim_flow": "valid_best"})
        df_best.set_index("Time", inplace=True)
        logger.info(f"Loaded valid_best streamflow from {self.valid_best_file}")

        # Load valid_best streamflow
        streamflow_loader_control = StreamflowDataLoader(self.valid_control_file)
        df_control = streamflow_loader_control.load_streamflow()
        df_control = df_control.rename(columns={"sim_flow": "valid_control"})
        df_control.set_index("Time", inplace=True)
        logger.info(f"Loaded valid_best streamflow from {self.valid_control_file}")

        # Merge streamflow dataframes
        streamflow = pd.merge(df_best, df_control, left_index=True, right_index=True, how="outer")

        # Load precip data
        precip = self.precip_parser.parse_precipitation_data(self.file_loader.csv_files)
        times = pd.to_datetime(self.file_loader.first_csv_df['time'].values)

        # Reindex streamflow to precipitation times, filling missing values with NaN
        streamflow = streamflow .reindex(times)
        streamflow.reset_index(inplace=True)
        streamflow.rename(columns={"index": "Time"}, inplace=True)

        return streamflow, precip, times

    def plot(
        self,
        streamflow: np.ndarray,
        precip: np.ndarray,
        times: np.ndarray
    ):
        """Create and save plot"""

        # Create plot
        fig, ax = self.plotter.plot_precip_streamflow(times, streamflow, precip, title=self.title)
        self.plotter.add_grids(ax)
        self.plotter.finalize_plot(fig, str(self.output_plot))

        logger.info(f"Plot saved to: {self.output_plot}")

    def execute(self):
        """Execute plotting workflow"""
        streamflow, precip, times = self.load_data()
        streamflow_cols = streamflow.drop(columns=["Time"] if "Time" in streamflow.columns else [])
        self.plot(streamflow_cols, precip, times)


def get_options(arg_list=None) -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Plot precipitation and streamflow data"
    )
    parser.add_argument(
        "valid_best_file",
        type=str,
        help="Path to valid best streamflow CSV file (columns: Time, sim_flow)",
    )
    parser.add_argument(
        "valid_control_file",
        type=str,
        help="Path to valid control streamflow CSV file (columns: Time, sim_flow)",
    )
    parser.add_argument(
        "precip_dir",
        type=str,
        help="Directory containing cat-*.csv files from ngen output"
    )
    parser.add_argument(
        "output_plot",
        type=str,
        help="Path where output plot will be saved"
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Title for precipitation-streamflow plot"
    )

    if arg_list is None:
        return parser.parse_args()

    try:
        return parser.parse_args(arg_list)
    except Exception as e:
        logger.critical(f"Error parsing arguments: {e}")
        raise


def plot_precip_streamflow(arg_list=None):
    """Main function to plot precipitation and streamflow data"""
    args = get_options(arg_list)
    processor = PrecipStreamflowProcessor(
        valid_best_file=args.valid_best_file,
        valid_control_file=args.valid_control_file,
        precip_dir=args.precip_dir,
        output_plot=args.output_plot,
        title=args.title,
    )
    processor.execute()


if __name__ == "__main__":
    plot_precip_streamflow()
