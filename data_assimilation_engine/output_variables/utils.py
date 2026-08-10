import os
import shutil
import requests
import xarray as xr
import csv
import pandas as pd
import geopandas as gpd
import numpy as np
import json
from pathlib import Path
from . import consts
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime
from pyproj import CRS
from typing import Any, Optional
from functools import reduce


# region common
def parse_filename_metadata(filename: str) -> tuple[str, str, str]:
    """
    Extract output_class, category and domain from filename.

    Args:
        filename: str
            The filename input that is in the same format as found in the NOMADS server
    
    Returns:
        tuple[str, str, str]
            Tuple of class, category and domain. For example: analysis_assim, terrain_rt, conus
    
    Raises:
        Exception if the filename format does not conform to the format on the NOMADS.
    """
    components = filename.split(".")

    if len(components) < 7:
        raise Exception(f"NWM Output file name doesn't follow expected format: {filename}")

    output_class = components[2]
    category = components[3]
    domain = components[5]
    return output_class, category, domain

def get_file_timestep_prefix(output_class: str) -> str:
    """
    Function to retrieve file name prefix for NWM products. For example:
    "nwm.t00z.medium_range.channel_rt_1.f001.alaska.nc" --> returns 'f'

    Args:
        cycle_run: str
            The output_class for NWM product. For example, medium_range, analysis_assim etc.

    Returns:
        str
            The prefix before the timestep number in a standard NWM product file name.
    """
    if output_class.startswith('analysis_assim'):
        return 'tm'
    else:
        return 'f'

def get_file_timestep_list(output_class: str, category: str, output_domain: str, number_only: bool) -> list[str] | list[int]:
    """
    Function to retrieve all the file name prefix for timesteps in NWM products. For example:
    analysis_assim --> returns ['tm00', 'tm01', 'tm02'] or [0,1,2]

    Args:
        output_class: str
            The output_class for NWM product. For example, medium_range, analysis_assim etc.
        category: str
            The product category For example: channel_rt, land
        output_domain: str
            The domain for the output products. For example, conus, hawaii, alaska
        number_only: bool
            A boolean flag that indicates whether the returned list includes filename prefix or not.
    Returns:
        list[str] | list[int]
            A list containing all the file name prefixes or the file numbers at each timestep in a run.
    """
    timesteps_list = []
    prefix = get_file_timestep_prefix(output_class)
    match output_class:
        case 'analysis_assim' | 'analysis_assim_no_da':
            timesteps_list = generate_formatted_string_list(0, 3, 1, 2, prefix)
        case 'analysis_assim_long':
            timesteps_list = generate_formatted_string_list(0, 12, 1, 2, prefix)
        case 'short_range':
            if output_domain == 'alaska':
                timesteps_list = generate_formatted_string_list(1, 16, 1, 3, prefix)
            else:
                timesteps_list = generate_formatted_string_list(1, 19, 1, 3, prefix)
        case 'long_range':
            if category.startswith('channel_rt') or category.startswith('reservoir'):
                timesteps_list = generate_formatted_string_list(6, 721, 6, 3, prefix)
            elif category.startswith('land'):
                timesteps_list = generate_formatted_string_list(24, 721, 24, 3, prefix)
        case 'medium_range' | 'medium_range_blend' | 'medium_range_no_da':
            if category.startswith('channel_rt') or category.startswith('reservoir'):
                timesteps_list = generate_formatted_string_list(1, 241, 1, 3, prefix)
            elif category.startswith('land') or category.startswith('terrain'):
                timesteps_list = generate_formatted_string_list(3, 241, 3, 3, prefix)
        case 'medium_range_no_da':
            if category.startswith('channel_rt'):
                timesteps_list = generate_formatted_string_list(3, 241, 3, 3, prefix)

    if len(timesteps_list) > 0 and number_only:
        return [int(time_step.lstrip(prefix)) for time_step in timesteps_list]
    else:
        return timesteps_list

