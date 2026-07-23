The `rfc_ingestion` folder was copied from the NWM 3.0.6_no_svn repo in the link below:
https://github.com/NGWPC/nwm.v3.0.6_no_svn/tree/main/ush/rfc_ingestion


## 2026 Instructions for Generating Reservoir Gage Data Timeseries NetCDF Files

1. Set up `.env` as needed to support downloading of FTP raw data, then run this to download raw XML files:
```
./data_assimilation_engine/utils/download_ftp.sh
```

2. Edit settings json as needed:

```
data_assimilation_engine/rfc_ingestion/reservoir_gage_data_settings.json
```

3. Run:

```
./data_assimilation_engine/rfc_ingestion/make_reservoir_gage_list.sh
```

4. Make sure the CSV accounts for all gages in the XML files by generating this report and reviewing it:

```
python ./data_assimilation_engine/rfc_ingestion/make_reservoir_gage_id_comparison_report.py
```

5. Convert the XML files to NetCDF with this script, and inspect the logs to see if there were any probems:

```
./data_assimilation_engine/rfc_ingestion/make_time_series_from_pi_xml.sh |& tee xml2netcdf.log
```

6. Copy the output files to s3 (as needed...see the bottom of the previous script).
