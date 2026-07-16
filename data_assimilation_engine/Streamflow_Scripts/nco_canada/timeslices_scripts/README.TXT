1) To start the download processes, at the prompt,

./run_canflow.sh

or put this script in a cron job. It will clear the log file every day at 5:28. 

Output is saved in the directory pointed to by the $OUTDIR variable. You can change the output directory by redefining the $OUTDIR variable in run_usgs.sh

The log file is saved to the file defined by the $log variable. You can change the log file by modifying the $log variable in the run_usgs.sh.

The log file is reset daily at 5:28. To change the time, redefine the $RESETLOGAT variable.

2) New to  NWM v3.1:

Since v3.1, a site file is needed to run this download script because the server has been changed to https://wateroffice.ec.gc.ca/mainmenu/real_time_data_index_e.html.

https://wateroffice.ec.gc.ca/services/real_time_data/csv/inline?stations[]=02AB014&parameters[]=47&start_date=2024-04-22%2000:00:00&end_date=2024-04-24%2023:59:59

An example site file can be found in the root directory named NWM_canadian_gage_inputs.txt. When stations are added or removed, this file needs to be uipdated.

NWM uses only stationId start with 02* based on NWM_canadian_gage_inputs.txt file and only use parameter=47 for discharge.
