import os
import csv
import json
import sys
import threading
import random
import concurrent.futures
import time
from datetime import datetime, timedelta, timezone
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# API Endpoint
BASE_URL_PULL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items"

# Multi-threading sync
tracker_lock = threading.Lock()
log_lock = threading.Lock()

def write_to_log_file(log_dir, message):
    """Writes status entries safely to a unified log file using a thread lock."""
    log_file_path = os.path.join(log_dir, "usgs_downloads_status.log")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    with log_lock:
        with open(log_file_path, "a", encoding="utf-8") as lf:
            lf.write(f"[{timestamp}] {message}\n")

def load_tracker(tracker_file_path):
    """Loads incremental sync state tracking safely."""
    with tracker_lock:
        if os.path.exists(tracker_file_path):
            with open(tracker_file_path, "r") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {}
        return {}

def update_tracker_for_site(tracker_file_path, site_id, timestamp_str):
    """Updates a single site checkpoint marker safely."""
    with tracker_lock:
        data = {}
        if os.path.exists(tracker_file_path):
            with open(tracker_file_path, "r") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    data = {}
        
        data[site_id] = timestamp_str
        with open(tracker_file_path, "w") as f:
            json.dump(data, f, indent=4)

def get_resilient_session():
    """Configures a requests session with automatic 429 exponential backoff."""
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=True
    )
    adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def fetch_usgs_data(row, session, now_utc, api_key, download_dir, log_dir, tracker, tracker_file_path):
    """Executes the API query for a single site and saves the output."""

    raw_site_id = row.get("site_no", "").strip()
    if not raw_site_id:
        return "skipped_empty"

    # Format leading zeroes if necessary. Add the 'USGS-' prefix required for API
    site_id = raw_site_id.zfill(8) if len(raw_site_id) < 8 else raw_site_id
    formatted_location_id = f"USGS-{site_id}"

    if site_id in tracker:
        start_time = datetime.fromisoformat(tracker[site_id].replace("Z", "+00:00"))
    else:
        start_time = now_utc - timedelta(hours=24)

    if now_utc - start_time < timedelta(minutes=15):
        write_to_log_file(log_dir, f"Site {site_id}: Already up to date (<15m window). Skipping fetch.")
        return "up_to_date"

    time_window = f"{start_time.strftime('%Y-%m-%dT%H:%M:%SZ')}/{now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    
    params = {
        "monitoring_location_id": formatted_location_id,
        "parameter_code": "00060", # USGS parameter code for "Discharge (Streamflow)"
        'time': time_window,
        'limit': 1000,
        "f": "json"
    }

    headers = {
        "API_KEY": api_key,
        "Accept": "application/json"
    }

    # After failures due to threading deadlock and server rejects , the following is being tested
    max_retries = 5
    base_delay = 2   # Start with a 2-second backoff multiplier
    max_delay = 30   # Never sleep longer than 30 seconds
    retries = 0

    while retries < max_retries:
        try:
            # Independent thread request with strict timeouts
            response = requests.get(BASE_URL_PULL, params=params, headers=headers, timeout=(10, 20))
            
            # Check for Rate Limiting (HTTP 429) manually before raising exceptions
            if response.status_code == 429:
                retries += 1
                if retries >= max_retries:
                    write_to_log_file(log_dir, f"Gage {site_id}: Hit max retries ({max_retries}) for HTTP 429. Aborting.")
                    return "failed"
                
                # Calculate Exponential Backoff with Jitter: base_delay * (2 ^ retry_number)
                backoff = base_delay * (2 ** retries)
                jitter = random.uniform(0.5, 1.5)
                delay = min(backoff * jitter, max_delay)
                
                write_to_log_file(log_dir, f"Gage {site_id}: Rate limited (429). Retry {retries}/{max_retries}. Backing off for {delay:.2f}s...")
                time.sleep(delay)
                continue  # Jump to the next iteration of the while loop to retry

            # Raise exceptions for other HTTP errors (401, 404, 500, etc.)
            response.raise_for_status()
            data = response.json()
            response.close()  # Cleanly close socket immediately

            # Handle empty data sets
            if not data.get("features"):
                write_to_log_file(log_dir, f"Gage {site_id}: Query executed cleanly but zero records found.")
                return "no_new_data"

            # Save valid downloads to disk
            output_path = os.path.join(download_dir, f"{site_id}.json")
            with open(output_path, "w") as out_file:
                json.dump(data, out_file, indent=2)

            write_to_log_file(log_dir, f"Gage {site_id}: Successfully saved records to {output_path}")
            update_tracker_for_site(tracker_file_path, site_id, now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"))

            return "success"  # Download successful, exit the function cleanly

        except requests.exceptions.RequestException as e:
            # Handle standard network drops/timeouts by treating them as retryable events
            retries += 1
            write_to_log_file(log_dir, f"Gage {site_id}: Network issue encountered ({e}). Retry {retries}/{max_retries}...")
            time.sleep(base_delay * retries)
            
    return "failed"

def main():
    start_time = time.time()

    # Load parameters from environment variables
    api_key = os.environ.get("USGS_API_KEY")
    download_root = os.environ.get("DCOMROOT")
    log_dir = os.path.join(os.environ.get("DBNROOT"), "log")
    tracker_dir = os.path.join(os.environ.get("DBNROOT"), "tracker")
    
    if not api_key:
        print("Error: API_KEY is missing from environment.", file=sys.stderr)
        sys.exit(1)

    csv_file_path = sys.argv[1]
    if not os.path.exists(csv_file_path):
        print(f"Error: The target CSV file was not found at: {csv_file_path}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(download_root, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(tracker_dir, exist_ok=True)

    tracker_file_path = os.path.join(tracker_dir, "usgs_tracker.json")
    
    # Setup connection session and load state tracking data
    session = get_resilient_session()
    tracker = load_tracker(tracker_file_path)
    
    # Current execution window (End time is fixed to 'now' in UTC)
    now_utc = datetime.now(timezone.utc)
    
    print(f"Starting USGS download run at {now_utc.isoformat()}")

    # Initialize execution metrics tracking dictionaries
    stats = {"success": 0, "no_new_data": 0, "up_to_date": 0, "failed": 0, "skipped_empty": 0}

    # Open CSV and read site IDs strictly as STRINGS to protect leading zeros
    with open(csv_file_path, mode="r", newline="", encoding="utf-8") as csv_file:
        # Assumes CSV has a column header 'site_id'. Change if it's headless.
        reader = csv.DictReader(csv_file)
        csv_rows = list(reader)
        row_count = len(csv_rows)

    filename = os.path.basename(csv_file_path)
    print(f"Initializing download process for {filename}: {row_count} gages in file")
    write_to_log_file(log_dir, f"INFO: Commencing batch file processing run: {filename}")

    # Using ThreadPoolExecutor to run downloads concurrently
    MAX_WORKERS = 5
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submitting all download tasks to the thread pool
        future_to_site = {
            executor.submit(fetch_usgs_data, row, session, now_utc, api_key, download_root, log_dir, tracker, tracker_file_path): row
            for row in csv_rows
        }
        for future in concurrent.futures.as_completed(future_to_site):
            try:
                execution_outcome = future.result()  # If a thread crashed, this raises the error!
                if execution_outcome in stats:
                    stats[execution_outcome] += 1
            except Exception as thread_error:
                print(f"Error: Thread crash detected: {thread_error}", file=sys.stderr)

    # Summary Output directly to stdout
    elapsed_time = time.time() - start_time
    write_to_log_file(log_dir, f"INFO: Downloads finished in {elapsed_time:.2f} seconds. Outcomes: {stats}")
    
    print(f"Batch completed: '{filename}' handled in {elapsed_time:.2f}s.")
    print(f" -> Downloads: {stats['success']} | No New Data: {stats['no_new_data']} | Skipped (Current): {stats['up_to_date']} | Failures: {stats['failed']}")

if __name__ == "__main__":
    main()
