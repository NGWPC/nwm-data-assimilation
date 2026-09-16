
# nwm-data-assimilation - Data Assimilation Engine

## Description
The Data Assimilation Engine performs several tasks related to the postprocessing and evaluation of outputs produced by NextGen simulations, including NWM operation output postprocessing, and soil moisture, snow water equivalent, and precipitation postprocessing.

## Requirements
- Python ~= 3.11
- Key dependencies listed in `pyproject.toml`
- AWS credentials configured if using `--direct_s3`, or a local mount of the observed data otherwise

## Installation
```bash
git close https://github.com/[GH_ORG]/nwm-data-assimilation.git
cd nwm-data-assimilation
pip install -e .
```

## Soil Moisture, SWE, and Precipitation Post-Postprocessing
This repository provides tools for postprocessing NextGen soil moisture, snow water equivalent, and precipitation outputs into formats suitable for comparison to observations.

### Overview

Functionality is organized into by variable of interest and postprocessing method:

| Variable | Method | Module | Entry point | Variable | Observed reference
|---|---|---|---|---|---|
| Soil Moisture | Time Series | `soil_moisture.timeseries.timeseries` | `soil_moisture_ts()` | Soil moisture (m3/m3) | SMAP L4 |
| Soil Moisture | Mapping | `soil_moisture.mapping.mapper` | `map_soil_moisture_data()` | Soil moisture (m3/m3) | SMAP L4 (gridded) |
| SWE | Time Series | `swe.timeseries.timeseries` | `swe_ts()` | Snow water equivalent (m) | SNODAS, SNOTEL optional |
| SWE | Mapping | `swe.mapping.mapper` | `map_swe_data()` | Snow water equivalent (m) | SNODAS (gridded) |
| Precipitation | Time Series | `precip.timeseries.timeseries` | `precip_ts()` | Rain + melt input (mm/hr) | simulated only |
| Precipitation | Plotting | `precip.plotting.plotter` | `plot_precip_streamflow()` | Rain + melt input (mm/hr)  vs. streamflow | simulated only |

Soil moisture and SWE share both a common time series pipeline (`data_assimilation_engine/utils/timeseries.py`) and a common mapping pipeline (`data_assimilation_engine/utils/mappers.py`). 
Precipitation is structurally different from both and is documented as its own group below.

### Configuration
Observed reference data (SNOTEL, SNODAS, SMAP) is read from S3 under a shared root prefix:

```
ngwpc-dev/nwm-tools/data/
- snotel_csv/   # SNOTEL station observations - timeseries, SWE
- snodas_csv/   # SNODAS gridded observations (basin-averaged) - timeseries, SWE
- snodas_nc/    # SNODAS gridded observations (raw netCDF) - mapping, SWE
- smap_csv/     # SMAP L4 gridded observations (basin-averaged) - timeseries, soil moisture
- smap_nc/      # SMAP L4 gridded observations (raw netCDF) - mapping, soil moisture
```

By default, the soil moisture and SWE modules look for this data under a local mount point, set with the `S3_MOUNT_POINT` environment variable (defaults to `~/s3`). Pass `--direct_s3` to read directly from S3 via `fsspec` instead of local mount.

Within a given prefix, observed files following the naming convention `gages-{basin_id}_{variable_name}.csv` (e.g. `gages-09359500_swe.csv`). `basin_id` is parsed from geopackage filename passed in.

### Time Series (Soil Mositure & SWE)

Reads ngen catchment output, computes an area-weighted basin average, pulls the matching observed dataset for the basin from S3, and writes a comparison CSV and/or PNG plot.

#### Common inputs
Both Soil Moisture and SWE pipelines take the same two required inputs:

- **`csv_directory`** - a directory of ngen catchmout output CSV, one per catchment, named `cat-{id}.csv`. NetCDF outputs are not supported.
- **`gpkg_file`** - a hydrofabric geopackage with a `dvidies` layer hold catchment geometries and areas. Used to compute area-weighted basin average and to locate stations within the basin.

Both pipelines also take the same optional flags
- **`--plot output PATH` - save a png comparion plot (simulated vs observed) to `PATH`
- **`--csv_output PATH` - save the basin-averaged time series to `PATH` as CSV
- **`--direct_s3` - read observed data directly from S3 instead of the local mount

