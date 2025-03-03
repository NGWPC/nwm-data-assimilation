import argparse
import time

import cartopy.crs as ccrs
import fsspec
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from shapely.geometry import Point

from ..utility.swe_minmax import get_minmax


def load_and_process_data(netcdf_file, gpkg_file=None, plot_type='grid'):
    """Load and process SWE data from NetCDF and optional geopackage files"""
    t0 = time.time()

    # Open the SNODAS NetCDF file with chunking to optimize performance and memory usage.
    print('Opening netCDF file', netcdf_file)
    with fsspec.open(netcdf_file, mode='rb') as f:
        ds = xr.open_dataset(f, chunks={"time": 1, "lat": 50, "lon": 50})
        # Chunking strategy:
        # - "time": 1 → Process one timestep at a time to avoid excessive memory usage.
        # - "lat": 50, "lon": 50 → Read 50x50 spatial chunks to balance memory usage and I/O performance.

    print(f"   NetCDF load time: {time.time() - t0:.2f}s")

    # t1 = time.time()
    gdf = read_geo(gpkg_file)

    # Combine all polygons from divides layer
    basin_geometry = gdf.union_all()
    # Store catchment boundaries
    bounds = basin_geometry.bounds

    # print(f"   Geometry load time: {time.time() - t1:.2f}s")

    return ds, gdf, basin_geometry, bounds


def read_geo(gpkg_file):
    """Read divides layer from .gpkg file to GeoDataFrame and convert to CRS if needed."""
    gdf = gpd.read_file(gpkg_file, layer='divides')
    if gdf.crs is None or not gdf.crs.is_geographic:
        gdf = gdf.to_crs('EPSG:4326')
    return gdf


def subset_to_basin(ds, basin_geometry):
    """Subset dataset to basin extent using bounding box filtering."""

    # Use bounding box to filter dataset
    bounds = basin_geometry.bounds
    lon_mask = (ds.lon >= bounds[0]) & (ds.lon <= bounds[2])
    lat_mask = (ds.lat >= bounds[1]) & (ds.lat <= bounds[3])

    # Apply the mask and compute to load required data
    ds_subset = ds.where(lon_mask & lat_mask, drop=True).compute()
    # `.compute()` ensures that the filtered dataset is fully materialized.

    # Convert units from millimeters to meters
    ds_subset['Band1'] = ds_subset.Band1 / 1000

    # Create meshgrid of lat/lon values
    lons, lats = np.meshgrid(ds_subset.lon, ds_subset.lat)

    return ds_subset, lons, lats


def calculate_catchment_mean(ds, basin_geometry, gdf):
    """Calculate mean SWE for each catchment efficiently"""

    # Subset to basin and compute to ensure faster processing
    ds_subset, lons, lats = subset_to_basin(ds, basin_geometry)

    # Convert meshgrid into Points for fast spatial operations
    points = np.array([Point(x, y) for x, y in zip(lons.ravel(), lats.ravel())])

    mean_values = []
    for _, row in gdf.iterrows():
        # Mask for each catchment using Shapely `contains`
        mask = np.array([row.geometry.contains(pt) for pt in points]).reshape(lons.shape)

        # Extract SWE data for catchment and compute mean
        catchment_data = ds_subset.Band1.where(mask)
        mean_swe = float(catchment_data.mean().compute())  # `.compute()` ensures calculation is performed before storing the value.
        mean_values.append(mean_swe)

        # Apply computed mean value efficiently
        ds_subset['Band1'] = xr.where(mask, mean_swe, ds_subset.Band1)

    # Add computed mean values to GeoDataFrame
    gdf['mean_swe'] = mean_values

    # Mask everything outside the basin
    basin_mask = np.array([basin_geometry.contains(pt) for pt in points]).reshape(lons.shape)
    ds_subset['Band1'] = ds_subset.Band1.where(basin_mask)

    return gdf, ds_subset


def plot_catchment_boundaries(ax, gdf, proj):
    """Add catchment boundaries to plot"""

    # Iterate over polygons in the dataframe, drawing boundaries
    for _, row in gdf.iterrows():
        ax.add_geometries([row.geometry], crs=proj,
                          facecolor='none',
                          edgecolor='black',
                          linewidth=0.5,
                          alpha=0.5)
    return ax


def plot_raw_swe(ax, ds, basin_geometry, gdf, proj):
    """Plot raw SWE values within basin boundary"""

    # Subset dataset
    ds_subset, lons, lats = subset_to_basin(ds, basin_geometry)

    # Convert lat/lon into Points for spatial operations
    points = np.array([Point(x, y) for x, y in zip(lons.ravel(), lats.ravel())])
    basin_mask = np.array([basin_geometry.contains(pt) for pt in points]).reshape(lons.shape)

    # Mask invalid values & apply basin mask
    swe_data = ds_subset.Band1.where(ds_subset.Band1 != -9999).where(basin_mask)

    # Compute min/max values for colormap scaling
    vmin, vmax = get_minmax(swe_data.compute())  # `.compute()` ensures SWE data is processed before computing range.

    # Create colormesh plot
    im = ax.pcolormesh(ds_subset.lon, ds_subset.lat.compute(), swe_data,
                       transform=proj,
                       cmap='Blues',
                       vmin=vmin,
                       vmax=vmax,
                       shading='auto')

    # Add catchment boundaries
    ax = plot_catchment_boundaries(ax, gdf, proj)

    return ax, im, vmin, vmax


