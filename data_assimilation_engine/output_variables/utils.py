import os
import requests
import xarray as xr
import csv
import numpy as np
import json
import logging
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime
from pyproj import CRS
from typing import List, Set, Tuple, Optional

nwm_variables_list = ['sfcheadsubrt', 'zwattablrt', 'inflow', 'outflow', 'reservoir_assimilated_value', 
'water_sfc_elev', 'nudge', 'qBucket', 'streamflow', 'velocity', 'qBtmVertRunoff', 'qSfcLatRunoff', 
'ACSNOM', 'ACCET', 'SNOWT_AVG', 'EDIR', 'SOILICE', 'SOILSAT_TOP', 'ISNOW', 'QRAIN', 'FSNO', 'SNOWH', 
'SNLIQ', 'SNEQV', 'QSNOW', 'SOIL_T', 'SOIL_M', 'SFCRNOFF', 'ACCECAN', 'ACCEDIR', 'ACCETRAN', 'UGDRNOFF', 
'GRDFLX', 'TRAD', 'FSA', 'CANWAT', 'LH', 'FIRA', 'HFX']


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
        output_class: str,
        category: str,
        domain: str,
    ) -> None:
        self.file_path: str = file_path
        self.resolution_x: float = resolution_x
        self.resolution_y: float = resolution_y
        self.origin_x: float = origin_x
        self.origin_y: float = origin_y
        self.x_name: str = x_loc
        self.y_name: str = y_loc
        self.nwm_variables: str = variables
        self.crs_wkt: str = wkt
        self.output_class: str = output_class
        self.category: str = category
        self.domain: str = domain

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

def create_nwm_template_grids(src_root_folder: str, dest_root_folder: str) -> None:
    """
    Creates template grids for all NWM netcdf products using a sample set of netcdfs.
    """
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
                dst_path = os.path.join(target_dir, file)

                # Process the NetCDF using xarray
                with xr.open_dataset(src_path) as ds:
                    # Reset data variables
                    for var in ds.data_vars:
                        if var in nwm_variables_list:
                            ds[var].values[:] = -1
                    
                    # Reset coordinate variables
                    for coord in coords_to_reset:
                        if coord in ds.coords:
                            ds[coord].values[:] = - 1
                    # Save to the desired location
                    ds.to_netcdf(dst_path)
                    print(f"Processed: {dst_path}")

def debug_netcdf_structure_in_folder(folder_path: str) -> None:
    """
    Recursively scans a folder for NetCDF files and prints their structure.
    """
    nc_files: List[str] = []
    logging.basicConfig(
        filename='app.log', 
        level=logging.INFO,
        format='%(message)s'
        #format='%(asctime)s - %(message)s'
    )
    data_variables_list = []
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.endswith(".nc"):
                nc_files.append(os.path.join(root, file))

    if not nc_files:
        print(f"No NetCDF files found in: {folder_path}")
        return
    logging.info(f"Found {len(nc_files)} NetCDF files within the folder")

    for file_path in nc_files:
        logging.info("=" * 80)
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
            with open('__variables_check.csv', 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Variable", "Class", "Category", "Domain"])
                for var in data_variables_list:
                    if not var.startswith('crs'):
                        row = var.split(";")
                        writer.writerow(row)
        except Exception as e:
            print(f"\n Failed to read file: {file_path}")
            print(f"Error: {e}")

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
    write_metadata_to_config_json(metadata_list, output_json)

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
    
    
def download_nwm_data_recursive(download_url: str, local_path: str, 
    existing_keys: Set[Tuple[str, str, str]]
) -> None:
    """
    Recursively download a unique set of output files from the server
    and create a mirrored folder structure as server
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
    Builds file keys in local folder. These keys are used for function re-runs 
    and enables the capability to not download a file again.
    """
    keys = set()
    for root, _, files in os.walk(local_root):
        for file in files:
            if file.endswith(".nc"):
                output_class, category, domain = parse_filename_metadata(file)
                keys.add((output_class, category, domain))

    return keys

def process_downloaded_files(local_root: str) -> List[NetCDFMetadata]:
    """
    Process downloaded files and create a list of metadata objects for a config json
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
    x_loc_info = ['x', 'lon', 'longitude']
    y_loc_info = ['y', 'lat', 'latitude']
    crs_info = ['crs', 'CRS', 'spatial_ref']
    res_x = -9999
    res_y = -9999
    origin_x = -9999
    origin_y = -9999
    proj_wkt = 'Not Available'
    vars_in_netcdf = []
    nwm_variables = ''
    x_loc_name = ''
    y_loc_name = ''

    ds = xr.open_dataset(file_path)
    for nwm_var in ds.variables:
        if nwm_var in x_loc_info: #XRes: assume only one of the x_loc_info will be in the file
            x = ds.variables[nwm_var].values
            res_x = compute_resolution(x)
            origin_x = float(x.min())
            x_loc_name = nwm_var
        elif nwm_var in y_loc_info: #YRes: assume only one of the y_loc_info will be in the file
            y = ds.variables[nwm_var].values
            res_y = compute_resolution(y)
            origin_y = float(y.min())
            y_loc_name = nwm_var
        elif nwm_var in crs_info: #CRS wkt
            proj_wkt = extract_wkt_from_crs(ds.variables[nwm_var])
        elif nwm_var in nwm_variables_list: #NWM output variables
            vars_in_netcdf.append(nwm_var)
    nwm_variables = ", ".join(vars_in_netcdf)
    return NetCDFMetadata(file_path, res_x, res_y, origin_x, origin_y, x_loc_name, y_loc_name, proj_wkt, nwm_variables, output_class, category, domain)

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

    :param metadata_list: List of NetCDFMetadata objects
    :param output_csv: Output CSV file path
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
    Writes NetCDFMetadata objects to config JSON using WKT CRS.
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
            "class": mdata.output_class,
            "category": mdata.category,
            "domain": mdata.domain
        }
        info_list.append(metadata_info_dict)

    config = {
        "files": info_list
    }
    # config: Dict[str, List[Dict[str, Any]]] = {
    #     "files": [to_dict(m) for m in metadata_list]
    # }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(config, f, indent = 2)

    print(f"Config JSON written to: {output_json}")