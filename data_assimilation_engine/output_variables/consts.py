NWM_VARIABLES_LIST = ['sfcheadsubrt', 'zwattablrt', 'inflow', 'outflow', 'reservoir_assimilated_value', 
'water_sfc_elev', 'nudge', 'qBucket', 'streamflow', 'velocity', 'qBtmVertRunoff', 'qSfcLatRunoff', 
'ACSNOM', 'ACCET', 'SNOWT_AVG', 'EDIR', 'SOILICE', 'SOILSAT_TOP', 'ISNOW', 'QRAIN', 'FSNO', 'SNOWH', 
'SNLIQ', 'SNEQV', 'QSNOW', 'SOIL_T', 'SOIL_M', 'SFCRNOFF', 'ACCECAN', 'ACCEDIR', 'ACCETRAN', 'UGDRNOFF', 
'GRDFLX', 'TRAD', 'FSA', 'CANWAT', 'LH', 'FIRA', 'HFX']

NWM_VARS_IGNORE_LIST = ['ACCET', 'ACCECAN', 'ACCEDIR', 'ACCETRAN', 'CANWAT', 'SOILSAT',
                        'EDIR', 'FSA', 'GRDFLX', 'ISNOW', 'UGDRNOFF', 'zwattablrt',
                        'qBtmVertRunoff', 'qSfcLatRunoff']

NOMADS_BASE_URL = 'https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod'
NWM_DATA_LOCAL_FOLDER = 'nwm_ref_files'
NWM_NGEN_TEMPLATE_FOLDER = 'ngen_templates'
NWM_NGEN_OUTPUT_FOLDER = 'ngen_outputs'
NWM_OUTPUT_FOLDER = 'nwm_output'
NWM_MOSAIC_FOLDER = 'nwm_mosaics'
NWM_CONFIG_LOCAL_FOLDER = 'configs'
NWM_CONFIG_FILE_NAME = 'metadata'
NWM_CONFIG_FILE_SUFFIX = '_config'
LOG_FOLDER = 'logs'
DIM_TIME = 'time'
DIM_CATCHMENTS = 'catchments'
DIM_SOIL_LYR = 'soil_layers_stag'
DIM_SNOW_LYR = 'snow_layers'
DIM_FEATURE_ID = 'feature_id'
DIM_REF_TIME = 'reference_time'
NUM_SOIL_LYR = 4
NUM_SNOW_LYR = 1
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
JSON_OUTPUT_CYCLE = 'output_cycle'
JSON_CLASS = 'class'
JSON_CATEGORY = 'category'
JSON_DOMAIN = 'domain'
CSV_BASE_COLS = ['time step','time'] #use lowercase
NC_BATCH_SIZE = 30
NC_SPATIAL_CHUNK_SIZE = 500
VALIDATION_SAMPLE_SIZE = 2

