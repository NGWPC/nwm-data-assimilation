set -euo pipefail

# Determine the directory of shell script
SHL_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Resolve the project root
PROJECT_ROOT="$(cd "$SHL_SCRIPT_DIR/../.." && pwd)"

# Path to the .env file in project root
ENV_FILE="$PROJECT_ROOT/.env"

# Path to the Python script (could get this from user via CL?)
PYTHON_SCRIPT="$PROJECT_ROOT/data_assimilation_engine/Streamflow_Scripts/usgs_download/stream_flow_download/usgs_discharges_download.py"

# Define the folder containing your CSV files
CSV_DIR="$PROJECT_ROOT/data_assimilation_engine/Streamflow_Scripts/usgs_download/stream_flow_download/gages_csv_dir"

# Verify .env exists, then source and export variables
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "Error: .env file not found at: $ENV_FILE" >&2
    exit 1
fi

# Check if the CSV directory exists and contains CSV files
if [ ! -d "$CSV_DIR" ]; then
    echo "Error: CSV directory does not exist at $CSV_DIR" >&2
    exit 1
fi

# Look for CSV files in the folder
CSV_FILES=("$CSV_DIR"/*.csv)
if [ ! -e "${CSV_FILES[0]}" ]; then
    echo "Error: No CSV files found in $CSV_DIR" >&2
    exit 1
fi

# Create the log file inside DBNROOT, if it doesn't exist already.
if [ -n "$DBNROOT" ]; then
    mkdir -p "$DBNROOT/log"
else
    echo "Error: DBNROOT is not defined in .env."
    exit 1
fi

# Verify Python script exists before executing
if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "Error: Python script not found at: $PYTHON_SCRIPT" >&2
    exit 1
fi

for csv_file in "${CSV_FILES[@]}"; do
    # Run the Python script, passing the specific CSV FILE PATH
    python3 "$PYTHON_SCRIPT" "$csv_file"
done

