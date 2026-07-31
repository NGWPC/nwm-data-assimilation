# Overview
This directory contains Python scripts for downloading and time-slicing real-time streamflow data from the USGS, US Army Corps of Engineers and Environment Canada. The time-slicing scripts process the native files into NetCDF files that can be directly used by T-Route for streamflow data assimilation. These scripts originated from the NWM v3 codebase.

USGS data download: usgs_download/stream_flow_download/usgs_current.py
USGS data time-slice: usgs_download/analysis/make_time_slice_from_usgs_waterml.py
USACE data download: ace_download/stream_flow_download/CWMS_download_current.py
USACE data time-slice: ace_download/analysis/make_time_slice_from_ace_xml.py
Env Canada data download: canada_download/parallel_dm_can.py
Env Canada data time-slice: canada_download/make_time_slice_from_canada.py
NCO Env Canada data Download: nco_canada/streamflow_download/get_station_list.sh,get_canadian_streamgauge.sh  
NCO Env Canada data time-slice: nco_canada/timeslices_scripts/make_time_slice_from_canada.py

# Setting Up Required Python Environment
python -m venv venv-streamflow
source venv-streamflow/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Script Usage
Each script has a help option (-h) for printing usage information.

The USGS streamflow download script (usgs_current.py) runs continuously and downloads the most recent files as they become available. The other streamflow download scripts exit after downloading the latest files available when the script was run. See usgs_download/stream_flow_download/README.TXT

CWMS_download_current.py [-h] [-f FILE_FORMAT] site_file output_dir
make_time_slice_from_ace_xml.py -i <inputdir> -o <outputdir> -s <sitefile>

canadian_flow_retrieval.py -o <outputdir>
make_time_slice_from_canada.py -i <inputdir> -o <outputdir>

See nco_canada/streamflow_download/README.TXT for downloading Canadian gages using NCO's script.
When NCO download script is used, the timeslices should be created using the script in the nco_canada/timeslices_scripts directory.

#### Examples ####
export USGS_API_KEY=[API KEY]
export DCOMROOT=/path/to/dcomroot
export DBNROOT=/path/to/dbnroot
mkdir $DBNROOT/log
python usgs_current.py
python make_time_slice_from_usgs_waterml.py -i ~/usgs_download -o ~/usgs/timeslice

python parallel_dm_can.py -o ~/canada_download
python make_time_slice_from_canada.py -i ~/canada_download -o ~/canada/timeslice

python CWMS_download_current.py -f json site-file.csv ~/usace_download
python make_time_slice_from_ace_xml.py -i ~/usace_download -o ~/usace_timeslice -s site-file.csv

export DCOMROOT=/path/to/dcomroot
export DBNROOT=/path/to/dbnroot
mkdir -p $DCOMROOT/
mkdir -p $DBNROOT/user/can_streamgauge
mkdir -p $DBNROOT/log
mkdir -p $DBNROOT/tmp
cd $DBNROOT/user/can_streamgauge
source /path/to/get_station_list.sh
source /path/to/get_canadian_streamgauge.sh
python make_time_slice_from_canada.py -i $DCOMROOT/YYYYMMDD/can_streamgauge -o ~/canada/timeslice

