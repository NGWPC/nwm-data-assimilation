import geopandas as gpd

from pathlib import Path
from shapely.ops import unary_union
from shapely.geometry.base import BaseGeometry


class GeoUtils:
    @staticmethod
    def read_geo(gpkg_file):
        """
        Read the 'divides' layer from a geopackage file and ensure geographic CRS.

        Parameters
        ----------
        gpkg_file : str
            Path to the geopackage file

        Returns
        -------
        geopandas.GeoDataFrame
            GeoDataFrame containing the basin divides with geographic CRS
        """
        if not Path(gpkg_file).exists():
            raise FileNotFoundError(f"Geopackage file '{gpkg_file}' not found. Please check the file path.")

        basin_gdf = gpd.read_file(gpkg_file, layer='divides', engine='pyogrio')
        basin_gdf = basin_gdf[['geometry']]

        if basin_gdf.crs is None or not basin_gdf.crs.is_geographic:
            basin_gdf = basin_gdf.to_crs('EPSG:4326')

        return basin_gdf

    @staticmethod
    def get_basin_geometry(basin_gdf: gpd.GeoDataFrame) -> tuple[BaseGeometry, tuple]:
        """
        extract a unified basin geometry and its bounds from a GeoDataFrame containing basin divides

        Parameters
        ------------
        basin_gdf: geopandas.GeoDataFrame
            GeoDataFrame with a 'geometry' column of Polygon/MultiPolygon features.
            must be in a geographic CRS (e.g. EPSG:4326) before calling.

        Returns
        --------
        tuple[BaseGeometry, tuple]
            unified_basin_geom: combined shapely geometry representing the entire basin
            basin_bounds: (minx, miny, maxx, maxy) tuple defining the basin extent
        """

        # requirements: geopandas, shapely; basin_gdf must include only the geometry column and proper CRS

        # repair invalid geometries: buffer(0) often fixes self-intersections or slivers
        valid_geometries = basin_gdf.geometry.apply(
            lambda geom: geom if geom.is_valid else geom.buffer(0)
        )

        # if there's only one polygon, use it directly
        if len(valid_geometries) == 1:
            unified_basin_geom = valid_geometries.iloc[0]
        else:
            # try the fast Shapely union of multiple pieces
            try:
                unified_basin_geom = unary_union(valid_geometries)
            except Exception:
                # fallback to GeoPandas’ union_all if unary_union isn’t available
                unified_basin_geom = basin_gdf.geometry.values.union_all()

        # compute the bounding box of the final basin shape
        basin_bounds = unified_basin_geom.bounds

        return unified_basin_geom, basin_bounds
