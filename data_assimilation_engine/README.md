# Data Assimilation Pipelines: ISMN Soil Moisture and SNODAS SWE Reprocessing

## Overview

This document covers two related data-assimilation pipelines used to produce
**ngenCERF-ready basin time series**:

1. [ISMN Top-1m Soil Moisture Pipeline](#1-ismn-top-1m-soil-moisture-pipeline)
2. [SNODAS SWE NHF Reprocessing Workflow](#2-snodas-swe-nhf-reprocessing-workflow)

Both workflows generate standardized basin-level CSV products that are consumed
by the existing visualization, validation, and data assimilation tools. The
implementations preserve backward compatibility with the existing processing
pipelines while extending support for new observation sources.

Run the commands below from the repository root.

---

# 1. ISMN Top-1m Soil Moisture Pipeline

## 1.1 Objective

Construct an ISMN (International Soil Moisture Network) archive and integrate
it into the existing soil-moisture workflow, consistent with the modeled and
SMAP pipelines.

The required product is average soil moisture over the top 1 meter (0–1 m).
When multiple soil depths or intervals are available, the pipeline applies
depth-overlap and thickness-weighted averaging.

## 1.2 Design Principles

- Preserve the existing modeled and SMAP workflows.
- Keep ISMN support optional.
- Produce the same basin-level CSV schema expected by existing time-series
  utilities.
- Avoid hard-coded input and output locations.

## 1.3 Pipeline

```text
Raw ISMN .stm files
        │
        ▼
Normalization and basin mapping
        │
        ▼
Station-level top-1 m calculation
        │
        ▼
Basin aggregation
        │
        ▼
gages-<gage_id>_soil_moisture.csv
```

The final schema is:

```text
timestamp,basin_avg_soil_moisture
```

## 1.4 Main Modules

| Module | Purpose |
|---|---|
| `ismn_download.py` | Optional staging of raw `.stm` files |
| `ismn_preprocessor.py` | Parsing, normalization, metadata extraction, and basin mapping |
| `ismn_top1m.py` | QC and top-1 m computation |
| `ismn_basin_timeseries.py` | Basin aggregation |
| `run_ismn_pipeline.py` | End-to-end orchestration |
| `check_ismn_basin_product.py` | Product validation |
| `compare_ismn_vs_model_basin.py` | Comparison with modeled soil moisture |

## 1.5 Run the Pipeline

Inspect the supported arguments:

```bash
python -m \
  data_assimilation_engine.soil_moisture.ISMN_preprocessing.run_ismn_pipeline \
  --help
```

Set the required paths:

```bash
export ISMN_RAW=/path/to/raw_ismn
export ISMN_GPKG=/path/to/gpkg_or_gpkg_directory
export ISMN_OUTPUT=/path/to/output
```

Run:

```bash
python -m \
  data_assimilation_engine.soil_moisture.ISMN_preprocessing.run_ismn_pipeline \
  --raw-ismn-source "$ISMN_RAW" \
  --gpkg-source "$ISMN_GPKG" \
  --output-root "$ISMN_OUTPUT" \
  --target-depth-m 1.0 \
  --min-station-coverage-fraction 0.5 \
  --min-basin-station-count 1 \
  --basin-aggregation-method mean \
  --verbose
```

For a small smoke test:

```bash
python -m \
  data_assimilation_engine.soil_moisture.ISMN_preprocessing.run_ismn_pipeline \
  --raw-ismn-source "$ISMN_RAW" \
  --gpkg-source "$ISMN_GPKG" \
  --output-root "$ISMN_OUTPUT" \
  --limit-files 20 \
  --verbose
```

## 1.6 Optional Single-Depth Proxy

Strict processing requires sufficient vertical information for a meaningful
top-1 m estimate. For exploratory testing only:

```bash
python -m \
  data_assimilation_engine.soil_moisture.ISMN_preprocessing.run_ismn_pipeline \
  --raw-ismn-source "$ISMN_RAW" \
  --gpkg-source "$ISMN_GPKG" \
  --output-root "$ISMN_OUTPUT" \
  --allow-single-depth-proxy \
  --verbose
```

The single-depth proxy is an approximation and should not be treated as a
physically integrated 0–1 m measurement.

## 1.7 Validate One Basin

```bash
export GAGE_ID=<gage_id>

python -m \
  data_assimilation_engine.soil_moisture.ISMN_preprocessing.check_ismn_basin_product \
  --output-root "$ISMN_OUTPUT" \
  --gage-id "$GAGE_ID" \
  --verbose
```

## 1.8 Output Structure

```text
<ISMN_OUTPUT>/
├── ismn_station_index.parquet
├── ismn_raw/
├── ismn_station_top1m/
├── ismn_csv/
│   └── gages-<gage_id>_soil_moisture.csv
├── ismn_csv_metadata/
└── ismn_basin_summary.csv
```

---

# 2. SNODAS SWE NHF Reprocessing Workflow

## 2.1 Objective

Generate one basin-average Snow Water Equivalent CSV per NHF gage using:

- a provider gage list;
- NHF gage GeoPackages;
- daily SNODAS NetCDF files.

The output filename is:

```text
gages-<gage_id>_swe.csv
```

The output schema is:

```text
timestamp,basin_avg_swe
```

Daily timestamps must be written at `06:00:00`.

A blank SWE field means no valid value was available. A numeric `0.0` means
valid source coverage with zero SWE.

## 2.2 Workflow

```text
Provider gage list
        │
        ▼
Fetch NHF GeoPackages
        │
        ▼
Read daily SNODAS NetCDF files
        │
        ▼
Compute basin-overlap weights
        │
        ▼
Generate basin SWE CSVs
        │
        ▼
Validate expected outputs
```

## 2.3 Main Modules

| Module | Purpose |
|---|---|
| `fetch_nhf_gage_gpkgs.py` | Downloads NHF gage GeoPackages |
| `nhf_gage_list_utils.py` | Parses provider-specific gage lists |
| `swe_gage_nhf.py` | Computes daily basin-average SWE |
| `validate_swe_csv_nhf.py` | Validates expected output files |
| `snodas_downloader.sh` | Downloads raw SNODAS source data |
| `snodas_convert.py` | Converts raw SNODAS data to NetCDF |

## 2.4 Required Variables

Set portable paths and run parameters:

```bash
export GAGE_LIST=/path/to/gage_list.txt
export WORK_DIR=/path/to/work
export OUTPUT_ROOT=/path/to/output
export SNODAS_NC_PREFIX=/path/or/remote/prefix/to/snodas_nc

export DOMAIN=CONUS
export PROVIDER=<provider>
export START_DATE=YYYY-MM-DD
export END_DATE=YYYY-MM-DD
```

Examples of `PROVIDER` include `USGS`, `CADWR`, and `ENVCA`.

## 2.5 Gage List Format

The processing scripts accept plain text gage-list files. Each non-comment line
represents one gage.

Supported format:

```text
<gage_id> <domain> <agency> <enabled>
```

where:

- **gage_id** – Provider-specific gage identifier.
- **domain** – Domain containing the gage (for example, `CONUS`).
- **agency** – Data provider (for example, `USGS`, `CADWR`, or `ENVCA`).
- **enabled** – Optional boolean (`true` or `false`) indicating whether the
  gage should be processed when the `--enabled-only` option is used.

Blank lines and lines beginning with `#` are ignored.

### Example: USGS

```text
01011000 CONUS USGS true
01015800 CONUS USGS true
02236500 CONUS USGS true
08025500 CONUS USGS true
11274790 CONUS USGS true
```

### Example: CADWR

```text
CMF CONUS CADWR true
CHC CONUS CADWR true
CLV CONUS CADWR true
CDR CONUS CADWR true
MCK CONUS CADWR true
```

### Example: ENVCA

```text
02AB021 CONUS ENVCA true
02AC001 CONUS ENVCA true
02AD010 CONUS ENVCA true
02BA003 CONUS ENVCA true
02CF011 CONUS ENVCA true
```

For one-column gage lists, specify the provider and domain using the command-line
options:

```bash
--default-domain CONUS
--default-agency USGS
```

or

```bash
--default-domain CONUS
--default-agency CADWR
```

or

```bash
--default-domain CONUS
--default-agency ENVCA
```

This allows simple lists such as:

```text
01011000
01015800
02236500
08025500
```

to be interpreted correctly.

## 2.6 Step 1: Fetch NHF GeoPackages

Inspect the supported arguments:

```bash
python -m \
  data_assimilation_engine.swe.SNODAS_preprocessing.fetch_nhf_gage_gpkgs \
  --help
```

Run:

```bash
python -m \
  data_assimilation_engine.swe.SNODAS_preprocessing.fetch_nhf_gage_gpkgs \
  --gage-list "$GAGE_LIST" \
  --output-dir "$WORK_DIR/nhf_gpkgs" \
  --environment oe \
  --source nhf \
  --domains "$DOMAIN" \
  --default-domain "$DOMAIN" \
  --default-agency "$PROVIDER" \
  --manifest "$WORK_DIR/nhf_gpkg_fetch_manifest.csv"
```

Add `--enabled-only` when the input list contains enabled/disabled rows and only
enabled entries should be processed.

The expected GeoPackage directory is:

```text
$WORK_DIR/nhf_gpkgs/$DOMAIN/$PROVIDER/
```

## 2.7 Step 2: Generate SWE CSVs

Inspect the supported arguments:

```bash
python -m \
  data_assimilation_engine.swe.SNODAS_preprocessing.swe_gage_nhf \
  --help
```

Run:

```bash
python -m \
  data_assimilation_engine.swe.SNODAS_preprocessing.swe_gage_nhf \
  --gage-gpkg-dir "$WORK_DIR/nhf_gpkgs/$DOMAIN/$PROVIDER" \
  --output-dir "$OUTPUT_ROOT/$DOMAIN/$PROVIDER" \
  --start-date "$START_DATE" \
  --end-date "$END_DATE" \
  --domain "$DOMAIN" \
  --snodas-nc-prefix "$SNODAS_NC_PREFIX" \
  --scratch-dir "$WORK_DIR/scratch_${DOMAIN}_${PROVIDER}" \
  --source-units mm \
  --output-units m \
  --manifest-file "$WORK_DIR/swe_nhf_${DOMAIN}_${PROVIDER}_manifest.csv"
```

Use `--overwrite` only when existing destination files should be replaced.

The generated files are written under:

```text
$OUTPUT_ROOT/$DOMAIN/$PROVIDER/
```

## 2.8 Step 3: Validate SWE CSVs

Inspect the supported arguments:

```bash
python -m \
  data_assimilation_engine.swe.SNODAS_preprocessing.validate_swe_csv_nhf \
  --help
```

Run:

```bash
python -m \
  data_assimilation_engine.swe.SNODAS_preprocessing.validate_swe_csv_nhf \
  --csv-prefix "$OUTPUT_ROOT/$DOMAIN/$PROVIDER" \
  --gage-list "$GAGE_LIST" \
  --domains "$DOMAIN" \
  --agencies "$PROVIDER" \
  --default-domain "$DOMAIN" \
  --default-agency "$PROVIDER" \
  --start-date "$START_DATE" \
  --end-date "$END_DATE" \
  --report "$WORK_DIR/swe_nhf_${DOMAIN}_${PROVIDER}_validation.csv"
```

Add `--enabled-only` when it was also used during GeoPackage retrieval.

## 2.9 Output Structure

```text
$WORK_DIR/
├── nhf_gpkgs/
│   └── <domain>/
│       └── <provider>/
├── scratch_<domain>_<provider>/
├── nhf_gpkg_fetch_manifest.csv
├── swe_nhf_<domain>_<provider>_manifest.csv
└── swe_nhf_<domain>_<provider>_validation.csv

$OUTPUT_ROOT/
└── <domain>/
    └── <provider>/
        └── gages-<gage_id>_swe.csv
```

## 2.10 Parallel Processing

To process several shards concurrently:

- create non-overlapping gage lists;
- use a unique `WORK_DIR` for every worker;
- use a unique `OUTPUT_ROOT` for every worker;
- share only the read-only SNODAS input prefix;
- combine results after every worker finishes;
- check for duplicate filenames before combining.

## 2.11 Preserve Local Outputs

Do not delete a worker directory until its CSVs are safely retained.

When the destination is remote, local generated CSVs are normally available
under:

```text
$WORK_DIR/scratch_<domain>_<provider>/outputs/
```

Copy them to a persistent directory before cleanup:

```bash
export SAVED_OUTPUTS=/path/to/saved_outputs

mkdir -p "$SAVED_OUTPUTS"

find "$WORK_DIR" \
  -path '*/scratch_*/outputs/gages-*_swe.csv' \
  -exec cp -uv {} "$SAVED_OUTPUTS/" \;
```

---

# 3. Backward Compatibility

## ISMN

- Existing modeled soil-moisture processing remains unchanged.
- Existing SMAP processing remains unchanged.
- ISMN loading is optional.

## SWE

- The existing CSV schema remains unchanged.
- Timestamps remain daily at 06Z.
- Input and output locations are supplied through CLI arguments or environment
  variables.
- No project-specific local path or remote bucket is required by this README.

---

# 4. Known Limitations

## ISMN

- True top-1 m integration requires multiple depths or explicit intervals.
- Some basins may contain no usable stations.
- Single-depth proxy mode is approximate.

## SNODAS SWE

- Historical source coverage may be incomplete.
- A source file may exist but contain no valid cells over a basin.
- Missing values must not be converted to zero.
- Long-running jobs should preserve local outputs before cleanup.

---

# 5. Minimal Validation Checklist

Before processing:

```text
[ ] Run each module with --help.
[ ] Confirm the gage-list provider and format.
[ ] Confirm the requested date range exists in the SNODAS input.
[ ] Use explicit work, input, and output paths.
[ ] Run a short smoke test.
```

After processing:

```text
[ ] Compare expected and generated gage IDs.
[ ] Confirm timestamps are at 06:00:00.
[ ] Check duplicate timestamps.
[ ] Review blank, zero, positive, and negative values separately.
[ ] Preserve manifests and validation reports.
[ ] Do not delete local outputs until verification is complete.
```
