#!/usr/bin/env bash
set -euo pipefail

# Reprocess SNODAS SWE for NHF gages.
# Required environment variables:
#   GAGE_LIST             path to USGS_gages.txt
# Optional environment variables:
#   WORK_DIR              default: /tmp/nhf_swe_work
#   ENVIRONMENT           Icefabric API env: oe or test, default: oe
#   SNODAS_NC_PREFIX_CONUS default: s3://ngwpc-forcing/snodas_nc_v4
#   SNODAS_NC_PREFIX_ALASKA default: same as CONUS unless set
#   SNODAS_NC_PREFIX_HAWAII default: same as CONUS unless set
#   S3_OUTPUT_PREFIX      default: s3://ngwpc-forcing/snodas_csv_nhf
#   START_DATE            default: 2009-12-09
#   END_DATE              default: 2025-01-30
#   LIMIT                 optional small test limit for gage fetch only

if [[ -z "${GAGE_LIST:-}" ]]; then
  echo "ERROR: set GAGE_LIST=/path/to/USGS_gages.txt" >&2
  exit 1
fi

WORK_DIR="${WORK_DIR:-/tmp/nhf_swe_work}"
ENVIRONMENT="${ENVIRONMENT:-oe}"
START_DATE="${START_DATE:-2009-12-09}"
END_DATE="${END_DATE:-2025-01-30}"
S3_OUTPUT_PREFIX="${S3_OUTPUT_PREFIX:-s3://ngwpc-forcing/snodas_csv_nhf}"
SNODAS_NC_PREFIX_CONUS="${SNODAS_NC_PREFIX_CONUS:-s3://ngwpc-forcing/snodas_nc_v4}"
SNODAS_NC_PREFIX_ALASKA="${SNODAS_NC_PREFIX_ALASKA:-$SNODAS_NC_PREFIX_CONUS}"
SNODAS_NC_PREFIX_HAWAII="${SNODAS_NC_PREFIX_HAWAII:-$SNODAS_NC_PREFIX_CONUS}"

mkdir -p "$WORK_DIR"

FETCH_ARGS=(
  --gage-list "$GAGE_LIST"
  --output-dir "$WORK_DIR/nhf_gpkgs"
  --environment "$ENVIRONMENT"
  --source nhf
  --domains CONUS Alaska Hawaii
  --manifest "$WORK_DIR/nhf_gpkg_fetch_manifest.csv"
)
if [[ -n "${LIMIT:-}" ]]; then
  FETCH_ARGS+=(--limit "$LIMIT")
fi

python -m data_assimilation_engine.swe.SNODAS_preprocessing.fetch_nhf_gage_gpkgs "${FETCH_ARGS[@]}"

for DOMAIN in CONUS Alaska Hawaii; do
  case "$DOMAIN" in
    CONUS) SNODAS_PREFIX="$SNODAS_NC_PREFIX_CONUS" ;;
    Alaska) SNODAS_PREFIX="$SNODAS_NC_PREFIX_ALASKA" ;;
    Hawaii) SNODAS_PREFIX="$SNODAS_NC_PREFIX_HAWAII" ;;
  esac

  GPKG_DIR="$WORK_DIR/nhf_gpkgs/$DOMAIN"
  if [[ ! -d "$GPKG_DIR" ]] || [[ -z "$(find "$GPKG_DIR" -name '*.gpkg' -print -quit)" ]]; then
    echo "WARNING: no gpkg files found for $DOMAIN at $GPKG_DIR; skipping"
    continue
  fi

  python -m data_assimilation_engine.swe.SNODAS_preprocessing.swe_gage_nhf \
    --gage-gpkg-dir "$GPKG_DIR" \
    --output-dir "$S3_OUTPUT_PREFIX/$DOMAIN" \
    --start-date "$START_DATE" \
    --end-date "$END_DATE" \
    --domain "$DOMAIN" \
    --snodas-nc-prefix "$SNODAS_PREFIX" \
    --scratch-dir "$WORK_DIR/scratch_$DOMAIN" \
    --source-units mm \
    --output-units m \
    --overwrite \
    --manifest-file "$WORK_DIR/swe_nhf_${DOMAIN}_manifest.csv"
done

VALIDATE_ARGS=(
  --csv-prefix "$S3_OUTPUT_PREFIX/CONUS"
  --gage-list "$GAGE_LIST"
  --domains CONUS
  --start-date "$START_DATE"
  --end-date "$END_DATE"
  --report "$WORK_DIR/swe_nhf_CONUS_validation.csv"
)

if [[ -n "${LIMIT:-}" ]]; then
  VALIDATE_ARGS+=(--limit "$LIMIT")
fi

python -m data_assimilation_engine.swe.SNODAS_preprocessing.validate_swe_csv_nhf \
  "${VALIDATE_ARGS[@]}" || true

# Optional: upload manifests and validation reports to S3.
# Example:
#   REPORT_S3_PREFIX=s3://ngwpc-forcing/snodas_csv_nhf/reports
if [[ -n "${REPORT_S3_PREFIX:-}" ]]; then
  echo "Uploading manifests/reports to $REPORT_S3_PREFIX"

  for f in \
    "$WORK_DIR/nhf_gpkg_fetch_manifest.csv" \
    "$WORK_DIR"/swe_nhf_*_manifest.csv \
    "$WORK_DIR"/swe_nhf_*_validation.csv
  do
    if [[ -f "$f" ]]; then
      aws s3 cp "$f" "$REPORT_S3_PREFIX/$(basename "$f")" --only-show-errors
    fi
  done
fi

echo "Done. Manifests and validation reports are in $WORK_DIR"
