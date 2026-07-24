from data_assimilation_engine.output_variables.NetCdfProductionManager import netcdf_production_workflow

download_inputs = [
    "sample_data/outputs_root",
    "download"
]
netcdf_production_workflow(download_inputs) # download and metadata_config.json creation.

template_inputs = [
    "sample_data/outputs_root",
    "sample_data/ngen_netcdfs/catchment_output_3n.nc"
    "sample_data/sample_gpkg/vpu_3n.gpkg"
    "sample_data/outputs_root/configs/metadata_config.json",
    None,
    "template"
]
# create templates for geopackage extents.
# assumes download is complete and metadata_config.json is available.
netcdf_production_workflow(template_inputs) 

production_inputs = [
    "sample_data/outputs_root",
    "sample_data/ngen_netcdfs/catchment_output_3n.nc"
    "sample_data/sample_gpkg/vpu_3n.gpkg"
    "sample_data/troute_netcdfs/toute_output_3n.nc"
    "sample_data/troute_netcdfs/toute_lakeout_3n.nc"
    "sample_data/outputs_root/configs/metadata_config.json",
    None,
    "output"
]
# create output for geopackage extents.
# assumes that templating is completed. it also means that the metadata_config.json is available.
netcdf_production_workflow(production_inputs) 

overall_workflow_inputs = [
    "sample_data/outputs_root",
    "sample_data/ngen_netcdfs/catchment_output_3n.nc"
    "sample_data/sample_gpkg/vpu_3n.gpkg"
    "sample_data/troute_netcdfs/toute_output_3n.nc"
    "sample_data/troute_netcdfs/toute_lakeout_3n.nc"
    "sample_data/outputs_root/configs/metadata_config.json",
    None,
    "all"
]
# overall workflow for creating products for geopackage extents.
# this downloads the nomads data, creates templates and produces outputs.
netcdf_production_workflow(overall_workflow_inputs)