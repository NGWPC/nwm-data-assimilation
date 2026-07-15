#!/bin/sh

#
# Script to pull Canadian streamgauge data using list of stations stored locally
#
##---check if process is already running --------------------
#cb_proc="get_canadian_streamgauge"
#if ps -ef | grep "get_canadian_streamgauge.sh" | grep -v grep > /dev/null
#then
#     echo "[$(date)] : $cb_proc process already running"
#     exit 1
#fi 
##------------------------------------------------------------

YYYYMMDD=`date -u +%Y%m%d`
#DATADIR="/lfs/h1/ops/prod/dcom/${YYYYMMDD}/can_streamgauge"
DATADIR="$DCOMROOT/${YYYYMMDD}/can_streamgauge"

#LDIR="/dfprod/dbnet/user/can_streamgauge"
LDIR="$DBNROOT/user/can_streamgauge"
LOG=$DBNROOT/log/can_streamgauge.log.${YYYYMMDD}

DD1=$(date -u +%Y-%m-%d)
DD2=$(date --date '2 days ago' +%Y-%m-%d)

url_start="https://wateroffice.ec.gc.ca/services/real_time_data/csv/inline?stations[]="
url_end="&parameters[]=5&parameters[]=46&parameters[]=47&start_date="${DD2}"%2000:00:00&end_date="${DD1}"%2023:59:59"

# DECODER="/lfs/h1/ops/prod/decoders/decod_dcwcan/scripts/copy_and_run_dcwcan.sh"

if [ ! -d ${DATADIR} ]; then
  mkdir -p -m 775 ${DATADIR}
fi

## Data pull
########################################

stations_file="stations_all.txt"
nstations=$(cat ${LDIR}/${stations_file} | wc -l)

for i in `seq $nstations`
  do
  station=$(cat ${LDIR}/${stations_file} | head -${i} | tail -1)
  curl_str=$(echo ${url_start}${station}${url_end})
  local_filename=${station}"_hydrometric.csv"

  output=`curl -w "%{size_download}\n" -s -o ${DATADIR}/${local_filename} ${curl_str}`
  # options: w=output file size, s=silent/no output to terminal, o=specify local file name
  # removed option: R=use upstream file timestamp. The same as local since URL-generated file 

  if [ "${output}" -gt 0 ]; then
    echo 'Successful pull, station ' ${station} 'at ' $(date -u +%Y%m%d-%H:%M:%S) >> ${LOG}
    touch $DBNROOT/tmp/can_streamgauge
    decoder=1
  else
    echo 'Not pulled, station ' ${station} 'at ' $(date -u +%Y%m%d-%H:%M:%S) >> ${LOG}
  fi

done

### Run decoder
#########################################
#
## Run the decoder if a new file was pulled
#if [ "${decoder}" == 1 ]; then
#        ${DECODER} "${DATADIR}"
#fi

echo 'Pull complete'
