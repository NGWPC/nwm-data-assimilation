"""Example script to run the SWE mapping process with sample data."""

from swe_processing.swe_mapping.core.run_swe import map_swe_data

map_swe_data(
    [
        "2015-12-01",
        "swe_processing/sample_data/sample_csv/13240000/",
        "swe_processing/sample_data/13240000.nc",
        "swe_processing/sample_data/sample_gpkg/gages-13240000.gpkg",
        "swe_processing/sample_data/simulated_map.png",
        "swe_processing/sample_data/raw_map.png",
        "swe_processing/sample_data/lumped_map.png",
        "--direct_s3",
    ]
)
