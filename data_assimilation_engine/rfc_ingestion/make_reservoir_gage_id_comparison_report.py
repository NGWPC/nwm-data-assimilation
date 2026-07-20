#!/usr/bin/env python

"""Script to scan the csv reservoirs list CSV and scan the XML data files already downloaded,
and build a report indicating which gages exist in both, or only in the CSV list, or only in the XML data.
Write the report to a json file.

The input file is defined by the global SETTINGS variable.

The json file has keys "both", "only_csv", and "only_xml" indicating the status of each gage.
The value of each key is a list gages.  Each gage itself is represented as a list of length 2: gage ID, RFC ID.

For example snippet:

{
  "both": [
    [
      "ABIN5",
      "WGRFC"
    ],
    [
      "ACDO2",
      "ABRFC"
    ],
...
}

Usage:
  Run from the repo root.
"""

import csv
import json
import os
import xml.etree.ElementTree as ET

from make_reservoir_gage_list import extract_rfc_code

SETTINGS = "data_assimilation_engine/rfc_ingestion/reservoir_gage_data_settings.json"


def main() -> None:
    """See docstring of this script."""
    print(f"Reading: {SETTINGS}")
    with open(SETTINGS) as f:
        settings = json.load(f)

    report_file = os.path.splitext(os.path.abspath(__file__))[0] + "_result.json"

    # Read CSV gages
    print(f"Reading: {settings['sites_file']}")
    with open(settings["sites_file"]) as f:
        csv_gages = {(row["gage"], row["RFC"]) for row in csv.DictReader(f)}

    # Read XML locationIds from forecast files
    xml_locs = set()

    print(f"Reading xml files within: {settings['data_dir_in']}")
    if not os.path.isdir(settings["data_dir_in"]):
        raise NotADirectoryError(settings["data_dir_in"])
    for root, dirs, files in os.walk(settings["data_dir_in"]):
        dirs.sort()
        files.sort()
        for fn in files:
            if not fn.lower().endswith(".xml"):
                continue
            xml_file = os.path.join(root, fn)
            rfc_code = extract_rfc_code(xml_file)
            print(f"Reading: {xml_file}")
            for elem in ET.parse(xml_file).iter():
                if "locationId" in elem.tag and elem.text:
                    xml_locs.add((elem.text, rfc_code))

    data = {
        "both": sorted(xml_locs & csv_gages),
        "only_xml": sorted(xml_locs - csv_gages),
        "only_csv": sorted(csv_gages - xml_locs),
    }

    print(f"{len(data['both'])} gages are in both")
    print(f"{len(data['only_xml'])} locationIds are in XML but not in CSV")
    print(f"{len(data['only_csv'])} gages are in CSV but not in XML")

    print(f"Writing: {report_file}")
    with open(report_file, "w") as f:
        f.write(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
