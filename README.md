
# NWM Output Variables Post-Processing Routines

**Description**:  The simulation NetCDF outputs from NGEN and T-Route needs to be post-processed to produce final NWM NetCDF products across various categories - channel, terrain, land and reservoir. This repository uses a set of national reference outputs from nomads (https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod) to extract the metadata for the final NWM output variables. The metadata include information such as the coordinate system variable units, long desriptive name of the NWM variables, fill value, and missing value. It also captures the pixel resolution (for spatial gridded products), origin, NWM output cycle type. The various output cycle types are the names of the folders in the nomads link above.

## Dependencies

  - Python ~= 3.12
  - Key dependencies and packages required are listed in `pyproject.toml`

## Installation

Refer to [INSTALL](INSTALL.md) document to get started on working with routines for producing NWM NetCDF outputs.

## Usage

The various capatibilities/workflows for post-processing are listed in `postprocessing_wrapper_sample.py`. The main entrypoint for post-processing routines can be found in `data_assimilation_engine\output_variables\NetCdfProductionManger.py`.

  - The function arguments that require a folder or file can be relative or absolute paths.
  - The allowed actions are specified as the last argument to the entrypoint function `netcdf_production_workflow` in `NetCdfProductionManger.py`.  Those include `"download ", "config", "template", "output", "all", "mosaic"`. Each action performs a specific task.
    - `download`: Downloads national reference NetCDF outputs for the requested output cycle type.
    - `config`: Creates the metadata config json that has metadata information about all NWM products.
    - `template`: Creates template NetCDF files that mimic the national reference NetCDF files but span the extent of the NGEN simulation geopackage
    - `output`: Generates output NetCDF with the simulation computational output values.
    - `all`: Performs all the steps above in series.
    - `mosaic`: Merges multiple geopackage level NetCDF outputs into a single NetCDF dataset.

### Input Parameters for NetCDF production workflow

  - `root_output_folder`: The main output directory where all intermediate and final products are saved. The program creates subdirectories as necessary
  - `netcdf_file`: The NetCDF file produced by NGEN that contains computational outputs of the simulation run.
  - `gpkg_file`: The geopackage file input to NGEN that defines the extent of the NWM NetCDF output files.
  - `troute_output_netcdf`: The NetCDF file produced by T-Route that contains computational outputs of the simulation run. allowed.
  - `troute_lakeout_netcdf`: The waterbody NetCDF file produced by T-Route that contains computational outputs of the simulation run.
  - `config_json`: The name of the metadata config file to be created or available from a previous run.
  - `output_cycle_type`: The name of the NWM output cycle for which these products are generated. For example, analysis_assim.
  - `output_cycle_domain`: The domain for which these products are generated. For example, conus.
  - `output_cycle_hour`: The hour in a day (0-23) for which the outputs are produced after simulations are run. For example, 6.
  - `output_templates_folder`: The directory where the post-processing templates are created or available from a previous run.
  - `action`: The parameter that defines which workflow needs to be executed.

### Input Parameters for NetCDF merge/mosaic workflow

  - `netcdf_folder`: Directory containing the netcdf products after all post-processing production runs.
  - `output_folder`: Output directory to save all the combined/mosaiced netcdf outputs.
  - `config_json`: The name of the metadata config file to be created or available from a previous run.
  - `output_cycle_type`: The name of the NWM output cycle for which these products are generated. For example, analysis_assim.
  - `output_cycle_domain`: The domain for which these products are generated. For example, conus.
  - `output_cycle_hour`: The hour in a day (0-23) for which the outputs are produced after simulations are run. For example, 6.

### Download NOMADS data
```
download_inputs = [
    "sample_data/outputs_root",
    "analysis_assim",
    True,
    "download"
]
netcdf_production_workflow(download_inputs)
```

### Generate metadata config file
```
build_config_inputs = [
    "sample_data/outputs_root",
    "config"
]
netcdf_production_workflow(build_config_inputs) 
```
### Create template NetCDF files for 
```
template_inputs = [
    "sample_data/outputs_root",
    "sample_data/ngen_netcdfs/catchment_output_3n.nc",
    "sample_data/sample_gpkg/vpu_3n.gpkg",
    "sample_data/outputs_root/configs/metadata_config.json",
    "conus",
    None,
    "template",
]
netcdf_production_workflow(template_inputs)
```

### Generate NetCDF NWM outputs
```
production_inputs = [
    "sample_data/outputs_root",
    "sample_data/ngen_netcdfs/catchment_output_3n.nc",
    "sample_data/sample_gpkg/vpu_3n.gpkg",
    "sample_data/troute_netcdfs/troute_output_3n.nc",
    "sample_data/troute_netcdfs/troute_lakeout_3n.nc",
    "sample_data/outputs_root/configs/metadata_config.json",
    None,
    "4",
    "analysis_assim",
    "conus",
    "output",
]
netcdf_production_workflow(production_inputs)
```
### Overall workflow for NetCDF NWM outputs
```
overall_workflow_inputs = [
    "sample_data/outputs_root",
    "sample_data/ngen_netcdfs/catchment_output_3n.nc"
    "sample_data/sample_gpkg/vpu_3n.gpkg",
    "sample_data/troute_netcdfs/troute_output_3n.nc",
    "sample_data/troute_netcdfs/troute_lakeout_3n.nc",
    "sample_data/outputs_root/configs/metadata_config.json",
    None,
    "0",
    "medium_range_blend",
    "conus",
    "all",
]
netcdf_production_workflow(overall_workflow_inputs)
```
### Mosaic workflow for domain level NetCDF NWM outputs
```
mosaic_workflow_inputs = [
    "sample_data/outputs_root/nwm_products_for_ngen",
    "sample_data/outputs_root/nwm_mosaics",
    "sample_data/outputs_root/configs/metadata_config.json",
    "0",
    "analysis_assim",
    "conus",
    "mosaic",
]
netcdf_production_workflow(mosaic_workflow_inputs)
```

## Known limitations

  - The routines are developed for conus, alaska, hawaii and puertorico domains only
  - Only the following output cylces have been tested
      - analysis_assim
      - analysis_assim_alaska
      - analysis_assim_hawaii
      - analysis_assim_puertorico
      - medium_range_* ensemble members for conus and alaska domains
      - short_range
      - short_range_alaska
      - short_range_hawaii
      - short_range_puertorico
    Note: For Hawaii, the existing 15 minute intervals are replaced by hourly intervals

## Getting involved

General instructions on _how_ to contribute can be found in [CONTRIBUTING](CONTRIBUTING.md).

----
## Open source licensing info

1. [TERMS](TERMS.md)
2. [LICENSE](LICENSE)
----