def generate_formatted_string_list(start: int, end: int, interval: int, 
                                   width: int, prefix: str) -> list[str]:
    """
    Function to generate all the file name prefixes for timesteps in NWM products.

    Args:
        start: int
            The first number in the file list for a given product.
        end: int
            The last number in the file list for a given product.
        interval: int
            The skip interval for the file list
        width: int
            The number of characters of the file number. "0" padding done as needed.
        prefix: str
            the prefix character(s) before the formatted file number.

    Returns:
        list[str]
            A list containing all the file name prefixes in a run.
    """
    ret_list = []
    for i in range(start, end, interval):
        ts = f"{prefix}{i:0{width}d}"
        ret_list.append(ts)
    return ret_list

def generate_formatted_timestring_for_naming(time_step: int, output_class: str, category: str) -> str:
    """
    Function to generate the file name prefix for a given timestep and given NWM product.

    Args:
        time_step: int
            The timestep of simulation run for a given product.
        output_class: str
            The output_class for NWM product. For example, medium_range, analysis_assim etc.
        category: str
            The product category For example: channel_rt, land

    Returns:
        str
            A string representing the file name prefix. For example, 'f024', 'tm02' etc.
    """
    match output_class:
        case 'analysis_assim' | 'analysis_assim_no_da' | 'analysis_assim_long':
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
        case 'medium_range_no_da':
            if category.startswith('channel_rt'):
                formatted = (time_step+1) * 3
                return f"{(formatted):03d}"
        case _:
            return "Unknown"  # This is the default 'else' case

def get_output_interval_hours(cycle_run: str, category: str) -> int | None:
    """
    Output interval (hours) for a given output cycle/category. None means no files should be 
    produced for that combination

    Args:
        cycle_run: str
            The run cycle for NWM product. For example, medium_range_mem2.
        category: str
            The product category For example: channel_rt, land

    Returns:
        int | None
        The integer number that represents the output interval hours in the file name of a product.
    """
    match cycle_run:
        case 'medium_range' | 'medium_range_blend' | 'medium_range_no_da':
            if category.startswith('channel_rt') or category.startswith('reservoir'):
                return 1
            elif category.startswith('land') or category.startswith('terrain'):
                return 3
        case 'long_range':
            if category.startswith('channel_rt') or category.startswith('reservoir'):
                return 6
            elif category.startswith('land'):
                return 24
            elif category.startswith('terrain'):
                return None
    return 1  # Covers all other cycles, should be updated with oCONUS regions if necessary
# endregion

# region data download
def download_nwm_data_from_server(local_root: str, re_download: bool) -> str:
    """
    Main function to download a unique set of output files from the NWM server.
    The root URL and the subfolder where the content is downloaded is dictated through 
    variables in consts.py. This also creates the metadata config

    Args:
        local_root: str
            The root folder for postprocessing outputs. 
        re_download: bool
            Argument indicating if the data exists and need to be redownloaded.
            Defaults to False.
    Returns:
        str
            The full file path of the metadata_config.json file.
    """
    os.makedirs(local_root, exist_ok = True)
    nwm_data_folder = os.path.join(local_root, consts.NWM_DATA_LOCAL_FOLDER)
    os.makedirs(nwm_data_folder, exist_ok = True)

    # Re-download if requested
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
    existing_keys: set[tuple[str, str, str]]
) -> None:
    """
    Recursively download a unique set of output files from the server
    and create a mirrored folder structure locally
    Args:
        download_url: str
            The download URL for NMW data. 
        local_path: str
            Folder path where the downloaded data needs to be saved
        existing_keys: set[tuple[str, str, str]]
            A unique combination key of NWM class, category and domain.
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

    Args:
        url: str
            The URL to download a specific NWM product
        save_path: str
            The folder path where the downloaded files are saved.
    """
    response = requests.get(url)
    if response.status_code == 200:
        with open(save_path, 'wb') as f:
            f.write(response.content)
        print(f"Downloaded: {save_path}")
    else:
        print(f"Failed to download: {url}, HTTP status code {response.status_code}")

