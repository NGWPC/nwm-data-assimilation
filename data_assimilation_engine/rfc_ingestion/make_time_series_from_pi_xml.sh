#!/usr/bin/env bash
# 
# Reads individual RFC forecast xml files and the RFC stations csv file.
# Writes timeseries netcdf files.
# 

set -euo pipefail

DATA_DIR_IN=data_assimilation_engine/rfc_ingestion/testdata/
DATA_DIR_OUT=data_assimilation_engine/rfc_ingestion/testdata_out/
SITES_FILE=data_assimilation_engine/rfc_ingestion/RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv

mkdir -p ${DATA_DIR_OUT}

set -x

python data_assimilation_engine/rfc_ingestion/make_time_series_from_pi_xml.py \
  -i ${DATA_DIR_IN} \
  -o ${DATA_DIR_OUT} \
  -s ${SITES_FILE}
