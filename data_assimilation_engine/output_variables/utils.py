import os
import requests
import xarray as xr
import csv
import numpy as np
import json
import logging
from . import consts
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime
from pyproj import CRS
from typing import List, Set, Tuple, Dict, Union, Optional
from functools import reduce


# region common
def parse_filename_metadata(filename: str) -> Tuple[str, str, str]:
    """
    Extract output_class, category and domain from filename.
    """
    components = filename.split(".")

    if len(components) < 7:
        raise Exception(f"NWM Output file name doesn't follow expected format: {filename}")

    output_class = components[2]
    category = components[3]
    domain = components[5]
    return output_class, category, domain
# endregion

# region data download
def download_nwm_data_from_server(base_url: str, local_root: str) -> None:
    """
    Main function to download a unique set of output files from the server
    """
    if not os.path.exists(local_root):
        os.makedirs(local_root)
    
    formatted_date = datetime.now().strftime("%Y%m%d")
    formatted_url = f"{base_url}/nwm.{formatted_date}/"
    existing_keys = build_existing_keys(local_root) # build class, category, domain keys in local folder, if exists.
    download_nwm_data_recursive(formatted_url, local_root, existing_keys)

def download_nwm_data_recursive(download_url: str, local_path: str, 
    existing_keys: Set[Tuple[str, str, str]]
) -> None:
    """
    Recursively download a unique set of output files from the server
    and create a mirrored folder structure locally
    """
    response = requests.get(download_url)
    if response.status_code != 200:
        raise Exception(f"Failed to access {download_url}")
    
    soup = BeautifulSoup(response.text, 'html.parser')
    links = soup.find_all('a', href=True)
    file_links = [link['href'] for link in links if not link['href'].startswith('/')]
    for file_link in file_links:
        file_url = urljoin(download_url, file_link)
        if (file_url.endswith('/')):
            local_file_path = os.path.join(local_path, file_link)
            download_nwm_data_recursive(file_url, local_file_path, existing_keys)
        else:
            if not file_link.endswith(".nc"):
                continue
            
            output_class, category, domain = parse_filename_metadata(file_link)
            key = (output_class, category, domain)

            # Skip if already exists
            if key in existing_keys:
                continue
            else:
                if not os.path.exists(local_path):
                    os.makedirs(local_path)
                save_path = os.path.join(local_path, file_link)
                download_file(file_url, save_path)
                # Add to existing set AFTER successful download
                existing_keys.add(key)

def download_file(url: str, save_path: str) -> None:
    """
    Downloads a file from a URL and saves it locally.
    """
    response = requests.get(url)
    if response.status_code == 200:
        with open(save_path, 'wb') as f:
            f.write(response.content)
        print(f"Downloaded: {save_path}")
    else:
        print(f"Failed to download: {url}, HTTP status code {response.status_code}")

def build_existing_keys(local_root: str) -> Set[Tuple[str, str, str]]:
    """
    Builds file keys in local folder. These keys are used when function is re-run 
    and enables the capability to not download a file again.
    """
    keys = set()
    for root, _, files in os.walk(local_root):
        for file in files:
            if file.endswith(".nc"):
                output_class, category, domain = parse_filename_metadata(file)
                keys.add((output_class, category, domain))

    return keys

# endregion

# region metadata extraction
class NetCDFMetadata:
    def __init__(
        self,
        file_path: str,
        resolution_x: float,
        resolution_y: float,
        origin_x: float,
        origin_y: float,
        x_loc: str,
        y_loc: str,
        wkt: Optional[str],
        variables: str,
        dimensions: str, 
        scalar_variables: Dict[str, List[str]], 
        data_variables_dim: Dict[str, Union[int, float, str]],
        output_class: str,
        category: str,
        domain: str,
    ) -> None:
        self.file_path = file_path
        self.resolution_x = resolution_x
        self.resolution_y = resolution_y
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.x_name = x_loc
        self.y_name = y_loc
        self.nwm_variables = variables
        self.nwm_dimensions = dimensions
        self.scalar_variables = scalar_variables
        self.data_variables_dim = data_variables_dim
        self.crs_wkt = wkt
        self.output_class = output_class
        self.category = category
        self.domain = domain

    def key(self) -> tuple[str, str, str]:
        """
        Unique identifier for duplicate checking
        """
        return (self.output_class, self.category, self.domain)

    def __repr__(self) -> str: #for debugging purposes
        return (
            f"NetCDFMetadata(file_path={self.file_path}, "
            f"class={self.output_class}, category={self.category}, domain={self.domain})"
        )

