# Script Description

NetCdfProductionManager.py: This script contains the main entrypoint functions for executing all routines to create the output netcdf files. The full workflow involves taking the output catchment netcdf, geopackage, troute outputs, and generate netcdf files of the output variables per timestep. It also has functions to produce the mosaiced netcdf combining multiple ngen run outputs. The script is implemented to be called from RTE. 

DataReader.py and DataProcessor.py: These scripts perform bulk of the processing in producing the intermediate NWM netcdf products.
utils.py: These scripts provide support to DataProcessor and also handle reference files download from NOMADS and producing the final mosaiced NWM products.

# Script Usage

#### download_netcdf_from_nomads:
This function downloads one reference files per combination of NWM cycle, class, category and domain from the NOMADS server. It also creates a config file with the gathred metadata from the downloaded files.

Positional Arguments:  
- root_output_folder: str - The root folder where all intermediate and final datasets in post-processing are saved.
- re_download : bool - This gives an option for the user to re-download the NOMADS data. Defaults to False.

#### extract_netcdf_metadata: 
This function creates a config file with the gathered metadata from the downloaded national reference files from NOMADS

Positional Arguments:  
- root_output_folder: str - The root folder where all intermediate and final datasets in post-processing are saved.

#### create_template_files_for_gpkg:
This function creates template netcdf files that covers the extent of the divides in the geopackage and updates all the variables to have a value of zero.

Positional Arguments:  
- root_output_folder: str - The root folder where all intermediate and final datasets in post-processing are saved.
- netcdf_file : str - The absolute or relative path to the ngen output NetCDF file.
- gpkg_file : str - The absolute or relative path to the geopackage file that was used for ngen run.
- output_cycle_domain: str - The domain for the output products. For example, conus, hawaii, alaska
- output_templates_folder: str | None - The folder path to where the output templates need to be stored. If None provided, it defaults to a subfolder with the `root_output_folder`

#### create_nwm_products_for_gpkg:
This function creates output NWM products using the template files. These output products span the extent of the diviides layer in the geopackage.

Positional Arguments:  
- root_output_folder: str - The root folder where all intermediate and final datasets in post-processing are saved.
- troute_output_netcdf : str - The absolute or relative path to the troute output NetCDF file.
- troute_lakeout_netcdf : str - The absolute or relative path to the troute lakeout (waterbody) output NetCDF file.
- config_json: str - The full or relative file path to config json file.
- output_templates_folder: str | None - The folder path to where the output templates need to be stored. If None provided, it defaults to a subfolder with the `root_output_folder`
- output_cycle_hr: str - The hour in a day (0-23) for which the outputs are produced after simulations are run.
- output_cycle_type: str - The cycle type for the output products. For example, medium_range_mem1, analysis_assim_no_da
- output_cycle_domain: str - The domain for the output products. For example, conus, hawaii, alaska

#### combine_basin_products:
This function creates mosaiced or combined netcdf products.

Positional Arguments:  
- netcdf_folder: str - Folder containing the netcdf products after all post-processing runs.
- output_folder: str - Output folder to save all the combined/mosaiced netcdf outputs.
- config_json: str - Full or relative path to the config json file
- output_cycle_hr: str - The hour in a day (0-23) for which the outputs are produced after simulations are run.
- output_cycle_type: str - The cycle type for the output products. For example, medium_range_mem1, analysis_assim_no_da
- output_cycle_domain: str - The domain for the output products. For example, conus, hawaii, alaska

