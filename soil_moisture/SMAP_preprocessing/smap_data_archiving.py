import glob
import json
import os
from datetime import datetime, timedelta
from functools import lru_cache

import boto3
import earthaccess
import fsspec
import numpy as np
import pygeohydro as gh
import ujson
import xarray as xr
from dotenv import find_dotenv, load_dotenv
from kerchunk.combine import MultiZarrToZarr
from kerchunk.hdf import SingleHdf5ToZarr

from utils.utils import timing_block

load_dotenv(find_dotenv())


class SMAPArchiver:
    """Class to handle the archiving of SMAP data."""

    def __init__(
        self, download_dir: str, start_date: str, end_date: str, dataset="SPL4SMGP"
    ):
        """Initialize the SMAPArchiver with date range and dataset."""
        self._dataset = dataset
        self._start_date = start_date
        self._end_date = end_date
        self._crs = 6933
        self._buffer = 10000  # Buffer in meters for clipping
        self._filesystem_type_netcdf = "s3"  # or 'local'
        self._filesystem_type_jsons = "local"  # or 's3'
        self._group = "Geophysical_Data"
        self._download_dir = download_dir

        self._times = []

    @property
    def group(self):
        """Get the HDF5 group name."""
        return self._group

    @group.setter
    def group(self, value):
        """Set the HDF5 group name."""
        self._group = value

    @property
    def times(self):
        """Get the list of times."""
        return self._times

    @times.setter
    def times(self, value):
        """Set the list of times."""
        self._times = value

    @property
    def download_dir(self):
        """Get the download directory."""
        return self._download_dir

    @download_dir.setter
    def download_dir(self, value):
        """Set the download directory."""
        self._download_dir = value

    @property
    def filesystem_type_netcdf(self):
        """Get the filesystem type for NetCDF files."""
        return self._filesystem_type_netcdf

    @filesystem_type_netcdf.setter
    def filesystem_type_netcdf(self, value):
        """Set the filesystem type for NetCDF files."""
        self._filesystem_type_netcdf = value

    @property
    def filesystem_type_jsons(self):
        """Get the filesystem type for JSON files."""
        return self._filesystem_type_jsons

    @filesystem_type_jsons.setter
    def filesystem_type_jsons(self, value):
        """Set the filesystem type for JSON files."""
        self._filesystem_type_jsons = value

    @property
    def buffer(self):
        """Get the buffer size for clipping."""
        return self._buffer

    @buffer.setter
    def buffer(self, value):
        """Set the buffer size for clipping."""
        self._buffer = value

    @property
    def crs(self):
        """Get the coordinate reference system (CRS) for the archiver."""
        return self._crs

    @crs.setter
    def crs(self, value):
        """Set the coordinate reference system (CRS) for the archiver."""
        self._crs = value

    @property
    def dataset(self):
        """Get the dataset name."""
        return self._dataset

    @dataset.setter
    def dataset(self, value):
        """Set the dataset name."""
        self._dataset = value

    @property
    def start_date(self):
        """Get the start date."""
        return self._start_date

    @start_date.setter
    def start_date(self, value):
        """Set the start date."""
        self._start_date = value

    @property
    def end_date(self):
        """Get the end date."""
        return self._end_date

    @end_date.setter
    def end_date(self, value):
        """Set the end date."""
        self._end_date = value

    @property
    @lru_cache
    def states(self):
        """Get the US states geometries."""
        return gh.get_us_states().to_crs(epsg=self.crs)

    @property
    @lru_cache
    def mask(self):
        """Get the CONUS mask by excluding non-continental states."""
        return self.states.loc[
            ~self.states["NAME"].isin(
                [
                    "Alaska",
                    "Hawaii",
                    "Puerto Rico",
                    "American Samoa",
                    "Commonwealth of the Northern Mariana Islands",
                    "United States Virgin Islands",
                    "Guam",
                ]
            )
        ].union_all()

    def login(self):
        """Login to Earthdata using earthaccess."""
        earthaccess.login(persist=True)

    def search(self) -> list:
        """Search for SMAP data within the specified date range."""
        return earthaccess.search_data(
            short_name=self.dataset, temporal=(self.start_date, self.end_date)
        )

    def download(self, results: list):
        """Download the searched SMAP data."""
        earthaccess.download(results, self.download_dir)

    @property
    def files(self):
        """Get the list of downloaded files."""
        return glob.glob(os.path.join(self.download_dir, "*.h5"))

    def clip_and_write_to_netcdf(
        self, processed_dir: str, variable_names: list = ["sm_rootzone", "sm_surface"]
    ):
        """Clip the downloaded SMAP data to CONUS and write to NetCDF files."""
        if not os.path.exists(processed_dir):
            os.makedirs(processed_dir)
        for file in self.files:
            basename = os.path.basename(file)
            out_file = os.path.join(processed_dir, basename.replace(".h5", ".nc"))
            ds = xr.open_dataset(file)
            xr_ds = xr.open_dataset(file, group=rf"/{self.group}", engine="h5netcdf")[
                variable_names
            ]

            xr_ds = xr_ds.expand_dims(dim={"time": 1})
            xr_ds = xr_ds.assign_coords({"time": [ds.time.values[0]]})

            xr_ds = xr_ds.assign_coords({"x": ds["x"], "y": ds["y"]})
            xr_ds = xr_ds.rio.write_crs(f"EPSG:{self.crs}")
            conus_sm = xr_ds.rio.clip(
                [self.mask.buffer(self.buffer)],
                xr_ds.rio.crs,
                all_touched=True,
                drop=True,
            )
            conus_sm.to_netcdf(out_file, engine="h5netcdf")
            self.times.append(ds.time.values[0])

    @property
    def fs_netcdf_files(self):
        """Get the filesystem for the processed directory."""
        if self.filesystem_type_netcdf == "local":
            return fsspec.filesystem("file")
        elif self.filesystem_type_netcdf == "s3":
            return fsspec.filesystem("s3")

    @property
    def fs_json_files(self):
        """Get the filesystem for the JSON files."""
        if self.filesystem_type_jsons == "local":
            return fsspec.filesystem("file")
        elif self.filesystem_type_jsons == "s3":
            return fsspec.filesystem("s3")

    def create_zarr_json(self, json_dir: str, s3_keys: list):
        """Create Zarr JSON files from the processed NetCDF files."""
        if not os.path.exists(json_dir):
            os.makedirs(json_dir)
        for key in s3_keys:
            with self.fs_netcdf_files.open(key, "rb") as f:
                basename = os.path.basename(key)
                outf = os.path.join(json_dir, basename.replace(".nc", ".json"))
                h5chunks = SingleHdf5ToZarr(f, key, inline_threshold=300)

                with self.fs_json_files.open(outf, "wb") as f:
                    f.write(json.dumps(h5chunks.translate()).encode())

    def combine_jsons(self, json_dir: str, outfile: str):
        """Combine individual JSON files into a single Zarr JSON file."""
        json_list = self.fs_json_files.glob(f"{json_dir}/*.json")

        mzz = MultiZarrToZarr(
            json_list,
            concat_dims=["time"],
            coo_map={"time": self.times},
            identical_dims=["x", "y"],
        )

        d = mzz.translate()

        with self.fs_json_files.open(outfile, "wb") as f:
            f.write(ujson.dumps(d).encode())

    @property
    @lru_cache
    def s3_client(self):
        """Create an S3 client using fsspec."""
        return boto3.client("s3")

    def copy_to_s3(self, local_dir: str, s3_dir: str):
        """Copy local files to S3."""
        keys = []
        for file in glob.glob(os.path.join(local_dir, "*")):
            basename = os.path.basename(file)
            self.s3_client.upload_file(
                file, s3_dir.split("/")[2], f"{s3_dir.split('/', 3)[-1]}/{basename}"
            )
            keys.append(f"{s3_dir}/{basename}")

        return keys

    def remove_local_files(self, local_dir: str):
        """Remove local files in the specified directory."""
        for file in glob.glob(os.path.join(local_dir, "*")):
            os.remove(file)


