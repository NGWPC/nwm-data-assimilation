import re
import fsspec
import pandas as pd
import geopandas as gpd
import shapely.geometry

from typing import Dict, List, Iterator, Tuple
from pathlib import PurePath
from shapely.geometry.base import BaseGeometry
from shapely.geometry import Point, Polygon, MultiPolygon

from utils.geo_utils import GeoUtils


class ISMNPreprocessor:
    """
    Class for preprocessing ISMN (International Soil Moisture Network) data files
    """

    """
    regex pattern matches raw ISMN file lines with:
    - start timestamp:
      (YYYY/MM/DD HH:MM)
    - end timestamp:
      (YYYY/MM/DD HH:MM)
    - the rest of the line:
      (CSE Identifier, Network, Station, Latitude, Longitude,
       Elevation, Depth from, Depth to, Soil Moisture value,
       ISMN Quality Flag, Data Provider Quality Flag)
    """
    _ISMN_LINE_PATTERN = re.compile(
        r'^(?P<start>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2})\s+'
        r'(?P<end>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2})\s+'
        r'(?P<rest>.*)$'
    )

    @staticmethod
    def parse_ismn_line(raw_line: bytes) -> list[str] | None:
        """
        Parse a single raw ISMN file line into its constituent fields.

        Parameters
        ----------
        raw_line : bytes
            A raw bytes line read from an ISMN .stm file.

        Returns
        -------
        list[str] | None
            A list of strings:
            [start_timestamp, end_timestamp, field1, ..., field11]
            or None if the line doesn't match the expected format or
            doesn't contain exactly 11 data fields after the timestamps.
        """
        # grab line
        text_line = raw_line.decode('utf-8', errors='ignore').strip()

        # try to match the timestamp regex
        match = ISMNPreprocessor._ISMN_LINE_PATTERN.match(text_line)
        if not match:
            return None  # line didn't match the expected pattern

        # split rest of line on whitespace into data fields
        rest_fields = match.group('rest').split()
        if len(rest_fields) != 11:
            return None  # we expect exactly 11 data columns after timestamps

        # build full record: [start, end, field1, ..., field11]
        return [match.group('start'), match.group('end')] + rest_fields

    @staticmethod
    def iter_ismn_records(file_obj: Iterator[bytes]) -> Iterator[list[str]]:
        """
        Iterate over all valid ISMN records in an open file object.

        Parameters
        ----------
        file_obj : Iterator[bytes]
            An iterator yielding raw bytes lines (e.g., from fs.open(..., 'rb')).

        Yields
        ------
        list[str]
            Each yield is a list of strings corresponding to one valid record:
            [start_timestamp, end_timestamp, field1, ..., field11]
        """
        for raw_line in file_obj:
            parsed = ISMNPreprocessor.parse_ismn_line(raw_line)
            if parsed:
                yield parsed

    @staticmethod
    def load_basin_geometries(
        gpkg_source: str,
        fs: fsspec.AbstractFileSystem,
        limit: int | None = None
    ) -> Dict[str, BaseGeometry]:
        """
        loads one or more gpkg files from a path (file or dir)
        and returns a dict mapping each gage_id to its unified basin geometry

        Parameters
        ------------
        gpkg_source: str
            path to a single geopackage file or a directory containing geopackages
        fs: fsspec.AbstractFileSystem
            filesystem instance for reading files (local or remote)
        limit: int or None, optional
            maximum number of files to process (for testing)

        Returns
        --------
        Dict[str, BaseGeometry]
            mapping of gage_id to unified basin geometry
        """
        basin_geoms: Dict[str, BaseGeometry] = {}
        files_processed = 0

        # decide whether gpkg_source is a single .gpkg file or a directory
        if fs.isfile(gpkg_source) and gpkg_source.lower().endswith('.gpkg'):
            # single-file input: wrap in a one-item list for uniform processing
            entries = [{'name': gpkg_source, 'type': 'file'}]
        elif fs.isdir(gpkg_source):
            # directory input: list all entries (files and subdirs)
            entries = fs.ls(gpkg_source, detail=True)
        else:
            raise FileNotFoundError(f"gpkg_source not found or not a .gpkg/dir: {gpkg_source}")

        # iterate entries and process each geopackage
        for entry in entries:
            path = entry['name']
            # only handle files ending in .gpkg
            if entry['type'] == 'file' and path.lower().endswith('.gpkg'):
                # derive the gage identifier by stripping prefix and suffix
                fname = PurePath(path).name
                gage_id = fname.removeprefix('gages-').removesuffix('.gpkg')

                print(f"Processing gage {gage_id}...")

                # read the 'divides' layer and ensure it's in geographic CRS
                basin_gdf = GeoUtils.read_geo(path)

                # compute a single, unified geometry for this basin
                unified_geom, _ = GeoUtils.get_basin_geometry(basin_gdf)

                # store the mapping of gage_id to its basin geometry
                basin_geoms[gage_id] = unified_geom
                files_processed += 1

                print(f"basin geometry type: {unified_geom.geom_type}")
                print(f"basin geometry area: {unified_geom.area}")
                print(f"basin geometry bounds: {unified_geom.bounds}")
                print(f"basin geometry centroid: {unified_geom.centroid}")

                # count exterior coords, handling both Polygon and MultiPolygon
                if isinstance(unified_geom, Polygon):
                    coord_count = len(unified_geom.exterior.coords)
                elif isinstance(unified_geom, MultiPolygon):
                    coord_count = sum(len(poly.exterior.coords) for poly in unified_geom.geoms)
                else:
                    coord_count = 0
                print(f"basin geometry number of coordinates: {coord_count}")

                # stop early if we've reached the specified limit
                if limit is not None and files_processed >= limit:
                    break

        return basin_geoms

    @staticmethod
    def get_raw_ismn_files(
        ismn_source: str,
        fs: fsspec.AbstractFileSystem,
        limit: int | None = None
    ) -> List[str]:
        """
        loads one or more raw .stm files from a path (file or dir), recursively if dir

        Parameters
        ------------
        ismn_source: str
            path to a single .stm file or a directory containing .stm files
        fs: fsspec.AbstractFileSystem
            filesystem instance for reading files (local or remote)
        limit: int or None
            maximum number of files to return (for testing)

        Returns
        --------
        List[str]
            list of raw .stm file paths found under the source
        """
        found_raw_ismn_files: List[str] = []
        files_processed = 0

        # decide whether ismn_source is a single .stm file or a directory
        if fs.isfile(ismn_source) and ismn_source.lower().endswith('.stm'):
            # single-file input: wrap in a list for uniform processing
            directory_entries = [{'name': ismn_source, 'type': 'file'}]
        elif fs.isdir(ismn_source):
            # directory input: list directory contents
            directory_entries = fs.ls(ismn_source, detail=True)
        else:
            raise FileNotFoundError(f"ismn_source not found or not a .stm file/dir: {ismn_source}")

        # iterate over entries to collect .stm files
        for entry in directory_entries:
            entry_path = entry['name']
            if entry['type'] == 'file' and entry_path.lower().endswith('.stm'):
                # add file to list when extension matches
                found_raw_ismn_files.append(entry_path)
                files_processed += 1

                # stop early if reached the specified limit
                if limit is not None and files_processed >= limit:
                    break

            elif entry['type'] == 'directory':
                # recurse into subdirectory for more .stm files
                remaining = None if limit is None else (limit - files_processed)
                sub_files = ISMNPreprocessor.get_raw_ismn_files(entry_path, fs, remaining)

                for sub_file in sub_files:
                    if limit is not None and files_processed >= limit:
                        break
                    found_raw_ismn_files.append(sub_file)
                    files_processed += 1

                # break outer loop if limit reached during recursion
                if limit is not None and files_processed >= limit:
                    break

        return found_raw_ismn_files

    @staticmethod
    def extract_network_and_station_from_ISMN_filename(file_path: str) -> Tuple[str, str] | None:
        """
        parses ISMN .stm filename to extract network and station

        File examples:
            SCAN_SCAN_AAMU-JTG_sm_0.050800_0.050800_Hydraprobe-Analog-C_20240716_20250717.stm
            USCRN_USCRN_Denio-52-WSW_sm_0.050000_0.050000_Stevens-Hydraprobe-II-Sdi-12_20240716_20250717.stm

        Parameters
        ------------
        file_path: str
            path to a raw .stm file

        Returns
        --------
        Tuple[str, str] | None
            (network, station) if filename matches expected pattern,
            otherwise None
        """
        # get file name without file extension
        filename = PurePath(file_path).stem

        # split filename on underscores
        parts = filename.split('_')

        # if we don't get 8 parts, invalid filename
        if len(parts) != 9:
            return None

        # return the network and station parts
        return parts[1], parts[2]

    @staticmethod
    def filter_ismn_files_within_basins(
        ismn_source: str,
        fs: fsspec.AbstractFileSystem,
        station_to_gage: Dict[Tuple[str, str], str],
        limit: int | None = None
    ) -> List[Tuple[str, str]]:
        """
        recursively filter raw .stm files and gage IDs under ismn_source
        by stations that fall within known basins
        returning tuples of (file_path, gage_id) for parsing

        Parameters
        ------------
        ismn_source: str
            path to a single .stm file or a directory containing .stm files
        fs: fsspec.AbstractFileSystem
            filesystem instance for reading files (local or remote)
        station_to_gage: Dict[(network, station), gage_id]
            mapping of valid stations to their basin gage_id
        limit: int or None
            maximum number of files to filter (for testing)

        Returns
        --------
        List[Tuple[str, str]]
            list of (file_path, gage_id) tuples for files belonging to known stations
        """
        pruned_files_and_gage_id: List[Tuple[str, str]] = []
        files_processed = 0

        # decide if source is a single file or directory
        if fs.isfile(ismn_source) and ismn_source.lower().endswith('.stm'):
            # emulate fs.ls for a single ISMN file by wrapping it in a dict
            entries = [{'name': ismn_source, 'type': 'file'}]
        elif fs.isdir(ismn_source):
            # get all ISMN files/directories
            entries = fs.ls(ismn_source, detail=True)
        else:
            raise FileNotFoundError(f"{ismn_source!r} not found or not a .stm file/dir")

        # iterate entries and collect matching ISMN files
        for entry in entries:
            path = entry['name']
            if entry['type'] == 'file' and path.lower().endswith('.stm'):
                # extract the station key and check if it's known
                network_station_tuple = ISMNPreprocessor.extract_network_and_station_from_ISMN_filename(path)
                if network_station_tuple and network_station_tuple in station_to_gage:
                    # add ISMN filepath and associated gage_id
                    pruned_files_and_gage_id.append((path, station_to_gage[network_station_tuple]))
                    files_processed += 1

                    # stop early if limit reached
                    if limit is not None and files_processed >= limit:
                        break
            elif entry['type'] == 'directory':
                # recurse into subdirectories with remaining limit
                remaining = None if limit is None else (limit - files_processed)

                # get subdirectory pruned files and gage ids list of tuples
                subdir_pruned_files_and_gage_id = ISMNPreprocessor.filter_ismn_files_within_basins(
                    path,
                    fs,
                    station_to_gage,
                    remaining
                )

                # iterate over subdir
                for file_path, gage_id in subdir_pruned_files_and_gage_id:
                    # stop early if limit reached
                    if limit is not None and files_processed >= limit:
                        break

                    # add ISMN filepath and associated gage_id
                    pruned_files_and_gage_id.append((file_path, gage_id))
                    files_processed += 1

                # break outer for loop if limit reached during recursion
                if limit is not None and files_processed >= limit:
                    break

        # apply overall limit and return
        return pruned_files_and_gage_id[:limit] if limit is not None else pruned_files_and_gage_id

    @staticmethod
    def extract_unique_stations(raw_ismn_files: list[str], fs: fsspec.AbstractFileSystem) -> gpd.GeoDataFrame:
        """
        loads unique station points from raw .stm files by reading first valid line of each file

        Parameters
        ------------
        raw_ismn_files: list[str]
            list of raw ISMN file paths
        fs: fsspec.AbstractFileSystem
            filesystem instance for reading files

        Returns
        --------
        geopandas.GeoDataFrame
            geodataframe with unique network, station, lat, lon, and geometry columns
        """
        records = []

        for file_path in raw_ismn_files:
            # open the raw file as bytes and get the first valid line
            with fs.open(file_path, 'rb') as f:
                # use iterator to get the first valid line
                first_line = next(ISMNPreprocessor.iter_ismn_records(f), None)

            # skip files with no valid lines
            if not first_line:
                continue

            print(f"first line:\n{first_line}")

            # get network, station, lat, and lon from line
            network = first_line[3]
            station = first_line[4]
            lat = float(first_line[5])
            lon = float(first_line[6])

            # add data from line to records
            records.append({
                'network': network,
                'station': station,
                'lat': lat,
                'lon': lon
            })

        # build a DataFrame, drop duplicate network/station combinations
        df = pd.DataFrame(records).drop_duplicates(['network', 'station'])

        # create geometry column from lon/lat
        df['geometry'] = df.apply(lambda row: Point(row['lon'], row['lat']), axis=1)

        # return as a GeoDataFrame in EPSG:4326
        return gpd.GeoDataFrame(df, geometry='geometry', crs='EPSG:4326')

    @staticmethod
    def map_stations_to_basins(stations_gdf: gpd.GeoDataFrame, basin_geoms: Dict[str, BaseGeometry]) -> Dict[Tuple[str, str], str]:
        """
        loads station→gage mapping via spatial join of station points to basin geometries

        Parameters
        ------------
        stations_gdf: geopandas.GeoDataFrame
            geodataframe with unique station points and geometry
        basin_geoms: Dict[str, BaseGeometry]
            mapping of gage_id to its basin geometry

        Returns
        --------
        Dict[Tuple[str, str], str]
            mapping of (network, station) to containing gage_id
        """
        print("stations CRS:", stations_gdf.crs)
        # build a geodataframe of basin polygons keyed by gage_id
        basin_df = gpd.GeoDataFrame(
            {'gage_id': list(basin_geoms.keys()),
             'geometry': list(basin_geoms.values())},
            crs=stations_gdf.crs
        )

        print("basins CRS:", basin_df.crs)

        print("stations bounds:", stations_gdf.total_bounds)
        print("basins   bounds:", basin_df.total_bounds)

        # spatial join stations to basins
        joined = gpd.sjoin(
            stations_gdf,
            basin_df,
            how='inner',
            predicate='intersects'
        )

        # build mapping of each station to its gage
        mapping = {
            (row['network'], row['station']): row['gage_id']
            for _, row in joined[['network', 'station', 'gage_id']].drop_duplicates().iterrows()
        }

        return mapping

    @staticmethod
    def find_stations_in_basin(ismn_data_gdf: gpd.GeoDataFrame, basin_geometry: shapely.geometry) -> gpd.GeoDataFrame:
        """
        Find ISMN stations within a given basin geometry.

        Parameters
        ----------
        ismn_data_gdf : geopandas.GeoDataFrame
            GeoDataFrame with columns for station_id, latitude, longitude, filename,
            and geometry (Point objects)
        basin_geometry : shapely.geometry
            Basin geometry of the basin to filter ISMN stations

        Returns
        -------
        geopandas.GeoDataFrame
            Filtered GeoDataFrame containing only ISMN stations within the basin.
        """
        if hasattr(basin_geometry, 'crs') and basin_geometry.crs != ismn_data_gdf.crs:
            ismn_data_gdf = ismn_data_gdf.to_crs(basin_geometry.crs)

        # Filter stations within the basin
        stations_in_basin = ismn_data_gdf[ismn_data_gdf.intersects(basin_geometry)]

        if not stations_in_basin['station_id'].empty:
            station_return = []
            for stations in stations_in_basin['station_id']:
                station_return.append(stations)
            print(f"{len(station_return)} SNOTEL stations found in basin: {station_return}")

        return stations_in_basin

    @staticmethod
    def preprocess_raw_ismn_files(raw_ismn_files: list[str], output_dir: str, fs: fsspec.filesystem, direct_s3: bool = False) -> None:
        """
        Preprocess raw ISMN files and save them to the output directory.

        Parameters
        ----------
        raw_ismn_files : list[str]
            List of raw ISMN file paths.
        output_dir : str
            Directory to save preprocessed ISMN files.
        fs : fsspec.filesystem
            Filesystem object for the specified base directory.
        direct_s3 : bool, optional
            If True, use s3 filesystem. If False, use local filesystem.
        """
        pass


