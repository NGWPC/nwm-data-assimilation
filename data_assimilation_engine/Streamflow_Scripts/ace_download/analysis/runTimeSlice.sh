#!/usr/bin/env bash
wkDir=$(pwd)
cd $wkDir
if [ ! -d output ]; then mkdir -p outputs; fi
rm -f ace.log
time python make_time_slice_from_ace.py \
	       -i rawdatafiles \
	       -o outputs \
	       -s $wkDir/site-file.csv >> ace.log 2>&1
