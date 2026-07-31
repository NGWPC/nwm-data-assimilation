#!/usr/bin/env bash
# 
# Downloads data from FTP server to a local directory, recursively, via ``wget``.
# 
# Usage:
#   1. Provide OS env vars: FTP_URL, FTP_DIR, FTP_USER, FTP_PASS
#   2. Run with CLI args:
#       1: (required) output local directory
#       2: (optional) value for --accept (glob include pattern for files on the server to get). If not provided, everything from FTP_DIR will be gotten.
# 
# Examples:
#   Download all xml files for reservoir "MARFC" into relative local dir "foo/bar/":
#       source .env && export FTP_URL FTP_DIR FTP_USER FTP_PASS && ./data_assimilation_engine/utils/download_ftp.sh "foo/bar/" '*_MARFC_*.xml'
#   Download all xml files into "data_assimilation_engine/rfc_ingestion/testdata/":
#       source .env && export FTP_URL FTP_DIR FTP_USER FTP_PASS && ./data_assimilation_engine/utils/download_ftp.sh "data_assimilation_engine/rfc_ingestion/testdata/" '*.xml'
# 
# Notes:
#   wget makes local dir trees automatically, no need to run `mkdir -p`.
#   The URL should not contain the "ftp://" prefix. That is prepended by the script.
# 

set -euo pipefail

_TARGET_LOCAL_DIR=$1
_ACCEPT_PATTERN=${2:-""}
_EXTRA_FLAGS=()

if [ "$_ACCEPT_PATTERN" != "" ]; then
    _EXTRA_FLAGS+=("--accept")
    _EXTRA_FLAGS+=("${_ACCEPT_PATTERN}")
fi

echo "Downloading from: ftp://${FTP_URL}${FTP_DIR} to: ${_TARGET_LOCAL_DIR} with extra flags: ${_EXTRA_FLAGS[@]}"

wget -m --user="${FTP_USER}" --password="${FTP_PASS}" \
    -P ${_TARGET_LOCAL_DIR} \
    -nH \
    --remove-listing \
    ${_EXTRA_FLAGS[@]} \
    ftp://${FTP_URL}${FTP_DIR}