#### Soil Moisture
Requires catchment CSV to contain one of more columns matching `sm_profile_<depth>` (e.g. `sm_profile_0_1m). Depths are parsed from the column names and used to compute a thickness-weighted average across the soil profile. 
Output is snapped to SMAP's 3-hourly cadence (01Z, 04Z, 07Z, ...).

```bash
python -m data_assimilation_engine.soil_moisture.timeseries.timeseries \
  sample_data/sample_csv/09359500 \
  sample_data/sample_gpkg/gauge_09359500.gpkg \
  --plot_output sample_data/comb_plot_soil_moisture.png \
  --csv_output sample_data/comb_table_soil_moisture.csv \
  --direct_s3
```

#### SWE
Requires each catchment CSV to contain either `swe_m` or `swe_mm`. Output is daily, snapped to 06Z.

```bash
python -m data_assimilation_engine.swe.timeseries.timeseries \
  sample_data/sample_csv/09359500 \
  sample_data/sample_gpkg/gauge_09359500.gpkg \
  --plot_output sample_data/comb_plot_swe.png \
  --csv_output sample_data/comb_table_swe.csv \
  --direct_s3
```

In addition to the basin-averaged SNODAS comparison, SWE overlays individual SNOTEL station observations for any stations located within the basin geometry.

#### Outputs
- **CSV** - `timestamp`, `Simulated_<Variable>` and `<ObsDataset>_<Variable>` columns, plus one additional column per SNOTEL station for SWE.
- **PNG** - simlated, observed, and (for SWE) station-level series overlain.

### Mapping (Soil Mositure & SWE)

Produces single-date spatial maps, via `map_soil_moisture_data()` and `map_swe_data()`. Both take the same arguments and run the same three stage pipeline:
1. Convert the ngen catchment CSVs in `sim_csv_dir` to a single netCDF file for the given `date`.
2. The matching gridded observed dataset (SMAP or SNODAS) is rendered two ways: a raw map at native grid resolution (`raw_output`) and a spatially averaged map to the catchment polygons from `gpkg_file` (`lumped_output`).
3. The converted `sim_netcdf` is read back, joined to the catchment polygons, and rendered as a simulated map (`sim_lumped_output`)

Observed gridded data for mapping is read froma separate netCDF S3 prefix (`smap_nc` / `snodas_nc`) from the CSV prefix (`smap_csv` / `snodas_csv`) used by the time series modules.

#### Common inputs
Both mappers take the same positional arguments, plus the same optional flag:

- **`date`** - date (or datetime for soil moisture) used for all produced maps
- **`sim_csv_dir`** - directory of ngen catchment output CSVs
- **`sim_netcdf`** - path for the intermediate converted netCDF file, writted by the mapper and read back to produce the simulated map
- **`gpkg_file`** - path to the geopackage file with catchment geometries
- **`sim_lumped_output`** - output PNG path for the simulated lumped map
- **`raw_output`** - output PNG path for the raw observed map
- **`lumped_output`** - output PNG path for the lumped observed map
- **`--direct_s3`** - read observed netCDF data directly from S3 instead of the local mount

#### Soil Moisture
```bash
python -m data_assimilation_engine.soil_moisture.mapping.mapper \
  2019-04-01 03:00:00 \
  sample_data/sample_csv/09359500/ \
  sample_data/09359500_soil_moisture.nc \
  sample_data/sample_gpkg/gages-09359500.gpkg \
  sample_data/simulated_soil_moisture_map.png \
  sample_data/raw_soil_moisture_map.png \
  sample_data/lumped_soil_moisture_map.png \
  --direct_s3
```

#### SWE
```bash
python -m data_assimilation_engine.swe.mapping.mapper \
  2019-04-01 \
  sample_data/sample_csv/09359500/ \
  sample_data/09359500_SWE.nc \
  sample_data/sample_gpkg/gages-09359500.gpkg \
  sample_data/simulated_swe_map.png \
  sample_data/raw_swe_map.png \
  sample_data/lumped_swe_map.png \
  --direct_s3
```

#### Outputs
- **PNG** - three maps per run: raw observed, lumped (catchment-averaged) observed, and lumped simulated.
- **NetCDF** - converted simulated dataset, written as an intermediate file and then read back for the simulated map.

### Precipitation
The precipitation pipeline aggregates simulated ngen output directly to produce a plot comparing precipitation (and melt) to streamflow.

#### Timeseries (`precip_ts`)
Aggregates ngen precipitation + melt output across full basin. Takes two required positional arguments:

- **`csv_directory`** - directory containing ngen catchment output CSVs (`cat-*.csv`), each within a `time` and `rainmelt` column
- **`csv_output`** - path where the basin-averaged csv is written

```bash
python -m data_assimilation_engine.precip.timeseries.timeseries \
  sample_data/sample_csv_precip/01123000 \
  sample_data/sample_csv_precip/01123000/precip_timeseries.csv
```

#### Precipitation vs. Streamflow Plot (`plot_precip_streamflow`)
Plots basin-precipitation + melt an an inverted hyetograph against streamflow from validation runs. Takes four positional arguments and one optional flag:

- **`valid_best_file`** - path to the "valid_best" streamflow CSV (`Time`, `sim_flow` columns)
- **`valid_control_file`** - path to the "valid_control" streamflow CSV (`Time`, `sim_flow` columns)
- **`precip_dir`** - directory containing ngen catchment output CSVs (`cat-*.csv`)
- **`output_plot`** - path where output png is saved
- **`--title`** - optional plot title

```bash
python -m data_assimilation_engine.precip.plotting.plotter \
  sample_data/sample_csv_precip/01123000/01223000_output_valid_best.csv \
  sample_data/sample_csv_precip/01123000/01223000_output_valid_control.csv \
  sample_data/sample_csv_precip/01123000/ \
  sample_data/sample_csv_precip/01123000/01223000_precip_streamflow.png \
  --title "USGS 01123000 - Precipitation-Streamflow Comparison"
```

#### Outputs
- **CSV** - (`precip_ts`) - `timestamp` and `rainmelt_mm_hr` columns
- **PNG** - (`plot_precip_streamflow) - two streamflow runs overlaid against an inverted precipitation+melt hyetograph on a secondary axis


