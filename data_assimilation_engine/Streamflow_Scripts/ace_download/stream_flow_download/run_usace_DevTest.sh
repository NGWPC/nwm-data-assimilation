#!/bin/bash

###############################################################################
#  File name: run_usace.sh                                                    #
#                                                                             #
#  Author     : Zhengtao Cui (Zhengtao.Cui@noaa.gov)                          #
#                                                                             #
#  Initial version date:                                                      #
#                                                                             #
#  Last modification date:  2/11/2020                                         #
#                                                                             #
#                                                                             #
#  Description: Run the US SACE Stream Flow scripts                           #
#               Supported by the NWS Water Predication Center                 #
#                                                                             #
#  OWP   12/12/2024    Change download xml to json data format.               #
#                                                                             #
###############################################################################

module unload python
module load python
module list

#log=$DBNROOT/user/usace_streamflow/parallel_download_master.log
log=/lfs/h1/owp/ptmp/$LOGNAME/usace_streamflow/usace_download.log

SITE_FILE=./site-file.csv

#OUTDIR=$DCOMROOT/${envir}/usace_streamflow
OUTDIR=/lfs/h1/owp/ptmp/$LOGNAME/usace_streamflow

if [ ! -e ${OUTDIR} ]; then mkdir -p ${OUTDIR}; fi

USACE_DOWNLOAD_MASTER=./CWMS_download_current.py

DATE=`/bin/date +%H:%M`

RESETLOGAT="05:28"

if [ "$DATE" = "$RESETLOGAT" ]
then
    echo "Message: reset ${USACE_DOWNLOAD_MASTER} log file"
    rm $log
fi

# Check if process is already running with this package
if pgrep -f ${USACE_DOWNLOAD_MASTER} > /dev/null 2>&1
then
  echo "Message: ${USACE_DOWNLOAD_MASTER} package is running"

else
  echo "Message: ${USACE_DOWNLOAD_MASTER} package NOT running"
  nohup python $USACE_DOWNLOAD_MASTER -f json ${SITE_FILE} ${OUTDIR} >> $log 2>&1 &
  echo "Message: ${USACE_DOWNLOAD_MASTER} package started"
fi
exit
