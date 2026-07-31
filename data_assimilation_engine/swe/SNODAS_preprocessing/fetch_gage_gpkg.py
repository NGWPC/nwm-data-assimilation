#!/usr/bin/env python3
"""
Fetch/collect gage geopackage files needed by the SWE SNODAS gage backfill workflow.

This script does NOT generate hydrofabric geopackages from scratch. It collects existing
`gages-<gage_id>.gpkg` files from local directories and/or S3 prefixes into one local
GPKG_DIR that can be passed to `swe_gage.py`.

Examples
--------
# Search local repo/sample dirs and copy matching gpkg files:
python fetch_gage_gpkg.py \
  --gage-ids 02236500 02266200 \
  --local-root /home/mohammed.karim/Calibration/nwm-data-assimilation \
  --output-dir /tmp/swe_gpkg_conus

# Search S3 prefixes and download matching files:
python fetch_gage_gpkg.py \
  --gage-ids 02236500 02266200 \
  --s3-prefix s3://ngwpc-forcing/gpkg \
  --s3-prefix s3://ngwpc-forcing/hydrofabric \
  --output-dir /tmp/swe_gpkg_conus
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

try:
    import boto3
except Exception:  # pragma: no cover
    boto3 = None


DEFAULT_CONUS_MISSING_GAGES = [
    "02236500",
    "02266200",
    "02266480",
    "02296500",
    "02297155",
    "02298123",
    "02307359",
    "02310947",
    "02312200",
    "08025500",
    "08144500",
    "11180900",
    "11274790",
]


def normalize_gage_id(value: str) -> str:
    """Keep leading zeros and remove common filename decorations."""
    v = str(value).strip()
    v = Path(v).stem
    v = v.replace("gages-", "").replace("gauge_", "").replace("gage_", "")
    v = v.replace("_swe", "")
    return v


def read_gage_ids(args: argparse.Namespace) -> list[str]:
    gage_ids: list[str] = []

    if args.default_conus_missing:
        gage_ids.extend(DEFAULT_CONUS_MISSING_GAGES)

    if args.gage_ids:
        gage_ids.extend(args.gage_ids)

    if args.gage_id_file:
        with open(args.gage_id_file, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # supports plain one-column files or CSV-ish lines
                gage_ids.append(line.split(",")[0])

    normalized = []
    seen = set()
    for gage in gage_ids:
        g = normalize_gage_id(gage)
        if g and g not in seen:
            normalized.append(g)
            seen.add(g)
    return normalized


def candidate_names(gage_id: str) -> list[str]:
    # The SWE processor expects `gages-<gage_id>.gpkg`. Other names are accepted
    # only so we can normalize older/sample files into the expected name.
    return [
        f"gages-{gage_id}.gpkg",
        f"gage_{gage_id}.gpkg",
        f"gauge_{gage_id}.gpkg",
        f"{gage_id}.gpkg",
    ]


def find_local_file(gage_id: str, local_roots: Iterable[str]) -> Optional[Path]:
    names = set(candidate_names(gage_id))
    for root in local_roots:
        root_path = Path(root).expanduser().resolve()
        if not root_path.exists():
            continue

        # Fast exact checks in common layouts.
        for name in names:
            direct = root_path / name
            if direct.exists():
                return direct

        # Recursive fallback. This is intentionally basename-based so it can
        # find files under domain folders such as conus_hf2.2/cadwr_hf2.2.
        for path in root_path.rglob("*.gpkg"):
            if path.name in names:
                return path
    return None


def parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Expected s3://bucket/prefix, got: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def s3_client():
    if boto3 is None:
        raise RuntimeError("boto3 is required for S3 download. Install boto3 or use --local-root only.")
    return boto3.client("s3")


def find_s3_key(gage_id: str, s3_prefixes: Iterable[str]) -> Optional[str]:
    client = s3_client()
    names = set(candidate_names(gage_id))

    for prefix_uri in s3_prefixes:
        bucket, prefix = parse_s3_uri(prefix_uri)
        prefix = prefix.rstrip("/") + "/" if prefix else ""

        # First try exact keys directly under prefix.
        for name in names:
            key = prefix + name
            try:
                client.head_object(Bucket=bucket, Key=key)
                return f"s3://{bucket}/{key}"
            except Exception:
                pass

        # Recursive search under prefix. This may be slower but robust when files
        # are stored in domain subdirectories.
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if Path(key).name in names:
                    return f"s3://{bucket}/{key}"
    return None


def download_s3_file(s3_uri: str, out_file: Path) -> None:
    client = s3_client()
    bucket, key = parse_s3_uri(s3_uri)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(bucket, key, str(out_file))


def collect_gpkg(
    gage_ids: list[str],
    output_dir: Path,
    local_roots: list[str],
    s3_prefixes: list[str],
    overwrite: bool,
    manifest_file: Path,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    missing = 0

    for gage_id in gage_ids:
        expected_out = output_dir / f"gages-{gage_id}.gpkg"
        if expected_out.exists() and not overwrite:
            rows.append({
                "gage_id": gage_id,
                "status": "already_exists",
                "source": str(expected_out),
                "output_file": str(expected_out),
                "note": "",
            })
            continue

        source_path = find_local_file(gage_id, local_roots) if local_roots else None
        if source_path is not None:
            shutil.copy2(source_path, expected_out)
            rows.append({
                "gage_id": gage_id,
                "status": "copied_local",
                "source": str(source_path),
                "output_file": str(expected_out),
                "note": "normalized filename to gages-<gage_id>.gpkg",
            })
            continue

        source_s3 = find_s3_key(gage_id, s3_prefixes) if s3_prefixes else None
        if source_s3 is not None:
            download_s3_file(source_s3, expected_out)
            rows.append({
                "gage_id": gage_id,
                "status": "downloaded_s3",
                "source": source_s3,
                "output_file": str(expected_out),
                "note": "normalized filename to gages-<gage_id>.gpkg",
            })
            continue

        missing += 1
        rows.append({
            "gage_id": gage_id,
            "status": "missing_gpkg",
            "source": "",
            "output_file": str(expected_out),
            "note": "not found in --local-root or --s3-prefix locations",
        })

    with open(manifest_file, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=["gage_id", "status", "source", "output_file", "note"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote GPKG manifest: {manifest_file}")
    by_status = {}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    for status, count in sorted(by_status.items()):
        print(f"{status}: {count}")
    return missing


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect gage geopackages for SWE SNODAS backfill.")
    parser.add_argument("--gage-ids", nargs="*", default=[], help="Gage IDs to collect.")
    parser.add_argument("--gage-id-file", help="Text/CSV file with one gage ID per line or in first CSV column.")
    parser.add_argument("--default-conus-missing", action="store_true", help="Use the known 13 missing CONUS gages.")
    parser.add_argument("--local-root", action="append", default=[], help="Local directory to search recursively. May be repeated.")
    parser.add_argument("--s3-prefix", action="append", default=[], help="S3 prefix to search recursively. May be repeated.")
    parser.add_argument("--output-dir", required=True, help="Destination GPKG_DIR for swe_gage.py.")
    parser.add_argument("--manifest", default="gpkg_fetch_manifest.csv", help="Output manifest CSV.")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing files in output dir.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    gage_ids = read_gage_ids(args)
    if not gage_ids:
        raise SystemExit("No gage IDs provided. Use --gage-ids, --gage-id-file, or --default-conus-missing.")

    missing = collect_gpkg(
        gage_ids=gage_ids,
        output_dir=Path(args.output_dir),
        local_roots=args.local_root,
        s3_prefixes=args.s3_prefix,
        overwrite=args.overwrite,
        manifest_file=Path(args.manifest),
    )
    if missing:
        raise SystemExit(f"Missing {missing} requested geopackage file(s). See {args.manifest}.")


if __name__ == "__main__":
    main()