def build_existing_keys(local_root: str) -> set[tuple[str, str, str]]:
    """
    Builds file keys in local folder. These keys are used when function is re-run 
    and enables the capability to not download a file again.

    Recursively download a unique set of output files from the server
    and create a mirrored folder structure locally
    Args:
        local_root: str
            The root folder path where all the reference files, intermediate and final products are getting saved
    
    Returns:
        set[tuple[str, str, str]]
            A unique combination key of NWM class, category and domain.
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
    """
    Custom class to hold metadata found in NWM reference files downloaded by `download_nwm_data_from_server`
    Sample json format produced by `obtain_metadata_information` showing the metadata attributes
        {
        "file_path": "sample_data/outputs/nwm_ref_files/analysis_assim/nwm.t00z.analysis_assim.terrain_rt.tm00.conus.nc",
        "resolution": {
            "x": 250.0,
            "y": 250.0
        },
        "origin": {
            "x": -2303874.17655,
            "y": -1919875.33671
        },
        "location_name": {
            "x": "x",
            "y": "y"
        },
        "crs_wkt": "PROJCS[\"Lambert_Conformal_Conic\",GEOGCS[\"GCS_Sphere\",DATUM[\"D_Sphere\",SPHEROID[\"Sphere\",6370000.0,0.0]],PRIMEM[\"Greenwich\",0.0],UNIT[\"Degree\",0.0174532925199433]],PROJECTION[\"Lambert_Conformal_Conic_2SP\"],PARAMETER[\"false_easting\",0.0],PARAMETER[\"false_northing\",0.0],PARAMETER[\"central_meridian\",-97.0],PARAMETER[\"standard_parallel_1\",30.0],PARAMETER[\"standard_parallel_2\",60.0],PARAMETER[\"latitude_of_origin\",40.0],UNIT[\"Meter\",1.0]];-35691800 -29075200 10000;-100000 10000;-100000 10000;0.001;0.001;0.001;IsHighPrecision",
        "nwm_variables": "zwattablrt, sfcheadsubrt",
        "nwm_dimensions": "time, y, x, reference_time",
        "nwm_scalar_variables": {
            "crs": ""
        },
        "nwm_var_dimensions": {
            "zwattablrt": [
            "time",
            "y",
            "x"
            ],
            "sfcheadsubrt": [
            "time",
            "y",
            "x"
            ],
            "time": [
            "time"
            ],
            "reference_time": [
            "reference_time"
            ],
            "x": [
            "x"
            ],
            "y": [
            "y"
            ]
        },
        "output_cycle": "analysis_assim",
        "class": "analysis_assim",
        "category": "terrain_rt",
        "domain": "conus"
        }

    """
    def __init__(
        self,
        file_path: str,
        resolution_x: float,
        resolution_y: float,
        origin_x: float,
        origin_y: float,
        x_loc: str,
        y_loc: str,
        wkt: str | None,
        variables: str,
        dimensions: str, 
        scalar_variables: dict[str, list[str]], 
        data_variables_dim: dict[str, int | float | str],
        output_cycle: str,
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
        self.output_cycle = output_cycle
        self.output_class = output_class
        self.category = category
        self.domain = domain

def obtain_metadata_information(local_root: str) -> str:
    """
    Parses the metadata information from the downloaded NWM output files and writes a json
    Args:
        local_root: str
            The root folder for postprocessing outputs. 

    Returns:
        str
            The full file path of the metadata_config.json file.
    
    Raises:
        Exception if the root output folder or the downloaded NWM reference files folder doesn't exist
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

def extract_metadata_from_downloaded_files(local_root: str) -> list[NetCDFMetadata]:
    """
    Process downloaded files and create a list of metadata objects for config json

    Args:
        local_root: str
            The root folder for postprocessing outputs.

    Returns:
        list[NetCDFMetadata]
            a list of NetCDFMetadata class objects
    """
    metadata_list = []

    for root, _, files in os.walk(local_root):
        for file in files:
            if file.endswith(".nc"):
                file_path = os.path.join(root, file)
                metadata_list.append(extract_netcdf_metadata_from_netcdf(file_path))

    return metadata_list

