Variables stored in separate files (CEOP formatted)

Filename
	
	Data_separate_files_startdate(YYYYMMDD)_enddate(YYYYMMDD).zip

	e.g., Data_separate_files_20050316_20050601.zip

	
Folder structure

	Networkname
		Stationname

		
Dataset Filename

	CSE_Network_Station_Variablename_depthfrom_depthto_startdate_enddate.ext

	CSE	- Continental Scale Experiment (CSE) acronym, if not applicable use Networkname
	Network	- Network abbreviation (e.g., OZNET)
	Station	- Station name (e.g., Widgiewa)
	Variablename - Name of the variable in the file (e.g., Soil-Moisture)
	depthfrom - Depth in the ground in which the variable was observed (upper boundary)
	depthto	- Depth in the ground in which the variable was observed (lower boundary)
	startdate -	Date of the first dataset in the file (format YYYYMMDD)
	enddate	- Date of the last dataset in the file (format YYYYMMDD)
	ext	- Extension .stm (Soil Temperature and Soil Moisture Data Set see CEOP standard)

	e.g., OZNET_OZNET_Widgiewa_Soil-Temperature_0.150000_0.150000_20010103_20090812.stm

	
File Content Sample

	2003/12/11 00:30 2003/12/11 00:40 OZNET      OZNET           Widgiewa         -35.09000   146.30600  121.00    0.15    0.15    28.30  U M

	UTC nominal date/time - yyyy/mm/dd HH:MM, where MM is 00 or 30, only
	UTC actual date/time - yyyy/mm/dd HH:MM
	CSE Identifier - Continental Scale Experiment (CSE) acronym, if not applicable use Networkname
	Network	- Network abbreviation (e.g., OZNET)
	Station	- Station name (e.g., Widgiewa)
	Latitude - Decimal degrees. South is negative. 
	Longitude -	Decimal degrees. West is negative.
	Elevation -	Meters above sea level
	Depth from - Depth in the ground in which the variable was observed (upper boundary)
	Depth to - Depth in the ground in which the variable was observed (lower boundary)
	Variable value
	ISMN Quality Flag
	Data Provider Quality Flag, if existing
	

For Definition of the CEOP Data Format see http://www.eol.ucar.edu/projects/ceop/dm/documents/refdata_report/ceop_soils_format.html


Network Information

	SCAN
		Abstract: Soil Climate Analysis Network contains 239 stations all over the USA including stations in Alaska, Hawaii, Puerto Rico or even one in Antarctica. Apart from soil moisture and soil temperature, also precipitation and air temperature are measured. Some stations have also additional measurements of snow depth and snow water equivalent. Almost 150 stations are updated on daily basis. The network is operated by the USDA NRCS National Water and Climate Center with assistance from the USDA NRCS National Soil Survey Center.
		Continent: Americas
		Country: USA
		Stations: 222
		Status: running
Data Range: 

		Type: project
		Url: http://www.wcc.nrcs.usda.gov/
		Reference: Schaefer, G., Cosh, M. & Jackson, T. (2007), ‘The usda natural resources conservation service soil climate analysis network (scan)’, Journal of Atmospheric and Oceanic Technology - J ATMOS OCEAN TECHNOL 24, https://doi.org/10.1175/2007JTECHA930.1;
		Variables: snow water equivalent, precipitation, soil temperature, air temperature, soil moisture, snow depth, 
		Soil Moisture Depths: 0.05 - 0.05 m, 0.10 - 0.10 m, 0.15 - 0.15 m, 0.20 - 0.20 m, 0.25 - 0.25 m, 0.30 - 0.30 m, 0.38 - 0.38 m, 0.51 - 0.51 m, 0.61 - 0.61 m, 0.69 - 0.69 m, 0.76 - 0.76 m, 0.84 - 0.84 m, 0.89 - 0.89 m, 1.02 - 1.02 m, 1.09 - 1.09 m, 1.30 - 1.30 m, 1.42 - 1.42 m
		Soil Moisture Sensors: Hydraprobe Sdi-12, Hydraprobe Analog, n.s., 

	USCRN
		Abstract: Soil moisture NRT network USCRN (Climate Reference Network) in United States;the  datasets of 114 stations were collected and processed by the National Oceanicand Atmospheric Administration"s National Climatic Data Center (NOAA"s NCDC)
		Continent: Americas
		Country: USA
		Stations: 115
		Status: running
		Data Range: from 2009-06-09 
		Type: meteo
		Url: https://www.ncei.noaa.gov/access/crn/
		Reference: Bell, J. E., M. A. Palecki, C. B. Baker, W. G. Collins, J. H. Lawrimore, R. D. Leeper, M. E. Hall, J. Kochendorfer, T. P. Meyers, T. Wilson, and H. J. Diamond. 2013: U.S. Climate Reference Network soil moisture and temperature observations. J. Hydrometeorol., 14, 977-988, https://doi.org/10.1175/JHM-D-12-0146.1;
		Variables: surface temperature, precipitation, soil temperature, air temperature, soil moisture, 
		Soil Moisture Depths: 0.05 - 0.05 m, 0.10 - 0.10 m, 0.20 - 0.20 m, 0.50 - 0.50 m, 1.00 - 1.00 m
		Soil Moisture Sensors: Stevens Hydraprobe II Sdi-12, 

