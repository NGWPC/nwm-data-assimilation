#
# Scan the csv reservoirs list CSV and scan the XML data files already downloaded,
# and build a report indicating which gages exist in both, or only in the CSV list, or only in the XML data.
# Write the report to a json file.
#
# Usage:
#   Run from the repo root.
#

import csv
import glob
import json
import os
import xml.etree.ElementTree as ET

RESERVOIR_GAGES_LIST_CSV = "data_assimilation_engine/rfc_ingestion/RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv"
RESERVOIR_DATA_GLOB_PATTERN = "data_assimilation_engine/rfc_ingestion/testdata/**/*.xml"
REPORT_FILE = os.path.splitext(os.path.abspath(__file__))[0] + "_result.json"

# Read CSV gages
print(f"Reading: {RESERVOIR_GAGES_LIST_CSV}")
csv_gages = {row["gage"] for row in csv.DictReader(open(RESERVOIR_GAGES_LIST_CSV))}

# Read XML locationIds from forecast files
xml_locs = set()
print(f"Reading files matching: {RESERVOIR_DATA_GLOB_PATTERN}")
for xml_file in glob.glob(RESERVOIR_DATA_GLOB_PATTERN, recursive=True):
    print(f"Reading: {xml_file}")
    for elem in ET.parse(xml_file).iter():
        if "locationId" in elem.tag and elem.text:
            xml_locs.add(elem.text)

data = {
    "both": sorted(xml_locs & csv_gages),
    "only_xml": sorted(xml_locs - csv_gages),
    "only_csv": sorted(csv_gages - xml_locs),
}

print(f"{len(data['both'])} gages are in both")
print(f"{len(data['only_xml'])} locationIds are in XML but not in CSV")
print(f"{len(data['only_csv'])} gages are in CSV but not in XML")

print(f"Writing: {REPORT_FILE}")
with open(REPORT_FILE, "w") as f:
    f.write(json.dumps(data, indent=2))
