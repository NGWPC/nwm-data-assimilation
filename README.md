# Soil Moisture

This package provides tools for working with soil moisture data, including functions for data ingestion, processing, and analysis. It's a work in progress, but you can run preprocessing and processing following the steps below.

## Installation

Create and activate Conda environment:

```bash
cd soil_moisture
conda env create -f environment.yml
conda activate soil_moisture
```

## Preprocessing Raw Soil Moisture Data

### ISMN Data Preprocessing

Run ISMN Preprocessing with sample data:

```bash
time python -m soil_moisture_preprocessing.ismn_preprocessing.ismn_preprocessor
```

### SMAP Data Preprocessing

## Processing Processed Soil Moisture Data

### ISMN Data Processing

Run ISMN Processing with sample data:

```bash
time python -m utils.ismn_utils
```

### SMAP Data Processing