NWM_PRODUCTS_LIST = ['analysis_assim.channel_rt.conus',
                     'analysis_assim.land.conus',
                     'analysis_assim.reservoir.conus',
                     'analysis_assim.terrain_rt.conus',

                     'analysis_assim.channel_rt.alaska',
                     'analysis_assim.land.alaska',
                     'analysis_assim.reservoir.alaska',
                     'analysis_assim.terrain_rt.alaska',

                     'analysis_assim.channel_rt.hawaii',
                     'analysis_assim.land.hawaii',
                     'analysis_assim.reservoir.hawaii',
                     'analysis_assim.terrain_rt.hawaii',

                     'analysis_assim.channel_rt.puertorico',
                     'analysis_assim.land.puertorico',
                     'analysis_assim.reservoir.puertorico',
                     'analysis_assim.terrain_rt.puertorico',

                     'analysis_assim_long.channel_rt.conus',
                     'analysis_assim_long.land.conus',
                     'analysis_assim_long.reservoir.conus',

                     'analysis_assim_extend.channel_rt.conus',
                     'analysis_assim_extend.land.conus',
                     'analysis_assim_extend.reservoir.conus',
                     'analysis_assim_extend.terrain_rt.conus',

                     'analysis_assim_extend.channel_rt.alaska',
                     'analysis_assim_extend.land.alaska',
                     'analysis_assim_extend.reservoir.alaska',
                     'analysis_assim_extend.terrain_rt.alaska',

                     'medium_range_blend.channel_rt.conus',
                     'medium_range_blend.land.conus',
                     'medium_range_blend.reservoir.conus',
                     'medium_range_blend.terrain_rt.conus',

                     'medium_range_blend.channel_rt.alaska',
                     'medium_range_blend.land.alaska',
                     'medium_range_blend.reservoir.alaska',
                     'medium_range_blend.terrain_rt.alaska',

                     'medium_range.channel_rt_1.conus',
                     'medium_range.land_1.conus',
                     'medium_range.reservoir_1.conus',
                     'medium_range.terrain_rt_1.conus',

                     'medium_range.channel_rt_2.conus',
                     'medium_range.land_2.conus',
                     'medium_range.reservoir_2.conus',
                     'medium_range.terrain_rt_2.conus',

                     'medium_range.channel_rt_3.conus',
                     'medium_range.land_3.conus',
                     'medium_range.reservoir_3.conus',
                     'medium_range.terrain_rt_3.conus',

                     'medium_range.channel_rt_4.conus',
                     'medium_range.land_4.conus',
                     'medium_range.reservoir_4.conus',
                     'medium_range.terrain_rt_4.conus',

                     'medium_range.channel_rt_5.conus',
                     'medium_range.land_5.conus',
                     'medium_range.reservoir_5.conus',
                     'medium_range.terrain_rt_5.conus',

                     'medium_range.channel_rt_6.conus',
                     'medium_range.land_6.conus',
                     'medium_range.reservoir_6.conus',
                     'medium_range.terrain_rt_6.conus',

                     'medium_range.channel_rt_1.alaska',
                     'medium_range.land_1.alaska',
                     'medium_range.reservoir_1.alaska',
                     'medium_range.terrain_rt_1.alaska',

                     'medium_range.channel_rt_2.alaska',
                     'medium_range.land_2.alaska',
                     'medium_range.reservoir_2.alaska',
                     'medium_range.terrain_rt_2.alaska',

                     'medium_range.channel_rt_3.alaska',
                     'medium_range.land_3.alaska',
                     'medium_range.reservoir_3.alaska',
                     'medium_range.terrain_rt_3.alaska',

                     'medium_range.channel_rt_4.alaska',
                     'medium_range.land_4.alaska',
                     'medium_range.reservoir_4.alaska',
                     'medium_range.terrain_rt_4.alaska',

                     'medium_range.channel_rt_5.alaska',
                     'medium_range.land_5.alaska',
                     'medium_range.reservoir_5.alaska',
                     'medium_range.terrain_rt_5.alaska',

                     'medium_range.channel_rt_6.alaska',
                     'medium_range.land_6.alaska',
                     'medium_range.reservoir_6.alaska',
                     'medium_range.terrain_rt_6.alaska',

                     'long_range.channel_rt_1.conus',
                     'long_range.land_1.conus',
                     'long_range.reservoir_1.conus',

                     'long_range.channel_rt_2.conus',
                     'long_range.land_2.conus',
                     'long_range.reservoir_2.conus',

                     'long_range.channel_rt_3.conus',
                     'long_range.land_3.conus',
                     'long_range.reservoir_3.conus',

                     'long_range.channel_rt_4.conus',
                     'long_range.land_4.conus',
                     'long_range.reservoir_4.conus',

                     'short_range.channel_rt.conus',
                     'short_range.land.conus',
                     'short_range.reservoir.conus',
                     'short_range.terrain_rt.conus',

                     'short_range.channel_rt.alaska',
                     'short_range.land.alaska',
                     'short_range.reservoir.alaska',
                     'short_range.terrain_rt.alaska',

                     'short_range.channel_rt.puertorico',
                     'short_range.land.puertorico',
                     'short_range.reservoir.puertorico',
                     'short_range.terrain_rt.puertorico',

                     'short_range.channel_rt.hawaii',
                     'short_range.land.hawaii',
                     'short_range.reservoir.hawaii',
                     'short_range.terrain_rt.hawaii',
                     ]
