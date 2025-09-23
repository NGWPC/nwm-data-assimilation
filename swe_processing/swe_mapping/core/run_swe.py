"""Runs the full SWE mapping process."""

import argparse
import logging
from functools import lru_cache

from dotenv import load_dotenv

from utils.utils import timing_block

from ..mapping.observed_data_mapper import SoilMoistureObsProcessor, SWEObsProcessor
from ..mapping.simulated_data_mapper import SoilMoistureSimProcessor, SWESimProcessor
from ..utility.converters import SoilMoistureConverter, SWEConverter

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()


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


class SWEMapper(Mapper):
    """SWE Mapper class to handle SWE mapping operations."""

    def __init__(self, args):
        """Initialize the SWEMapper with command line arguments."""
        super().__init__(args)
        self.converter = SWEConverter(*self.conversion_args)
        self.sim_processor = SWESimProcessor(*self.sim_mapper_args)
        self.obs_processor = SWEObsProcessor(*self.obs_args)


class SoilMoistureMapper(Mapper):
    """Soil Moisture Mapper class to handle soil moisture mapping operations."""

    def __init__(self, args):
        """Initialize the SoilMoistureMapper with command line arguments."""
        super().__init__(args)
        self.converter = SoilMoistureConverter(*self.conversion_args)
        self.sim_processor = SoilMoistureSimProcessor(*self.sim_mapper_args)
        self.obs_processor = SoilMoistureObsProcessor(*self.obs_args)


def get_options(arg_list=None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("date", type=str, help="Date to use for all plots.")
    parser.add_argument(
        "sim_csv_dir",
        type=str,
        help="Path that contains ngen output csv files.\
                        This is your ngen output directory.",
    )
    parser.add_argument(
        "sim_netcdf",
        type=str,
        help="Path for simulated output netcdf file.\
                        convert_csv writes to this file, simulated_data_mapper\
                        reads from this file.",
    )
    parser.add_argument("gpkg_file", type=str, help="Path to geopackage file.")
    parser.add_argument(
        "sim_lumped_output",
        type=str,
        help="Path where simulated lumped data map output saved.\
                        Output will be a .png file.",
    )
    parser.add_argument(
        "raw_output",
        type=str,
        help="Path where raw data map output saved.\
                        Output will be a .png file.",
    )
    parser.add_argument(
        "lumped_output",
        type=str,
        help="Path where lumped data map output saved.\
                        Output will be a .png file.",
    )
    parser.add_argument(
        "--direct_s3",
        action="store_true",
        help="Use direct S3 access instead of local mount",
        default=False,
    )

    if arg_list is None:
        return parser.parse_args()

    try:
        return parser.parse_args(arg_list)
    except Exception as e:
        logger.info(f"Error parsing arguments: {e}")
        logger.info(f"Argument list: {arg_list}")
        raise


def map_swe_data(arg_list=None):
    """Map the SWE data."""
    args = get_options(arg_list)
    mapper = SWEMapper(args)
    mapper.execute_mapping()


def map_soil_moisture_data(arg_list=None):
    """Map the soil moisture data."""
    args = get_options(arg_list)
    mapper = SoilMoistureMapper(args)
    mapper.execute_mapping()


if __name__ == "__main__":
    # map_swe_data()
    map_soil_moisture_data()