if __name__ == "__main__":
    fs = fsspec.filesystem('file')
    ismn_raw_data_base_path = "/home/miguel.pena/noaa-owp/soil_moisture_sample_data"

    # get raw ISMN files
    raw_ismn_files = ISMNPreprocessor.get_raw_ismn_files(ismn_raw_data_base_path, fs)

    print(f"Found {len(raw_ismn_files)} raw ISMN files...")
    # extract unique stations from raw ISMN files
    stations_gdf = ISMNPreprocessor.extract_unique_stations(raw_ismn_files, fs)

    # print the first few rows of unique stations GeoDataFrame
    print(f"{len(stations_gdf)} unique ISMN stations extracted...")

    print("First few rows of unique stations:")
    print(stations_gdf.head())

    print("Last few rows of unique stations:")
    print(stations_gdf.tail())

    gpkg_path = "/home/miguel.pena/s3/ngwpc-dev/miguel.pena/conus_geopackages"
    # gpkg_path = "/home/miguel.pena/s3/ngwpc-dev/miguel.pena/conus_geopackages/gages-08447020.gpkg"
    output_dir = "/home/s3/ngwpc-dev/miguel.pena/ismn_preprocessed_data"

    # load basin geometries from geopackages into a dictionary
    # where keys are gage_ids and values are shapely geometries
    basin_geometries = ISMNPreprocessor.load_basin_geometries(gpkg_path, fs)
    print("loaded basins:", list(basin_geometries.keys()))

    station_to_gage = ISMNPreprocessor.map_stations_to_basins(stations_gdf, basin_geometries)
    print(f"mapped {len(station_to_gage)} SCAN and USCRN stations to CONUS gages:")
    for (network, station), gage_id in station_to_gage.items():
        print(f"Network: {network}, Station: {station} -> Gage ID: {gage_id}")

    # all_stations = {(r.network, r.station) for r in stations_gdf.itertuples()}
    # mapped = set(station_to_gage)
    # unmapped = all_stations - mapped
    # print(f"{len(unmapped)} stations unmapped:")
    # for (network, station) in unmapped:
    #     print(f"Network: {network}, Station: {station} -> Gage ID: None (unmapped)")

    # filter ISMN files to only those that have stations within known basins
    ismn_files_within_basins = ISMNPreprocessor.filter_ismn_files_within_basins(
        ismn_raw_data_base_path,
        fs,
        station_to_gage,
    )

    print(f"Found {len(ismn_files_within_basins)} ISMN files within known basins...")
    for file_path, gage_id in ismn_files_within_basins:
        print(f"File: {file_path}")
        print(f"Gage ID: {gage_id}")
