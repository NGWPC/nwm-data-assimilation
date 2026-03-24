import argparse
from data_assimilation_engine.output_variables.DataReader import DataReader
from data_assimilation_engine.output_variables.DataProcessor import DataProcessor

def randomize_values(netcdf_file: str, output_file: str) -> None:
    #Usage:
    # python netcdf_wrapper_sample.py randomize sample_data/sample_netcdf/g01123000.nc sample_data/sample_netcdf/catchment_randomvals.nc

    reader = DataReader(netcdf_file)
    reader.assign_random_values(output_file)

def create_template_grid(netcdf_file: str, gpkg_file: str, template_grid_file: str):
    #Usage
    #python netcdf_wrapper_sample.py create-template-grid sample_data/sample_netcdf/final_test/catchment_randomvals.nc sample_data/sample_gpkg/gages-01123000.gpkg sample_data/sample_netcdf/final_test/grid_template.nc
    processor = DataProcessor(netcdf_file, gpkg_file, template_grid_file, True, False)

def create_nwm_grid(netcdf_file: str, gpkg_file: str, template_grid_file: str):
    #Usage:
    #python netcdf_wrapper_sample.py create-nwm-grid sample_data/sample_netcdf/final_test/catchment_randomvals.nc sample_data/sample_gpkg/gages-01123000.gpkg sample_data/sample_netcdf/final_test/grid_template.nc
    processor = DataProcessor(netcdf_file, gpkg_file, template_grid_file, False, True)

def create_nwm_grid_dask(netcdf_file: str, gpkg_file: str, template_grid_file: str):
    processor = DataProcessor(netcdf_file, gpkg_file, template_grid_file, False, True)

def main() -> None:

    parser = argparse.ArgumentParser(description="NetCDF Data Tool")

    subparsers = parser.add_subparsers(dest="command")

    #random values
    parser_randomize = subparsers.add_parser("randomize")
    parser_randomize.add_argument("input_file")
    parser_randomize.add_argument("output_file")

    #create template grid
    parser_grid = subparsers.add_parser("create-template-grid")
    parser_grid.add_argument("catchment_netcdf_file")
    parser_grid.add_argument("catchment_gpkg_file")
    parser_grid.add_argument("template_grid_file")
    
    #create nwm grid
    parser_nwm_grid = subparsers.add_parser("create-nwm-grid")
    parser_nwm_grid.add_argument("catchment_netcdf_file")
    parser_nwm_grid.add_argument("catchment_gpkg_file")
    parser_nwm_grid.add_argument("template_grid_file")

    args = parser.parse_args()

    if args.command == "randomize":
        randomize_values(args.input_file, args.output_file)
    elif args.command == "create-template-grid":
        create_template_grid(args.catchment_netcdf_file, args.catchment_gpkg_file, args.template_grid_file)
    elif args.command == "create-nwm-grid":
        create_nwm_grid(args.catchment_netcdf_file, args.catchment_gpkg_file, args.template_grid_file)
    else:
        parser.print_help()
    
if __name__ == "__main__":
    main()