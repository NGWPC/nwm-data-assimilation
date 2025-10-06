import glob
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from dotenv import find_dotenv, load_dotenv
from shapely import MultiPoint, Polygon, voronoi_polygons

from utils.utils import time_function, timing_block

load_dotenv(find_dotenv())


class BasinAverageProcessor:
    """Processor for calculating basin averages from SMAP data."""

    def __init__(
        self,
        local_ref_file,
        gage_gpkg_file_directory: str,
        start_date=None,
        end_date=None,
    ):
        """Initialize the processor."""
        self.local_ref_file = local_ref_file
        self.gage_gpkg_file_directory = gage_gpkg_file_directory
        self.start_date = start_date
        self.end_date = end_date

        self.group_id = "gage_id"
        self.column = "smap_rootzone"
        self.dataset_name = "sm_rootzone"
        self.x_dim_name = "x"
        self.y_dim_name = "y"
        self._data = None
        self.crs = "EPSG:6933"

    @property
    @lru_cache
    def times(self):
        """Get the list of times from the dataset."""
        return list(
            np.arange(
                np.datetime64(f"{self.start_date}T01:28:55.816000000", "s"),
                np.datetime64(f"{self.end_date}T01:28:55.816000000", "s"),
                np.timedelta64(3, "h"),
            )
        )

    @property
    @lru_cache
    def gage_ids(self):
        """Get the list of gage IDs."""
        return self.gage_gdf["gage_id"].unique().tolist()

    @property
    def data(self):
        """Get the SMAP data."""
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

    # def process_one(self, time, gages):
    #     """Process one gage."""
    #     with timing_block(f"processing: {str(time)}"):
    #         data = self.ds.sel(
    #             time=time,
    #             x=slice(self.bounds[0], self.bounds[2]),
    #             y=slice(self.bounds[3], self.bounds[1]),
    #         ).load()  # ["sm_rootzone"]
    #         self.data = data.rio.write_crs(self.crs)
    #         gages[time] = gages[self.group_id].map(self.mean_values)
    #         return gages[time]

    @time_function
    def process(self):
        """Process the data."""
        gages = pd.DataFrame({self.group_id: self.gage_ids})
        # futures = {}
        year = self.times[0].astype(datetime).year
        for time in self.times:
            # with concurrent.futures.ProcessPoolExecutor() as executor:
            #     futures[executor.submit(self.process_one, time, gages)] = time
            # for future in concurrent.futures.as_completed(futures):
            #     time = futures[future]
            #     gages[time] = future.result()
            with timing_block(f"processing: {str(time)}"):
                if time.astype(datetime).year != year:
                    gages.to_parquet(f"{year}.parquet")
                    gages = pd.DataFrame({self.group_id: self.gage_ids})
                    year = time.astype(datetime).year
                data = self.ds.sel(
                    time=time,
                    x=slice(self.bounds[0], self.bounds[2]),
                    y=slice(self.bounds[3], self.bounds[1]),
                ).load()
                self.data = data.rio.write_crs(self.crs)
                gages[time] = gages[self.group_id].map(self.mean_values)

    @property
    def mean_values(self):
        """Calculate mean value for each catchment using area-weighted averaging."""
        return self.fishnet_with_values.groupby(self.group_id).apply(
            lambda x: np.average(x["value"], weights=x["area"])
        )

    @property
    def fishnet_with_values(self):
        """Compute Fishnet with sampled values."""
        gdf = self.fishnet_overlay.copy()
        gdf["value"] = (
            self.data[self.dataset_name]
            .sel(x=self.x_coords, y=self.y_coords, method="nearest")
            .values
        )
        return gdf

    @property
    @lru_cache
    def x_coords(self):
        """Get x coordinates."""
        return xr.DataArray(self.fishnet_overlay.centroid.x)

    @property
    @lru_cache
    def y_coords(self):
        """Get y coordinates."""
        return xr.DataArray(self.fishnet_overlay.centroid.y)

    @property
    @lru_cache
    @time_function
    def fishnet_overlay(self):
        """Compute Fishnet overlay with basin GeoDataFrame."""
        gdf = gpd.overlay(self.fishnet, self.gage_gdf, how="intersection")
        gdf["area"] = gdf.to_crs(5070).geometry.area
        return gdf

    @property
    @lru_cache
    def fishnet(self):
        """Compute Fishnet."""
        # create fishnet geodataframe
        mp = MultiPoint(
            [(x, y) for x in self.data.x.values for y in self.data.y.values]
        )

        polygons = voronoi_polygons(mp)
        return gpd.GeoDataFrame(
            {"geometry": [Polygon(i) for i in polygons.geoms]},
            crs=self.data.rio.crs,
            geometry="geometry",
        )

    @property
    @lru_cache
    def gage_files(self):
        """Get the list of gage geopackage files."""
        return glob.glob(f"{self.gage_gpkg_file_directory}/*")

    @property
    @lru_cache
    def gage_gdf(self):
        """Get the gage GeoDataFrame."""
        gdfs = []
        for file in self.gage_files:
            gdf = gpd.read_file(file, layer="divides")
            gdf["gage_id"] = str(Path(file).stem).replace("gages-", "")
            gdfs.append(gdf)

        return pd.concat(gdfs, ignore_index=True).to_crs(self.crs)

    @property
    @lru_cache
    def bounds(self):
        """Get the bounding box of the gage."""
        return self.gage_gdf.to_crs(self.crs).total_bounds  # (minx, miny, maxx, maxy)

    @property
    @lru_cache
    def ds(self):
        """Get the SMAP dataset."""
        ds = xr.open_dataset(
            "reference://",
            engine="zarr",
            backend_kwargs={
                "consolidated": False,
                "storage_options": {
                    "fo": self.local_ref_file,
                    "remote_protocol": "s3",
                    "asynchronous": False,
                },
            },
        )
        return ds

    @property
    def start_year(self):
        """Get the start year."""
        return self.times[0].astype(datetime).year

    @property
    def end_year(self):
        """Get the end year."""
        return self.times[-1].astype(datetime).year

    def process_yearly_data(self, output_directory: str):
        """Process yearly data."""
        dfs = []
        for year in range(self.start_year, self.end_year + 1):
            pass
            dfs.append(pd.read_parquet(f"{year}.parquet").T)
        df = pd.concat(dfs)

        df.columns = df.iloc[0]
        df.drop("gage_id", inplace=True)
        df.index = pd.to_datetime(df.index)

        if not os.path.exists(output_directory):
            os.makedirs(output_directory)
        for col in df.columns:
            print(col)
            file = os.path.join(output_directory, f"gages-{col}_soil_moisture.csv")
            df["basin_avg_soil_moisture"] = df[col]
            df.drop(columns=[col], inplace=True)
            df.index.name = "timestamp"
            # df.index = (
            #     pd.to_datetime(df.index).strftime("%Y-%m-%d %H:%M:%S").astype(str)
            # )
            df["basin_avg_soil_moisture"].to_csv(
                file, header=True, date_format="%Y-%m-%d %H:%M:%S"
            )


def main(
    local_ref_file: str,
    gage_gpkg_file_directory: str,
    output_directory: str,
    start_date: str,
    end_date: str,
):
    """Process SMAP data and compute basin averages."""
    processor = BasinAverageProcessor(
        local_ref_file=local_ref_file,
        gage_gpkg_file_directory=gage_gpkg_file_directory,
        start_date=start_date,
        end_date=end_date,
    )
    # processor.process()
    processor.process_yearly_data(output_directory=output_directory)


if __name__ == "__main__":
    local_ref_file = "/home/matthew.deshotel/repos/data-assimilation-engine/smap_data/smap_combined.json"
    gage_gpkg_file_directory = "/home/matthew.deshotel/repos/data-assimilation-engine/sample_data/sample_gpkg/conus_hf2.2"
    start_date = "2015-01-31"
    end_date = "2024-09-01"
    output_directory = Path(
        "/home/matthew.deshotel/repos/data-assimilation-engine/smap_csv"
    )
    main(
        local_ref_file, gage_gpkg_file_directory, output_directory, start_date, end_date
    )
