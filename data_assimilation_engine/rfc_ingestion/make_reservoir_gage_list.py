#!/usr/bin/env python

"""CLI script to discover raw reservoir forecast xml files within the input dir, read them to determine their gages and RFC codes,
and write a reservoir gages list file (CSV) to be consumed by existing scripts. Args namespace mimics patterns of existing legacy scripts."""

import argparse
import csv
import os
import re
import xml.etree.ElementTree as ET


def extract_rfc_code(file_name: str) -> str:
    """Extract the RFC code associated with the provided string, assuming its word is separated by other words in the string via underscore.
    Only the file basename is considered, not the full path.

    Examples:
        "/path/to/foo_RFCBAR_bazqux.xml" -> "RFCBAR"
        "/path/to/bar_FOORFC_bazqux.xml" -> "FOORFC"
    """
    extractor_pattern = r"([^_]*RFC[^_]*)(?=_)"
    bn_no_ext = os.path.splitext(os.path.basename(file_name))[0]
    # print(f"extracting pattern {extractor_pattern} from string {bn_no_ext}")

    groups = re.findall(extractor_pattern, bn_no_ext)
    if len(groups) != 1:
        raise ValueError(
            f"Found {len(groups)} matches for pattern {repr(extractor_pattern)} in {repr(bn_no_ext)} (expected 1)."
        )

    rfc_code = groups[0]
    if not (rfc_code.startswith("RFC") or rfc_code.endswith("RFC")):
        raise ValueError(
            f"Unexpected rfc_code: {rfc_code} when parsing pattern {repr(extractor_pattern)} in {repr(bn_no_ext)}"
        )
    if rfc_code == "RFC":
        raise ValueError(f"RFC code is just {rfc_code}")
    return rfc_code


def cli() -> argparse.Namespace:
    """Parse the current CLI args via argparse and returns an argparse.Namespace instance of the parsed result.
    Args namespace mimics patterns of existing legacy scripts."""
    parser = argparse.ArgumentParser(description="Generate RFC reservoir gage list")
    parser.add_argument(
        "-i",
        "--input_dir",
        required=True,
        help="Input directory containing RFC forecast XML files. These are read to build the csv.",
    )
    parser.add_argument(
        "-s",
        "--output_sites_file",
        required=True,
        help="Output CSV file. Error raised if this already exists.",
    )
    args = parser.parse_args()
    return args


def main(input_dir: str, output_sites_file: str) -> None:
    """See docstring of this script."""

    if os.path.exists(output_sites_file):
        raise FileExistsError(f"Output CSV file {output_sites_file} already exists.")
    if not os.path.exists(input_dir):
        raise FileNotFoundError(f"Input directory {input_dir} does not exist.")

    # Dictionary of RFC code to set of associated reservoir gages.
    rfc2gages: dict[str, set[str]] = {}

    for root, dirs, files in os.walk(input_dir):
        dirs.sort()
        files.sort()
        for fn in files:
            if not fn.endswith(".xml"):
                continue

            rfc_code = extract_rfc_code(fn)

            fp = os.path.join(root, fn)
            print(f"Reading: {fp} (RFC code: {rfc_code})")
            for elem in ET.parse(fp).iter():
                if "locationId" in elem.tag and elem.text:
                    rfc2gages.setdefault(rfc_code, set()).add(elem.text)

    out_records: list[dict] = []
    out_fields = [
        "gage",
        "gagedFlowline",
        "NHDWaterbodyComID",
        "lakeLink",
        "SiteName",
        "RFC",
    ]

    for rfc in sorted(rfc2gages):
        gages = rfc2gages[rfc]
        print(f"RFC {repr(rfc)} had {len(gages)} reservoir gages")
        for gage in sorted(gages):
            rec = {k: "" for k in out_fields}
            rec["gage"] = gage
            rec["RFC"] = rfc
            out_records.append(rec)

    print(f"Writing: {output_sites_file}")
    with open(output_sites_file, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(out_records)


if __name__ == "__main__":
    _ARGS = cli()
    main(_ARGS.input_dir, _ARGS.output_sites_file)
