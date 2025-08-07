import re
import csv
import fsspec
import pandas as pd
import geopandas as gpd

from typing import IO
from datetime import datetime
from shapely.geometry import Point
from io import BytesIO, TextIOWrapper


class ISMNDataLoader:
    """
    Class to load and process ISMN data.

    File structure of ISMN data:
        ismn_base_dir/
        ├── gage_{gage_id}/
        │   ├── network={network}/
        │   │   ├── station={station}/
        │   │   │   ├── date={YYY-MM-DD}/
        │   │   │   │   ├── depth_{depth}.parquet/
    """

    @staticmethod
    def get_ismn_files(ismn_base_dir: str, gage_id: str, target_date: str, fs: fsspec.AbstractFileSystem) -> list:
        """
        Get all ISMN parquet files for a specific gage ID and date.

        Parameters
        ----------
        ismn_base_dir : str
            Base directory containing ISMN files.

        gage_id : str
            Gage ID to filter station directories.

        target_date : str
            Date in the format 'YYYY-MM-DD' to filter data.

        fs : fsspec.AbstractFileSystem
            Filesystem object for the specified directory.

        Returns
        -------
        list
            List of ISMN file paths for the specified gage ID and date.
        """
        ismn_files = []
        # construct the path to the gage directory
        gage_dir = f"{ismn_base_dir}/gage_{gage_id}"

        # check if gage_dir exists
        if not fs.exists(gage_dir):
            print(f"Gage directory {gage_dir} does not exist.")
            return ismn_files

        # iterate over all directories in the gage directory
        for entry in fs.ls(gage_dir, detail=True):
            if entry['type'] == 'directory':
                network_dir = entry['name']

                # verify that network_dir is in 'network={network}' format
                if not network_dir.startswith('network='):
                    print(f"Skipping non-network directory: {network_dir}")
                    continue

                # check if network_dir exists
                if not fs.exists(network_dir):
                    print(f"Network directory {network_dir} does not exist for gage {gage_id}.")
                    continue

                # iterate over all station directories in the network directory
                for station_entry in fs.ls(network_dir, detail=True):
                    if station_entry['type'] == 'directory':
                        station_dir = station_entry['name']

                        # verify that station_dir is in 'station={station}' format
                        if not station_dir.startswith('station='):
                            print(f"Skipping non-station directory: {station_dir}")
                            continue

                        # check if station_dir exists
                        if not fs.exists(station_dir):
                            print(f"Station directory {station_dir} does not exist for gage {gage_id}.")
                            continue

                        # construct the path to the target date directory
                        date_dir = f"{station_dir}/date={target_date}"

                        # check if the date directory exists
                        if fs.exists(date_dir):
                            # iterate over all files in the date directory
                            for file_entry in fs.ls(date_dir, detail=True):
                                if file_entry['type'] == 'file' and file_entry['name'].endswith('.parquet'):
                                    ismn_files.append(file_entry['name'])

                        else:
                            print(f"Date directory {date_dir} does not exist for gage {gage_id}.")

        print(f"Found {len(ismn_files)} ISMN files for gage {gage_id} on date {target_date}.")
        return ismn_files

    @staticmethod
    def get_ismn_data(ismn_files: list, gage_id: str, target_date: str, fs: fsspec.AbstractFileSystem) -> gpd.GeoDataFrame | None:
        """
        Get ISMN station directories which fall within basin boundaries

        Parameters
        ----------
        ismn_files : list
            List of ISMN parquet file paths
        gage_id : str
            Gage ID to filter station directories
        target_date : str
            Date in the format 'YYYY-MM-DD' to filter data
        fs : fsspec.AbstractFileSystem
            Filesystem object for the specified files

        Returns
        -------
        gpd.GeoDataFrame | None
            GeoDataFrame containing ISMN data for the specified gage_id and date
        """
        column_names = [
            'gage_id', 'network', 'station', 'date', 'utc_nominal',
            'utc_actual', 'cse_id', 'lat', 'lon', 'elevation',
            'depth_from', 'depth_to', 'soil_moisture_value', 'ismn_flag',
            'provider_flag'
        ]

        all_ismn_dfs = []

        for ismn_file in ismn_files:
            with fs.open(ismn_file, 'rb') as file:
                ismn_file_df = pd.read_parquet(
                    path=file,
                    columns=column_names)

                # create a geometry column from lat/lon
                ismn_file_df['geometry'] = ismn_file_df.apply(
                    lambda row: Point(row['lon'], row['lat']), axis=1)

                all_ismn_dfs.append(ismn_file_df)

        if not all_ismn_dfs:
            print(f"No valid ISMN data found for gage {gage_id} on date {target_date}.")
            return None

        # concatenate all DataFrames into a single GeoDataFrame
        ismn_data_gdf = gpd.GeoDataFrame(pd.concat(all_ismn_dfs, ignore_index=True), geometry='geometry', crs='EPSG:4326')

        print(f"ISMN data GeoDataFrame shape: {ismn_data_gdf.shape}")
        # print 10 random rows from the ismn_data_gdf
        n = min(10, len(ismn_data_gdf))
        print("Sample ISMN data GeoDataFrame:")
        print(ismn_data_gdf.sample(n).to_string(index=False))

        return ismn_data_gdf


