"""Example script to run the SWE and soil moisture mapping process with sample data."""

from data_assimilation_engine.soil_moisture.mapping.mapper import (
    map_soil_moisture_data,
)
from data_assimilation_engine.swe.mapping.mapper import map_swe_data

from data_assimilation_engine.precip.plotting.plotter import plot_precip_streamflow

swe_input = [
    "2019-04-01",
    "sample_data/sample_csv/09359500",
    "sample_data/sample_gpkg/gages-09359500.gpkg",
    "sample_data/simulated_swe_map.png",
    "sample_data/raw_swe_map.png",
    "sample_data/lumped_swe_map.png",
    "--direct_s3",
]

soil_moisture_input = [
    "2019-04-01 03:00:00",
    "sample_data/sample_csv/09359500",
    "sample_data/sample_gpkg/gages-09359500.gpkg",
    "sample_data/simulated_soil_moisture_map.png",
    "sample_data/raw_soil_moisture_map.png",
    "sample_data/lumped_soil_moisture_map.png",
    "--direct_s3",
]

precip_streamflow_input = [
    "sample_data/sample_csv_precip/01123000/01123000_output_valid_best.csv",
    "sample_data/sample_csv_precip/01123000/01123000_output_valid_control.csv",
    "sample_data/sample_csv_precip/01123000/",
    "sample_data/sample_csv_precip/01123000/01123000_precip_streamflow.png",
    "--title",
    "USGS 01123000 - Precipitation-Streamflow Comparison"
]

map_swe_data(swe_input)
map_soil_moisture_data(soil_moisture_input)
plot_precip_streamflow(precip_streamflow_input)
