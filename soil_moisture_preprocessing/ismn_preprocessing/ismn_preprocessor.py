import re
import fsspec
import pandas as pd
import geopandas as gpd
import shapely.geometry

from typing import Dict, Tuple
from pathlib import Path
from shapely.geometry.base import BaseGeometry
from shapely.geometry import Point, Polygon, MultiPolygon

from utils.geo_utils import GeoUtils


class ISMNPreprocessor:
    @staticmethod
    def load_basin_geometries(gpkg_dir: str, fs: fsspec.AbstractFileSystem) -> Dict[str, BaseGeometry]:
        """
        loads all 'gages-<gage_id>.gpkg' files in gpkg_dir and returns a dict mapping each gage_id to its unified basin geometry

        Parameters
        ----------
        gpkg_dir: str
            path to the directory containing basin geopackages
        fs: fsspec.AbstractFileSystem
            filesystem instance for reading files

        Returns
        -------
        Dict[str, BaseGeometry]
            mapping of gage_id to its unified basin geometry
        """
        # limit the number of files processed for testing purposes
        # limit = 10
        basin_geoms: Dict[str, BaseGeometry] = {}
        # list everything under the directory
        for entry in fs.ls(gpkg_dir, detail=True):
            path = entry["name"]
            if entry["type"] == "file" and path.lower().endswith(".gpkg"):
                # extract gage_id from filename
                fname = Path(path).name
                gage_id = fname.removeprefix("gages-").removesuffix(".gpkg")

                print(f"processing gage_id: {gage_id}...")

                # read the divides layer and get its unioned geometry
                basin_gdf = GeoUtils.read_geo(path)
                print(f"GeoDataFrame containing the basin divides with geographic CRS for gage_id: {gage_id}...")
                print(basin_gdf.head())
                geom, _ = GeoUtils.get_basin_geometry(basin_gdf)

                basin_geoms[gage_id] = geom

                # compute coordinate count handling both Polygon and MultiPolygon
                if isinstance(geom, Polygon):
                    coord_count = len(geom.exterior.coords)
                elif isinstance(geom, MultiPolygon):
                    coord_count = sum(len(poly.exterior.coords) for poly in geom.geoms)
                else:
                    coord_count = 0

                print(f"basin geometry type: {geom.geom_type}")
                print(f"basin geometry area: {geom.area}")
                print(f"basin geometry bounds: {geom.bounds}")
                print(f"basin geometry centroid: {geom.centroid}")
                print(f"basin geometry number of coordinates: {coord_count}")

                # if len(basin_geoms) >= limit:
                #     print(f"Reached limit of {limit} basin geometries, stopping further processing.")
                #     break

        return basin_geoms

    @staticmethod
    def get_raw_ismn_files(ismn_raw_data_base_dir: str, fs: fsspec.AbstractFileSystem, direct_s3: bool = False) -> list[str]:
        """
        Get all ISMN files from the specified base directory recursively.

        Parameters
        ----------
        ismn_raw_data_base_dir : str
            Base directory for ISMN raw data.
        direct_s3 : bool, optional
            If True, use s3 filesystem. If False, use local filesystem.

        Returns
        -------
        list[str]
            List of ISMN file paths.
        """
        ismn_files = []
        for entry in fs.ls(ismn_raw_data_base_dir, detail=True):
            if entry['type'] == 'file' and entry['name'].endswith('.stm'):
                ismn_files.append(entry['name'])
            elif entry['type'] == 'directory':
                ismn_files.extend(ISMNPreprocessor.get_raw_ismn_files(entry['name'], fs))

        # for ismn_file in ismn_files:
        #     print(ismn_file)

        return ismn_files

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
        # regex pattern to match the first valid line in ISMN files
        ts_pattern = re.compile(
            r'^(?P<start>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2})\s+'
            r'(?P<end>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2})\s+'
            r'(?P<rest>.*)$'
        )

        records = []
        for file_path in raw_ismn_files:
            # open file and scan for first valid line
            with fs.open(file_path, 'rb') as f:
                for raw in f:
                    line = raw.decode('utf-8').strip()
                    m = ts_pattern.match(line)
                    if not m:
                        continue
                    parts = m.group('rest').split()
                    if len(parts) != 11:
                        continue
                    network, station = parts[1], parts[2]
                    lat, lon = float(parts[4]), float(parts[5])
                    records.append({
                        'network': network,
                        'station': station,
                        'lat': lat,
                        'lon': lon
                    })
                    break

        df = pd.DataFrame(records).drop_duplicates(['network', 'station'])
        # create geometry column
        df['geometry'] = df.apply(lambda row: Point(row['lon'], row['lat']), axis=1)
        # build geodataframe
        gdf = gpd.GeoDataFrame(df, geometry='geometry', crs='EPSG:4326')
        return gdf

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
        # build a geodataframe of basin polygons keyed by gage_id
        basin_df = gpd.GeoDataFrame(
            {'gage_id': list(basin_geoms.keys()),
             'geometry': list(basin_geoms.values())},
            crs=stations_gdf.crs
        )

        # spatial join stations to basins
        joined = gpd.sjoin(
            stations_gdf,
            basin_df,
            how='inner',
            predicate='within'
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
    ismn_raw_data_base_dir = "/home/miguel.pena/noaa-owp/soil_moisture_sample_data"

    # get raw ISMN files
    raw_ismn_files = ISMNPreprocessor.get_raw_ismn_files(ismn_raw_data_base_dir, fs)

    print(f"Found {len(raw_ismn_files)} raw ISMN files...")
    # extract unique stations from raw ISMN files
    stations_gdf = ISMNPreprocessor.extract_unique_stations(raw_ismn_files, fs)

    # print the first few rows of unique stations GeoDataFrame
    print(f"{len(stations_gdf)} unique ISMN stations extracted...")
    print(stations_gdf.head())
    print(stations_gdf.tail())

    gpkg_dir = "/home/miguel.pena/s3/ngwpc-dev/miguel.pena/conus_geopackages"
    output_dir = "/home/s3/ngwpc-dev/miguel.pena/ismn_preprocessed_data"

    # load basin geometries from geopackages into a dictionary
    # where keys are gage_ids and values are shapely geometries
    basin_geometries = ISMNPreprocessor.load_basin_geometries(gpkg_dir, fs)
    print("loaded basins:", list(basin_geometries.keys()))

    station_to_gage = ISMNPreprocessor.map_stations_to_basins(stations_gdf, basin_geometries)
    print(station_to_gage)