class ISMNCalculator:
    @staticmethod
    def calculate_depth_weighted_average(ismn_data_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
        """
        Calculate depth-weighted average of ISMN soil moisture data over a fixed 1.25 m depth range
        The top bound is always 0 m, and the bottom bound is always 1.25 m

        Parameters
        ----------
        ismn_data_gdf : geopandas.GeoDataFrame
            GeoDataFrame containing ISMN data with columns:
            ['gage_id', 'network', 'station', 'date', 'utc_nominal',
            'utc_actual', 'cse_id', 'lat', 'lon', 'elevation',
            'depth_from', 'depth_to', 'soil_moisture_value', 'ismn_flag',
            'provider_flag']

        Returns
        -------
        pd.DataFrame
            DataFrame with columns ['gage_id', 'network','station','date','hour','lat','lon','depth_weighted_sm_avg']
        """
        # work on a copy to avoid mutating the input geodataframe
        gdf = ismn_data_gdf.copy()

        # round each timestamp down to the start of its hour for grouping
        gdf['hour'] = gdf['utc_nominal'].dt.floor('h')

        # determine the unique measurement depths (we assume depth_to == depth_from)
        depths = sorted(gdf['depth_to'].unique())

        # print(f"Measurement depths (m): {depths}")

        unique_depth_from = sorted(gdf['depth_from'].unique())

        print("unique depth_from values (m):")
        for d_f in unique_depth_from:
            print(f"{d_f} m")

        unique_depth_to = depths.copy()

        print("unique depth_to values (m):")
        for d_t in unique_depth_to:
            print(f"{d_t} m")

        # calculate the midpoints between each pair of adjacent sensor depths
        midpoints = [
            (depths[i] + depths[i+1]) / 2
            for i in range(len(depths) - 1)
        ]

        # the topmost layer starts at 0 m; subsequent layers start at each midpoint
        lower_bounds = [0.0] + midpoints

        print("Lower bounds of depth layers (m):")
        for lb in lower_bounds:
            print(f"{lb:.3f} m")

        # each layer ends at the next midpoint, except the deepest always ends at 1.25 m
        upper_bounds = midpoints + [1.25]

        print("Upper bounds of depth layers (m):")
        for ub in upper_bounds:
            print(f"{ub:.3f} m")

        # build a mapping from depth to layer thickness (upper_bound minus lower_bound)
        weight_map = {
            depth: ub - lb
            for depth, lb, ub in zip(depths, lower_bounds, upper_bounds)
        }

        for k, v in weight_map.items():
            print(f"Weight for depth {k} m: {v:.3f} m")

        # assign each measurement its layer thickness as its weight
        df['weight'] = df['depth_to'].map(weight_map)

        # create a new DataFrame hourly that holds one row per station-hour,
        # computing the depth-weighted average soil moisture for each group
        hourly = (
            df
            .groupby(['network', 'station', 'hour'])[['value', 'weight']]
            .apply(lambda grp: (grp['value'] * grp['weight']).sum()
                                / grp['weight'].sum())
            .reset_index(name='depth_weighted_sm_avg')
        )

        # add date column to 'hourly' by extracting just the calendar date from the hourly timestamp
        hourly['date'] = hourly['hour'].dt.date

        # convert the 'hour' column to a string format 'HH:MM'
        hourly['hour'] = hourly['hour'].dt.strftime('%H:%M')

        # build a small DataFrame 'coords' with one entry per station,
        # containing the station identifier and its latitude/longitude
        coords = df.drop_duplicates('station')[['station', 'lat', 'lon']]

        # merge coords into hourly to attach the geographic coordinates
        # to each station-hour weighted average, producing the result DataFrame
        result = hourly.merge(coords, on='station', how='left')

        # reorder columns
        result = result[['network', 'station', 'date', 'hour', 'lat', 'lon', 'depth_weighted_sm_avg']]

        print(f"Result DataFrame shape: {result.shape}")
        print("First 10 rows of result DataFrame:")
        print(result.head(10).to_string(index=False))

        print("Last 10 rows of result DataFrame:")
        print(result.tail(10).to_string(index=False))
        return result


class ISMNPlotter:
    pass


if __name__ == "__main__":
    ismn_base_dir = "/home/miguel.pena/s3/ngwpc-dev/miguel.pena/ismn_preprocessed_data"
    date = "2024-09-20"
    fs = fsspec.filesystem('file')

    ismn_files = ISMNDataLoader.get_ismn_files(
        ismn_base_dir=ismn_base_dir,
        gage_id="07241780",
        target_date=date,
        fs=fs
    )

    print(f"Total ISMN files found: {len(ismn_files)}")

    print("Sample ISMN files:")
    min = min(5, len(ismn_files))
    for i in range(min):
        ismn_file = ismn_files[i]
        print(ismn_file)

    # load ISMN data into a GeoDataFrame
    ismn_data_gdf = ISMNDataLoader.get_ismn_data(
        ismn_files=ismn_files,
        gage_id="07241780",
        target_date=date,
        fs=fs
    )

    # getting the depth-weighted average of ISMN soil moisture data into a DataFrame
    depth_weighted_avg_df = ISMNCalculator.calculate_depth_weighted_average(ismn_data_gdf)