def extract_netcdf_metadata_from_netcdf(file_path: str) -> NetCDFMetadata:
    """
    Extracts the metadata from the netcdf file into a custom `NetCDFMetadata` class object.
    Args:
        file_path: str
            The full or relative file path to the netcdf file
    
    Returns:
        NetCDFMetadata
            An instance of `NetCDFMetadata` object with all the metadata info for the netcdf file
    """
    filename = os.path.basename(file_path)
    output_class, category, domain = parse_filename_metadata(filename)
    output_cycle = Path(file_path).parent.name
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
                          nwm_variables, dimensions, scalar_dict, data_dict, output_cycle, output_class, category, domain)

def compute_resolution(coords: np.ndarray) -> float:
    """
    Compute resolution from coordinate array using median spacing.

    Args:
        coords: np.ndarray
            A numpy array of X or Y coordinates found in the downloaded NWM ref files

    Returns:
        float
            a float value of the resolution for the coordinates.
    """
    if coords.size < 2:
        return 0.0

    diffs = np.diff(coords)
    return float(np.median(np.abs(diffs)))

def extract_wkt_from_crs(crs_var: xr.Variable) -> str | None:
    """
    Extract wkt attribute from CRS variable.
    Args:
        crs_var: xr.Variable
            The crs scalar variable found in the NWM netcdf products.
    
    Returns:
        str | None
            If exists, it returns the wkt string from the crs variable attributes.
    """
    if "spatial_ref" in crs_var.attrs:
        return crs_var.attrs["spatial_ref"]
    elif "esri_pe_string" in crs_var.attrs:
        return crs_var.attrs["esri_pe_string"]
    return None
    
def write_metadata_to_config_json(metadata_list: list[NetCDFMetadata], output_json: str) -> None:
    """
    Writes NetCDFMetadata objects to config JSON.

    Args:
        metadata_list: list[NetCDFMetadata]
            list of  custom `NetCDFMetadata` objects
    
        output_json: str
            Full or relative path to the config json file
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
            consts.JSON_OUTPUT_CYCLE: mdata.output_cycle,
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

def read_output_variables_info_from_config(json_file: str) -> list[NetCDFMetadata]:
    """
    Parses a multi-element JSON string into a list of `NetCDFMetadata` objects.
    
    Args:
        output_json: str
            Full or relative path to the config json file
    
    Returns:
        list[NetCDFMetadata]
            list of  custom `NetCDFMetadata` objects
    
    Raises:
        ValueError if the specified config json file does not exist.
    """
    netcdf_metadata_list = []
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
                output_cycle = item.get(consts.JSON_OUTPUT_CYCLE, ''),
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
    Main calling function to create mosaiced or combined netcdf products.
    
    Args:
        netcdf_folder: str
            Folder containing the netcdf products after all post-processing runs.
        output_folder: str
            Output folder to save all the combined/mosaiced netcdf outputs.
        config_json: str
            Full or relative path to the config json file
        output_cycle_hr: str
            The hour in a day (0-23) for which the outputs are produced after simulations are run.
        output_cycle_type: str
            The cycle type for the output products. For example, medium_range_mem1, analysis_assim_no_da
        output_cycle_domain: str
            The domain for the output products. For example, conus, hawaii, alaska
    
    Raises:
        Raises FileNotFoundError if the input netcdf folder or the config json file does not exist.
    """
    input_path = Path(netcdf_folder)
    if not input_path.is_dir():
        raise FileNotFoundError(f"The folder {netcdf_folder} does not exist.")

    input_path = Path(config_json)
    if not input_path.is_file():
        raise FileNotFoundError(f"The config file {config_json} does not exist.")

    os.makedirs(output_folder, exist_ok=True)
    cycle_hr = f"t{str(output_cycle_hr).zfill(2)}z"

    netcdf_metadata_list = read_output_variables_info_from_config(config_json)
    product_categories = {}
    output_class = ''
    for mdata in netcdf_metadata_list:
        if mdata.output_cycle == output_cycle_type and mdata.domain == output_cycle_domain:
            product_categories[mdata.category] = mdata.file_path
            output_class = mdata.output_class
    
    is_gridded = True
    for category, ref_file in product_categories.items():
        if category.startswith('channel_rt') or category.startswith('reservoir'):
            is_gridded = False
        elif category.startswith('land') or category.startswith('terrain_rt'):
            is_gridded = True
        
        time_list = get_file_timestep_list(output_class, output_cycle_domain, category, False)
        # print(f"File times List: {time_list}")
        for tm in time_list:
            keywords_list = [cycle_hr, output_class, category, tm, output_cycle_domain]
            # print(f"Keywords list: {keywords_list}")

            # for full_file_path in Path(netcdf_folder).glob("*.nc"):
            #     print(str(full_file_path))
            matching_files = [str(full_file_path)
                for full_file_path in Path(netcdf_folder).glob("*.nc")
                if all(keyword in full_file_path.name for keyword in keywords_list)
            ]

            if len(matching_files) > 0:
                print(f"Merging files for {output_class}, {category}, {tm}")
                if is_gridded:
                    merged_ds, encoding = create_multi_basin_netcdfs(ref_file, matching_files, None, 1.0, True)
                else:
                    # print(f"File category: {category}; Feature ID present: {has_featureid}")
                    merged_ds, encoding = combined_non_gridded_netcdfs(matching_files, True)
                # Write dataset to disk
                output_file = os.path.join(output_folder, f"nwm.{cycle_hr}.{output_class}.{category}.{tm}.{output_cycle_domain}.nc")
                merged_ds.to_netcdf(output_file, encoding = encoding, engine='netcdf4')
            else:
                print(f"Warning: No matching files to combine for {output_cycle_type}, {output_class}, {category}, {output_cycle_domain}")

