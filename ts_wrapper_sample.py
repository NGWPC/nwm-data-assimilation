"""Wrapper script to demonstrate the functionality of swe_timeseries.swe_ts."""

from data_assimilation_engine.soil_moisture.timeseries.timeseries import (
    soil_moisture_ts,
)
from data_assimilation_engine.swe.timeseries.timeseries import swe_ts

from data_assimilation_engine.precip.timeseries.timeseries import precip_ts

swe_inputs = [
    "sample_data/sample_csv/09359500",
    "sample_data/sample_gpkg/gauge_09359500.gpkg",
    "--plot_output",
    "sample_data/comb_plot_swe.png",
    "--csv_output",
    "sample_data/comb_table_swe.csv",
    "--direct_s3",
]

swe_ts(swe_inputs)

soil_moisture_inputs = [
    "sample_data/sample_csv/09359500",
    "sample_data/sample_gpkg/gauge_09359500.gpkg",
    "--plot_output",
    "sample_data/comb_plot_soil_moisture.png",
    "--csv_output",
    "sample_data/comb_table_soil_moisture.csv",
    "--direct_s3",
]

soil_moisture_ts(soil_moisture_inputs)

precip_csv_inputs = [
    "/home/jeff.wade/ngwpc/data-assimilation-engine/sample_data/sample_csv_precip/01123000",
    "/home/jeff.wade/ngwpc/data-assimilation-engine/sample_data/sample_csv_precip/01123000/precip_timeseries.csv",
]

precip_ts(precip_csv_inputs)

precip_nc_inputs = [
    "/home/jeff.wade/ngwpc/data-assimilation-engine/sample_data/sample_netcdf/01123000/catchment_output.nc",
    "/home/jeff.wade/ngwpc/data-assimilation-engine/sample_data/sample_netcdf/01123000/precip_timeseries.csv",
]

precip_ts(precip_nc_inputs)
