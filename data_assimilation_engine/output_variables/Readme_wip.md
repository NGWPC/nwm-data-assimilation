# Script Description

netcdf_production_sample.py: This script contains the main function for executing all routines to create the output netcdf files. The full workflow involves taking the output catchment netcdf file produced by ngen as input and generate netcdf files of the output variables per timestep. The existing 

# Sample data

Sample catchment output netcdf data has been included for testing in the sample_data/sample_netcdf directory. This includes a netcdf file for all the catchments in basin 01123000 (catchment_output_01123000.nc). Geopackage file for the corresponding catchments is included in the sample_data/sample_gpkg folder (gages-01123000.gpkg). 

# Script Usage

All the required packages are already part of the toml file. All paths specified in the positional arguments for the functions listed
below can be absolute or relative.

#### randomize:
python netcdf_production_sample.py randomize catchment_netcdf catchment_netcdf_randomized

Positional Arguments:  
- catchment_netcdf: Path where the catchment netcdf file output from ngen is located.
- catchment_netcdf_randomized: Path where the output netcdf file is created with random values from 1-10 assigned to the output variables.

#### create-template-grid: 
python netcdf_production_sample.py create-template-grid catchment_netcdf_randomized basin_geopackage output_netcdf_grid

Positional Arguments:  
- catchment_netcdf_randomized: Path to the output netcdf file with random values from 1-10 assigned to the output variables.
- basin_geopackage: Path to the basin geopackage. It can be in the existing or the new NHF schema.
- output_netcdf_grid: Path where the gridded 1 km x 1km netcdf file is created.

#### create-nwm-grid:
python netcdf_production_sample.py create-nwm-grid catchment_netcdf_randomized basin_geopackage output_netcdf_grid

Positional Arguments:  
- catchment_netcdf_randomized: Path to the output netcdf file with random values from 1-10 assigned to the output variables.
- basin_geopackage: Path to the basin geopackage. It can be in the existing or the new NHF schema.
- output_netcdf_grid: Path where the gridded 1 km x 1km netcdf file is created.

# Examples

#### randomize
python netcdf_production_sample.py randomize sample_data/sample_netcdf/g01123000.nc sample_data/sample_netcdf/catchment_randomvals.nc

#### create-template-grid
python netcdf_production_sample.py create-template-grid sample_data/sample_netcdf/catchment_randomvals.nc sample_data/sample_gpkg/gages-01123000.gpkg sample_data/sample_netcdf/grid_template.nc

#### create-nwm-grid
python netcdf_production_sample.py create-nwm-grid sample_data/sample_netcdf/catchment_randomvals.nc sample_data/sample_gpkg/gages-01123000.gpkg sample_data/sample_netcdf/grid_template.nc