def obtain_metadata_information(local_root: str, output_name: str) -> None:
    """
    Parse the metadata information from the downloaded NWM output files and write a CSV and a json
    """
    if not os.path.exists(local_root):
        raise Exception(f"Folder does not exist: {local_root}")
    
    metadata_list = process_downloaded_files(local_root)
    output_csv = os.path.join(local_root, output_name + ".csv")
    write_metadata_to_csv(metadata_list, output_csv)
    output_json = os.path.join(local_root, output_name + "_config.json")
    ngen_json = os.path.join(local_root, output_name + "_ngenconfig.json")
    write_metadata_to_config_json(metadata_list, output_json, ngen_json)
    
    

def process_downloaded_files(local_root: str) -> List[NetCDFMetadata]:
    """
    Process downloaded files and create a list of metadata objects for config json
    """
    metadata_list: List[NetCDFMetadata] = []

    for root, _, files in os.walk(local_root):
        for file in files:
            if file.endswith(".nc"):
                file_path = os.path.join(root, file)
                metadata_list.append(extract_netcdf_metadata(file_path))

    return metadata_list

def extract_netcdf_metadata(file_path: str) -> NetCDFMetadata:

    filename = os.path.basename(file_path)
    output_class, category, domain = parse_filename_metadata(filename)
    res_x = -9999
    res_y = -9999
    origin_x = -9999
    origin_y = -9999
    proj_wkt = 'Not Available'
    vars_in_netcdf = []
    nwm_variables = ''
    dimensions = ''
    x_loc_name = ''
    y_loc_name = ''
    scalar_dict = {}
    data_dict = {}

    ds = xr.open_dataset(file_path)
    dimensions = ", ".join(ds.sizes.keys());
    for nwm_var in ds.variables:
        dims_list = list(ds[nwm_var].dims)
        num_dims = len(dims_list)
        if num_dims == 0:
            scalar_val = ds[nwm_var].values.item()
            if isinstance(scalar_val, bytes): #scalar variables need to be converted from bytes to string.
                scalar_val = scalar_val.decode('utf-8')
            scalar_dict[str(nwm_var)] = scalar_val
        elif num_dims > 0:
            data_dict[str(nwm_var)] = dims_list
        
        if nwm_var in consts.X_LOC: #XRes: assume only one of the x_loc will be in the file
            x = ds.variables[nwm_var].values
            res_x = compute_resolution(x)
            origin_x = float(x.min())
            x_loc_name = nwm_var
        elif nwm_var in consts.Y_LOC: #YRes: assume only one of the y_loc will be in the file
            y = ds.variables[nwm_var].values
            res_y = compute_resolution(y)
            origin_y = float(y.min())
            y_loc_name = nwm_var
        elif nwm_var in consts.CRS_INFO: #CRS wkt
            proj_wkt = extract_wkt_from_crs(ds.variables[nwm_var])
        elif nwm_var in consts.NWM_VARIABLES_LIST: #NWM output variables
            vars_in_netcdf.append(nwm_var)
    nwm_variables = ", ".join(vars_in_netcdf)
    return NetCDFMetadata(file_path, res_x, res_y, origin_x, origin_y, x_loc_name, y_loc_name, proj_wkt, 
                          nwm_variables, dimensions, scalar_dict, data_dict, output_class, category, domain)

def compute_resolution(coords: np.ndarray) -> float:
    """
    Compute resolution from coordinate array using median spacing.
    """
    if coords.size < 2:
        return 0.0

    diffs = np.diff(coords)
    return float(np.median(np.abs(diffs)))

def extract_wkt_from_crs(crs_var) -> Optional[str]:
    """
    Extract wkt attribute from CRS variable.
    """
    if "spatial_ref" in crs_var.attrs:
        return crs_var.attrs["spatial_ref"]
    elif "esri_pe_string" in crs_var.attrs:
        return crs_var.attrs["esri_pe_string"]
    return None
    
