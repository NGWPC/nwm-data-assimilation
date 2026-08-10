#!/bin/bash
# 
# Usage:
#   Run this from the repo root, after making a fresh clone and editing the vars near the top of the script.
#   Note that there is a "pause point" in this script after the calls to `git filter-repo`, this is so the
#   operator of the script reviews the state of things before force-pushing a history rewrite.
#
#   The BRANCH_TO_PURGE is parameterized as CLI arg $1 since the git filter-repo call will revert this file
#   when it runs (it will not work to store a value in this file as a hard-coded variable).
#
#   You may need to install `git filter-repo` first, e.g. `sudo apt install git-filter-repo` or via pip.
# 


set -euo pipefail
set -x


GH_ORG=ngwpc
BRANCH_TO_PURGE=$1
ORIGIN=https://github.com/${GH_ORG}/nwm-data-assimilation.git


### backup_to_s3 copies files from the local filesystem to s3, then deletes them locally. This gives you a chance to add a commit for the deletion, before purging from the history.
function backup_to_s3() {
    local local_root=$1
    local readme_content=$2
    local target_s3_root="s3://ngwpc-dev/nwm-data-assimilation/${local_root}"

    aws s3 cp ${local_root}/ ${target_s3_root}/ --recursive
    echo -n "${readme_content}" | aws s3 cp - ${target_s3_root}/README.txt
    # rm -rf ${local_root}
}


### These commands back up the files that are currently in the working tree by copying them to S3.
### If someone already ran this in another branch, then there is no need to run it again.
# backup_to_s3 "data_assimilation_engine/rfc_ingestion/testdata" "Data originally sourced from: https://github.com/NGWPC/nwm.v3.0.6_no_svn/tree/main/ush/rfc_ingestion/testdata/"
# backup_to_s3 "data_assimilation_engine/Streamflow_Scripts/usgs_download/analysis/test_data" "Backed up from nwm-data-assimilation repo on `date +%Y-%m-%d`"
# backup_to_s3 "sample_data/sample_csv" "Backed up from nwm-data-assimilation repo on `date +%Y-%m-%d`"
# backup_to_s3 "sample_data/sample_csv_precip" "Backed up from nwm-data-assimilation repo on `date +%Y-%m-%d`"
# backup_to_s3 "sample_data/sample_gpkg" "Backed up from nwm-data-assimilation repo on `date +%Y-%m-%d`"
# backup_to_s3 "sample_data/snotel_data" "Backed up from nwm-data-assimilation repo on `date +%Y-%m-%d`"


### Purge the data files, then confirm that the git dir becomes small.
git fetch
git checkout ${BRANCH_TO_PURGE}
git filter-repo \
    --path "data_assimilation_engine/rfc_ingestion/testdata/" \
    --path "data_assimilation_engine/Streamflow_Scripts/ace_download/analysis/old/test_data/" \
    --path "ngwpc/nwm-data-assimilation/data_assimilation_engine/Streamflow_Scripts/ace_download/analysis/old/test_data/" \
    --path "data_assimilation_engine/Streamflow_Scripts/usgs_download/analysis/test_data/" \
    --path "ngwpc/nwm-data-assimilation/data_assimilation_engine/Streamflow_Scripts/usgs_download/analysis/test_data/" \
    --path "swe_processing/sample_data/" \
    --path "sample_data/" \
    --invert-paths \
    --force

### Should be small
du -sh .git
### Should be empty or near-empty
git rev-list --objects --all | grep data/ || true

### Pause point before pushing new history to remote
echo "At pause point -- exiting. Operator should review script carefully before running the rest of it." && exit 1

### git filter-repo also clears out remotes etc. Reinstate the origin, fetch, and force-push the new history of this branch.
git remote add origin ${ORIGIN}
git fetch
git branch --set-upstream-to=origin/${BRANCH_TO_PURGE} ${BRANCH_TO_PURGE}
git push --force
### Go ahead and reinstate the development branch remote assignment.
git branch --set-upstream-to=origin/development development

### Whenever ready, standard rebases against origin/development from here
### should not have extra complication from history rewrite,
### since the data files were already purged from both.
# git rebase origin/development
# git push --force-with-lease
