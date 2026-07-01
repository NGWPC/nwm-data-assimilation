import argparse
import os
from datetime import datetime
from data_assimilation_engine.output_variables.DataReader import DataReader
from data_assimilation_engine.output_variables.DataProcessor import DataProcessor
import data_assimilation_engine.output_variables.utils as utils
import data_assimilation_engine.output_variables.consts as consts

def randomize_values(netcdf_file: str, output_file: str) -> None:
    #Usage:
    # python netcdf_production_sample.py randomize sample_data/sample_netcdf/catchment_output_CNF.nc sample_data/sample_netcdf/catchment_randomvals_cnf.nc

    reader = DataReader(netcdf_file)
    reader.assign_random_values(output_file)

def create_template_grid_for_gpkg(netcdf_file: str, gpkg_file: str, template_grid_file: str):
    #Usage
    # python netcdf_production_sample.py create-template-grid sample_data/sample_netcdf/final_test/catchment_randomvals.nc sample_data/sample_gpkg/gages-01123000.gpkg sample_data/sample_netcdf/final_test/new_grid_template.nc sample_data/nwm_output/metadata_config.json
    #processor = DataProcessor(netcdf_file, gpkg_file, config_json_file, 'analysis_assim', 'land', 'conus')
    processor = DataProcessor(netcdf_file, gpkg_file)
    processor.create_template_grid_netcdf_using_config(template_grid_file)

def create_nwm_grid(netcdf_file: str, gpkg_file: str, template_grid_file: str, config_json_file: str):
    #Usage:
    # python netcdf_production_sample.py create-nwm-grid sample_data/sample_netcdf/final_test/catchment_randomvals.nc sample_data/sample_gpkg/gages-01123000.gpkg sample_data/sample_netcdf/final_test/new_grid_template.nc sample_data/nwm_output/metadata_config.json
    processor = DataProcessor(netcdf_file, gpkg_file, config_json_file, 'analysis_assim', 'land', 'conus')
    processor.set_template_grid(template_grid_file)
    output_dir = 'sample_data/sample_netcdf/sample_output/new_test'
    processor.produce_nwm_output_grid(output_dir)

def download_netcdf_from_nomads(output_folder: str, re_download: bool = False):
    #Usage:
    # python netcdf_production_sample.py download-nwm-outputs sample_data
    utils.download_nwm_data_from_server(output_folder, re_download)

def extract_netcdf_metadata(netcdf_root_folder: str):
    #Usage:
    # python netcdf_production_sample.py obtain-netcdf-metadata sample_data/nwm_output metadata
    utils.obtain_metadata_information(netcdf_root_folder)
    #utils.debug_netcdf_structure_in_folder(netcdf_root_folder)

def create_template_nwm_grids_data(netcdf_root_folder: str, templates_folder: str):
    #Usage:
    # python netcdf_production_sample.py create-template-nwm-grid sample_data/nwm_output sample_data/nwm_templates
    utils.create_nwm_template_grids(netcdf_root_folder, templates_folder)

def combine_basin_grids(reference_grid: str, netcdf_folder: str, output_folder: str):
    #Usage:
    # python netcdf_production_sample.py create-combined-basin-grid sample_data/nwm_output/analysis_assim/nwm.t00z.analysis_assim.land.tm00.conus.nc sample_data/sample_netcdf/sample_output/merge_test sample_data/sample_netcdf/sample_output/merge_test
    utils.create_combined_basin_netcdf_products(reference_grid, netcdf_folder, output_folder)

def overall_netcdf_workflow(ngen_netcdf_output_file: str, ngen_gpkg_file: str, output_folder: str):
    #Usage
    # python netcdf_production_sample.py test-overall-workflow sample_data/outputs_0629/ngen_outputs/catchment_output_sr_01123000.nc sample_data/sample_gpkg/gauge_01123000.gpkg sample_data/outputs_0629
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
    print('Read output variables info from config')

    # Begin data processing
    # reader = DataReader(ngen_netcdf_output_file)
    # randomized_nc_name = 'ngen_randomvals_' + datetime.now().strftime("%Y%m%d_%H%M%S") + '.nc'
    # ngen_netcdf_output_file = os.path.join(output_folder, randomized_nc_name)
    # reader.add_missing_variables(ngen_netcdf_output_file)
    # reader.assign_random_values(ngen_netcdf_output_file)

    processor = DataProcessor(ngen_netcdf_output_file, ngen_gpkg_file)
    ngen_template_nc_folder = os.path.join(output_folder, consts.NWM_NGEN_TEMPLATE_FOLDER)
    nwm_output_folder = os.path.join(output_folder, consts.NWM_OUTPUT_FOLDER)
    for mdata in netcdf_metadata_list:
        print(f"Ready to process: {mdata.output_class}, {mdata.category}, {mdata.domain}")
        if any(cat.lower() in mdata.category.lower() for cat in ['channel_rt', 'reservoir', 'total_water']):
            print(f"The requested category - {mdata.category} - is not a gridded netcdf. The functionality is not implemented yet")
            continue
        processor.create_template_grid_netcdf_using_config(mdata, ngen_template_nc_folder)
        processor.produce_nwm_output_grid(mdata, nwm_output_folder)

