#!/usr/bin/env python
# This is python2.7

# James McCreight (jamesmcc -at- ucar -dot- edu)
# Feb 19, 2019

# Script for merging US and Canadian timeslices.

# Usage: 
# jamesmcc@hydro-c1[546]:~/WRF_Hydro/wrf_hydro_nwm_NWIS/merge_timeslices> ./merge_timeslices.py --help
# usage: merge_timeslices.py [-h] --in_file_new IN_FILE_NEW --in_file_copy_addto
#                            IN_FILE_COPY_ADDTO --out_file OUT_FILE
#
# Script merges two timeslice files into a third.The out_file may not exist. The
# in_file_copy_addtois copied to out_file and the in_file_new is appended to
# out_file.
#
# optional arguments:
#   -h, --help            show this help message and exit

# Required, named arguments:
#   --in_file_new IN_FILE_NEW
#                         The first file to be combined.
#   --in_file_copy_addto IN_FILE_COPY_ADDTO
#                         The second file to be combined.
#   --out_file OUT_FILE   The output path/file.

# Examples:
# See test_merge_interactive.py and test_merge.sh in the same directory for more.

# ---------------------------------------------------------------------------

import argparse
import datetime
import netCDF4
import os
import shutil
import sys
import logging


def merge_timeslices(
    in_file_new,
    in_file_copy_addto,
    out_file,
    verbose=False
):

    # Do not overwrite an existing out_file.
    if os.path.exists(out_file):
        raise IOError("The requested output file already exists.")

    # Sanity check the input files
    nc_new = netCDF4.Dataset(in_file_new, "r",)
    nc_copy_addto = netCDF4.Dataset(in_file_copy_addto, "r")

    if nc_new.sliceCenterTimeUTC != nc_copy_addto.sliceCenterTimeUTC:
        raise ValueError(
            "Files do not have matching sliceCenterTimeUTC values. No merge, exiting."
        )
    if nc_new.sliceTimeResolutionMinutes != nc_copy_addto.sliceTimeResolutionMinutes:
        raise ValueError(
            "Files do not have matching sliceTimeResolutionMinutes values. No merge, exiting."
        )

    # Close and copy the file, then open it for appending
    nc_copy_addto.close()
    shutil.copyfile(in_file_copy_addto, out_file)
    nc_append = netCDF4.Dataset(out_file, "r+")
    
    usgs_dim = len(nc_append.dimensions['stationIdInd'])

    # Append data
    for name, variable in nc_append.variables.items():
       if verbose: print(name)
       nc_append.variables[name][usgs_dim:] = nc_new.variables[name][:]

    # Update metadata
    update_time = datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    nc_append.fileUpdateTimeUTC = update_time

    # Close files
    nc_new.close()
    nc_append.close()

    return 0

logging.basicConfig(format=\
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',\
                level=logging.INFO)
logger = logging.getLogger(__name__)
formatter = logging.Formatter(\
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#logger.setFormatter(formatter)
logger.info( "System Path: " + str( sys.path ) )

if __name__=='__main__':
    parser = argparse.ArgumentParser(
        description=(
            'Script merges two timeslice files into a third.'
            'The out_file may not exist. The in_file_copy_addto'
            'is copied to out_file and the in_file_new is appended to out_file.'
        )

    )
    requiredNamed = parser.add_argument_group('Required, named arguments')
    requiredNamed.add_argument(
        '--in_file_new',
        required=True,
        action='store',
        help='The first file to be combined.'
    )
    requiredNamed.add_argument(
        '--in_file_copy_addto',
        required=True,
        action='store',
        help='The second file to be combined.'
    )
    requiredNamed.add_argument(
        '--out_file',
        required=True,
        action='store',
        help='The output path/file.'
    )
    args = parser.parse_args()

    in_file_new = args.in_file_new
    in_file_copy_addto = args.in_file_copy_addto
    out_file = args.out_file

    try:
       result = merge_timeslices(
           in_file_new=in_file_new,
        in_file_copy_addto=in_file_copy_addto,
        out_file=out_file
       )
    except Exception as e:
       logger.error("Failed to merge USGS and Canadian timeslice files: FATAL ERROR:" + str(e), exc_info=True)
       sys.exit(3)

    sys.exit(result)
