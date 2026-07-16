# Overview
This directory contains shell scripts to download Environment Canada streamflow observations in realtime from https://wateroffice.ec.gc.ca/mainmenu/real_time_data_index_e.html. There are two scripts. They are run in twp steps. First, run the `get_station_list.sh` to get a list of station IDs. Than run the `get_canadian_streamgauge.sh` script to download observed values for each of the stations in the list. 

Three types of variables are downloaded, 5(??), 46(water level), and 47(discharge). We use only discharge here.

# Prerequisite

A DBNROOT directory for storing log files, temporary files and the station list file.

A DCOMROOT directory for storing the raw data files.

# Script description
`get_station_list.sh`: This script downloads all station IDs that have observed data for variables 5, 46 and 47. The `stations_all.txt` file in the current directory that contains a list of station IDs is created from this script.
`get_canadian_streamgauge.sh`: This script read the `stations_all.txt` and download observed values fro variables 5, 46, and 47. Save the files in `${YYYYMMDD}/can_streamgauge` under the given `$DBNROOT`.

# Script Usage

## Setup environmental variables
Set the DBNROOT and DCOMROOT environmental variables
For example,

```
export DCOMROOT=/path/to/dcomroot
export DBNROOT=/path/to/dbnroot
```
## Create directories 
```
mkdir -p $DCOMROOT/
mkdir -p $DBNROOT/user/can_streamgauge
mkdir -p $DBNROOT/log
mkdir -p $DBNROOT/tmp
```

## Fetch station IDs

```
cd $DBNROOT/user/can_streamgauge
source /path/to/get_station_list.sh
```
Output file, stations_all.txt, is saved in the current directory, $DBNROOT/user/can_streamgauge 

The log file is saved to the directory at `$DBNROOT/log`. 

## Download the realtime data

```
cd $DBNROOT/user/can_streamgauge
source /path/to/get_canadian_streamgauge.sh
```
The output files files are saved in `$DCOMROOT/${YYYYMMDD}/can_streamgauge` where `${YYYYMMDD}` is current date.