## NWM Output Variables Post-Processing Routines

The simulation NetCDF outputs from NGEN and T-Route needs to be post-processed to produce final NWM NetCDF products across various categories - channel, terrain, land and reservoir. This repository uses a set of national reference outputs from nomads (https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod) to extract the metadata for the final NWM output variables. The metadata include information such as the coordinate system variable units, long desriptive name of the NWM variables, fill value, and missing value. It also captures the pixel resolution (for spatial gridded products), origin, NWM output cycle type. The various output cycle types are the names of the folders in the nomads link above.


### Usage

The various capatibilities/workflows for post-processing are listed in `postprocessing_wrapper_sample.py`. The main entrypoint for post-processing routines can be found in `data_assimilation_engine\output_variables\NetCdfProductionManger.py`.

  - The function arguments that require a folder or file can be relative or absolute paths.
  - The allowed actions are specified as the last argument to the entrypoint function `netcdf_production_workflow` in `NetCdfProductionManger.py`.  Those include `"download ", "config", "template", "output", "all", "mosaic"`. Each action performs a specific task.
    - `download`: Downloads national reference NetCDF outputs for the requested output cycle type.
    - `config`: Creates the metadata config json that has metadata information about all NWM products.
    - `template`: Creates template NetCDF files that mimic the national reference NetCDF files but span the extent of the NGEN simulation geopackage
    - `output`: Generates output NetCDF with the simulation computational output values.
    - `all`: Performs all the steps above in series.
    - `mosaic`: Merges multiple geopackage level NetCDF outputs into a single NetCDF dataset.

#### Input Parameters for NetCDF production workflow

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

#### Input Parameters for NetCDF merge/mosaic workflow

  - `netcdf_folder`: Directory containing the netcdf products after all post-processing production runs.
  - `output_folder`: Output directory to save all the combined/mosaiced netcdf outputs.
  - `config_json`: The name of the metadata config file to be created or available from a previous run.
  - `output_cycle_type`: The name of the NWM output cycle for which these products are generated. For example, analysis_assim.
  - `output_cycle_domain`: The domain for which these products are generated. For example, conus.
  - `output_cycle_hour`: The hour in a day (0-23) for which the outputs are produced after simulations are run. For example, 6.

#### Download NOMADS data
```
download_inputs = [
    "sample_data/outputs_root",
    "analysis_assim",
    True,
    "download"
]
netcdf_production_workflow(download_inputs)
```

#### Generate metadata config file
```
build_config_inputs = [
    "sample_data/outputs_root",
    "config"
]
netcdf_production_workflow(build_config_inputs) 
```
#### Create template NetCDF files for 
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

#### Generate NetCDF NWM outputs
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
#### Overall workflow for NetCDF NWM outputs
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
#### Mosaic workflow for domain level NetCDF NWM outputs
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

### Known limitations

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

