"""Example script to run the SWE and soil moisture mapping process with sample data."""

from data_assimilation_engine.soil_moisture.mapping.mapper import (
    map_soil_moisture_data,
)
from data_assimilation_engine.swe.mapping.mapper import map_swe_data

swe_input = [
    "2019-04-01",
    "sample_data/sample_csv/09359500/",
    "sample_data/09359500_SWE.nc",
    "sample_data/sample_gpkg/gages-09359500.gpkg",
    "sample_data/simulated_swe_map.png",
    "sample_data/raw_swe_map.png",
    "sample_data/lumped_swe_map.png",
    "--direct_s3",
]

soil_moisture_input = [
    "2019-04-01 03:00:00",
    "sample_data/sample_csv/09359500/",
    "sample_data/09359500_soil_moisture.nc",
    "sample_data/sample_gpkg/gages-09359500.gpkg",
    "sample_data/simulated_soil_moisture_map.png",
    "sample_data/raw_soil_moisture_map.png",
    "sample_data/lumped_soil_moisture_map.png",
    "--direct_s3",
]
map_swe_data(swe_input)
map_soil_moisture_data(soil_moisture_input)
