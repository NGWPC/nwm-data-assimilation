#!/bin/bash
# 
# Usage: Run this from the repo root
#   ./data_assimilation_engine/purge_data.sh
# 

set -euo pipefail
set -x

### delete_dir_backup_to_s3 copies files from the local filesystem to s3, then deletes them locally. This gives you a chance to add a commit for the deletion, before purging from the history.
function delete_dir_backup_to_s3() {
    local local_root=$1
    local readme_content=$2
    local target_s3_root="s3://ngwpc-dev/nwm-data-assimilation/${local_root}"

    aws s3 cp ${local_root}/ ${target_s3_root}/ --recursive
    echo -n "${readme_content}" | aws s3 cp - ${target_s3_root}/README.txt
    rm -rf ${local_root}
}


### git_filter_dir runs git filter-repo to purge the directory from the repo history. This should be called after ``delete_dir_backup_to_s3`` and after adding a commit message about the deletion.
function git_filter_dir() {
    local local_root=$1

    git filter-repo --path "${local_root}/" --invert-paths --force --prune-empty never
    echo "Listing remaining files in git history within ${local_root} (should be empty):"
    git rev-list --objects --all | grep "${local_root}"
}


### Run these, then make a commit for removing the files, then run the actual git filter to purge them from the history.
delete_dir_backup_to_s3 "data_assimilation_engine/rfc_ingestion/testdata" "Data originally sourced from: https://github.com/NGWPC/nwm.v3.0.6_no_svn/tree/main/ush/rfc_ingestion/testdata/"
delete_dir_backup_to_s3 "data_assimilation_engine/Streamflow_Scripts/usgs_download/analysis/test_data" "Removed from nwm-data-assimilation repo on `date +%Y-%m-%d`"
delete_dir_backup_to_s3 "sample_data/sample_csv" "Removed from nwm-data-assimilation repo on `date +%Y-%m-%d`"
delete_dir_backup_to_s3 "sample_data/sample_csv_precip" "Removed from nwm-data-assimilation repo on `date +%Y-%m-%d`"
delete_dir_backup_to_s3 "sample_data/sample_gpkg" "Removed from nwm-data-assimilation repo on `date +%Y-%m-%d`"
delete_dir_backup_to_s3 "sample_data/snotel_data" "Removed from nwm-data-assimilation repo on `date +%Y-%m-%d`"


# ### Purge from history. Before calling these, make commits for the file removals.
# git_filter_dir "data_assimilation_engine/rfc_ingestion/testdata"
# git_filter_dir "data_assimilation_engine/Streamflow_Scripts/usgs_download/analysis/test_data"
# git_filter_dir "sample_data/sample_csv"
# git_filter_dir "sample_data/sample_csv_precip"
# git_filter_dir "sample_data/sample_gpkg"
# git_filter_dir "sample_data/snotel_data"


# After running all of the above, run a git push --force-with-lease to purge the files from the remote.
