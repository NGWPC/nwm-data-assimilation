import os
import shutil
import requests
import xarray as xr
import csv
import pandas as pd
import numpy as np
import json
import logging
from pathlib import Path
from . import consts
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime
from pyproj import CRS
from typing import List, Set, Tuple, Dict, Union, Any, Optional
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

def convert_csvs_to_netcdf(csv_folder: str):
    """
    Takes a directory for ngen output CSVs, automatically discovers NWM variables,
    analyzes their native data types, and converts them to netcdf.
    """
    # Find all CSV files in the target directory
    csv_files = []
    try:
        with os.scandir(csv_folder) as entries:
            for entry in entries:
                if entry.is_file() and entry.name.lower().endswith('.csv'):
                    csv_files.append(entry.path)
    except FileNotFoundError:
        print(f"The directory '{csv_folder}' does not exist.")
        return
    
    if not csv_files:
        print(f"No CSV files found in directory: {csv_folder}")
        return

    # 1. Discover variables using the first valid CSV file
    template_df = pd.read_csv(csv_files[0])
    base_cols = consts.CSV_BASE_COLS
    nwm_variables = [col for col in template_df.columns if col.lower() not in base_cols]
    
    print(f"NWM variables for netcdf: {nwm_variables}")

    catchment_nc_data = []

    for file_path in csv_files:
        filename = os.path.basename(file_path)
        try:
            # Use file names to extract the catchment IDs. We are using splitext and isdigit 
            # instead of the usual replace 'cat-' so that it can handle other filename formats 
            # Assumes that the file name contains long integer catchment IDs.
            catchment_id_name = os.path.splitext(filename)[0]
            catchment_id_str = ''.join(filter(str.isdigit, catchment_id_name))
            catchment_id = np.int64(catchment_id_str) # for latest NHF schema
        except ValueError:
            print(f"Skipping {filename}: Could not parse catchment ID as a long integer.")
            continue

        # Load CSV into Pandas
        df = pd.read_csv(file_path)

        #Convert Time column to lower case
        if 'Time' in df.columns:
            df.rename(columns={'Time': consts.DIM_TIME}, inplace=True)

        # Safety check: Ensure this specific CSV contains all discovered data columns
        if not set(nwm_variables).issubset(df.columns):
            print(f"Skipping {filename}: Headers do not match the expected dataset schema.")
            continue

        # Convert time to UNIX Epoch
        df['datetime'] = pd.to_datetime(df['time'])
        df['epoch'] = (df['datetime'].astype('int64') // 10**9).astype(np.int32) # int32 good until year 2038

        # 2. Dynamically extract columns based on their native types
        nwm_vars_dict = {}
        for var in nwm_variables:
            col_type = df[var].dtype

            if col_type.kind in {"U", "S", "O"}: # If the column is text/string or generic object data
                nwm_vars_dict[var] = (["time"], df[var].astype(str).values)
            elif col_type.kind in {"i", "u"}: # If the column is an integer type (like status codes, IDs)
                nwm_vars_dict[var] = (["time"], df[var].values)
            else: # Default floats/doubles
                nwm_vars_dict[var] = (["time"], df[var].values)

        # Set coordinates for xarray translation
        df = df.set_index('epoch')

        # Convert individual dataframe to an xarray Dataset
        catchment_ds = xr.Dataset(
            data_vars = nwm_vars_dict,
            coords = {
                consts.DIM_TIME: (["time"], df.index.values.astype(np.int32)),
                consts.DIM_CATCHMENTS: catchment_id
            }
        )

        # Expand the dataset to include catchments as a dimension axis
        catchment_ds = catchment_ds.expand_dims(consts.DIM_CATCHMENTS)
        catchment_nc_data.append(catchment_ds)

    if not catchment_nc_data:
        print("No valid data was extracted. NetCDF generation aborted.")
        return

    print(" Combining and aligning all catchments")
    
    # Merge all separate catchments together along the catchments dimension
    combined_ds = xr.combine_by_coords(catchment_nc_data)

    # Enforce structural array coordinates to be 64-bit long integers
    combined_ds[consts.DIM_TIME] = combined_ds[consts.DIM_TIME].astype(np.int32)
    combined_ds[consts.DIM_CATCHMENTS] = combined_ds[consts.DIM_CATCHMENTS].astype(np.int64)

    # Add descriptive metadata attributes dynamically
    combined_ds[consts.DIM_TIME].attrs = {"units": "seconds since 1970-01-01 00:00:00", "calendar": "gregorian"}
    combined_ds[consts.DIM_CATCHMENTS].attrs = {"Catchment_ID": "Catchment identifier in input"}
    
    for var in nwm_variables:
        # Do we need to have a dictionary of variable name, mapping and units for attributes?
        type_label = combined_ds[var].dtype.name
        combined_ds[var].attrs = {"long_name": f"{var}"}
        combined_ds[var].attrs["_FillValue"] = -1.0
        combined_ds[var].attrs["missing_value"] = -1.0


    output_netcdf_path = os.path.join(csv_folder, 'catchment_output.nc')
    print(f"Saving unified NetCDF to: {output_netcdf_path}")
    combined_ds.to_netcdf(output_netcdf_path)
    print("Process complete!")

def get_file_timestep_prefix(cycle_run: str) -> str:
    if cycle_run.startswith('analysis_assim'):
        return 'tm'
    else:
        return 'f'

def get_file_timestep_list(cycle_run: str, category: str) -> List[str]:
    timesteps = []
    match cycle_run:
        case 'analysis_assim':
            return generate_formatted_string_list(0, 2, 1, 2)
        case 'short_range':
            return generate_formatted_string_list(1, 18, 1, 3)
        case 'long_range':
            if category.startswith('channel_rt') or category.startswith('reservoir'):
                return generate_formatted_string_list(6, 720, 6, 3)
            elif category.startswith('land'):
                return generate_formatted_string_list(24, 720, 24, 3)
        case 'medium_range' | 'medium_range_blend':
            if category.startswith('channel_rt') or category.startswith('reservoir'):
                return generate_formatted_string_list(1, 240, 1, 3)
            elif category.startswith('land') or category.startswith('terrain'):
                return generate_formatted_string_list(3, 240, 3, 3)
        case _:
            return "Unknown"  # This is the default 'else' case
    return timesteps

def generate_formatted_string_list(start: int, end: int, 
                                   interval: int, width: int) -> List[str]:
    ret_list = []
    for i in range(start, end, interval):
        ts = f"{i:0{width}d}"
        ret_list.append(ts)
    return ret_list

def generate_formatted_timestring_for_naming(time_step: int, cycle_run: str, category: str) -> str:
    match cycle_run:
        case 'analysis_assim':
            return f"{time_step:02d}"
        case 'short_range':
            formatted = (time_step+1)
            return f"{(formatted):03d}"
        case 'long_range':
            if category.startswith('channel_rt') or category.startswith('reservoir'):
                formatted = (time_step+1) * 6
                return f"{(formatted):03d}"
            elif category.startswith('land'):
                formatted = (time_step+1) * 24
                return f"{(formatted):03d}"
        case 'medium_range' | 'medium_range_blend':
            if category.startswith('channel_rt') or category.startswith('reservoir'):
                formatted = (time_step+1)
                return f"{(formatted):03d}"
            elif category.startswith('land') or category.startswith('terrain'):
                formatted = (time_step+1) * 3
                return f"{(formatted):03d}"
        case _:
            return "Unknown"  # This is the default 'else' case

# endregion

# region data download
def download_nwm_data_from_server(local_root: str, re_download: bool) -> str:
    """
    Main function to download a unique set of output files from the NWM server.
    The root URL and the subfolder where the content is downloaded is dictated through 
    variables in consts.py

    Args:
        local_root (str): The root folder for outputs. 
        re_download (bool): argument indicating that we need to redownload the data.
        Defaults to False.
    """
    os.makedirs(local_root, exist_ok = True)
    nwm_data_folder = os.path.join(local_root, consts.NWM_DATA_LOCAL_FOLDER)
    os.makedirs(nwm_data_folder, exist_ok = True)

    # Re-download if requested
    # To consider: may be we should do away with the re_download argument altogether
    if (re_download): 
        if len(os.listdir(nwm_data_folder)) > 0:
            # Delete all the contents in the local folder and re-create
            shutil.rmtree(nwm_data_folder)
            os.makedirs(nwm_data_folder, exist_ok = True)
    
    formatted_date = datetime.now().strftime("%Y%m%d")
    formatted_url = f"{consts.NOMADS_BASE_URL}/nwm.{formatted_date}/"
    existing_keys = build_existing_keys(nwm_data_folder) # build class, category, domain keys in local folder, if exists.
    download_nwm_data_recursive(formatted_url, nwm_data_folder, existing_keys)

    # After successful download of data, build the metadata config and save it to configs subfolder
    config_json = obtain_metadata_information(local_root)
    return config_json

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
    if len(file_links) == 0:
        raise Exception(f"No valid file links available for download from {download_url}")
    
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
                # Add to existing set after successful download
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

    def key(self) -> tuple[str, str, str]: # not used yet.
        """
        Unique identifier for duplicate checking
        """
        return (self.output_class, self.category, self.domain)

    def __repr__(self) -> str: # for debugging purposes
        return (
            f"NetCDFMetadata(file_path={self.file_path}, "
            f"class={self.output_class}, category={self.category}, domain={self.domain})"
        )

def obtain_metadata_information(local_root: str) -> str:
    """
    Parse the metadata information from the downloaded NWM output files and write a CSV and a json
    """
    if not os.path.exists(local_root):
        raise Exception(f"Folder does not exist: {local_root}")
    
    nwm_local_folder = os.path.join(local_root, consts.NWM_DATA_LOCAL_FOLDER)
    if not os.path.exists(nwm_local_folder):
        raise Exception(f"Folder does not exist: {nwm_local_folder}")
    
    nwm_config_folder = os.path.join(local_root, consts.NWM_CONFIG_LOCAL_FOLDER)
    os.makedirs(nwm_config_folder, exist_ok = True)
    metadata_list = extract_metadata_from_downloaded_files(nwm_local_folder)
    output_json = os.path.join(nwm_config_folder, 
                               consts.NWM_CONFIG_FILE_NAME + consts.NWM_CONFIG_FILE_SUFFIX + ".json")
    write_metadata_to_config_json(metadata_list, output_json)
    return output_json 

def extract_metadata_from_downloaded_files(local_root: str) -> List[NetCDFMetadata]:
    """
    Process downloaded files and create a list of metadata objects for config json
    """
    metadata_list: List[NetCDFMetadata] = []

    for root, _, files in os.walk(local_root):
        for file in files:
            if file.endswith(".nc"):
                file_path = os.path.join(root, file)
                metadata_list.append(extract_netcdf_metadata_from_netcdf(file_path))

    return metadata_list

def extract_netcdf_metadata_from_netcdf(file_path: str) -> NetCDFMetadata:

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
        elif nwm_var in consts.NWM_VARIABLES_LIST or len(ds[nwm_var].dims) > 1: #NWM output variables
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

def write_metadata_to_config_json(metadata_list: List[NetCDFMetadata], output_json: str) -> None:
    """
    Writes NetCDFMetadata objects to config JSON.
    """
    # Delete any existing config file
    if os.path.exists(output_json):
        os.remove(output_json)

    info_list = []
    for mdata in metadata_list:
        metadata_info_dict = {
            consts.JSON_FILE_PATH: mdata.file_path,
            consts.JSON_RESOLUTION: {
                consts.JSON_X: mdata.resolution_x,
                consts.JSON_Y: mdata.resolution_y,
            },
            consts.JSON_ORIGIN: {
                consts.JSON_X: mdata.origin_x,
                consts.JSON_Y: mdata.origin_y,
            },
            consts.JSON_LOC: {
                consts.JSON_X: mdata.x_name,
                consts.JSON_Y: mdata.y_name,
            },
            consts.JSON_CRS: mdata.crs_wkt,
            consts.JSON_NWM_VAR: mdata.nwm_variables,
            consts.JSON_DIMENSION: mdata.nwm_dimensions,
            consts.JSON_SCALAR_VAR: mdata.scalar_variables,
            consts.JSON_VAR_DIM_MAP: mdata.data_variables_dim,
            consts.JSON_CLASS: mdata.output_class,
            consts.JSON_CATEGORY: mdata.category,
            consts.JSON_DOMAIN: mdata.domain
        }
        info_list.append(metadata_info_dict)

    config = {
        "files": info_list
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(config, f, indent = 2)

    print(f"Config JSON written to: {output_json}")

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

def read_output_variables_info_from_config(json_file: str) -> List[NetCDFMetadata]:
    """
        Parses a multi-element JSON string into a list of NetCDFMetadata objects.
    """
    netcdf_metadata_list: List[NetCDFMetadata] = []
    if os.path.isfile(json_file):
        with open(json_file, "r", encoding="utf-8") as file_stream:
            config_data = json.load(file_stream)
        
        for item in config_data.get("files", []):
            info_item = NetCDFMetadata(
                file_path = item.get(consts.JSON_FILE_PATH, ''),
                resolution_x = item.get(consts.JSON_RESOLUTION, {}).get(consts.JSON_X, -9999),
                resolution_y = item.get(consts.JSON_RESOLUTION, {}).get(consts.JSON_Y, -9999),
                origin_x = item.get(consts.JSON_ORIGIN, {}).get(consts.JSON_X, -9999),
                origin_y = item.get(consts.JSON_ORIGIN, {}).get(consts.JSON_Y, -9999),
                x_loc = item.get(consts.JSON_LOC, {}).get(consts.JSON_X, ''),
                y_loc = item.get(consts.JSON_LOC, {}).get(consts.JSON_Y, ''),
                wkt = item.get(consts.JSON_CRS, ''),
                variables = item.get(consts.JSON_NWM_VAR, ''),
                dimensions = item.get(consts.JSON_DIMENSION, ''),
                scalar_variables = item.get(consts.JSON_SCALAR_VAR, {}),
                data_variables_dim = item.get(consts.JSON_VAR_DIM_MAP, {}),
                output_class = item.get(consts.JSON_CLASS, ''),
                category = item.get(consts.JSON_CATEGORY, ''),
                domain = item.get(consts.JSON_DOMAIN, '')
            )
            netcdf_metadata_list.append(info_item)
    else:
        raise ValueError("Specified config file does not exist")
    
    return netcdf_metadata_list
# endregion

# region basin grid products
def create_combined_basin_netcdf_products (netcdf_folder: str, output_folder: str, config_json: str,
                            output_cycle_hr: str, output_cycle_type: str, output_cycle_domain: str) -> None:
    """
    Main calling function to create a combined basins product
    """
    os.makedirs(output_folder, exist_ok=True)
    cycle_hr = f"t{str(output_cycle_hr).zfill(2)}z"

    netcdf_metadata_list = read_output_variables_info_from_config(config_json)
    product_categories = {}
    for mdata in netcdf_metadata_list:
        if mdata.output_class == output_cycle_type and mdata.domain == output_cycle_domain:
            product_categories[mdata.category] = mdata.file_path
    
    is_gridded = True
    for category, ref_file in product_categories.items():
        if category.startswith('channel_rt') or category.startswith('reservoir'):
            is_gridded = False
        elif category.startswith('land') or category.startswith('terrain_rt'):
            is_gridded = True
        
        time_list = get_file_timestep_list(output_cycle_type, category)
        for tm in time_list:
            keywords_list = [cycle_hr, output_cycle_type, category, tm, output_cycle_domain]
            matching_files = [str(full_file_path)
                for full_file_path in Path(netcdf_folder).glob("*.nc")
                if all(keyword in full_file_path.name for keyword in keywords_list)
            ]
            if len(matching_files) > 0:
                if is_gridded:
                    merged_ds, encoding = create_multi_basin_netcdfs(ref_file, matching_files, None, 1.0, True)
                else:
                    # print(f"File category: {category}; Feature ID present: {has_featureid}")
                    merged_ds, encoding = combined_non_gridded_netcdfs(matching_files, True)
                # Write dataset to disk
                output_file = os.path.join(output_folder, f"nwm.{cycle_hr}.{output_cycle_type}.{category}.{tm}.{output_cycle_domain}.nc")
                merged_ds.to_netcdf(output_file, encoding = encoding, engine='netcdf4')
            else:
                print(f"Warning: No matching files to combine for {output_cycle_type}, {category}, {output_cycle_domain}")

def create_multi_basin_netcdfs(reference_grid: str, nc_files: list[str], variables_of_interest: list[str] = None, 
                              tolerance: float = 1.0, check_crs: bool = True 
) -> Tuple[xr.Dataset, Dict[str, Dict[str, Any]]]:
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

    # Gather the time and global attributes from the first dataset
    global_attrs = None
    with xr.open_dataset(nc_files[0]) as first_da:
        standardized_time = first_da.time.values
        global_attrs = first_da.attrs.copy()

    # Automatically grab all data variables from the first file 
    # if variables of interest is not provided.
    if variables_of_interest is None:
        with xr.open_dataset(nc_files[0]) as temp_ds:
            variables_of_interest = list(temp_ds.data_vars)

    combined_variables_dict = {}
    
    for var in variables_of_interest:
        reindexed_var_array = []
        for nc_file in nc_files:
            with xr.open_dataset(nc_file) as ds:
                var_of_interest = ds[var]

                # Map to the national spatial coordinates layout and add to the reindexed var array
                var_reindexed = var_of_interest.reindex(y=ref_grid.y, x=ref_grid.x, method="nearest", tolerance=tolerance)
                reindexed_var_array.append(var_reindexed)

            # merge the variable for all individual basins
            # get the attributes from the first element of the reindexed
            var_attrs = reindexed_var_array[0].attrs.copy()
            var_encoding = reindexed_var_array[0].encoding.copy()
            combined = reduce(lambda left, right: left.combine_first(right), reindexed_var_array)
            combined.attrs = var_attrs
            combined.encoding = var_encoding

            combined_variables_dict[var] = combined
    
    ds_combined = xr.Dataset(data_vars=combined_variables_dict, 
                           coords={"time": standardized_time, "y": ref_grid.y, "x": ref_grid.x}, 
                           attrs=global_attrs)
            
    encoding_config = {}
    for var_name in variables_of_interest:
        encoding_config[str(var_name)] = {
            "zlib": True,
            "complevel": 4
        }

    return ds_combined, encoding_config

def combined_non_gridded_netcdfs(nc_files: list[str], has_featureid: bool) -> Tuple[xr.Dataset, Dict[str, Dict[str, Any]]]:

    if has_featureid:
        combined = xr.open_mfdataset(
        nc_files,
        combine="nested",
        concat_dim=consts.DIM_FEATURE_ID,
        preprocess=preprocess_sort,
        combine_attrs="override"
        )
        combined = combined.sortby(consts.DIM_FEATURE_ID)
    # else:
    #     combined = xr.open_mfdataset(
    #         nc_files,
    #         combine="by_coords",
    #         preprocess=preprocess_sort,
    #         combine_attrs="override"
    #     )
    encoding = {}
    for var in combined.data_vars:
        if consts.DIM_FEATURE_ID in combined[var].dims:
            encoding[var] = {
                "zlib": True,
                "complevel": 4,
                "shuffle": True
            }
        else:
            encoding[var] = {
                "zlib": True,
                "complevel": 4,
                "shuffle": True
            }
    return combined, encoding

def preprocess_sort(ds: xr.Dataset) -> xr.Dataset:
    # This sorts the dataset sequentially. 
    
    # It is necessary to avoid the following error:
    # ValueError: Resulting object does not have monotonic global indexes along dimension feature_id
    if consts.DIM_FEATURE_ID in ds.dims and consts.DIM_FEATURE_ID in ds.coords:
        if not ds.indexes[consts.DIM_FEATURE_ID].is_monotonic_increasing:
            ds = ds.sortby(consts.DIM_FEATURE_ID)
    return ds
# endregion