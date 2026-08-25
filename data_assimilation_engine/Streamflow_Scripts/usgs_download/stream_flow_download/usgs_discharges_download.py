import os
import csv
import json
import sys
import time
from datetime import datetime, timedelta, timezone
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# API Endpoint
BASE_URL_PULL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items"

def write_to_log_file(log_dir, message):
    """Writes status entries safely to a unified log file using a thread lock."""
    log_file_path = os.path.join(log_dir, "usgs_downloads_status.log")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(log_file_path, "a", encoding="utf-8") as lf:
        lf.write(f"[{timestamp}] {message}\n")

def load_tracker(tracker_file_path):
    """Loads incremental sync state tracking safely."""
    if os.path.exists(tracker_file_path):
        with open(tracker_file_path, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def update_tracker_for_site(tracker_file_path, site_id, timestamp_str):
    """Updates checkpoints inside the custom tracker directory safely."""
    data = load_tracker(tracker_file_path)
    data[site_id] = timestamp_str
    with open(tracker_file_path, "w") as f:
        json.dump(data, f, indent=4)

def main():
    start_watch = time.time()

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
    tracker = load_tracker(tracker_file_path)
    now_utc = datetime.now(timezone.utc) # Current execution window (End time is fixed to 'now' in UTC)

    print(f"Starting USGS download run at {now_utc.isoformat()}")

    # Initialize execution metrics tracking dictionaries
    stats = {"success": 0, "no_new_data": 0, "up_to_date": 0, "failed": 0}

    # Open CSV and read site IDs strictly as STRINGS to protect leading zeros
    with open(csv_file_path, mode="r", newline="", encoding="utf-8") as csv_file:
        # Assumes CSV has a column header 'site_id'. Change if it's headless.
        reader = csv.DictReader(csv_file)
        csv_rows = list(reader)
        row_count = len(csv_rows)

    filename = os.path.basename(csv_file_path)
    print(f"Initializing download process for {filename}: {row_count} gages in file")
    write_to_log_file(log_dir, f"INFO: Commencing batch file processing run: {filename}")

    for idx, row in enumerate(csv_rows, 1):
        raw_site_id = row.get("site_no", "").strip()
        if not raw_site_id:
            continue

        site_id = raw_site_id.zfill(8) if len(raw_site_id) < 8 else raw_site_id
        formatted_location_id = f"USGS-{site_id}"

        # Check tracking window
        if site_id in tracker:
            start_time = datetime.fromisoformat(tracker[site_id].replace("Z", "+00:00"))
        else:
            start_time = now_utc - timedelta(hours=24)

        if now_utc - start_time < timedelta(minutes=15):
            write_to_log_file(log_dir, f"Gage {site_id}: Up to date. Skipping.")
            stats["up_to_date"] += 1
            continue

        time_window = f"{start_time.strftime('%Y-%m-%dT%H:%M:%SZ')}/{now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        params = {
            "monitoring_location_id": formatted_location_id,
            "parameter_code": "00060",
            "time": time_window,
            "limit": 1000,
            "f": "json"
        }
        headers = {"API_KEY": api_key, "Accept": "application/geo+json"}

        # Print console progress indicator every 20 files
        if idx % 20 == 0 or idx == row_count:
            print(f" -> Processing progress: Checked {idx}/{row_count} gages...")

        try:
            # Execute request with strict timeouts
            response = requests.get(BASE_URL_PULL, params=params, headers=headers, timeout=(10, 20))
            
            if response.status_code == 429:
                write_to_log_file(log_dir, f"Gage {site_id}: Hit rate limit (429). Waiting 5 seconds...")
                stats["failed"] += 1
                time.sleep(5.0)  # Take a small break if a 429 happens
                continue

            response.raise_for_status()
            data = response.json()
            response.close()

            if not data.get("features"):
                write_to_log_file(log_dir, f"Gage {site_id}: No continuous discharge records found.")
                stats["no_new_data"] += 1
            else:
                output_path = os.path.join(download_root, f"{site_id}.json")
                with open(output_path, "w") as out_file:
                    json.dump(data, out_file, indent=2)
                
                write_to_log_file(log_dir, f"Gage {site_id}: Successfully saved records.")
                stats["success"] += 1
                update_tracker_for_site(tracker_file_path, site_id, now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"))

        except Exception as e:
            write_to_log_file(log_dir, f"Gage {site_id}: Failed due to error: {e}")
            stats["failed"] += 1

        # Mandatory Micro-Throttle: Pause 1 seconds between EVERY request.
        # Reduces frequent 429 bans.
        time.sleep(1)

    # Summary Output directly to stdout
    elapsed_time = time.time() - start_watch
    write_to_log_file(log_dir, f"INFO: Downloads finished in {elapsed_time:.2f} seconds. Outcomes: {stats}")
    
    print(f"Batch completed: '{filename}' handled in {elapsed_time:.2f}s.")
    print(f" -> Downloads: {stats['success']} | No New Data: {stats['no_new_data']} | Skipped (Current): {stats['up_to_date']} | Failures: {stats['failed']}")

if __name__ == "__main__":
    main()
