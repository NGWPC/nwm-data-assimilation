NWM_VARIABLES_LIST = ['sfcheadsubrt', 'zwattablrt', 'inflow', 'outflow', 'reservoir_assimilated_value', 
'water_sfc_elev', 'nudge', 'qBucket', 'streamflow', 'velocity', 'qBtmVertRunoff', 'qSfcLatRunoff', 
'ACSNOM', 'ACCET', 'SNOWT_AVG', 'EDIR', 'SOILICE', 'SOILSAT_TOP', 'ISNOW', 'QRAIN', 'FSNO', 'SNOWH', 
'SNLIQ', 'SNEQV', 'QSNOW', 'SOIL_T', 'SOIL_M', 'SFCRNOFF', 'ACCECAN', 'ACCEDIR', 'ACCETRAN', 'UGDRNOFF', 
'GRDFLX', 'TRAD', 'FSA', 'CANWAT', 'LH', 'FIRA', 'HFX']

NOMADS_BASE_URL = 'https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod'
NWM_DATA_LOCAL_FOLDER = 'nwm_ref_files'
NWM_NGEN_TEMPLATE_FOLDER = 'ngen_templates'
NWM_NGEN_OUTPUT_FOLDER = 'ngen_outputs'
NWM_OUTPUT_FOLDER = 'nwm_output'
NWM_CONFIG_LOCAL_FOLDER = 'configs'
NWM_CONFIG_FILE_NAME = 'metadata'
NWM_CONFIG_FILE_SUFFIX = '_config'
DIM_TIME = 'time'
DIM_CATCHMENTS = 'catchments'
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
