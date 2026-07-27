import sys
import os
from datetime import datetime
import time
from typing import List, Any, Optional
from data_assimilation_engine.output_variables.DataReader import DataReader
from data_assimilation_engine.output_variables.DataProcessor import DataProcessor
import data_assimilation_engine.output_variables.utils as utils
import data_assimilation_engine.output_variables.consts as consts

_processor: Optional[DataProcessor] = None # Shared instance of DataProcessor

def create_dataprocessor(root_output_folder: str, netcdf_file: str, gpkg_file: str) -> DataProcessor:
    global _processor
    if _processor is None:
        _processor = DataProcessor(netcdf_file, gpkg_file)
        # Create log file
        log_folder = os.path.join(root_output_folder, consts.LOG_FOLDER)
        os.makedirs(log_folder, exist_ok = True)
        log_file = os.path.join(log_folder, 'nwm_postprocessing_' + datetime.now().strftime("%Y%m%d_%H%M%S") + '.log')
        _processor.log_file = log_file
    return _processor

def download_netcdf_from_nomads(root_output_folder: str, re_download: bool = False) -> str:
    return utils.download_nwm_data_from_server(root_output_folder, re_download)

def create_template_files_for_gpkg(root_output_folder: str, netcdf_file: str, gpkg_file: str, 
                                   config_json: str, output_cycle_domain: str, output_templates_folder: str | None):
    
    if not os.path.isfile(netcdf_file):
        raise ValueError("Specified ngen output cathments netcdf file does not exist")

    if not os.path.isfile(gpkg_file):
        raise ValueError("Specified ngen geopackage file does not exist")
    
    netcdf_metadata_list = []
    if os.path.isfile(config_json):
        netcdf_metadata_list = utils.read_output_variables_info_from_config(config_json)
    else:
        raise ValueError("Specified config file does not exist")
    
    # create necessary folders
    os.makedirs(root_output_folder, exist_ok = True)
    if output_templates_folder is None or output_templates_folder == '':
        # If no folder is specified, we will create it as a subfolder within the root.
        ngen_template_nc_folder = os.path.join(root_output_folder, consts.NWM_NGEN_TEMPLATE_FOLDER)
    else:
        ngen_template_nc_folder = output_templates_folder
    os.makedirs(ngen_template_nc_folder, exist_ok = True)

    # Create templates.
    for mdata in netcdf_metadata_list:
        if mdata.domain == output_cycle_domain:
            _processor.create_template_netcdf_using_config(mdata, ngen_template_nc_folder)

def create_nwm_products_for_gpkg(root_output_folder: str, troute_output_netcdf: str, troute_lakeout_netcdf: str, 
                                   config_json: str, output_templates_folder: str | None, 
                                   output_cycle_hour: int, output_cycle_type: str, 
                                   output_cycle_domain: str):
    
    if output_templates_folder is None or output_templates_folder == '':
        # If no folder is specified, we will assume it as a subfolder within the root as defined in consts.py.
        ngen_template_nc_folder = os.path.join(root_output_folder, consts.NWM_NGEN_TEMPLATE_FOLDER)
    else:
        ngen_template_nc_folder = output_templates_folder
    
    netcdf_metadata_list = []
    if os.path.isfile(config_json):
        netcdf_metadata_list = utils.read_output_variables_info_from_config(config_json)
    else:
        raise ValueError("Specified config file does not exist")
    
    # Confirm that template files exist for the cycle type. Gather a dictionary as well
    # To do: Update this to include only conus for demo?
    template_files_dict = {}
    for mdata in netcdf_metadata_list:
        if mdata.output_class == output_cycle_type and mdata.domain == output_cycle_domain:
            template_nc_name = _processor.geo_id + '_' + mdata.output_class + '_' + mdata.category + '_' + mdata.domain
            template_nc_file = os.path.join(ngen_template_nc_folder, template_nc_name + '.nc')
            if os.path.isfile(template_nc_file):
                template_files_dict[template_nc_name] = template_nc_file
            else:
                raise ValueError(f"Template file for {_processor.geo_id}.{mdata.output_class}.{mdata.category}.{mdata.domain} does not exist")
    
    # set output folder for the nwm products for the geopackage
    nwm_output_folder = os.path.join(root_output_folder, consts.NWM_OUTPUT_FOLDER)
    os.makedirs(nwm_output_folder, exist_ok = True)

    # set cycle hour
    formatted_hr = f"{output_cycle_hour:02d}"

    for mdata in netcdf_metadata_list:
        if mdata.output_class == output_cycle_type and mdata.domain == output_cycle_domain:
            _processor.nwm_output_class = mdata.output_class
            _processor.nwm_category = mdata.category
            _processor.nwm_domain = mdata.domain
            template_nc_name = _processor.geo_id + '_' + mdata.output_class + '_' + mdata.category + '_' + mdata.domain
            _processor.set_template_netcdf(template_files_dict[template_nc_name])
            _processor.set_troute_netcdf(troute_output_netcdf)
            _processor.set_troute_lakeout_netcdf(troute_lakeout_netcdf)
            _processor.produce_nwm_output_product(mdata, nwm_output_folder, formatted_hr)

