"""Base mapper classes to handle mapping operations."""

import argparse
import logging
import os
from functools import lru_cache

from data_assimilation_engine.utils.utils import timing_block

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class Mapper:
    """Mapper class to handle SWE mapping operations."""

    def __init__(self, args: argparse.Namespace):
        """Initialize the Mapper with command line arguments."""
        self.args = args

    @property
    def netcdf_input(self) -> bool:
        """Determine if the input is a netCDF file based on the path."""
        if os.path.isdir(self.args.sim_csv_dir_or_netcdf_file):
            return False
        elif os.path.isfile(
            self.args.sim_csv_dir_or_netcdf_file
        ) and self.args.sim_csv_dir_or_netcdf_file.endswith(".nc"):
            return True
        else:
            raise ValueError(
                f"Unexpected input path: must be a directory or a .nc file. Received {self.args.sim_csv_dir_or_netcdf_file}"
            )

    @property
    @lru_cache
    def vmin(self):
        """Get the vmin value from the sim_processor plotter."""
        self.sim_processor.basin_gdf_with_data  # Ensure basin_gdf_with_data is computed
        return self.sim_processor.plotter.vmin

    @property
    @lru_cache
    def vmax(self):
        """Get the vmax value from the sim_processor plotter."""
        self.sim_processor.basin_gdf_with_data  # Ensure basin_gdf_with_data is computed
        return self.sim_processor.plotter.vmax

    @property
    def obs_args(self):
        """Get the arguments for observed data processor."""
        obs_args = [
            self.args.date,
            self.args.gpkg_file,
            self.args.raw_output,
            self.args.lumped_output,
        ]
        if self.args.direct_s3:
            obs_args.append("--direct_s3")
        return obs_args

    @property
    def sim_mapper_args(self):
        """Get the arguments for simulated_swe_mapper."""
        sim_mapper_args = [
            self.args.sim_csv_dir_or_netcdf_file,
            self.args.gpkg_file,
            self.args.date,
            self.args.sim_lumped_output,
        ]
        if self.args.direct_s3:
            sim_mapper_args.append("--direct_s3")
        return sim_mapper_args

    def execute_mapping(self) -> None:
        """Execute the full mapping process."""
        with timing_block("Full Mapping"):
            if not self.netcdf_input:
                with timing_block("CSV to NetCDF conversion"):
                    self.sim_processor.netcdf_file = (
                        self.sim_processor.dl.csv_to_netcdf()
                    )
                    self.obs_processor.netcdf_file = self.sim_processor.netcdf_file
            with timing_block("observed data mapping"):
                self.obs_processor.run(self.vmin, self.vmax)

            with timing_block("simulated data mapping"):
                self.sim_processor.vmin = self.obs_processor.vmin
                self.sim_processor.vmax = self.obs_processor.vmax
                self.sim_processor.run()
