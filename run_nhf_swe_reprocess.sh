#!/usr/bin/env bash
set -euo pipefail

# Reprocess SNODAS SWE for NHF gages from one or more provider lists.
# Required:
#   GAGE_LIST or GAGE_LISTS    one or more paths. GAGE_LISTS may be colon-separated or space-separated.
# Optional:
#   WORK_DIR                   default: /tmp/nhf_swe_work
#   ENVIRONMENT                Icefabric API env: oe or test, default: oe
#   DOMAINS                    default: "CONUS Alaska Hawaii"
#   DEFAULT_DOMAIN             domain for one-column lists, default: CONUS
#   DEFAULT_AGENCY             agency fallback, default: inferred from filename
#   ENABLED_ONLY               true/false, default: false
#   SNODAS_NC_PREFIX_CONUS     default: s3://ngwpc-forcing/snodas_nc_v4
#   SNODAS_NC_PREFIX_ALASKA    default: same as CONUS unless set
#   SNODAS_NC_PREFIX_HAWAII    default: same as CONUS unless set
#   S3_OUTPUT_PREFIX           default: s3://ngwpc-forcing/snodas_csv_nhf
#   REPORT_S3_PREFIX           optional s3:// prefix for manifests/reports
#   START_DATE                 default: 2009-12-09
#   END_DATE                   default: 2025-01-30
#   LIMIT                      optional small test limit, applied to fetch and validation

if [[ -z "${GAGE_LIST:-}" && -z "${GAGE_LISTS:-}" ]]; then
  echo "ERROR: set GAGE_LIST=/path/to/list.txt or GAGE_LISTS='/path/a.txt:/path/b.txt'" >&2
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
DEFAULT_DOMAIN="${DEFAULT_DOMAIN:-CONUS}"
DEFAULT_AGENCY="${DEFAULT_AGENCY:-}"
DOMAINS="${DOMAINS:-CONUS Alaska Hawaii}"
ENABLED_ONLY="${ENABLED_ONLY:-false}"

mkdir -p "$WORK_DIR"

# Build gage-list array. Supports colon-separated GAGE_LISTS or whitespace-separated values.
GAGE_LIST_ARGS=()
if [[ -n "${GAGE_LISTS:-}" ]]; then
  if [[ "$GAGE_LISTS" == *":"* ]]; then
    IFS=':' read -r -a GAGE_LIST_ARGS <<< "$GAGE_LISTS"
  else
    # shellcheck disable=SC2206
    GAGE_LIST_ARGS=( $GAGE_LISTS )
  fi
else
  GAGE_LIST_ARGS=( "$GAGE_LIST" )
fi

# shellcheck disable=SC2206
DOMAIN_ARGS=( $DOMAINS )

FETCH_ARGS=(
  --gage-list "${GAGE_LIST_ARGS[@]}"
  --output-dir "$WORK_DIR/nhf_gpkgs"
  --environment "$ENVIRONMENT"
  --source nhf
  --domains "${DOMAIN_ARGS[@]}"
  --default-domain "$DEFAULT_DOMAIN"
  --manifest "$WORK_DIR/nhf_gpkg_fetch_manifest.csv"
)
if [[ -n "$DEFAULT_AGENCY" ]]; then
  FETCH_ARGS+=(--default-agency "$DEFAULT_AGENCY")
fi
if [[ "$ENABLED_ONLY" == "true" ]]; then
  FETCH_ARGS+=(--enabled-only)
fi
if [[ -n "${LIMIT:-}" ]]; then
  FETCH_ARGS+=(--limit "$LIMIT")
fi

python -m data_assimilation_engine.swe.SNODAS_preprocessing.fetch_nhf_gage_gpkgs "${FETCH_ARGS[@]}"

# Process every domain/provider directory that actually has gpkg files.
for DOMAIN_DIR in "$WORK_DIR"/nhf_gpkgs/*; do
  [[ -d "$DOMAIN_DIR" ]] || continue
  DOMAIN="$(basename "$DOMAIN_DIR")"

  case "$DOMAIN" in
    CONUS) SNODAS_PREFIX="$SNODAS_NC_PREFIX_CONUS" ;;
    Alaska) SNODAS_PREFIX="$SNODAS_NC_PREFIX_ALASKA" ;;
    Hawaii) SNODAS_PREFIX="$SNODAS_NC_PREFIX_HAWAII" ;;
    *)
      echo "WARNING: no SNODAS prefix configured for domain $DOMAIN; skipping"
      continue
      ;;
  esac

  for PROVIDER_DIR in "$DOMAIN_DIR"/*; do
    [[ -d "$PROVIDER_DIR" ]] || continue
    PROVIDER="$(basename "$PROVIDER_DIR")"

    if [[ -z "$(find "$PROVIDER_DIR" -name '*.gpkg' -print -quit)" ]]; then
      echo "WARNING: no gpkg files found for $DOMAIN/$PROVIDER at $PROVIDER_DIR; skipping"
      continue
    fi

    python -m data_assimilation_engine.swe.SNODAS_preprocessing.swe_gage_nhf \
      --gage-gpkg-dir "$PROVIDER_DIR" \
      --output-dir "$S3_OUTPUT_PREFIX/$DOMAIN/$PROVIDER" \
      --start-date "$START_DATE" \
      --end-date "$END_DATE" \
      --domain "$DOMAIN" \
      --snodas-nc-prefix "$SNODAS_PREFIX" \
      --scratch-dir "$WORK_DIR/scratch_${DOMAIN}_${PROVIDER}" \
      --source-units mm \
      --output-units m \
      --manifest-file "$WORK_DIR/swe_nhf_${DOMAIN}_${PROVIDER}_manifest.csv"
  done
done

# Validate per domain/provider output prefix. This avoids 404 spam during LIMIT tests.
for DOMAIN_DIR in "$WORK_DIR"/nhf_gpkgs/*; do
  [[ -d "$DOMAIN_DIR" ]] || continue
  DOMAIN="$(basename "$DOMAIN_DIR")"

  for PROVIDER_DIR in "$DOMAIN_DIR"/*; do
    [[ -d "$PROVIDER_DIR" ]] || continue
    PROVIDER="$(basename "$PROVIDER_DIR")"
    [[ -n "$(find "$PROVIDER_DIR" -name '*.gpkg' -print -quit)" ]] || continue

    VALIDATE_ARGS=(
      --csv-prefix "$S3_OUTPUT_PREFIX/$DOMAIN/$PROVIDER"
      --gage-list "${GAGE_LIST_ARGS[@]}"
      --domains "$DOMAIN"
      --agencies "$PROVIDER"
      --default-domain "$DEFAULT_DOMAIN"
      --start-date "$START_DATE"
      --end-date "$END_DATE"
      --report "$WORK_DIR/swe_nhf_${DOMAIN}_${PROVIDER}_validation.csv"
    )
    if [[ "$ENABLED_ONLY" == "true" ]]; then
      VALIDATE_ARGS+=(--enabled-only)
    fi
    if [[ -n "${LIMIT:-}" ]]; then
      VALIDATE_ARGS+=(--limit "$LIMIT")
    fi

    python -m data_assimilation_engine.swe.SNODAS_preprocessing.validate_swe_csv_nhf "${VALIDATE_ARGS[@]}" || true
  done
done

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