def plot_polygon_swe(ax, gdf, proj):
    """Plot catchment polygons colored by mean SWE values."""

    # Use vmin and vmax to explicitly define a colorbar
    vmin, vmax = get_minmax(gdf['mean_swe'])
    norm = plt.Normalize(vmin=vmin, vmax=vmax)
    cmap = plt.cm.Blues
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])

    # Plot filled polygons
    for _, row in gdf.iterrows():
        ax.add_geometries([row.geometry], crs=proj,
                          facecolor=cmap(norm(row['mean_swe'])),
                          edgecolor='none')

    # Add catchment boundaries
    ax = plot_catchment_boundaries(ax, gdf, proj)

    return ax, sm, vmin, vmax


def plot_swe_map(netcdf_file, gpkg_file, output_file_raw, output_file_catchment, date_str):
    """Creates a base map, and calls functions to plot SWE data based
     on visualization type.

    Arguments:

    netcdf_file: Path to SNODAS NetCDF file.
    gpkg_file: Path to geopackage file.
    output_file_raw: Path where raw visualization output is saved.
    output_file_catchment: Path where catchment-averaged output is saved.
    """
    # Load raw data first
    ds, gdf, basin_geometry, bounds = load_and_process_data(netcdf_file, gpkg_file, 'raw')

    # Create raw plot
    t3 = time.time()
    proj = ccrs.PlateCarree()
    fig, ax = plt.subplots(figsize=(15, 10), subplot_kw={'projection': proj})

    # Set the extent using dynamic vertical and horizontal buffers
    buff_v = abs(bounds[2] - bounds[0]) * .01
    buff_h = abs(bounds[3] - bounds[1]) * .01
    ext = [
        bounds[0] - buff_v,
        bounds[2] + buff_v,
        bounds[1] - buff_h,
        bounds[3] + buff_h
    ]
    ax.set_extent(ext, crs=proj)

    # Plot raw SWE values
    ax, im, vmin, vmax = plot_raw_swe(ax, ds, basin_geometry, gdf, proj)

    # Overlay basin outline
    ax.add_geometries([basin_geometry], crs=proj,
                      facecolor='none', edgecolor='red',
                      linewidth=1.5)

    # Plot colorbar based on settings in plot functions
    cbar = plt.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label(f'Snow Water Equivalent (m)', fontsize=10)

    plt.title(f'Raw SNODAS Snow Water Equivalent\n {date_str} - 06z')

    # Add gridlines
    gl = ax.gridlines(draw_labels=True, linewidth=0.5,
                      color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False

    # Saves the raw version to the correct path
    if output_file_raw:
        t4 = time.time()
        plt.savefig(output_file_raw, dpi=300, bbox_inches='tight')
        plt.close()
        print(f"   Raw output time: {time.time() - t4:.2f}s")

    # Calculate catchment means
    gdf, ds_catchment = calculate_catchment_mean(ds, basin_geometry, gdf)

    # Create catchment plot
    fig, ax = plt.subplots(figsize=(15, 10),
                           subplot_kw={'projection': proj})
    ax.set_extent(ext, crs=proj)

    # Plot catchment-averaged SWE values
    ax, im, vmin, vmax = plot_polygon_swe(ax, gdf, proj)

    # Add basin outline
    ax.add_geometries([basin_geometry], crs=proj,
                      facecolor='none', edgecolor='red',
                      linewidth=1.5)

    # Plot colorbar based on settings in plot functions
    cbar = plt.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label(f'Snow Water Equivalent (m)', fontsize=10)

    plt.title(f'Lumped SNODAS Snow Water Equivalent\n {date_str} - 06z')

    # Add gridlines
    gl = ax.gridlines(draw_labels=True, linewidth=0.5,
                      color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False

    print(f"   Lumped plotting time: {time.time() - t3:.2f}s")

    # Save lumped output
    if output_file_catchment:
        t6 = time.time()
        plt.savefig(output_file_catchment, dpi=300, bbox_inches='tight')
        plt.close()
        print(f"   Lumped output time: {time.time() - t6:.2f}s")


def get_options(args_list=None):
    """Read and pass in command-line arguments"""
    parser = argparse.ArgumentParser()
    parser.add_argument('date', type=str,
                        help="Date of SNODAS data to map.")
    parser.add_argument('gpkg_file', type=str,
                        help="Path to geopackage file.")
    parser.add_argument('output_file_raw', type=str,
                        help="Path where raw visualization output is saved.")
    parser.add_argument('output_file_lumped', type=str,
                        help="Path where catchment-averaged output is saved.")
    return parser.parse_args(args_list)


def main(args_list=None):
    args = get_options(args_list)
    file_date = args.date.replace('-', '')

    # Construct NetCDF file path
    netcdf_file = f"s3://ngwpc-forcing/snodas_nc/zz_ssmv11034tS__T0001TTNATS{file_date}05HP001.nc"

    # Run SWE plotting
    plot_swe_map(netcdf_file, args.gpkg_file, args.output_file_raw, args.output_file_lumped, args.date)


if __name__ == "__main__":
    main()
