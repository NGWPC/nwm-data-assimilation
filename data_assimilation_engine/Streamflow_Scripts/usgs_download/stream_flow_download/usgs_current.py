#!/usr/bin/env python3

###################################################################
# Script: usgs_monitor.py
# Version: 1.0
# Purpose: Find updated usgs steamflow gauge data and pull in json
#          format.
# Author: Salemi 01/25/2025
#
###################################################################

import requests
import datetime
import json
import pytz
import os
import time
import sys
import signal
import concurrent.futures
import logging
from logging.handlers import TimedRotatingFileHandler

# Import environmental variables
required_env_vars = ['DCOMROOT', 'DBNROOT']
env_vars = {}

for var in required_env_vars:
    value = os.getenv(var)
    if value:
        # If the variable is found, store it in the dictionary.
        env_vars[var] = value
    else:
        # If not found, log a critical error and exit.
        print(f"Required {var} not found")
        exit()

# --- CONFIGURATION CONSTANTS ---
DBN_ROOT = env_vars['DBNROOT']
DCOM_ROOT = env_vars['DCOMROOT']
SLEEP_INTERVAL_MIN = 2   # How long to wait between checks
LOOKBACK_BUFFER_MIN = 3  # Time window to search for updates
MAX_WORKERS = 20         # Maximum number of concurrent threads for downloading

BASE_URL_CHECK = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/latest-continuous/items"
BASE_URL_PULL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items"
# We only care about streamflow data (00060)
PARAMETER_CODE = '00060'
HEARTBEAT_TIMEOUT_MINS = 15

STATE_FILE = os.path.join(DBN_ROOT, 'user/usgs_api/last_pull_time.txt')
PID_FILE = os.path.join(DBN_ROOT, 'user/usgs_api/daemon.pid')


# --- HELPER FUNCTIONS ---

def setup_logging(log_path):

    logger = logging.getLogger('usgs_streamflow_monitor.log')
    logger.setLevel(logging.INFO)
# Create a TimedRotatingFileHandler.
    handler = TimedRotatingFileHandler(
        LOG_FILE_PATH,
        when='midnight',
        interval=1,
        backupCount=7,
        delay=True
    )
# Create a formatter and add it to the handler.
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def load_manual_env(file_path=None):
    if file_path is None:
        file_path = os.path.join(DBN_ROOT, "user/usgs_api", ".usgs_env")

    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            for line in f:
                # Remove whitespace and ignore comments or empty lines
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # Split by the first '=' found
                if "=" in line:
                    key, value = line.split("=", 1)
                    # Set it in the environment so os.environ.get works later
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")


