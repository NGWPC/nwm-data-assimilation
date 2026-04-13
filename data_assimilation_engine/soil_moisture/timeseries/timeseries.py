"""Soil Moisture Timeseries."""

import logging
from functools import lru_cache

import numpy as np
import pandas as pd
import fsspec

from data_assimilation_engine.utils.timeseries import (
    DataParser,
    FileLoader,
    Plotter,
    Processor,
    S3Loader,
    get_options,
)
from data_assimilation_engine.utils.utils import time_function

logger = logging.getLogger(__name__)


def soil_moisture_ts(args_list=None) -> None:
    """Run soil moisture time series processing."""
    args = get_options(args_list)
    processor = SoilMoistureProcessor(
        csv_directory=args.csv_directory,
        gpkg_file=args.gpkg_file,
        plot_output=args.plot_output,
        csv_output=args.csv_output,
        direct_s3=args.direct_s3,
    )
    processor.process()


class SoilMoistureProcessor(Processor):
    """Main class for processing and visualizing Soil Moisture data."""

    def __init__(
        self,
        csv_directory: str,
        gpkg_file: str,
        plot_output: str = None,
        csv_output: str = None,
        direct_s3: bool = False,
    ):
        super().__init__(csv_directory, gpkg_file, plot_output, csv_output, direct_s3)
        self.variable = "Soil_Moisture"
        self.sim_col_output = "Simulated_Soil_Moisture"
        self.obs_col_output = "SMAP_Soil_Moisture"
        self.gage_col_output = "ISMN_Soil_Moisture"

        self.lfl = SoilMoistureFileLoader(csv_directory, self.gpkg_file)
        self.s3l = SoilMoistureS3Loader(self.basin_id, self.direct_s3)
        self.parser = SoilMoistureDataParser(self.lfl.times, self.lfl.ids)
        self.plotter = SoilMoisturePlotter()

    @property
    @lru_cache
    @time_function
    def gage_ts(self) -> dict:
        """Dictionary of ISMN basin-average timeseries data.

        Version 1 returns one pseudo-station entry named 'ISMN' backed by the
        basin-level CSV archive.
        """
        gage_df = self.s3l.gage_df
        if gage_df is None or gage_df.empty:
            return {}

        values = self.parser.parse_obs_dataframe(gage_df)
        return {
            "ISMN": {
                "soil_moisture": values
            }
        }


class SoilMoisturePlotter(Plotter):
    """Handles visualization of soil moisture data."""

    def __init__(self):
        super().__init__()
        self.variable_name = "Soil Moisture"
        self.variable_units = "m³/m³"
        self.gage_type = "ISMN"
        self.observed_dataset_name = "SMAP"


class SoilMoistureDataParser(DataParser):
    """Parses soil moisture data from various sources."""

    def __init__(self, times: np.ndarray, catchment_ids: np.ndarray):
        self.timestamp_col = "timestamp"
        self.basin_avg_col = "basin_avg_soil_moisture"
        self.variable_name = "sm"
        super().__init__(times, catchment_ids)

    def check_columns(self, df: pd.DataFrame, file_path: str):
        """Check that sm_profile columns exist."""
        columns = [column for column in df.columns if "sm_profile" in column]
        if len(columns) == 0:
            logger.info("sm columns not found in %s", file_path)
            return False

        self.columns = columns
        return True

    def convert_units(self, df: pd.DataFrame, mask: pd.DataFrame):
        """Return thickness-weighted soil moisture profile average."""
        return np.average(
            df.loc[mask, self.columns].values,
            axis=1,
            weights=self.soil_thickness,
        )

    @property
    def depths(self):
        depths = []
        for column in self.columns:
            depths.append(
                float(
                    column.replace("sm_profile_", "").replace("_", ".").replace("m", "")
                )
            )
        return depths

    @property
    def soil_thickness(self):
        sorted_depths = sorted(self.depths, reverse=True) + [0]
        soil_thickness = [
            sorted_depths[i] - sorted_depths[i + 1]
            for i in range(len(sorted_depths) - 1)
            if i + 1 < len(sorted_depths + [0])
        ]
        ordered_soil_thickness = []
        for depth in self.depths:
            idx = sorted_depths.index(depth)
            ordered_soil_thickness.append(soil_thickness[idx])
        return ordered_soil_thickness


class SoilMoistureS3Loader(S3Loader):
    """Handles loading and retrieving soil moisture data from S3."""

    def __init__(
        self,
        basin_id: str,
        direct_s3: bool,
        obs_prefix: str = "ngwpc-forcing/smap_csv",
        gage_prefix: str = "ngwpc-forcing/ismn_csv",
    ):
        super().__init__(basin_id, direct_s3)
        self.variable_name = "soil_moisture"
        self.obs_prefix = obs_prefix
        self.gage_prefix = gage_prefix

    @property
    @lru_cache
    def gage_path(self) -> str:
        """Construct the basin-level ISMN CSV path."""
        filename = f"gages-{self.basin_id}_{self.variable_name}.csv"
        if not self.direct_s3:
            fs = fsspec.filesystem("local")
            path = f"{self.s3_mount_point}/{self.gage_prefix}/{filename}"
            if fs.exists(path):
                return path
            raise FileNotFoundError(f"Could not find local ISMN csv file: {path}")
        else:
            fs = fsspec.filesystem("s3")
            uri = f"s3://{self.gage_prefix}/{filename}"
            if fs.exists(uri):
                return uri
            raise FileNotFoundError(f"Could not find ISMN S3 csv file: {uri}")

    @property
    @lru_cache
    @time_function
    def gage_df(self) -> pd.DataFrame | None:
        """Read basin-level ISMN CSV."""
        try:
            with fsspec.open(self.gage_path) as f:
                return pd.read_csv(f)
        except Exception as e:
            logger.info("Error reading ISMN file %s: %s", getattr(self, "gage_path", "unknown"), e)
            return None


class SoilMoistureFileLoader(FileLoader):
    """Handles loading and retrieving soil moisture files."""

    def __init__(self, csv_directory: str, gpkg_file: str):
        super().__init__(csv_directory, gpkg_file)

    @property
    @lru_cache
    @time_function
    def times(self) -> np.ndarray:
        """Create 3-hour timestamps on the 01,04,07,... schedule."""
        start_hour = 1 + (3 * round((self.start_date.hour - 1) / 3))
        end_hour = 1 + (3 * round((self.end_date.hour - 1) / 3))

        if end_hour == 25:
            end_hour = 22
        if start_hour == 25:
            start_hour = 22

        times = np.arange(
            np.datetime64(
                f"{self.start_date.strftime('%Y-%m-%d')} {start_hour:02d}:00:00"
            ),
            np.datetime64(
                f"{self.end_date.strftime('%Y-%m-%d')} {end_hour:02d}:00:00"
            ),
            np.timedelta64(3, "h"),
        ).astype("datetime64[ns]")
        return times


if __name__ == "__main__":
    soil_moisture_ts()
