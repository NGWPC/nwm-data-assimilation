import os
import time

import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import numpy as np
import geopandas as gpd
import argparse
import fsspec
from ..utility.swe_minmax import get_minmax
#import time

def load_and_process_data(netcdf_file, gpkg_file, date_str):
    """Load and process SWE data from NetCDF and geopackage files
    
    Args:
        netcdf_file: Path to NetCDF file
        gpkg_file: Path to geopackage file
        date_str: Date string from NetCDF time dim (ex: '2015-12-01')
    """
    t0 = time.time()
    ds = xr.open_dataset(netcdf_file)
    print(f"   NetCDF load time: {time.time() - t0:.2f}s")
    
    # Read divides layer from geopackage
    # t1 = time.time()
    gdf = read_geo(gpkg_file)

    # Combine all polygons for basin outline
    try:
        basin_geometry = gdf.union_all()
    except AttributeError:
        basin_geometry = gdf.unary_union
    bounds = basin_geometry.bounds
    # print(f"   Geometry load time: {time.time() - t1:.2f} seconds")

    # Select timestep
    # t2 = time.time()
    swe_data = ds.swe.sel(date=date_str).values

    # Create a mapping dictionary from catchment IDs to SWE values
    catchment_ids = ds.catchment.values
    swe_dict = dict(zip(catchment_ids, swe_data))
    
    # Create catchment ID column and then lookup values from dict
    gdf['catchment_id'] = gdf['divide_id'].str.split('-').str[1].astype(int)
    gdf['mean_swe'] = gdf['catchment_id'].map(swe_dict).fillna(np.nan)
    # print(f"   SWE load/process time: {time.time() - t2:.2f}s")

    return ds, gdf, basin_geometry, bounds

def read_geo(gpkg_file):
    """Read divides layer from .gpkg file to GeoDataFrame"""
    if not os.path.exists(gpkg_file):
        raise FileNotFoundError(f"Geopackage file '{gpkg_file}' not found. Please check the file path.")

    gdf = gpd.read_file(gpkg_file, layer='divides')

    if not gdf.crs.is_geographic:
        gdf = gdf.to_crs('EPSG:4326')

    return gdf


def plot_catchment_boundaries(ax, gdf, proj):
    """Add catchment boundaries to plot"""
    for _, row in gdf.iterrows():
        ax.add_geometries([row.geometry], crs=proj,
                         facecolor='none',
                         edgecolor='black',
                         linewidth=0.5,
                         alpha=0.5)
    return ax

def plot_polygon_simulated_swe(ax, gdf, proj):
    """Plot catchments filled with their simulated (lumped) SWE values"""
    
    # Set color scale based on min/max values
    #vmin = float(gdf['mean_swe'].min())
    vmin,vmax = get_minmax(gdf['mean_swe'])
    norm = plt.Normalize(vmin=vmin, vmax=vmax)
    cmap = plt.cm.Blues
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    
    for _, row in gdf.iterrows():
        if not np.isnan(row['mean_swe']):
            ax.add_geometries([row.geometry], crs=proj,
                            facecolor=cmap(norm(row['mean_swe'])),
                            edgecolor='none')
    
    ax = plot_catchment_boundaries(ax, gdf, proj)
    return ax, sm, vmin, vmax

def plot_swe_map(netcdf_file, gpkg_file, date_str, output_file, mode='plot'):
    """Creates a map of simulated SWE values by catchment"""
    
    ds, gdf, basin_geometry, bounds = load_and_process_data(netcdf_file,
                                                            gpkg_file,
                                                            date_str)
    if mode == 'scan':
        return get_minmax(gdf['mean_swe'])
    # t1 = time.time()
    # Create base plot
    proj = ccrs.PlateCarree()
    fig, ax = plt.subplots(figsize=(15, 10), 
                          subplot_kw={'projection': proj})
    
    # Set the extent using dynamic vertical and horizontal buffers
    buff_v = abs(bounds[2]-bounds[0])*.01
    buff_h = abs(bounds[3]-bounds[1])*.01
    ax.set_extent([
        bounds[0] - buff_v,
        bounds[2] + buff_v,
        bounds[1] - buff_h,
        bounds[3] + buff_h
    ], crs=proj)
    
    # Call plot function
    ax, im, vmin, vmax = plot_polygon_simulated_swe(ax, gdf, proj)
    
    # Plot basin outline
    ax.add_geometries([basin_geometry], crs=proj,
                     facecolor='none', edgecolor='red',
                     linewidth=1.5)
    
    # Plot colorbar based on settings in plot functions
    cbar = plt.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label('Snow Water Equivalent (m)', fontsize=10)
    
    # Title bar with date
    plt.title(f'Simulated Snow Water Equivalent (SWE)\n {date_str} - 06z')
    
    # Add gridlines and set labels
    gl = ax.gridlines(draw_labels=True, linewidth=0.5,
                      color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    # print(f"   Plotting time: {time.time() - t1:.2f}s")


    if output_file:
        # t4=time.time()
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()
        # print(f"   output time: {time.time() - t4:.2f}s")
    else:
        plt.show()

def get_options(args_list=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('netcdf_file', type=str,
                       help="Path to NetCDF file")
    parser.add_argument('gpkg_file', type=str,
                       help="Path to geopackage file")
    parser.add_argument('date', type=str,
                       help="Date to plot (ex: '2015-12-01')")
    parser.add_argument('--output_file', type=str, default=None,
                       help="Path where output image is saved")
    parser.add_argument('--mode', type=str, default='plot',
                       choices=['plot', 'scan'],
                       help="Operation mode: 'plot' or 'scan'")
    return parser.parse_args(args_list)

def main(args_list=None):
    args = get_options(args_list)
    plot_swe_map(args.netcdf_file, args.gpkg_file, args.date, 
                 args.output_file, args.mode)

if __name__ == "__main__":
    main()