def combine_basin_products(netcdf_folder: str, output_folder: str, config_json: str, 
                            output_cycle_hr: str, output_cycle_type: str, output_cycle_domain: str):

    utils.create_combined_basin_netcdf_products(netcdf_folder, output_folder, config_json, output_cycle_hr, 
                                                output_cycle_type, output_cycle_domain)

# Postprocessing Entrypoint
def netcdf_production_workflow(args_list) -> Optional[Any]:
    """
    Main entrypoint function. Parses the args list and handles action
    based on user preferences.
    """

    global _processor

    if not args_list:
        print("The arguments list to post processing is either null or empty.")
        raise ValueError("Workflow aborted: The arguments list cannot be None or empty.")
    
    action_item = str(args_list[-1]).lower() # last item is the action.

    match action_item:
        case "download":
            if len(args_list) < 2:
                raise ValueError("'download' action requires argument for: [root output folder path, 'download']")
            root_output_folder = args_list[0]
            config_json_file = download_netcdf_from_nomads(root_output_folder)
            return config_json_file

        case "template":
            if len(args_list) < 7:
                raise ValueError("'template' action requires following arguments: " + 
                "[root output folder path, catchments netcdf, geopackage, " + 
                "config json, output cycle domain, optional template output folder, 'template']")
            root_output_folder = args_list[0]
            ngen_catchments_netcdf = args_list[1]
            ngen_geopackage = args_list[2]
            config_json_file = args_list[3]
            output_cycle_domain = args_list[4]
            output_templates_folder = args_list[5]
            if(_processor is None):
                _processor = create_dataprocessor(root_output_folder, ngen_catchments_netcdf, ngen_geopackage)
            create_template_files_for_gpkg(root_output_folder, ngen_catchments_netcdf, ngen_geopackage, config_json_file, output_cycle_domain, output_templates_folder)

        case "output":
            if len(args_list) < 11:
                raise ValueError("'output' action requires following arguments: " + 
                " [root output folder path, catchments netcdf, geopackage, " + 
                "troute output, troute lakeout, config json, " +
                "optional template output folder, output cycle hour, output cycle type, " +
                "output_cycle_domain, 'output']")
            root_output_folder = args_list[0]
            ngen_catchments_netcdf = args_list[1]
            ngen_geopackage = args_list[2]
            troute_output_netcdf = args_list[3]
            troute_lakeout_netcdf = args_list[4]
            config_json_file = args_list[5]
            output_templates_folder = args_list[6]
            output_cycle_hour = int(args_list[7])
            output_cycle_type = args_list[8]
            output_cycle_domain = args_list[9]
            if(_processor is None):
                _processor = create_dataprocessor(root_output_folder, ngen_catchments_netcdf, ngen_geopackage)
            create_nwm_products_for_gpkg(root_output_folder, troute_output_netcdf, troute_lakeout_netcdf, 
                                         config_json_file, output_templates_folder, output_cycle_hour, output_cycle_type, output_cycle_domain)

        case "all":
            if len(args_list) < 11:
                raise ValueError("'all' action requires following arguments: " + 
                "[root output folder path, catchments netcdf, geopackage, " + 
                "troute output, troute lakeout, config json, " +
                "optional template output folder, output cycle hour, output cycle type, " +
                "output_cycle_domain, 'all']")
            root_output_folder = args_list[0]
            ngen_catchments_netcdf = args_list[1]
            ngen_geopackage = args_list[2]
            troute_output_netcdf = args_list[3]
            troute_lakeout_netcdf = args_list[4]
            config_json_file = args_list[5]
            output_templates_folder = args_list[6]
            output_cycle_hour = int(args_list[7])
            output_cycle_type = args_list[8]
            output_cycle_domain = args_list[9]

            config_json_file = download_netcdf_from_nomads(root_output_folder)
            if(_processor is None):
                _processor = create_dataprocessor(root_output_folder, ngen_catchments_netcdf, ngen_geopackage)
            create_template_files_for_gpkg(root_output_folder, ngen_catchments_netcdf, ngen_geopackage, config_json_file, output_cycle_domain, output_templates_folder)
            create_nwm_products_for_gpkg(root_output_folder, troute_output_netcdf, troute_lakeout_netcdf, 
                                         config_json_file, output_templates_folder, output_cycle_hour, output_cycle_type, output_cycle_domain)
            
        case "mosaic":
            if len(args_list) < 6:
                raise ValueError("'mosaic' action requires following arguments: " + 
                "[output folder path containing ngen NWM products, " + 
                "coutput folder to save mosaics, config json, " +
                "output cycle hour, output cycle type, output cycle domain, 'mosaic']")
            ngen_nwm_products_folder = args_list[0]
            mosaic_products_folder = args_list[1]
            config_json_file = args_list[2]
            output_cycle_hour = int(args_list[3])
            output_cycle_type = args_list[4]
            output_cycle_domain = args_list[5]
            combine_basin_products(ngen_nwm_products_folder, mosaic_products_folder, config_json_file, 
                            output_cycle_hour, output_cycle_type, output_cycle_domain)

    print("NetCDF Production workflow completed Successfully")