def load_last_pull_time():
    """Loads the last recorded pull time from the state file."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            # Strip newline and return the ISO 8601 string
            return f.read().strip()

    # If file doesn't exist, start 3 minutes in the past
    logger.info("INFO: No state file found. Starting 5 minutes ago.")
    initial_start = datetime.datetime.now(pytz.utc) - datetime.timedelta(minutes=5)
    return initial_start.strftime("%Y-%m-%dT%H:%M:%SZ")


def save_last_pull_time(timestamp_str):
    """Saves the current time as the new starting time for the next cycle."""
    with open(STATE_FILE, 'w') as f:
        f.write(timestamp_str)
    logger.info(f"State updated to {timestamp_str}")


def get_time_range(last_pull_time_str):
    """Calculates the time range (start/end) for the API query."""
    # Ensure current time is UTC
    now_utc = datetime.datetime.now(pytz.utc)

    # Calculate the end time (1 minute ago for safety)
    end_time = now_utc - datetime.timedelta(minutes=1)
    end_time_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Use the previous pull time as the start time
    start_time_str = last_pull_time_str

    return start_time_str, end_time_str


def fetch_full_site_data(site_id, odir, site_name):
    """Fetches the full JSON data for a specific site and saves it."""

    # The time parameter requests the last 6 hours of instantaneous data (PT6H)
    params = {
        'monitoring_location_id': site_id,
        'parameter_code': PARAMETER_CODE,
        'time': 'PT6H',
        'f': 'json',  # Request JSON format explicitly
        'limit': 50
    }

    API_KEY = os.environ.get("USGS_API_KEY")

    headers = {
            'X-Api-Key': API_KEY,
            'Accept': 'application/json'
            }

    try:
        response = requests.get(BASE_URL_PULL, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        data['monitoring_location_name'] = site_name

        # Save the file
        site_id = site_id.replace('USGS-', '')
        file_name = f"{site_id}.json"
        output_path = os.path.join(odir, file_name)

        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)

        os.chmod(output_path, 0o664)

        logger.info(f"SUCCESS: Downloaded and saved data for site {site_id}.")
        return True

    except requests.exceptions.RequestException as e:
        logger.info(f"WARNING: Failed to pull full data for site {site_id}. Error: {e}")
        return False


def run_monitor_cycle(last_pull_time_str, odir):
    """Runs one complete cycle: discovers updated sites and initiates data pull."""

    start_time_str, end_time_str = get_time_range(last_pull_time_str)

    logger.info(f"\n--- Starting Check: {start_time_str} to {end_time_str} ---")

    time_range_value = f"{start_time_str}/{end_time_str}"

    try:
        # datetime_value_encoded = quote(time_range_value, safe=':/Z-')

        # --- 1. Discover Updated Sites ---
        params = {
            'last_modified': time_range_value,
            'parameter_code': PARAMETER_CODE,
            'limit': 700  # Adjust based on expected volume
        }

        response = requests.get(BASE_URL_CHECK, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

    except requests.exceptions.RequestException as e:
        logger.info(f"FATAL: Discovery API request failed. Skipping cycle. Error: {e}")
        return last_pull_time_str, 0  # Return old time to retry range later

    features = data.get('features', [])
    updated_sites = {}

    for feature in features:
        # Extract the site ID from the properties dictionary
        props = feature.get('properties', {})
        site_id = props.get('monitoring_location_id')
        site_name = (
                props.get('monitoring_location_name') or
                props.get('name') or
                "Unknown Name"
        )

        if site_id:
            # Remove the "USGS-" prefix for consistency with the site URL query
            # site_id = site_id.replace('USGS-', '')
            updated_sites[site_id] = site_name

    if not updated_sites:
        logger.info("INFO: No sites found with updates in the interval.")
        # Only update state time if we successfully queried the server
        return end_time_str, 0

    logger.info(f"INFO: Found {len(updated_sites)} unique sites with updates.")

    # --- 2. Pull Full Data for Each Updated Site (Parallelized) ---
    successful_downloads = 0

    # Using ThreadPoolExecutor to run downloads concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submitting all download tasks to the thread pool
        future_to_site = {
            executor.submit(fetch_full_site_data, sid, odir, sname): sid
            for sid, sname in updated_sites.items()
        }

        # Waiting for results and counting successes
        for future in concurrent.futures.as_completed(future_to_site):
            site_id = future_to_site[future]
            try:
                # future.result() returns the boolean (True/False) result of fetch_full_site_data
                if future.result():
                    successful_downloads += 1
            except Exception as exc:
                logger.info(f'WARNING: Site {site_id} generated an unhandled exception during pull: {exc}')

    # Only update the state time if the discovery was successful
    logger.info(f"INFO: {successful_downloads} out of {len(updated_sites)} sites downloaded successfully.")
    return end_time_str, successful_downloads


def is_process_running(pid):
    """Check if there is any running process with given PID."""
    try:
        os.kill(pid, 0)  # Signal 0 does nothing but checks if process exists
    except OSError:
        return False
    return True


def manage_process_state():
    # 1. Check if PID file exists
    if os.path.exists(PID_FILE):
        with open(PID_FILE, 'r') as f:
            try:
                old_pid = int(f.read().strip())
            except ValueError:
                old_pid = None

        if old_pid and is_process_running(old_pid):
            # 2. Check if the state file is "stale"
            if os.path.exists(STATE_FILE):
                last_mtime = os.path.getmtime(STATE_FILE)
                seconds_since_update = time.time() - last_mtime

                if seconds_since_update > (HEARTBEAT_TIMEOUT_MINS * 60):
                    logger.info(f"Stale process detected (PID {old_pid}). Killing and restarting...")
                    try:
                        os.kill(old_pid, signal.SIGTERM)
                        time.sleep(2)  # Give it a moment to release ports/files
                    except OSError:
                        pass
                else:
                    logger.info(f"Daemon already running (PID {old_pid}) and active. Exiting.")
                    sys.exit(0)

    # 3. Create/Overwrite PID file for the current process
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))


# --- MAIN EXECUTION BLOCK ---
def run_daemon():
    # Load initial state
    last_pull_time = load_last_pull_time()

    # Define the main monitoring loop
    while True:
        try:
            current_date = datetime.datetime.now().strftime('%Y%m%d')
            output_dir = os.path.join(DCOM_ROOT, current_date, 'obs/raw/water_level/usgs_streamflow')
            # Setup output directory
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)

                new_parts = [current_date, "obs", "raw", "water_level", "usgs_streamflow"]

                current_path = DCOM_ROOT
                for part in new_parts:
                    current_path = os.path.join(current_path, part)
                    # Apply 775 only to these segments
                    os.chmod(current_path, 0o775)
                logger.info(f"INFO: Created output directory: {output_dir}")

            # Run the data retrieval cycle
            new_pull_time, count = run_monitor_cycle(last_pull_time, output_dir)

            #  Update the state for the next run
            if new_pull_time != last_pull_time:
                save_last_pull_time(new_pull_time)
                last_pull_time = new_pull_time

            # Wait for the next interval
            logger.info(f"\nINFO: Cycle complete. Sleeping for {SLEEP_INTERVAL_MIN} minutes...")
            time.sleep(SLEEP_INTERVAL_MIN * 60)

        except KeyboardInterrupt:
            logger.info("\nMonitor stopped by user.")
            sys.exit(0)
        except Exception as e:
            logger.info(f"CRITICAL ERROR in main loop: {e}. Sleeping for 5 minutes.")
            time.sleep(300)  # Sleep longer on critical errors


if __name__ == "__main__":
    load_manual_env()

    lock_file = manage_process_state()

    LOG_FILE_PATH = os.path.join(DBN_ROOT, "log", "usgs_streamflow_monitor.log")
    logger = setup_logging(LOG_FILE_PATH)

    logger.info("Daemon started successfully. Monitoring cycle beginning...")

    try:
        run_daemon()
    finally:
        # Cleanup PID file on clean exit
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
