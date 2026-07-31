# Data Assimilation Pipelines

## Executive Summary

This document describes two related data-assimilation workflows used to produce
**ngenCERF-ready basin time series**:

1. **ISMN Top-1m Soil Moisture Pipeline**
2. **SNODAS SWE NHF Reprocessing Workflow**

Both workflows generate standardized basin-level CSV products that are consumed
by the existing visualization, validation, and data assimilation tools. The
implementations were designed to preserve backward compatibility with the
existing processing pipelines while extending support for new observation
sources.

The README combines architecture, implementation details, and operational
instructions. All commands are intended to be executed from the repository root
unless noted otherwise.

---

# Repository Structure

```text
data_assimilation_engine/
├── soil_moisture/
│   ├── ISMN_preprocessing/
│   ├── timeseries/
│   └── ...
├── swe/
│   ├── SNODAS_preprocessing/
│   ├── nhf_swe_multi_provider_workflow/
│   └── ...
└── utils/
```

---

# 1. ISMN Top-1m Soil Moisture Pipeline

## 1.1 Objective

Construct an ISMN (International Soil Moisture Network) archive and integrate
it into the existing soil-moisture workflow without changing existing modeled
or SMAP processing.

**Key requirement:** represent soil moisture over the **top 1 m (0–1 m)**.

The top-1 m soil column is widely used when comparing land-surface models and
observation products. Where multiple observation depths exist, thickness-
weighted averaging is used to produce a representative value.

## 1.2 Design Principles

- Preserve existing SMAP workflow behavior.
- Preserve backward compatibility.
- Produce the same basin CSV format expected by existing time-series utilities.
- Keep ISMN-specific logic isolated from existing code.

## 1.3 Existing Workflow

Existing soil moisture supports

- modeled profile soil moisture
- SMAP basin observations

Expected basin filename

```text
gages-<basin_id>_soil_moisture.csv
```

Schema

```text
timestamp,basin_avg_soil_moisture
```

## 1.4 Pipeline Overview

```text
Optional Download
        │
Raw .stm Files
        │
ISMN Preprocessor
        │
Normalized Parquet
        │
Top-1m Calculator
        │
Station Time Series
        │
Basin Aggregation
        │
Basin CSV
```

## 1.5 Core Modules

| Module | Responsibility |
|---|---|
| ismn_download.py | Optional staging/synchronization |
| ismn_preprocessor.py | Parse, normalize, basin mapping |
| ismn_top1m.py | QC and top-1 m computation |
| ismn_basin_timeseries.py | Basin aggregation |
| run_ismn_pipeline.py | End-to-end workflow |
| check_ismn_basin_product.py | Validation |
| compare_ismn_vs_model_basin.py | Comparison utilities |

Modified existing modules

- `soil_moisture/timeseries/timeseries.py`
- `utils/timeseries.py`

## 1.6 Running the Pipeline

Display supported options

```bash
python -m data_assimilation_engine.soil_moisture.ISMN_preprocessing.run_ismn_pipeline --help
```

Example

```bash
export ISMN_RAW=/path/to/raw_ismn
export ISMN_GPKG=/path/to/gpkg
export OUTPUT_ROOT=/path/to/output

python -m data_assimilation_engine.soil_moisture.ISMN_preprocessing.run_ismn_pipeline \
  --raw-ismn-source "$ISMN_RAW" \
  --gpkg-source "$ISMN_GPKG" \
  --output-root "$OUTPUT_ROOT"
```

Expected outputs

```text
output_root/
├── ismn_raw/
├── ismn_station_top1m/
├── ismn_csv/
├── ismn_csv_metadata/
└── ismn_basin_summary.csv
```

---

# 2. SNODAS SWE NHF Reprocessing

## 2.1 Objective

Generate basin-average Snow Water Equivalent CSV products from daily SNODAS
NetCDF files and NHF GeoPackages.

Filename

```text
gages-<gage_id>_swe.csv
```

Schema

```text
timestamp,basin_avg_swe
```

Daily timestamps are expected at **06:00:00**.

Interpretation

| Value | Meaning |
|---|---|
| blank | missing source or invalid processing |
| 0.0 | valid snow-free observation |
| positive | valid SWE |

## 2.2 Workflow

```text
NHF GeoPackages
        │
SNODAS NetCDF
        │
Raster Clipping
        │
Area-weighted Average
        │
Basin CSV
```

## 2.3 Main Modules

| Module | Responsibility |
|---|---|
| fetch_nhf_gage_gpkgs.py | Download GeoPackages |
| swe_gage_nhf.py | Compute basin SWE |
| validate_swe_csv_nhf.py | Validation |
| snodas_downloader.sh | Download raw SNODAS |
| snodas_convert.py | Convert raw files |
| run_nhf_swe_reprocess.sh | End-to-end wrapper |

## 2.4 Running the Workflow

Show options

```bash
python -m data_assimilation_engine.swe.SNODAS_preprocessing.swe_gage_nhf --help
```

Wrapper example

```bash
export GAGE_LIST=/path/to/gage_list.txt
export WORK_DIR=/path/to/work
export SNODAS_NC_PREFIX=/path/to/snodas_nc
export OUTPUT_PREFIX=/path/to/output

GAGE_LIST="$GAGE_LIST" \
WORK_DIR="$WORK_DIR" \
SNODAS_NC_PREFIX_CONUS="$SNODAS_NC_PREFIX" \
S3_OUTPUT_PREFIX="$OUTPUT_PREFIX" \
REPORT_S3_PREFIX="" \
bash data_assimilation_engine/swe/nhf_swe_multi_provider_workflow/run_nhf_swe_reprocess.sh
```

Expected outputs

```text
WORK_DIR/
├── nhf_gpkgs/
├── scratch_*/
├── *_manifest.csv
└── *_validation.csv

OUTPUT_PREFIX/
└── <Domain>/<Provider>/gages-*_swe.csv
```

## 2.5 Parallel Processing

For parallel execution:

- split gage lists into non-overlapping shards;
- use a unique `WORK_DIR` per worker;
- use a unique local output directory per worker;
- share the same read-only SNODAS NetCDF directory;
- merge outputs only after all workers finish.

---

# 3. Validation

Validate ISMN products

```bash
python -m data_assimilation_engine.soil_moisture.ISMN_preprocessing.check_ismn_basin_product --help
```

Validate SWE products

```bash
python -m data_assimilation_engine.swe.SNODAS_preprocessing.validate_swe_csv_nhf --help
```

Recommended checks

- timestamps
- duplicate records
- expected gage count
- missing values
- manifest contents

---

# 4. Backward Compatibility

The implementation preserves existing modeled and SMAP workflows.

ISMN support is optional and does not change existing processing when ISMN data
are unavailable.

The SWE workflow continues to produce the same CSV schema expected by existing
downstream tools.

---

# 5. Known Limitations

## ISMN

- Multi-depth observations provide the best top-1 m estimates.
- Some basins may contain no stations.
- Single-depth proxy mode is intended only for exploratory analyses.

## SWE

- Historical source coverage may be incomplete.
- Missing source data produce blank values rather than zero.
- Long-running jobs should preserve local outputs until validation completes.

---

# 6. Operational Checklist

Before processing

- Activate the correct environment.
- Verify required Python packages.
- Run each tool with `--help`.
- Confirm input paths.
- Perform a small smoke test.

After processing

- Validate outputs.
- Verify timestamps.
- Compare expected versus generated gage counts.
- Preserve manifests and validation reports.
- Verify uploaded objects before deleting local results.
