"""S3 path configuration for ngwpc-forcing datasets."""

# Root bucket prfix for all forcing data
FORCING_ROOT = "ngwpc-dev/nwm-tools-data"

# SWE (SNOTEL observed gage data)
SNOTEL_CSV_PREFIX = f"{FORCING_ROOT}/snotel_csv"

# SWE (SNODAS observed gridded data)
SNODAS_CSV_PREFIX = f"{FORCING_ROOT}/snodas_csv"
SNODAS_NC_PREFIX = f"{FORCING_ROOT}/snodas_nc"

# Soil Moisture (SMAP L4 observed gridded data)
SMAP_CSV_PREFIX = f"{FORCING_ROOT}/smap_csv"
SMAP_NC_PREFIX = f"{FORCING_ROOT}/smap_nc"
