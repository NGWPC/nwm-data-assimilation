"""Runs the full SWE mapping process."""

import argparse
import logging
from functools import lru_cache

from dotenv import load_dotenv

from utils.utils import timing_block

from ..mapping.simulated_swe_mapper import SimSoilMoistureProcessor, SimSWEProcessor
from ..mapping.snodas_mapper import SNODASProcessor
from ..utility.convert_swe import SoilMoistureConverter, SWEConverter
from ..utility.swe_minmax import reset_minmax

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

    # @property
    # def sim_scan_args(self):
    #     """Get the arguments for simulated_swe_mapper scan."""
    #     sim_scan_args = [
    #         self.args.sim_netcdf,
    #         self.args.gpkg_file,
    #         self.args.date,
    #     ]
    #     if self.args.direct_s3:
    #         sim_scan_args.append("--direct_s3")
    #     return sim_scan_args

    # def run_sim_scan(self) -> None:
    #     """Scan simulated data for vmin/vmax."""
    # self.sim_processor.scan()

    @property
    @lru_cache
    def vmin(self):
        """Get the vmin value from the sim_processor plotter."""
        self.sim_processor.simulated_gdf  # Ensure simulated_gdf is computed
        return self.sim_processor.plotter.vmin

    @property
    @lru_cache
    def vmax(self):
        """Get the vmax value from the sim_processor plotter."""
        self.sim_processor.simulated_gdf  # Ensure simulated_gdf is computed
        return self.sim_processor.plotter.vmax

    @property
    def raw_snodas_args(self):
        """Get the arguments for snodas_mapper raw."""
        raw_snodas_args = [
            self.args.date,
            self.args.gpkg_file,
            self.args.snodas_raw_output,
            self.args.snodas_lumped_output,
        ]
        if self.args.direct_s3:
            raw_snodas_args.append("--direct_s3")
        return raw_snodas_args

    @property
    def sim_swe_mapper_args(self):
        """Get the arguments for simulated_swe_mapper."""
        sim_swe_mapper_args = [
            self.args.sim_netcdf,
            self.args.gpkg_file,
            self.args.date,
            self.args.sim_lumped_output,
        ]
        if self.args.direct_s3:
            sim_swe_mapper_args.append("--direct_s3")
        return sim_swe_mapper_args

    def run_sim_swe_mapper(self) -> None:
        """Generate the simulated SWE map."""
        self.sim_processor.run()

    def execute_mapping(self) -> None:
        """Execute the full SWE mapping process."""
        with timing_block("Full SWE Mapping"):
            with timing_block(self.run_conversion.__name__):
                self.run_conversion()

            with timing_block(self.run_snodas_mapper.__name__):
                self.run_snodas_mapper()

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
        self.sim_processor = SimSWEProcessor(*self.sim_swe_mapper_args)
        self.obs_processor = SNODASProcessor(*self.raw_snodas_args)


class SoilMoistureMapper(Mapper):
    """Soil Moisture Mapper class to handle soil moisture mapping operations."""

    def __init__(self, args):
        """Initialize the SoilMoistureMapper with command line arguments."""
        super().__init__(args)
        self.converter = SoilMoistureConverter(*self.conversion_args)
        self.sim_processor = SimSoilMoistureProcessor(self.sim_scan_args)


def get_options(arg_list=None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("date", type=str, help="Date to use for all plots.")
    parser.add_argument(
        "sim_csv_dir",
        type=str,
        help="Path that contains ngen swe csv files.\
                        This is your ngen output directory.",
    )
    parser.add_argument(
        "sim_netcdf",
        type=str,
        help="Path for simulated swe netcdf file.\
                        convert_csv writes to this file, simulated_swe_mapper\
                        reads from this file.",
    )
    parser.add_argument("gpkg_file", type=str, help="Path to geopackage file.")
    parser.add_argument(
        "sim_lumped_output",
        type=str,
        help="Path where simulated lumped swe map output saved.\
                        Output will be a .png file.",
    )
    parser.add_argument(
        "snodas_raw_output",
        type=str,
        help="Path where snodas raw swe map output saved.\
                        Output will be a .png file.",
    )
    parser.add_argument(
        "snodas_lumped_output",
        type=str,
        help="Path where snodas lumped swe map output saved.\
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


def swe_map(arg_list=None):
    """Map the SWE data."""
    args = get_options(arg_list)
    mapper = SWEMapper(args)
    mapper.execute_mapping()


if __name__ == "__main__":
    swe_map()
