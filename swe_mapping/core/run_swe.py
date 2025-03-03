import time

from ..utility.swe_minmax import reset_minmax
from ..mapping import snodas_mapper
from ..mapping import simulated_swe_mapper
from ..utility import convert_swe
import argparse

# Resets global vmin/vmax
reset_minmax()

# Converts ngen csv to netcdf
def run_convert_swe(args):
    convert_swe_args = [
        args.sim_csv_dir,
        args.date,
        args.sim_netcdf
    ]
    start_time = time.time()
    convert_swe.main(convert_swe_args)
    elapsed_time = time.time() - start_time
    print(f"Finished running convert_swe in {elapsed_time:.2f} seconds")

# Gets just vmin/vmax from the simulated SWE
def run_sim_scan(args):
    sim_scan_args = [
        args.sim_netcdf,
        args.gpkg_file,
        args.date,
        '--mode', 'scan'
    ]
    start_time = time.time()
    simulated_swe_mapper.main(sim_scan_args)
    elapsed_time = time.time() - start_time
    print(f"Finished running simulated_swe_mapper in {elapsed_time:.2f} seconds")

# Generates SNODAS SWE map
# if SNODAS vmin/vmax are higher/lower than ngen swe range, 
# SNODAS vmin and/or vmax values will become global
def run_snodas_mapper(args):
    raw_snodas_args = [
        args.date,
        args.gpkg_file,
        args.snodas_raw_output,
        args.snodas_lumped_output
    ]
    start_time = time.time()
    snodas_mapper.main(raw_snodas_args)
    elapsed_time = time.time() - start_time
    print(f"Finished running snodas_mapper in {elapsed_time:.2f} seconds")


# Generates the simulated SWE map
def run_sim_swe_mapper(args):
    sim_swe_mapper_args = [
        args.sim_netcdf,
        args.gpkg_file,
        args.date,
        '--output_file', args.sim_lumped_output
    ]
    start_time = time.time()
    simulated_swe_mapper.main(sim_swe_mapper_args)
    elapsed_time = time.time() - start_time
    print(f"Finished running simulated_swe_mapper in {elapsed_time:.2f} seconds")

def get_options(arg_list=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('date', type=str,
                        help="Date to use for all plots.")
    parser.add_argument('sim_csv_dir', type=str,
                        help="Path that contains ngen swe csv files.\
                        This is your ngen output directory.")
    parser.add_argument('sim_netcdf', type=str,
                        help="Path for simulated swe netcdf file.\
                        convert_csv writes to this file, simulated_swe_mapper\
                        reads from this file.")
    parser.add_argument('gpkg_file', type=str,
                        help="Path to geopackage file.")
    parser.add_argument('sim_lumped_output', type=str,
                        help="Path where simulated lumped swe map output saved.\
                        Output will be a .png file.")
    parser.add_argument('snodas_raw_output', type=str,
                        help="Path where snodas raw swe map output saved.\
                        Output will be a .png file.")
    parser.add_argument('snodas_lumped_output', type=str,
                        help="Path where snodas lumped swe map output saved.\
                        Output will be a .png file.")
    if arg_list is not None:
        return parser.parse_args(arg_list)
    return parser.parse_args()

def execute(args):
    run_convert_swe(args)
    run_sim_scan(args)
    run_snodas_mapper(args)
    run_sim_swe_mapper(args)

def swe_map(arg_list=None):
    args = get_options(arg_list)
    execute(args)

if __name__ == "__main__":
    swe_map()
