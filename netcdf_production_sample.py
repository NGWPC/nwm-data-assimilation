import argparse
import os
from datetime import datetime
import time
from data_assimilation_engine.output_variables.DataReader import DataReader
from data_assimilation_engine.output_variables.DataProcessor import DataProcessor
import data_assimilation_engine.output_variables.utils as utils
import data_assimilation_engine.output_variables.consts as consts

def download_netcdf_from_nomads(output_folder: str, re_download: bool = False):
    #Usage:
    # python netcdf_production_sample.py download-nwm-outputs sample_data
    utils.download_nwm_data_from_server(output_folder, re_download)

def extract_netcdf_metadata(netcdf_root_folder: str):
    #Usage:
    # python netcdf_production_sample.py obtain-netcdf-metadata sample_data/nwm_output metadata
    utils.obtain_metadata_information(netcdf_root_folder)

def combine_basin_products(netcdf_folder: str, output_folder: str, config_json: str, 
                            output_cycle_hr: str, output_cycle_type: str, output_cycle_domain: str):
    #Usage:
    # 
    utils.create_combined_basin_netcdf_products(netcdf_folder, output_folder, config_json, output_cycle_hr, 
                                                output_cycle_type, output_cycle_domain)

def overall_netcdf_workflow(ngen_netcdf_output_file: str, ngen_gpkg_file: str, output_folder: str,
                            troute_output_file: str, troute_lakeout_file: str, 
                            output_cycle_hr: str, output_cycle_type: str, output_cycle_domain: str):

    download = False
    create_config = False
    if download:
        re_download = False
        download_netcdf_from_nomads(output_folder, re_download) # Download unqiue set of NWM data
        print('Downloaded NWM data from NOMADS')
    
    if create_config:
        # Create the config file for the nwm output netcdf files
        extract_netcdf_metadata(output_folder)
        print('Extracted netcdf metadata')

    # Read all metadata from the config file for each NWM output category, class and domain.
    json_file = os.path.join(output_folder, consts.NWM_CONFIG_LOCAL_FOLDER, 
                             consts.NWM_CONFIG_FILE_NAME + consts.NWM_CONFIG_FILE_SUFFIX + ".json")
    netcdf_metadata_list = []
    if os.path.isfile(json_file):
        netcdf_metadata_list = utils.read_output_variables_info_from_config(json_file)
    else:
        raise ValueError("Specified config file does not exist")

    # Begin data processing
    start_time = time.perf_counter()
    gpkg_name, extension = os.path.splitext(os.path.basename(ngen_gpkg_file))
    
    processor = DataProcessor(ngen_netcdf_output_file, ngen_gpkg_file)
    log_file = os.path.join(output_folder, consts.LOG_FOLDER, 'nwm_postprocessing_' + datetime.now().strftime("%Y%m%d_%H%M%S") + '.log')
    processor.log_file  =log_file
    end_time = time.perf_counter()
    duration_minutes = (end_time - start_time) / 60
    print(f"Post-processing started for: {gpkg_name}")
    print(f"--ngen output netcdf read in: {duration_minutes:.2f} minutes")

    start_time = time.perf_counter()
    ngen_template_nc_folder = os.path.join(output_folder, consts.NWM_NGEN_TEMPLATE_FOLDER)
    nwm_output_folder = os.path.join(output_folder, consts.NWM_OUTPUT_FOLDER)
    for mdata in netcdf_metadata_list:
        if mdata.output_cycle == output_cycle_type and mdata.domain == output_cycle_domain:
            if mdata.category.startswith('channel_rt') and troute_output_file is None:
                raise ValueError("T-Route output file is not specified")
            if mdata.category.startswith('reservoir') and troute_lakeout_file is None:
                raise ValueError("T-Route lakeout file is not specified")
            #if mdata.category.startswith('terrain_rt'): # == False:
            processor.nwm_output_class = mdata.output_class
            processor.nwm_category = mdata.category
            processor.nwm_domain = mdata.domain
            processor.create_template_netcdf_using_config(mdata, ngen_template_nc_folder)
            if mdata.category.startswith('channel_rt'):
                processor.set_troute_netcdf(troute_output_file)
            if mdata.category.startswith('reservoir'):
                processor.set_troute_lakeout_netcdf(troute_lakeout_file)
            product_created = processor.produce_nwm_output_product(mdata, nwm_output_folder, output_cycle_hr)
            if not product_created:
                raise ValueError("FATAL: NWM Production creation failed. See log for more details.")

    end_time = time.perf_counter()
    duration_minutes += (end_time - start_time) / 60
    print(f"Overall Post-processing execution time: {duration_minutes:.2f} minutes")

def main() -> None:

    parser = argparse.ArgumentParser(description="NetCDF Data Tool")

    subparsers = parser.add_subparsers(dest="command")

    #download current NWM output netcdfs from nomads server
    parser_nwm_download = subparsers.add_parser("download-nwm-outputs")
    parser_nwm_download.add_argument("output_folder_path")
    parser_nwm_download.add_argument("re_download")

    #Extract metadata info from current NWM output netcdfs that are downloaded 
    parser_nwm_info = subparsers.add_parser("obtain-netcdf-metadata")
    parser_nwm_info.add_argument("local_folder_path")

    #create combined netcdf using timestep netcdfs
    parser_basin_grids = subparsers.add_parser("create-combined-basin-products")
    parser_basin_grids.add_argument("netcdf_folder")
    parser_basin_grids.add_argument("output_basin_grids_folder")
    parser_basin_grids.add_argument("json_config_file")
    parser_basin_grids.add_argument("output_cycle_hr")
    parser_basin_grids.add_argument("output_cycle_type")
    parser_basin_grids.add_argument("output_cycle_domain")
    
    #overall netcdf workflow
    overall_workflow = subparsers.add_parser("test-overall-workflow")
    overall_workflow.add_argument("ngen_netcdf_output_file")
    overall_workflow.add_argument("ngen_gpkg_file")
    overall_workflow.add_argument("output_folder")
    overall_workflow.add_argument("troute_out_file")
    overall_workflow.add_argument("troute_lakeout_file")
    overall_workflow.add_argument("output_cycle_hr")
    overall_workflow.add_argument("output_cycle_type")
    overall_workflow.add_argument("output_cycle_domain")
    args = parser.parse_args()

    if args.command == "download-nwm-outputs":
        download_netcdf_from_nomads(args.download_url, args.output_folder_path)
    elif args.command == "obtain-netcdf-metadata":
        extract_netcdf_metadata(args.local_folder_path)
    elif args.command == "create-combined-basin-products":
        combine_basin_products(args.netcdf_folder, args.output_basin_grids_folder, args.json_config_file,
                            args.output_cycle_hr, args.output_cycle_type, args.output_cycle_domain)
    elif args.command == "test-overall-workflow":
        overall_netcdf_workflow(args.ngen_netcdf_output_file, args.ngen_gpkg_file, args.output_folder, 
                                args.troute_out_file, args.troute_lakeout_file, args.output_cycle_hr,
                                args.output_cycle_type, args.output_cycle_domain)
    else:
        parser.print_help()
    
if __name__ == "__main__":
    main()