def write_metadata_to_csv(metadata_list: List[NetCDFMetadata], output_csv: str) -> None:
    """
    Writes a list of NetCDFMetadata objects to a CSV file.
    """
    fieldnames: List[str] = [
        "file_path",
        "resolution_x",
        "resolution_y",
        "origin_x",
        "origin_y",
        "x_name",
        "y_name",
        "crs_wkt",
        "variables",
        "class",
        "category",
        "domain",
    ]

    with open(output_csv, mode="w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()

        for metadata in metadata_list:
            writer.writerow(
                {
                    "file_path": metadata.file_path,
                    "resolution_x": metadata.resolution_x,
                    "resolution_y": metadata.resolution_y,
                    "origin_x": metadata.origin_x,
                    "origin_y": metadata.origin_y,
                    "x_name": metadata.x_name,
                    "y_name": metadata.y_name,
                    "crs_wkt": metadata.crs_wkt if metadata.crs_wkt is not None else "Not Available",
                    "variables": metadata.nwm_variables,
                    "class": metadata.output_class or "",
                    "category": metadata.category or "",
                    "domain": metadata.domain or "",
                }
            )

def write_metadata_to_config_json(metadata_list: List[NetCDFMetadata], output_json: str, ngen_json: str) -> None:
    """
    Writes NetCDFMetadata objects to config JSON.
    """
    info_list = []
    for mdata in metadata_list:
        metadata_info_dict = {
            "file_path": mdata.file_path,
            "resolution": {
                "x": mdata.resolution_x,
                "y": mdata.resolution_y,
            },
            "origin": {
                "x": mdata.origin_x,
                "y": mdata.origin_y,
            },
            "location_name": {
                "x": mdata.x_name,
                "y": mdata.y_name,
            },
            "crs_wkt": mdata.crs_wkt,
            "nwm_variables": mdata.nwm_variables,
            "nwm_dimensions": mdata.nwm_dimensions,
            "nwm_scalar_variables": mdata.scalar_variables,
            "nwm_var_dimensions": mdata.data_variables_dim,
            "class": mdata.output_class,
            "category": mdata.category,
            "domain": mdata.domain
        }
        info_list.append(metadata_info_dict)

    config = {
        "files": info_list
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(config, f, indent = 2)

    print(f"Config JSON written to: {output_json}")

    info_list = []
    for mdata in metadata_list:
        metadata_info_dict = {
            "class": mdata.output_class,
            "category": mdata.category,
            "domain": mdata.domain,
            "nwm_variables": mdata.nwm_variables,
            "nwm_dimensions": mdata.nwm_dimensions,
            "nwm_scalar_variables": mdata.scalar_variables,
            "nwm_var_dimensions": mdata.data_variables_dim
        }
        info_list.append(metadata_info_dict)

    config = {
        "nwm_info": info_list
    }
    with open(ngen_json, "w", encoding="utf-8") as f:
        json.dump(config, f, indent = 2)

    print(f"Config JSON written to: {ngen_json}")

def debug_netcdf_structure_in_folder(folder_path: str) -> None:
    """
    Recursively scans a folder for NetCDF files and prints their structure.
    """
    # This function is used for testing purposes. 
    # It also uses a local logging to save all information into a file.
    nc_files: List[str] = []
    data_variables_list = []
    logging.basicConfig(filename='app.log', level=logging.INFO, format='%(message)s')
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.endswith(".nc"):
                nc_files.append(os.path.join(root, file))

    if not nc_files:
        print(f"No NetCDF files found in: {folder_path}")
        return
    logging.info(f"Found {len(nc_files)} NetCDF files within the folder")

    for file_path in nc_files:
        logging.info("-" * 80)
        logging.info(f"FILE: {file_path}")

        try:
            with xr.open_dataset(file_path) as ds:
                # Variables
                logging.info("--Variables:")
                for var_name, var in ds.data_vars.items():
                    logging.info(f"----  {var_name}: shape={var.shape}, dtype={var.dtype}")
                    output_class, category, domain = parse_filename_metadata(file_path)
                    data_variables_list.append(var_name + ";" + output_class + ";" + category + ";" + domain)

                # Dimensions
                logging.info("--Dimensions:")
                for dim_name, dim_size  in ds.sizes.items():
                    logging.info(f"----  {dim_name}: size={dim_size}")

                # CRS-specific attributes if present
                is_crs_present = False 
                is_sref_present = False 
                for crs_name in ["crs", "CRS", "spatial_ref"]:
                    if crs_name in ds.variables:
                        logging.info(f"--CRS Variable: {crs_name}")
                        is_crs_present = True
                        crs_var = ds.variables[crs_name]
                        if 'spatial_ref' in crs_var.attrs:
                            spatial_ref_raw = ds.variables[crs_name].attrs['spatial_ref']
                            is_sref_present = True
                            logging.info(f"----{spatial_ref_raw}")
                logging.info(f"-- CRS Available: {is_crs_present}; Spatial_ref Available: {is_sref_present}")
            
            # The snippet below is use to write variables along with the class, category and domain
            # This produces an additional csv with just basic variables information.
            with open('variables_ccategories.csv', 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Variable", "Class", "Category", "Domain"])
                for var in data_variables_list:
                    if not var.startswith('crs'):
                        row = var.split(";")
                        writer.writerow(row)
        except Exception as e:
            print(f"\n Failed to read file: {file_path}")
            print(f"Error: {e}")
# endregion

# region (to delete) create template grids
def create_nwm_template_grids(src_root_folder: str, dest_root_folder: str) -> None:
    """
    Creates template grids for all NWM netcdf products using a sample set of netcdfs.
    """
    # This function is there for testing purposes.
    # We can delete this once we are prodution ready.
    coords_to_reset = ['time', 'x', 'y', 'latitude', 'longitude']

    for root, dirs, files in os.walk(src_root_folder):
        # Determine the relative path to recreate subfolders
        rel_path = os.path.relpath(root, src_root_folder)
        target_dir = os.path.join(dest_root_folder, rel_path)
        
        # Create the target directory if it doesn't exist
        os.makedirs(target_dir, exist_ok=True)

        for file in files:
            if file.endswith('.nc'):
                src_path = os.path.join(root, file)
                dest_path = os.path.join(target_dir, file)

                # Process the NetCDF using xarray
                with xr.open_dataset(src_path) as ds:
                    # Reset data variables
                    for var in ds.data_vars:
                        if var in consts.NWM_VARIABLES_LIST:
                            ds[var].values[:] = -1
                    
                    # Reset coordinate variables
                    for coord in coords_to_reset:
                        if coord in ds.coords:
                            ds[coord].values[:] = - 1 # To do: Gives warning for time. Need to address
                    # Save to the desired location
                    ds.to_netcdf(dest_path)
                    print(f"Processed: {dest_path}")
# endregion

# region basin grid products
def create_combined_basin_netcdf_products (reference_grid: str, timestep_netcdf_folder: str, output_folder: str) -> None:
    """
    Main calling function to create a combined basins product
    """
    # Randomly pick timestep outputs at 6 hour intervals
    for i in range(0, 20, 6):
        search_string = f"01T{i:02}"
        files_list = find_files_by_timestep(timestep_netcdf_folder, search_string)
        variables_of_interest = ["ACCET"]
        # merged_ds = merge_basin_netcdfs(reference_grid, files_list)
        merged_ds, encoding = create_multi_basin_netcdfs(reference_grid, files_list, variables_of_interest, 1.0, None, True)
        output_file = os.path.join(output_folder, f"combined_grid_{i:02}_.nc")
        merged_ds.to_netcdf(output_file, encoding = encoding, engine='netcdf4')

def find_files_by_timestep(root_dir: str, search_timestep: str) -> List[str]:
    """
    Function to recursively search a folder for a specific substring
    """
    matched_files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for fname in filenames:
            if search_timestep in fname and fname.endswith('.nc'):
                full_path = os.path.join(dirpath, fname)
                matched_files.append(full_path)
    return matched_files

def merge_basin_netcdfs(reference_grid: str, nc_files: list[str], fill_value: float | None = None, check_crs: bool = True
) -> xr.Dataset:
    """
    Merge multiple NetCDF subsets.
    Assumes same grid resolution, same coordinate system and no overlaps
    """
    # For testing purposes, making the variables and the units uniform
    # across all datasets being combined.
    # Also, this function tests combine function with only two datasets
    
    ref_grid = xr.open_dataset(reference_grid)
    datasets = [xr.open_dataset(f) for f in nc_files]
    dt_list = []
    for ds in datasets:
        # the test datasets have different units for variables. 
        # For testing, just making them all same units.
        for var in ds.data_vars:
            ds[var].attrs['variable units'] = 'm'

        # To avoid shift changes due to precision in the lat-lon values, we will
        # re-index the coordinates to match the reference grid.
        # tolerance of 1m meaning any misalignment within 1m gets snapped.
        ds_reindexed = ds.reindex(y=ref_grid.y, x=ref_grid.x, method="nearest", tolerance=1.0)
        if len(dt_list) == 0:
            dt_list.append(ds_reindexed) # add first file as is.
        else:
            # For testing purposes, have been using datasets with different timesteps.
            # Using the snippet below to match timesteps as well.
            ds_updated = ds_reindexed.assign_coords(time=dt_list[0].time)
            dt_list.append(ds_updated)
    
    # Check CRS and confirm that they are the same for all the netcdf files
    if check_crs:
        crs_list = []
        for ds in datasets:
            if "crs" in ds:
                crs_list.append(ds.variables["crs"].attrs['spatial_ref'])
            else:
                raise ValueError("One dataset missing CRS")
        if len(set(crs_list)) != 1:
            raise ValueError("CRS mismatch between datasets")

    ds_combined = reduce(lambda left, right: left.combine_first(right), dt_list)

    # Optional fill value , if provided
    # To do: Examine NWM products to see if there are multiple fill values
    # and whether they need to be filled. 
    if fill_value is not None:
        ds_combined = ds_combined.fillna(fill_value)

    return ds_combined

def create_multi_basin_netcdfs(reference_grid: str, nc_files: list[str], variables_of_interest: list[str] = None, 
                              tolerance: float = 1.0, fill_value: float | None = None, 
                              check_crs: bool = True 
) -> xr.Dataset:
    """
    Merge multiple NetCDF subsets.
    Assumes same grid resolution, same coordinate system and no overlaps
    """
    # Check CRS and confirm that they are the same for all the netcdf files
    if check_crs:
        crs_list = []
        for nc_file in nc_files:
            with xr.open_dataset(nc_file) as ds:
                if "crs" in ds:
                    crs_list.append(ds.variables["crs"].attrs['spatial_ref'])
                else:
                    raise ValueError("One dataset missing CRS")
            
        if len(set(crs_list)) != 1:
            raise ValueError("CRS mismatch between datasets")

    ref_grid = xr.open_dataset(reference_grid)
    # the test datasets have different units for variables. 
    # For testing, just making them all same units.
    with xr.open_dataset(nc_files[0]) as ds_sample:
        standardized_time = ds_sample.time.values

    # Automatically grab all data variables from the first file 
    # if variables of interest is not provided.
    if variables_of_interest is None:
        with xr.open_dataset(nc_files[0]) as temp_ds:
            variables_of_interest = list(temp_ds.data_vars)

    combined_variables_dict = {}
    for var in variables_of_interest:
        reindexed_var_arrays = []
        for nc_file in nc_files:
            with xr.open_dataset(nc_file) as ds:
                # the test datasets have different units for variables. 
                # For testing, just making them all same units.
                for data_var in ds.data_vars:
                    ds[data_var].attrs['variable units'] = 'm'

                # Isolate the target variable to protect other variables from blooming into NaNs prematurely
                var_of_interest = ds[var]

                # Map to the national spatial coordinates layout
                var_reindexed = var_of_interest.reindex(y=ref_grid.y, x=ref_grid.x, method="nearest", tolerance=tolerance)

                # Unify the timestamp - this is only for testing. 
                # In reality, all grids will have the same simulation timesteps
                var_aligned = var_reindexed.assign_coords(time=standardized_time)
                reindexed_var_arrays.append(var_aligned)

            # merge the variable for all individual basins
            combined_variables_dict[var] = reduce(lambda left, right: left.combine_first(right), reindexed_var_arrays)
    
    ds_combined = xr.Dataset(data_vars=combined_variables_dict, 
                           coords={"time": standardized_time, "y": ref_grid.y, "x": ref_grid.x}, 
                           attrs=ref_grid.attrs)
            
    encoding_config = {}
    for var_name in variables_of_interest:
        encoding_config[str(var_name)] = {
            "zlib": True,
            "complevel": 4,
            "_FillValue": fill_value,
        }

    return ds_combined, encoding_config
# endregion