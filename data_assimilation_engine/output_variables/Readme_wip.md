# Script Description

netcdf_production_sample.py: This script contains the main function for executing all routines to create the output netcdf files. The full workflow involves taking the output catchment netcdf file produced by ngen as input and generate netcdf files of the output variables per timestep. The existing 

# Sample data

Sample catchment output netcdf data has been included for testing in the sample_data/sample_netcdf directory. This includes a netcdf file for all the catchments in basin 01123000 (catchment_output_01123000.nc). Geopackage file for the corresponding catchments is included in the sample_data/sample_gpkg folder (gages-01123000.gpkg). 

# Script Usage

All the required packages are already part of the toml file. All paths specified in the positional arguments for the functions listed
below can be absolute or relative.

#### randomize:
This is a function used for testing to create random values for all variables in the catchment output. This should be deleted when production ready.
python netcdf_production_sample.py randomize catchment_netcdf catchment_netcdf_randomized

Positional Arguments:  
- catchment_netcdf: Path where the catchment netcdf file output from ngen is located.
- catchment_netcdf_randomized: Path where the output netcdf file is created with random values from 1-10 assigned to the output variables.

#### create-template-grid: 
This function creates the template grid that spans the geopackage catchments extent (not the bounding box). This works only for gridded files.
python netcdf_production_sample.py create-template-grid catchment_netcdf_randomized basin_geopackage output_template_netcdf_grid config_json

Positional Arguments:  
- catchment_netcdf_randomized: Path to the output netcdf file with random values from 1-10 assigned to the output variables.
- basin_geopackage: Path to the basin geopackage. It can be in the existing or the new NHF schema.
- output_template_netcdf_grid: Path where the gridded netcdf file is created. Specify the name as well.
- config_json: Path to the config json that holds the metadata information for NWM output products.

#### create-nwm-grid:
This function creates a basin level NetCDF grid from the template grid. 
python netcdf_production_sample.py create-nwm-grid catchment_netcdf_randomized basin_geopackage template_netcdf_grid config_json

Positional Arguments:  
- catchment_netcdf_randomized: Path to the output netcdf file with random values from 1-10 assigned to the output variables.
- basin_geopackage: Path to the basin geopackage. It can be in the existing or the new NHF schema.
- template_netcdf_grid: Path for the gridded template netcdf file to use for producing the NWM grid product.
- config_json: Path to the config json that holds the metadata information for NWM output products.

#### download-nwm-outputs:
This function downloads a unique set of NWM output products from the NOMADS server that can be used for templating. 
python netcdf_production_sample.py download-nwm-outputs nomads_root_url output_folder_path

Positional Arguments:  
- nomads_root_url: Root URL for NOMADS. This folder should not include the date
- output_folder_path: Folder to download the NWM data products.

#### obtain-netcdf-metadata:
This function reads all the metadata information needed from the NWM output files and saves it in a csv and json. 
python netcdf_production_sample.py obtain-netcdf-metadata nwm_local_download_path output_file_name

Positional Arguments:  
- nwm_local_download_path: Path to the folder where all netcdf files have been downloaded from NOMADS.
- output_file_name: Output file name for the csv and json.

#### create-template-nwm-grid:
This function is primarily used for producing intermediate files for testing. This should be deleted when scripts are production-ready.
python netcdf_production_sample.py create-template-nwm-grid nwm_local_download_path nwm_local_template_path

Positional Arguments:  
- nwm_local_download_path: Path to the folder where all netcdf files have been downloaded from NOMADS.
- nwm_local_template_path: Path to the folder where all template grids will be created.

#### create-combined-basin-grid:
This function is primarily used for producing intermediate files for testing. This should be deleted when scripts are production-ready.
python netcdf_production_sample.py create-combined-basin-grid nwm_timestep_grid_path nwm_multibasin_grid_path

Positional Arguments:  
- nwm_timestep_grid_path: Path to the folder where the necessary timestep netcdf files have been created.
- nwm_multibasin_grid_path: Path to the folder where all the combined/merged multi-basin grids will be saved.

# Examples

#### randomize
python netcdf_production_sample.py randomize sample_data/sample_netcdf/g01123000.nc sample_data/sample_netcdf/catchment_randomvals.nc

#### create-template-grid
python netcdf_production_sample.py create-template-grid sample_data/sample_netcdf/final_test/catchment_randomvals.nc sample_data/sample_gpkg/gages-01123000.gpkg sample_data/sample_netcdf/final_test/new_grid_template.nc sample_data/nwm_output/metadata_config.json

#### create-nwm-grid
python netcdf_production_sample.py create-nwm-grid sample_data/sample_netcdf/final_test/catchment_randomvals.nc sample_data/sample_gpkg/gages-01123000.gpkg sample_data/sample_netcdf/final_test/new_grid_template.nc sample_data/nwm_output/metadata_config.json

#### download-nwm-outputs
python netcdf_production_sample.py download-nwm-outputs https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod sample_data/nwm_output

#### obtain-netcdf-metadata
python netcdf_production_sample.py obtain-netcdf-metadata sample_data/nwm_output metadata

#### create-template-nwm-grid
python netcdf_production_sample.py create-template-nwm-grid sample_data/nwm_output sample_data/nwm_templates

#### create-combined-basin-grid
python netcdf_production_sample.py create-combined-basin-grid sample_data/sample_netcdf/sample_output/merge_test sample_data/sample_netcdf/sample_output/merge_test