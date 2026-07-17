#!/usr/bin/env bash
# 
# Reads individual RFC forecast xml files.
# Writes a RFC stations csv file.
# 
# Usage:
#   Run from repo root:
#   ./data_assimilation_engine/rfc_ingestion/make_reservoir_gage_list.sh
# 

set -euo pipefail

_SETTINGS="data_assimilation_engine/rfc_ingestion/reservoir_gage_data_settings.json"

DATA_DIR_IN="`jq -r '.data_dir_in' ${_SETTINGS}`"
SITES_FILE="`jq -r '.sites_file' ${_SETTINGS}`"

set -x

python data_assimilation_engine/rfc_ingestion/make_reservoir_gage_list.py -i ${DATA_DIR_IN} -s ${SITES_FILE}