def main(start_year=2015, end_year=2025):
    """Main function to run the SMAP archiving process."""
    all_s3_keys = []
    for year in range(start_year, end_year):
        for month in range(1, 13):
            start_date = f"{year}-{month:02d}-01"
            end_date = (datetime(year, month, 1) + timedelta(days=32)).strftime(
                "%Y-%m-%d"
            )
            with timing_block(f"Processing year: {year} | month: {month}"):
                archiver = SMAPArchiver(
                    download_dir="./smap_data/raw",
                    start_date=start_date,
                    end_date=end_date,
                )
                archiver.login()

                with timing_block(
                    f"Searching for data for year: {year} | month: {month}"
                ):
                    results = archiver.search()
                if len(results) == 0:
                    continue
                with timing_block(
                    f"Downloading data for year: {year} | month: {month}"
                ):
                    archiver.download(results)

                with timing_block(f"Processing data for year: {year} | month: {month}"):
                    archiver.clip_and_write_to_netcdf(
                        processed_dir="./smap_data/processed",  # or local directory
                        variable_names=["sm_rootzone"],  # , "sm_surface"],
                    )

                with timing_block(f"Copying to s3 for year: {year} | month: {month}"):
                    s3_keys = archiver.copy_to_s3(
                        "./smap_data/processed", "s3://ngwpc-forcing/smap_nc"
                    )

                all_s3_keys.extend(s3_keys)

                with timing_block(
                    f"Removing local files for year: {year} | month: {month}"
                ):
                    archiver.remove_local_files("./smap_data/raw")
                    archiver.remove_local_files("./smap_data/processed")

    # with timing_block("Creating individual Zarr JSON"):
    #     archiver.create_zarr_json("./smap_data/json", all_s3_keys)

    # with timing_block("Combining Zarr JSONs into single JSON"):
    #     archiver.combine_jsons(
    #         json_dir="./smap_data/json", outfile="./smap_data/smap_combined.json"
    #     )


def list_keys(bucket_name: str, prefix: str):
    """List all keys in an S3 bucket with optional prefix using pagination."""
    s3_client = boto3.client("s3")
    paginator = s3_client.get_paginator("list_objects_v2")

    # Use the paginate method to iterate through all pages of results
    pages = paginator.paginate(
        Bucket=bucket_name,
        Prefix=prefix,  # Optional
        # MaxKeys=1000 # Default, but can be adjusted for smaller page sizes
    )

    all_objects = []
    for page in pages:
        if "Contents" in page:
            for obj in page["Contents"]:
                all_objects.append(f"s3://{bucket_name}/{obj['Key']}")
                # You can process each object here, e.g., print(obj['Key'])
    return all_objects


if __name__ == "__main__":
    main(start_year=2015, end_year=2025)