def main() -> None:

    parser = argparse.ArgumentParser(description="NetCDF Data Tool")

    subparsers = parser.add_subparsers(dest="command")

    #random values
    parser_randomize = subparsers.add_parser("randomize")
    parser_randomize.add_argument("input_file")
    parser_randomize.add_argument("output_file")

    #create template grid
    parser_template_grid = subparsers.add_parser("create_template_grid_for_gpkg")
    parser_template_grid.add_argument("catchment_netcdf_file")
    parser_template_grid.add_argument("catchment_gpkg_file")
    parser_template_grid.add_argument("template_grid_file")
    parser_template_grid.add_argument("config_json_file")
    
    #create nwm grid
    parser_nwm_grid = subparsers.add_parser("create-nwm-grid")
    parser_nwm_grid.add_argument("catchment_netcdf_file")
    parser_nwm_grid.add_argument("catchment_gpkg_file")
    parser_nwm_grid.add_argument("template_grid_file")
    parser_nwm_grid.add_argument("config_json_file")

    #download current NWM output netcdfs from nomads server
    parser_nwm_download = subparsers.add_parser("download-nwm-outputs")
    parser_nwm_download.add_argument("output_folder_path")
    parser_nwm_download.add_argument("re_download")

    #Extract metadata info from current NWM output netcdfs that are downloaded 
    parser_nwm_info = subparsers.add_parser("obtain-netcdf-metadata")
    parser_nwm_info.add_argument("local_folder_path")

    #create template NWM output grids using the downloaded files from nomad server
    parser_template_grids = subparsers.add_parser("create-template-nwm-grid")
    parser_template_grids.add_argument("nwm_output_grids_folder")
    parser_template_grids.add_argument("nwm_template_grids_folder")

    #create basin level netcdf using timestep netcdfs
    parser_basin_grids = subparsers.add_parser("create-combined-basin-grid")
    parser_basin_grids.add_argument("reference_grid")
    parser_basin_grids.add_argument("timestep_grids_folder")
    parser_basin_grids.add_argument("output_basin_grids_folder")
    
    #overall netcdf workflow
    overall_workflow = subparsers.add_parser("test-overall-workflow")
    overall_workflow.add_argument("ngen_netcdf_output_file")
    overall_workflow.add_argument("ngen_gpkg_file")
    overall_workflow.add_argument("output_folder")
    
    args = parser.parse_args()

    if args.command == "randomize":
        randomize_values(args.input_file, args.output_file)
    elif args.command == "create-template-grid":
        create_template_grid_for_gpkg(args.catchment_netcdf_file, args.catchment_gpkg_file, args.template_grid_file)
    elif args.command == "create-nwm-grid":
        create_nwm_grid(args.catchment_netcdf_file, args.catchment_gpkg_file, args.template_grid_file, args.config_json_file)
    elif args.command == "download-nwm-outputs":
        download_netcdf_from_nomads(args.download_url, args.output_folder_path)
    elif args.command == "obtain-netcdf-metadata":
        extract_netcdf_metadata(args.local_folder_path)
    elif args.command == "create-template-nwm-grid":
        create_template_nwm_grids_data(args.nwm_output_grids_folder, args.nwm_template_grids_folder)
    elif args.command == "create-combined-basin-grid":
        combine_basin_grids(args.reference_grid, args.timestep_grids_folder, args.output_basin_grids_folder)
    elif args.command == "test-overall-workflow":
        overall_netcdf_workflow(args.ngen_netcdf_output_file, args.ngen_gpkg_file, args.output_folder)
    else:
        parser.print_help()
    
if __name__ == "__main__":
    main()