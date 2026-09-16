#### OWP Open Source Project Template Instructions

1. Create a new project.
2. [Copy these files into the new project](#installation)
3. Update the README, replacing the contents below as prescribed.
4. Add any libraries, assets, or hard dependencies whose source code will be included
   in the project's repository to the _Exceptions_ section in the [TERMS](TERMS.md).
  - If no exceptions are needed, remove that section from TERMS.
5. If working with an existing code base, answer the questions on the [open source checklist](opensource-checklist.md)
6. Delete these instructions and everything up to the _Project Title_ from the README.
7. Write some great software and tell people about it.

> Keep the README fresh! It's the first thing people see and will make the initial impression.

## Installation

To install all of the template files, run the following script from the root of your project's directory:

```
bash -c "$(curl -s https://raw.githubusercontent.com/NOAA-OWP/owp-open-source-project-template/open_source_template.sh)"
```

----

# NWM Output Variables Post-Processing Routines

**Description**:  The simulation NetCDF outputs from NGEN and T-Route needs to be post-processed to produce final NWM NetCDF products across various categories - channel, terrain, land and reservoir. This repository uses a set of national reference outputs from nomads (https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod) to extract the metadata for the final NWM output variables. The metadata include information such as the coordinate system variable units, long desriptive name of the NWM variables, fill value, and missing value. It also captures the pixel resolution (for spatial gridded products), origin, NWM output cycle. The various output cycles are the names of the folders in the nomads link above.

## Dependencies

  - Python ~= 3.12
  - Key dependencies and packages required are listed in `pyproject.toml`

## Installation

Refer to [INSTALL](INSTALL.md) document to get started on working with routines for producing NWM NetCDF outputs.

## Usage

The various capatibilities/workflows for post-processing are listed in `postprocessing_wrapper_sample.py`. The main entrypoint for post-processing routines can be found in `data_assimilation_engine\output_variables\NetCdfProductionManger.py`
    - The function arguments that require a folder path can be relative or absolute.
    - The allowed actions are specified as the last argument to the entrypoint function `netcdf_production_workflow` in `NetCdfProductionManger.py`.  Those include "download ", "config", "template", "output", "all" and "mosaic". Each action performs a specific task.
         - download: Downloads national reference NetCDF outputs for the requested output cycle.
         - config: Creates the metadata config json that has metadata information about all NWM products.
         - template: Creates template NetCDF files that mimic the national reference NetCDF files but span the extent of the NGEN simulation geopackage
         - output: Generates output NetCDF with the simulation computational output values.
         - all: Performs all the steps above in series.
         - mosaic: Merges multiple geopackage level NetCDF outputs into a single NetCDF dataset.



## Known limitations

Document any known significant shortcomings with the software.


## Getting involved

General instructions on _how_ to contribute can be found in [CONTRIBUTING](CONTRIBUTING.md).

----
## Open source licensing info

1. [TERMS](TERMS.md)
2. [LICENSE](LICENSE)
----

