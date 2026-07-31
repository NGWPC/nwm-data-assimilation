#!/usr/bin/env bash
# 
# Reads individual RFC forecast xml files and the RFC stations csv file.
# Writes timeseries netcdf files.
# 
# Usage:
#   Run from repo root:
#   ./data_assimilation_engine/rfc_ingestion/make_time_series_from_pi_xml.sh
# 

set -euo pipefail

_SETTINGS="data_assimilation_engine/rfc_ingestion/reservoir_gage_data_settings.json"

set -x

rm -rf "`jq -r '.data_dir_out' ${_SETTINGS}`"
mkdir -p "`jq -r '.data_dir_out' ${_SETTINGS}`"

python data_assimilation_engine/rfc_ingestion/make_time_series_from_pi_xml.py \
  -i "`jq -r '.data_dir_in' ${_SETTINGS}`" \
  -o "`jq -r '.data_dir_out' ${_SETTINGS}`" \
  -s "`jq -r '.sites_file' ${_SETTINGS}`"

# # Upload the sites file and the written netcdf files to s3
# aws s3 cp "`jq -r '.sites_file' ${_SETTINGS}`" "`jq -r '.target_s3_root' ${_SETTINGS}`/sites/"
# aws s3 sync "${DATA_DIR_OUT}" "`jq -r '.target_s3_root' ${_SETTINGS}`/timeseries/"
