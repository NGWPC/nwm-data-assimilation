"""Runs the full SWE mapping process."""

import argparse
import logging

from dotenv import load_dotenv

from utils.utils import timing_block

from ..mapping import simulated_swe_mapper, snodas_mapper
from ..utility.convert_swe import SoilMoistureConverter, SWEConverter
from ..utility.swe_minmax import reset_minmax

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
# Resets global vmin/vmax
reset_minmax()

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
    def sim_scan_args(self):
        """Get the arguments for simulated_swe_mapper scan."""
        sim_scan_args = [
            self.args.sim_netcdf,
            self.args.gpkg_file,
            self.args.date,
            "--mode",
            "scan",
        ]
        if self.args.direct_s3:
            sim_scan_args.append("--direct_s3")
        return sim_scan_args

    def run_sim_scan(self) -> None:
        """Scan simulated SWE data for vmin/vmax."""
        simulated_swe_mapper.main(self.sim_scan_args)

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

    def run_snodas_mapper(self) -> None:
        """Run the SNODAS mapper to generate SWE maps.

        If SNODAS vmin/vmax are higher/lower than ngen swe range, SNODAS vmin and/or vmax values will become global
        """
        snodas_mapper.main(self.raw_snodas_args)

    @property
    def sim_swe_mapper_args(self):
        """Get the arguments for simulated_swe_mapper."""
        sim_swe_mapper_args = [
            self.args.sim_netcdf,
            self.args.gpkg_file,
            self.args.date,
            "--output_file",
            self.args.sim_lumped_output,
        ]
        if self.args.direct_s3:
            sim_swe_mapper_args.append("--direct_s3")
        return sim_swe_mapper_args

    def run_sim_swe_mapper(self) -> None:
        """Generate the simulated SWE map."""
        simulated_swe_mapper.main(self.sim_swe_mapper_args)

    def execute_mapping(self) -> None:
        """Execute the full SWE mapping process."""
        with timing_block("Full SWE Mapping"):
            with timing_block(self.run_conversion.__name__):
                self.run_conversion()

            with timing_block(self.run_sim_scan.__name__):
                self.run_sim_scan()

            with timing_block(self.run_snodas_mapper.__name__):
                self.run_snodas_mapper()

            with timing_block(self.run_sim_swe_mapper.__name__):
                self.run_sim_swe_mapper()


class SWEMapper(Mapper):
    def __init__(self, args):
        super().__init__(args)
        self.converter = SWEConverter(*self.conversion_args)


class SoilMoistureMapper(Mapper):
    def __init__(self, args):
        super().__init__(args)
        self.converter = SoilMoistureConverter(*self.conversion_args)


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
