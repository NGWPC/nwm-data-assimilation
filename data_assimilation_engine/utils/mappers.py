"""Base mapper classes to handle mapping operations."""

import argparse
import logging
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
    def conversion_args(self):
        """Get the arguments for to convert csv to netcdf."""
        date = self.args.date
        if isinstance(date, str):
            date = [date]
        return [self.args.sim_csv_dir, date, self.args.sim_netcdf]

    def run_conversion(self) -> None:
        """Convert_swe to convert ngen swe csv files to a single netcdf file."""
        data = self.converter.read_values_from_dir()
        logger.info(f"Converted {len(self.converter.catchment_ids)} catchments")
        self.converter.write_to_netcdf(
            self.converter.catchment_ids, self.converter.times, data
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
            self.args.sim_netcdf,
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
            with timing_block(self.run_conversion.__name__):
                self.run_conversion()

            with timing_block("observed data mapping"):
                self.obs_processor.run(self.vmin, self.vmax)

            with timing_block("simulated data mapping"):
                self.sim_processor.vmin = self.obs_processor.vmin
                self.sim_processor.vmax = self.obs_processor.vmax
                self.sim_processor.run()
