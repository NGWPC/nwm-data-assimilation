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
    @staticmethod
    def get_ismn_dirs_by_date(ismn_base_dir: str, target_date: str, direct_s3: bool = False) -> tuple:
        """
        Filter ISMN directories that contain the target date between their start and end date.

        Parameters
        ----------
        ismn_base_dir : str
            Base directory containing ISMN data (can be local path or S3 prefix).
        target_date : str
            Date in the format 'YYYY-MM-DD'.
        direct_s3 : bool
            If True, use S3 filesystem. If False, use local filesystem.

        Returns
        -------
        tuple
        matching_dirs : list[str]
            List of directories that match the target date.
        fs : fsspec.filesystem
            Filesystem object for the specified base directory.
        """
        fs = fsspec.filesystem('s3') if direct_s3 else fsspec.filesystem('file')
        pattern = re.compile(r".*_(\d{8})_(\d{8})_.*")

        try:
            target = datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid date format: {target_date}. Expected 'YYYY-MM-DD'.")

        matching_dirs = []
        for entry in fs.ls(ismn_base_dir, detail=True):
            if entry['type'] == 'directory':
                dir_path = entry['name']
                dir_name = dir_path.rstrip('/').split('/')[-1]
                match = pattern.match(dir_name)
                if match:
                    start_str, end_str = match.groups()
                    try:
                        start_date = datetime.strptime(start_str, "%Y%m%d")
                        end_date = datetime.strptime(end_str, "%Y%m%d")
                    except ValueError:
                        continue  # skip invalid dates

                    if start_date <= target <= end_date:
                        matching_dirs.append(dir_path)

        # print(matching_dirs)
        return matching_dirs, fs

    @staticmethod
    def get_ismn_files(ismn_dir: str, fs: fsspec.filesystem) -> list:
        """
        Get all ISMN files in a given directory recursively.

        Parameters
        ----------
        ismn_dir : str
            Directory containing ISMN files.
        fs : fsspec.filesystem
            Filesystem object for the specified directory.

        Returns
        -------
        list
            List of ISMN file paths.
        """
        ismn_files = []
        for entry in fs.ls(ismn_dir, detail=True):
            if entry['type'] == 'file' and entry['name'].endswith('.stm'):
                ismn_files.append(entry['name'])
            elif entry['type'] == 'directory':
                ismn_files.extend(ISMNDataLoader.get_ismn_files(entry['name'], fs))

        # for ismn_file in ismn_files:
        #     print(ismn_file)

        return ismn_files

    @staticmethod
    def preprocess_ismn_file_to_fs_buffer(file: IO, target_date: str) -> BytesIO:
        """
        Preprocess a raw ISMN file and filter data by target_date.

        Parameters
        ----------
        file : IO
            A file-like object containing the raw ISMN data
        target_date : str
            The target date for filtering data (format: 'YYYY-MM-DD')

        Returns
        -------
        BytesIO
            A binary buffer containing the preprocessed data for file
        """
        # compile regex to capture two datetime stamps and the rest of the line
        ts_pattern = re.compile(
            # start timestamp: yyyy/mm/dd hh:mm
            r'^(?P<start>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2})\s+'
            # end timestamp: yyyy/mm/dd hh:mm
            r'(?P<end>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2})\s+'
            # everything else on the line
            r'(?P<rest>.*)$'
        )

        # create a binary buffer for output
        output = BytesIO()

        # wrap the binary buffer with text mode for csv.writer
        text_buf = TextIOWrapper(output, encoding='utf-8', newline='')

        # create a csv writer that writes to the text buffer
        writer = csv.writer(text_buf)

        # track empty file
        empty_file = True

        # iterate over each raw line in the input file
        for raw in file:
            # decode bytes to string and strip trailing whitespace/newline
            line = raw.decode('utf-8').strip()

            # attempt to match the line against the timestamp regex
            m = ts_pattern.match(line)

            # skip this line if not regex match
            if not m:
                continue

            # extract start timestamp
            start_time = m.group('start')

            # extract end timestamp
            end_time = m.group('end')

            # check if target_date is between start and end dates. ignore times
            try:
                start_dt = datetime.strptime(start_time, "%Y/%m/%d %H:%M")
                end_dt = datetime.strptime(end_time, "%Y/%m/%d %H:%M")
                target_dt = datetime.strptime(target_date, "%Y-%m-%d")

                if not (start_dt.date() <= target_dt.date() <= end_dt.date()):
                    # skip this line if target_date is not in range
                    continue

            except ValueError:
                # if date parsing fails, skip the line
                continue

            # if we reach here, we have a valid line for the target date and file is not empty
            empty_file = False

            # extract rest of line
            rest_str = m.group('rest')

            # split the remainder on whitespace into exactly 11 items
            rest = rest_str.split()

            # if splitting did not yield 11 fields, skip the line
            if len(rest) != 11:
                continue
            # write the row to the csv buffer (automatically adds newline)
            writer.writerow([start_time, end_time] + rest)

        # flush the text buffer to ensure all data is written to the binary buffer
        text_buf.flush()

        # detach the text buffer from the binary buffer but keep the binary buffer open
        text_buf.detach()

        # if file had no matching lines, return None
        if empty_file:
            print(f"No data found for date {target_date} in file.")
            return None

        # rewind the binary buffer to the beginning for reading
        output.seek(0)
        # return the prepared buffer
        return output

    @staticmethod
    def get_ismn_data(ismn_files: list, target_date: str, fs: fsspec.filesystem) -> gpd.GeoDataFrame:
        """
        Load ISMN data from a list of ISMN files into a GeoDataFrame.

        Parameters
        ----------
        ismn_files : list
            List of ISMN file paths.
        fs : fsspec.filesystem
            Filesystem object for the specified files.

        Returns
        -------
        gpd.GeoDataFrame
            GeoDataFrame containing ISMN data.
        """
        column_names = [
            'utc_nominal', 'utc_actual', 'cse_id', 'network', 'station',
            'lat', 'lon', 'elevation', 'depth_from', 'depth_to',
            'value', 'ismn_flag', 'provider_flag'

        ]
        # print(f"number of columns: {len(column_names)}")

        usecols = [
            'utc_nominal', 'network', 'station', 'lat', 'lon',
            'depth_from', 'depth_to', 'value', 'ismn_flag', 'provider_flag'
        ]

        all_ismn_dfs = []
        for ismn_file in ismn_files:
            with fs.open(ismn_file, 'rb') as file:
                # preprocess the file to handle whitespace and commas within fields
                processed_file = ISMNDataLoader.preprocess_ismn_file_to_fs_buffer(file, target_date)

                if processed_file is None:
                    print(f"Skipping file {ismn_file} as it has no data for date {target_date}.")
                    continue

                ismn_file_df = pd.read_csv(
                    processed_file,
                    sep=',',
                    header=None,
                    names=column_names,
                    usecols=usecols
                )
                ismn_file_df['geometry'] = ismn_file_df.apply(
                    lambda row: Point(row['lon'], row['lat']), axis=1
                )

                print(f"Processing file: {ismn_file}")
                # n = min(10, len(ismn_file_df))
                # print(ismn_file_df.sample(n).to_string(index=False))

                all_ismn_dfs.append(ismn_file_df)

        print(f"Total ISMN files processed: {len(all_ismn_dfs)}")
        # n = min(25, len(all_ismn_dfs))
        # print(all_ismn_dfs[:n])

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
            ['utc_nominal','network','station','lat','lon',
            'depth_from','depth_to','value','ismn_flag','provider_flag','geometry']

        Returns
        -------
        pd.DataFrame
            DataFrame with columns ['network','station','date','hour','lat','lon','depth_weighted_sm_avg']
            giving, for each station-hour, the date and depth-weighted soil moisture average.
        """
        # work on a copy to avoid mutating the input geodataframe
        df = ismn_data_gdf.copy()

        # ensure utc_nominal is a datetime column
        df['utc_nominal'] = pd.to_datetime(
            df['utc_nominal'],
            format='%Y/%m/%d %H:%M',
            errors='raise'
        )

        # round each timestamp down to the start of its hour for grouping
        df['hour'] = df['utc_nominal'].dt.floor('h')

        # determine the unique measurement depths (we assume depth_to == depth_from)
        depths = sorted(df['depth_to'].unique())

        # print(f"Measurement depths (m): {depths}")

        unique_depth_from = sorted(df['depth_from'].unique())

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
    @staticmethod
    def add_ismn_overlay(ax, ismn_data_df, proj):
        """
        Add ISMN data overlay to a given plot axis.

        Parameters
        ----------
        ax : matplotlib.axes.Axes
            Axes object to add overlay to
        ismn_data_df : pd.DataFrame
            DataFrame with station information and ISMN soil moisture depth-weighted average values
        proj : cartopy.crs
            The projection to use for the overlay
        """
        pass


if __name__ == "__main__":
    ismn_base_dir = "/home/miguel.pena/noaa-owp/soil_moisture_sample_data"
    date = "2024-09-20"

    # get list of ISMN directories for the given date
    ismn_dirs, fs = ISMNDataLoader.get_ismn_dirs_by_date(ismn_base_dir, date)
    # print(f"Total ISMN directories found: {len(ismn_dirs)}\n")

    # print sample dirs
    # n = min(5, len(ismn_dirs))
    # print("Sample ISMN directories:")
    # for i in range(n):
    #     print(ismn_dirs[i])

    ismn_files = []

    # get all ISMN files from the directories
    for ismn_dir in ismn_dirs:
        ismn_files.extend(ISMNDataLoader.get_ismn_files(ismn_dir, fs))

    # print(f"Total ISMN files found: {len(ismn_files)}")

    # print("Sample ISMN files:")
    # for i in range(5):
    #     ismn_file = ismn_files[i]
    #     print(ismn_file)

    # load ISMN data into a GeoDataFrame
    ismn_data_gdf = ISMNDataLoader.get_ismn_data(ismn_files, date, fs)

    # getting the depth-weighted average of ISMN soil moisture data into a DataFrame
    depth_weighted_avg_df = ISMNCalculator.calculate_depth_weighted_average(ismn_data_gdf)
