#!/usr/bin/env python3
"""Fetch NHF gage GeoPackages from Icefabric for multiple gage providers."""

from __future__ import annotations

import argparse
import csv
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote

import httpx

try:
    from data_assimilation_engine.swe.SNODAS_preprocessing.nhf_gage_list_utils import (
        GageRecord,
        normalize_domain,
        read_gage_lists,
        safe_file_id,
    )
except ImportError:  # standalone/local execution
    from nhf_gage_list_utils import GageRecord, normalize_domain, read_gage_lists, safe_file_id

DEFAULT_LAYERS = [
    "divides",
    "flowpaths",
    "network",
    "nexus",
    "virtual_nexus",
    "virtual_flowpaths",
    "waterbodies",
    "gages",
    "reference_flowpaths",
    "hydrolocations",
]

SNODAS_DOMAINS_DEFAULT = {"CONUS", "Alaska", "Hawaii"}


@dataclass
class FetchResult:
    gage_id: str
    file_id: str
    domain: str
    agency: str
    status: str
    output_file: str
    url: str
    note: str = ""


def icefabric_base_url(environment: str) -> str:
    if environment == "test":
        return "http://edfs.test.nextgenwaterprediction.com/api/v1/hydrofabric"
    if environment == "oe":
        return "https://edfs.oe.nextgenwaterprediction.com/api/v1/hydrofabric"
    raise ValueError("environment must be 'test' or 'oe'")


def fetch_one_gpkg(
    client: httpx.Client,
    record: GageRecord,
    output_dir: Path,
    environment: str,
    source: str = "nhf",
    overwrite: bool = False,
    layers: Optional[list[str]] = None,
) -> FetchResult:
    layers = layers or DEFAULT_LAYERS
    file_id = safe_file_id(record.gage_id)
    domain_dir = output_dir / record.domain / (record.agency or "UNKNOWN")
    domain_dir.mkdir(parents=True, exist_ok=True)

    output_file = domain_dir / f"gauge_{file_id}.gpkg"
    basin_for_url = quote(record.gage_id, safe="")
    url = f"{icefabric_base_url(environment)}/{basin_for_url}/gpkg"

    if output_file.exists() and not overwrite and output_file.stat().st_size > 0:
        return FetchResult(
            record.gage_id,
            file_id,
            record.domain,
            record.agency,
            "exists",
            str(output_file),
            url,
            "file already exists; use --overwrite to replace",
        )

    params = {
        "id_type": "gage_id",
        "source": source,
        "domain": record.domain,
        "layers": layers,
    }

    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        content = response.content
        if not content or len(content) < 1024:
            return FetchResult(
                record.gage_id,
                file_id,
                record.domain,
                record.agency,
                "empty_response",
                str(output_file),
                str(response.url),
                f"response size={len(content) if content else 0} bytes",
            )
        output_file.write_bytes(content)
        return FetchResult(record.gage_id, file_id, record.domain, record.agency, "downloaded", str(output_file), str(response.url), "")
    except httpx.TimeoutException as exc:
        return FetchResult(record.gage_id, file_id, record.domain, record.agency, "timeout", str(output_file), url, str(exc))
    except httpx.HTTPStatusError as exc:
        return FetchResult(record.gage_id, file_id, record.domain, record.agency, f"http_{exc.response.status_code}", str(output_file), str(exc.request.url), str(exc))
    except Exception as exc:  # noqa: BLE001
        return FetchResult(record.gage_id, file_id, record.domain, record.agency, "failed", str(output_file), url, repr(exc))


def write_manifest(path: str | Path, rows: Iterable[FetchResult]) -> None:
    path = Path(path)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    fieldnames = list(asdict(rows[0]).keys()) if rows else ["gage_id", "file_id", "domain", "agency", "status", "output_file", "url", "note"]
    with open(path, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch NHF gage GeoPackages from Icefabric API.")
    parser.add_argument("--gage-list", required=True, nargs="+", help="One or more gage-list files. Supports USGS, TXDOT, ENVCA, CADWR formats.")
    parser.add_argument("--output-dir", required=True, help="Directory to write downloaded geopackages, grouped by domain/provider.")
    parser.add_argument("--environment", choices=["test", "oe"], default="oe", help="Icefabric API environment.")
    parser.add_argument("--source", choices=["hf", "nhf"], default="nhf", help="Hydrofabric source/version to request.")
    parser.add_argument("--domains", nargs="+", default=["CONUS", "Alaska", "Hawaii"], help="Domains to process. Default: CONUS Alaska Hawaii.")
    parser.add_argument("--default-domain", default="CONUS", help="Domain to use for one-column lists, e.g. TXDOT_gages.txt.")
    parser.add_argument("--default-agency", default="", help="Agency/provider to use when not present in the file; otherwise inferred from filename.")
    parser.add_argument("--enabled-only", action="store_true", help="Only process rows whose enabled flag is true/1/yes when present.")
    parser.add_argument("--manifest", default="nhf_gpkg_fetch_manifest.csv", help="CSV manifest output path.")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout seconds per request.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Optional sleep seconds between API calls.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of gages for testing.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing geopackages.")
    args = parser.parse_args()

    domains = {normalize_domain(d) for d in args.domains}
    invalid_for_story = domains - SNODAS_DOMAINS_DEFAULT
    if invalid_for_story:
        print(f"WARNING: requested domains outside default SNODAS NHF story scope: {sorted(invalid_for_story)}")

    records = read_gage_lists(
        args.gage_list,
        domains=domains,
        default_domain=args.default_domain,
        default_agency=args.default_agency,
        enabled_only=args.enabled_only,
        limit=args.limit,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[FetchResult] = []
    with httpx.Client(timeout=args.timeout) as client:
        for i, record in enumerate(records, start=1):
            print(f"[{i}/{len(records)}] fetching {record.domain}/{record.agency or 'UNKNOWN'} gage {record.gage_id}")
            result = fetch_one_gpkg(
                client=client,
                record=record,
                output_dir=output_dir,
                environment=args.environment,
                source=args.source,
                overwrite=args.overwrite,
            )
            print(f"  {result.status}: {result.output_file}")
            results.append(result)
            if args.sleep > 0:
                time.sleep(args.sleep)

    write_manifest(args.manifest, results)
    print(f"Wrote manifest: {args.manifest}")
    if results:
        counts: dict[str, int] = {}
        for row in results:
            counts[row.status] = counts.get(row.status, 0) + 1
        print("Status counts:")
        for status, count in sorted(counts.items()):
            print(f"  {status}: {count}")


if __name__ == "__main__":
    main()
