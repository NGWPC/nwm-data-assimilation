"""Runs the full soil moisture mapping process."""

import argparse
import logging

from ..mapping.mapper import SoilMoistureMapper

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


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


def map_soil_moisture_data(arg_list=None):
    """Map the soil moisture data."""
    args = get_options(arg_list)
    mapper = SoilMoistureMapper(args)
    mapper.execute_mapping()


if __name__ == "__main__":
    map_soil_moisture_data()
