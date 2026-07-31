# Data Assimilation Pipelines: ISMN Soil Moisture & SWE Reprocessing

## Executive Summary

This document describes two data-assimilation workflows developed for ngenCERF:

1. **ISMN Top-1m Soil Moisture Pipeline** – converts raw International Soil Moisture Network (ISMN) observations into basin-level soil moisture CSVs that are compatible with the existing modeled soil moisture and SMAP workflows.
2. **SWE NHF Reprocessing Workflow** – regenerates basin-average Snow Water Equivalent (SWE) CSVs for NHF gages using SNODAS raster products and NHF GeoPackages.

Both workflows generate standardized basin-level CSV products that are consumed by the existing visualization, validation, and data assimilation tools. The implementations were designed to preserve backward compatibility with the existing processing pipelines while extending support for new observation sources.

This document covers two related data assimilation pipelines used to produce
ngenCERF-ready basin time series:

1. [ISMN Top-1m Soil Moisture Pipeline](#1-ismn-top-1m-soil-moisture-pipeline)
2. [SWE NHF Reprocessing Workflow](#2-swe-nhf-reprocessing-workflow)

---

## 1. ISMN Top-1m Soil Moisture Pipeline

### 1.1 Objective

Construct an ISMN (International Soil Moisture Network) data archive and
integrate it into the ngenCERF soil moisture pipeline, consistent with the
existing SMAP and modeled soil moisture workflows.

**Key requirement:** ISMN data must represent average soil moisture over the
top 1 meter (0–1 m).

The **0–1 m soil column** was selected because it is the standard depth commonly
used for comparison between land-surface models and observation products. When
multiple soil layers are available, they are combined using thickness-weighted
averaging to produce a single representative basin-average soil moisture value.



### 1.1.1 Design Principles

The ISMN integration follows four design principles:

- Preserve the existing SMAP workflow without behavioral changes.
- Produce basin-level CSVs using the same format expected by the existing time-series utilities.
- Keep the implementation backward compatible so existing users do not need to modify their workflows.
- Isolate ISMN-specific functionality from the existing modeled and SMAP processing.

### 1.2 Existing Soil Moisture Workflow (Reference Standard)

The soil moisture pipeline already integrates basin-level soil moisture for:

- **Modeled soil moisture** (`sm_profile_*`) — uses thickness-weighted
  averaging across depth layers, producing `basin_avg_soil_moisture`.
- **SMAP observations** — already available in basin-level CSV format:
  `timestamp, basin_avg_soil_moisture`.

Timeseries integration expects files named:
```
gages-{basin_id}_soil_moisture.csv
```

### 1.3 Pipeline Overview

```
[Optional Download]
        ↓
Raw .stm files
        ↓
ISMN Preprocessor
        ↓
Normalized Parquet Archive
        ↓
Top-1m Calculator
        ↓
Station-Level Time Series
        ↓
Basin Aggregation
        ↓
Basin CSV (ngenCERF-ready)
```

### 1.4 File Structure

**Core pipeline files:**

| File | Responsibility |
|---|---|
| `ismn_download.py` | Optional remote/local sync of `.stm` files (uses `fsspec`) |
| `ismn_preprocessor.py` | `.stm` parsing, normalization, station metadata extraction, spatial mapping to basins, raw parquet archive writing |
| `ismn_top1m.py` | QC filtering, depth overlap computation, thickness-weighted averaging |
| `ismn_basin_timeseries.py` | Aggregates stations → basin, produces final CSV (`timestamp, basin_avg_soil_moisture`) |
| `run_ismn_pipeline.py` | Orchestrates the full workflow: optional download → preprocessing → top-1m computation → basin aggregation |

**Validation & debug tools:**

- `check_ismn_basin_product.py` — validates the raw archive, station top-1m
  output, and basin CSV.
- `compare_ismn_vs_model_basin.py` — compares ISMN vs. modeled soil moisture
  (MAE, RMSE, correlation).

**Modified files:**

- `soil_moisture/timeseries/timeseries.py` — added `gage_ts` → ISMN support.
- `utils/timeseries.py` — replaced hardcoded SWE handling with generic
  variable handling.

### 1.5 How to Run

**Run full pipeline (local files):**
```bash
python -m data_assimilation_engine.soil_moisture.ISMN_preprocessing.run_ismn_pipeline \
  --raw-ismn-source /path/to/raw_ismn \
  --gpkg-source /path/to/gpkg \
  --output-root /path/to/output \
  --target-depth-m 1.0 \
  --min-station-coverage-fraction 0.5 \
  --verbose
```

**Run with download stage:**
```bash
python -m data_assimilation_engine.soil_moisture.ISMN_preprocessing.run_ismn_pipeline \
  --raw-ismn-source s3://bucket/ismn \
  --gpkg-source /path/to/gpkg \
  --output-root /path/to/output \
  --download-first \
  --verbose
```

**Validate one basin:**
```bash
python -m data_assimilation_engine.soil_moisture.ISMN_preprocessing.check_ismn_basin_product \
  --output-root /path/to/output \
  --gage-id 01435000
```

**Compare against model:**
```bash
python -m data_assimilation_engine.soil_moisture.ISMN_preprocessing.compare_ismn_vs_model_basin \
  --output-root /path/to/output \
  --gage-id 01435000 \
  --csv-directory /path/to/ngen_csv \
  --gpkg-file /path/to/gpkg
```

### 1.6 Output Structure

```
output_root/
│
├── ismn_station_index.parquet
│
├── ismn_raw/
│   └── gage_x/
│
├── ismn_station_top1m/
│   └── gage_x/
│
├── ismn_csv/
│   └── gages-{gage_id}_soil_moisture.csv   ← final output
│
├── ismn_csv_metadata/
│
└── ismn_basin_summary.csv
```

### 1.7 Strict Physics vs. Single-Depth Proxy

**Single-depth proxy** is a fallback mode: when a station only reports one
depth (e.g., 0.05 m or 0.20 m), that single value can optionally be used to
approximate the full 0–1 m column average, rather than discarding the
station entirely.

```python
if num_nominal_depths == 1:
    return {
        ...
        "method_used": "single_depth_proxy",
        "valid_thickness_m": 0.0,
        "coverage_fraction": 0.0,
    }
```

| | Strict mode (default) | Proxy mode (`--allow-single-depth-proxy`) |
|---|---|---|
| Physics correct | Yes | No (approximation) |
| Requires multi-depth | Yes | No |
| Produces output | Only if sufficient depth data exists | Always |
| `coverage_fraction` | > 0 required | 0 allowed |
| `method_used` | `interval` / `midpoint` | `single_depth_proxy` |

**Observed behavior with current sample data:**
- Strict mode: 0 station-level top-1m products generated (`ValueError: No
  station-level top-1m products were generated`) — correctly rejected due to
  insufficient depth information.
- Proxy mode: 24 station top-1m rows generated; pipeline completes, but
  values are approximations, not physically integrated top-1m soil moisture.

**Root cause:** the sample ISMN data contains only a single depth per
station with no vertical profile or depth intervals, so
`∫₀¹ᵐ θ(z) dz` cannot be computed directly. This is a data limitation, not a
pipeline defect — the pipeline correctly implements interval integration,
midpoint weighting, QC filtering, and rejection of invalid physics cases.

### 1.8 Status Summary

**Implemented:**
- Raw ISMN ingestion and normalized archive creation
- Depth-aware aggregation logic (interval integration, midpoint weighting)
- Strict physics enforcement, with an optional single-depth proxy fallback
- Basin aggregation pipeline
- Output formats aligned with the existing SMAP/modeled soil moisture system

**Next steps:**
- Source ISMN data with either multiple depths (e.g., 0.05, 0.20, 0.50,
  1.0 m) or explicit depth intervals (e.g., 0–0.1, 0.1–0.3 m, ...)
- Validate any new dataset's depth coverage before running the pipeline

---

## 2. SWE NHF Reprocessing Workflow

### 2.1 Objective

Regenerate Snow Water Equivalent (SWE) CSV time series using NextGen
Hydrofabric (NHF) gage GeoPackages and SNODAS SWE NetCDF data, producing one
SWE CSV per gage:

```
gages-<gage_id>_swe.csv
```

These files support ngenCERF / validation workflows that require SWE data
for NHF gages.

### 2.2 Scripts

| Script | Purpose |
|---|---|
| `run_nhf_swe_reprocess.sh` | Entry point; loops through the gage list |
| `fetch_nhf_gage_gpkgs.py` | Fetches NHF GeoPackages (basin geometry) from Icefabric |
| `nhf_gage_list_utils.py` | Gage-list parsing utilities |
| `swe_gage_nhf.py` | Core per-gage SWE processing |
| `validate_swe_csv_nhf.py` | Validates output CSVs |
| `snodas_downloader.sh` | Downloads SNODAS source data |
| `snodas_convert.py` | Converts `.dat` SNODAS files to NetCDF |

### 2.3 High-Level Workflow

```
NHF gage list
    ↓
Fetch NHF GeoPackages
    ↓
For each gage:
    For each day:
        Download/read SNODAS NetCDF
            ↓
        Clip/intersect basin geometry
            ↓
        Extract SWE grid values
            ↓
        Compute basin-average SWE
            ↓
        Append to CSV
```

Final output format:
```
timestamp,basin_avg_swe
2020-01-01 00:00:00,0.0
2020-01-02 00:00:00,0.0
...
```

### 2.4 SWE Calculation

For each gage and date, the workflow:
1. Reads the NHF GeoPackage divides layer and gets the basin polygon.
2. Opens the daily SNODAS NetCDF file and subsets it to the basin bounding box.
3. Builds SNODAS grid cells and intersects them with the basin polygon.
4. Computes an area-weighted average SWE value:

```
SWE_basin(t) = sum(SWE_cell * overlap_area) / sum(overlap_area)
```

**Note:** SWE = amount of water contained in snowpack (e.g., 100 mm SWE
means 100 mm of water depth if all snow melted). Units are typically mm or
kg/m² (numerically equivalent, since water density ≈ 1000 kg/m³).


---

## Appendix A. Known Limitations

- Current sample ISMN datasets primarily contain single-depth observations.
- Physically correct top-1 m integration requires multiple soil depths or explicit layer intervals.
- Basin-average values depend on station availability within each basin.
- Some basins may legitimately contain no ISMN stations.
- Proxy mode (`--allow-single-depth-proxy`) is intended for exploratory analyses only and should not be used for scientific validation.

## Appendix B. Software Requirements

Recommended Python packages:

- Python 3.10+
- numpy
- pandas
- geopandas
- fsspec
- pyarrow
- shapely
- rasterio

## Appendix C. Downstream Consumers

The generated basin CSV products are consumed by:

- Existing `data_assimilation_engine` time-series utilities.
- ngenCERF visualization workflows.
- Model-versus-observation validation workflows.
- Basin-level calibration and verification tools.