def create_multi_basin_netcdfs(reference_netcdf: str, nc_files: list[str], variables_of_interest: list[str] = None, 
                              tolerance: float = 1.0, check_crs: bool = True 
) -> tuple[xr.Dataset, dict[str, dict[str, Any]]]:
    """
    Merge multiple NetCDF subsets.
    Assumes same grid resolution, same coordinate system

    Args:
        reference_netcdf: str
            The national reference netcdf file for the given product type, class, domain
        nc_files: list[str]
            List of netcdf files to be merged/combined.
        variables_of_interest: list[str]
            NWM output variables that need to be merged. Typically None to allow merging all variables in the netcdfs
        tolerance: float
            Tolerance distance to snap a point to the reference grid. Default is 1.0m
        check_crs: bool
            Boolean variable to check if all the netcdfs have the same crs. Default is True.

    Returns:
        tuple[xr.Dataset, dict[str, dict[str, Any]]]
            tuple representing the xarray dataset and the encoding config
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

    ref_grid = xr.open_dataset(reference_netcdf)

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

def combined_non_gridded_netcdfs(nc_files: list[str], has_featureid: bool) -> tuple[xr.Dataset, dict[str, dict[str, Any]]]:
    """
    Merge multiple NetCDF files that are not gridded. This is specific for channel_rt and reservoir NWM products

    Args:
        nc_files: list[str]
            List of netcdf files to be merged/combined.

        has_featureid: bool
            Boolean variable indicating that the feature_id dimension exists. Default is True.

    Returns:
        tuple[xr.Dataset, dict[str, dict[str, Any]]]
            tuple representing the xarray dataset and the encoding config
    """
    if has_featureid:
        combined = xr.open_mfdataset(
        nc_files,
        data_vars="all",
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
    """
    Sort the feature_id in the xarray dataset before combining. It avoids the following error
    ValueError: Resulting object does not have monotonic global indexes along dimension feature_id

    Args:
        ds: xr.Dataset
            xarray NetCDF dataset whose feature ids need to be sorted.
    Returns:
        ds: xr.Dataset
            xarray NetCDF dataset with sorted feature ids.
    """
    if consts.DIM_FEATURE_ID in ds.dims and consts.DIM_FEATURE_ID in ds.coords:
        if not ds.indexes[consts.DIM_FEATURE_ID].is_monotonic_increasing:
            ds = ds.sortby(consts.DIM_FEATURE_ID)
    return ds
# endregion