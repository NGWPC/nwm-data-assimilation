import argparse
from data_assimilation_engine.output_variables.DataReader import DataReader
from data_assimilation_engine.output_variables.DataProcessor import DataProcessor
import data_assimilation_engine.output_variables.utils as utils

def randomize_values(netcdf_file: str, output_file: str) -> None:
    #Usage:
    # python netcdf_wrapper_sample.py randomize sample_data/sample_netcdf/g01123000.nc sample_data/sample_netcdf/catchment_randomvals.nc

    reader = DataReader(netcdf_file)
    reader.assign_random_values(output_file)

def create_template_grid(netcdf_file: str, gpkg_file: str, template_grid_file: str, config_json_file: str):
    #Usage
    #python netcdf_wrapper_sample.py create-template-grid sample_data/sample_netcdf/final_test/catchment_randomvals.nc sample_data/sample_gpkg/gages-01123000.gpkg sample_data/sample_netcdf/final_test/grid_template.nc
    #new workflow: python netcdf_production_sample.py create-template-grid sample_data/sample_netcdf/final_test/catchment_randomvals.nc sample_data/sample_gpkg/gages-01123000.gpkg sample_data/sample_netcdf/final_test/new_grid_template.nc sample_data/nwm_output/metadata_config.json
    processor = DataProcessor(netcdf_file, gpkg_file, template_grid_file, config_json_file, 'analysis_assim', 'land', 'conus', True, False)

def create_nwm_grid(netcdf_file: str, gpkg_file: str, template_grid_file: str, config_json_file: str):
    #Usage:
    #python netcdf_wrapper_sample.py create-nwm-grid sample_data/sample_netcdf/final_test/catchment_randomvals.nc sample_data/sample_gpkg/gages-01123000.gpkg sample_data/sample_netcdf/final_test/grid_template.nc
    #new workflow: python netcdf_production_sample.py create-nwm-grid sample_data/sample_netcdf/final_test/catchment_randomvals.nc sample_data/sample_gpkg/gages-01123000.gpkg sample_data/sample_netcdf/final_test/new_grid_template.nc sample_data/nwm_output/metadata_config.json
    processor = DataProcessor(netcdf_file, gpkg_file, template_grid_file, config_json_file, 'analysis_assim', 'land', 'conus', False, True)

def create_nwm_grid_dask(netcdf_file: str, gpkg_file: str, template_grid_file: str):
    #Usage:
    #python netcdf_wrapper_sample.py create-nwm-grid sample_data/sample_netcdf/final_test/catchment_randomvals.nc sample_data/sample_gpkg/gages-01123000.gpkg sample_data/sample_netcdf/final_test/grid_template.nc
    processor = DataProcessor(netcdf_file, gpkg_file, template_grid_file, False, True)

def download_netcdf(download_url: str, output_folder: str):
    #Usage:
    #python netcdf_production_sample.py download-nwm-outputs https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod sample_data/nwm_output
    utils.download_nwm_data_from_server(download_url, output_folder)

def extract_netcdf_metadata(netcdf_root_folder: str, output_file_name: str):
    #Usage:
    #python netcdf_production_sample.py obtain-netcdf-metadata sample_data/nwm_output metadata
    utils.obtain_metadata_information(netcdf_root_folder, output_file_name)
    #utils.debug_netcdf_structure_in_folder(netcdf_root_folder)

def create_template_nwm_grids_data(netcdf_root_folder: str, templates_folder: str):
    #Usage:
    #python netcdf_production_sample.py create-template-nwm-grid sample_data/nwm_output sample_data/nwm_templates
    utils.create_nwm_template_grids(netcdf_root_folder, templates_folder)

def main() -> None:

    parser = argparse.ArgumentParser(description="NetCDF Data Tool")

    subparsers = parser.add_subparsers(dest="command")

    #random values
    parser_randomize = subparsers.add_parser("randomize")
    parser_randomize.add_argument("input_file")
    parser_randomize.add_argument("output_file")

    #create template grid
    parser_template_grid = subparsers.add_parser("create-template-grid")
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
    parser_nwm_download.add_argument("download_url")
    parser_nwm_download.add_argument("output_folder_path")

    #Extract metadata info from current NWM output netcdfs that are downloaded 
    parser_nwm_info = subparsers.add_parser("obtain-netcdf-metadata")
    parser_nwm_info.add_argument("local_folder_path")
    parser_nwm_info.add_argument("file_name")

    #create template NWM output grids using the downloaded files from nomad server
    parser_template_grids = subparsers.add_parser("create-template-nwm-grid")
    parser_template_grids.add_argument("nwm_output_grids_folder")
    parser_template_grids.add_argument("nwm_template_grids_folder")

    args = parser.parse_args()

    if args.command == "randomize":
        randomize_values(args.input_file, args.output_file)
    elif args.command == "create-template-grid":
        create_template_grid(args.catchment_netcdf_file, args.catchment_gpkg_file, args.template_grid_file, args.config_json_file)
    elif args.command == "create-nwm-grid":
        create_nwm_grid(args.catchment_netcdf_file, args.catchment_gpkg_file, args.template_grid_file, args.config_json_file)
    elif args.command == "download-nwm-outputs":
        download_netcdf(args.download_url, args.output_folder_path)
    elif args.command == "obtain-netcdf-metadata":
        extract_netcdf_metadata(args.local_folder_path, args.file_name)
    elif args.command == "create-template-nwm-grid":
        create_template_nwm_grids_data(args.nwm_output_grids_folder, args.nwm_template_grids_folder)
    else:
        parser.print_help()
    
if __name__ == "__main__":
    main()