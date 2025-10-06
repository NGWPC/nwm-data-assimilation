"""Setup script for the soil_moisture package."""

from setuptools import find_packages, setup

setup(
    name="soil_moisture",
    packages=find_packages(),
    install_requires=[
        "xarray",
        "matplotlib",
        "cartopy",
        "numpy",
        "scipy",
        "geopandas~=1.0",
        "shapely~=2.0",
        "fsspec",
        "pandas",
        "s3fs",
        "dask[complete]",  # Includes Dask core + recommended dependencies
        "distributed",  # Adds support for parallel computing
        "requests",
    ],
    python_requires=">=3.8",
)
