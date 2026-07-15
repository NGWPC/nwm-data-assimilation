NWM_VARIABLES_LIST = ['sfcheadsubrt', 'zwattablrt', 'inflow', 'outflow', 'reservoir_assimilated_value', 
'water_sfc_elev', 'nudge', 'qBucket', 'streamflow', 'velocity', 'qBtmVertRunoff', 'qSfcLatRunoff', 
'ACSNOM', 'ACCET', 'SNOWT_AVG', 'EDIR', 'SOILICE', 'SOILSAT_TOP', 'ISNOW', 'QRAIN', 'FSNO', 'SNOWH', 
'SNLIQ', 'SNEQV', 'QSNOW', 'SOIL_T', 'SOIL_M', 'SFCRNOFF', 'ACCECAN', 'ACCEDIR', 'ACCETRAN', 'UGDRNOFF', 
'GRDFLX', 'TRAD', 'FSA', 'CANWAT', 'LH', 'FIRA', 'HFX']

NWM_VARS_IGNORE_LIST = ['ACCET', 'ACCECAN', 'ACCEDIR', 'ACCETRAN', 'CANWAT', 'SOILSAT',
                        'EDIR', 'FSA', 'GRDFLX', 'ISNOW', 'UGDRNOFF', 'zwattablrt',
                        'qBtmVertRunoff', 'qSfcLatRunoff']

NWM_PRODUCTS_LIST = ['analysis_assim.land.conus', 'analysis_assim.terrain_rt.conus', 
                     'medium_range_blend.land.conus', 'medium_range_blend.terrain_rt.conus',
                     'medium_range.land_1.conus', 'medium_range.terrain_rt_1.conus',
                     'medium_range.land_2.conus', 'medium_range.terrain_rt_2.conus',
                     'medium_range.land_3.conus', 'medium_range.terrain_rt_3.conus',
                     'medium_range.land_4.conus', 'medium_range.terrain_rt_4.conus',
                     'long_range.land_1.conus', 'long_range.land_2.conus', 'long_range.land_3.conus', 'long_range.land_4.conus', 
                     'short_range.land.conus', 'short_range.terrain_rt.conus']

NOMADS_BASE_URL = 'https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod'
NWM_DATA_LOCAL_FOLDER = 'nwm_ref_files'
NWM_NGEN_TEMPLATE_FOLDER = 'ngen_templates'
NWM_NGEN_OUTPUT_FOLDER = 'ngen_outputs'
NWM_OUTPUT_FOLDER = 'nwm_output'
NWM_CONFIG_LOCAL_FOLDER = 'configs'
NWM_CONFIG_FILE_NAME = 'metadata'
NWM_CONFIG_FILE_SUFFIX = '_config'
LOG_FOLDER = 'logs'
DIM_TIME = 'time'
DIM_CATCHMENTS = 'catchments'
DIM_SOIL_LYR = 'soil_layers_stag'
DIM_SNOW_LYR = 'snow_layers'
NHF_REF_OBJECT = 'reference_flowpaths'
NHF_DIV_ID = 'div_id'
NONNHF_DIV_ID = 'divide_id'
GPKG_DIVIDES_LYR = 'divides'
GPKG_GEOMETRY_TYPE_IDENTIFIER = 'geometry_type'
GPKG_FILE_PREFIX = 'gauge_'
X_LOC = ['x', 'lon', 'longitude']
Y_LOC = ['y', 'lat', 'latitude']
CRS_INFO = ['crs', 'CRS', 'spatial_ref']
JSON_X = 'x'
JSON_Y = 'y'
JSON_FILE_PATH = 'file_path'
JSON_RESOLUTION = 'resolution'
JSON_ORIGIN = 'origin'
JSON_LOC = 'location_name'
JSON_CRS = 'crs_wkt'
JSON_NWM_VAR = 'nwm_variables'
JSON_DIMENSION = 'nwm_dimensions'
JSON_VAR_DIM_MAP = 'nwm_var_dimensions'
JSON_SCALAR_VAR = 'nwm_scalar_variables'
JSON_CLASS = 'class'
JSON_CATEGORY = 'category'
JSON_DOMAIN = 'domain'
CSV_BASE_COLS = ['time step','time'] #use lowercase
