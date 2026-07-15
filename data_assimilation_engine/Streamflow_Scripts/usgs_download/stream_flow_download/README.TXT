# Overview
This directory contains Python scripts to download USGS streamflow observations in realtime. The script runs as a daemon process when it is started. It will continously check the USGS server for any locations that have updated streamflow data since it was last checked, and then download only the updated streamflows.

# Prerequisite
It requires an USGS API Key. USGS API Keys can be obtained from https://api.waterdata.usgs.gov/signup.

A DBNROOT directory for storing log files.

A DCOMROOT directory for storing the raw data files.

# Script description
usgs_current.py: The main driver and the realtime download script using USGS OGC APIs

# Script Usage

## Setup environmental variables
Set the USGS_API_KEY, DBNROOT and DCOMROOT environmental variables
For example,

```
export USGS_API_KEY=[API KEY]
export DCOMROOT=/path/to/dcomroot
export DBNROOT=/path/to/dbnroot
mkdir $DBNROOT/log
```
## Start the daemon script
```
python ./usgs_current.py
```
Output is saved in the directory pointed to by the $DCOMROOT variable.

The log file is saved to the file defined by the $DBNROOT variable. 

# To kill the daemon program

```
ps -ef|grep usgs_current.py
kill -9 `pgrep -f parallel_download_master.py`
```
