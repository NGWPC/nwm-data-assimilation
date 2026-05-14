#!/usr/bin/env python3
"""
Fetch NHF gage GeoPackages from the Icefabric API for SWE reprocessing.

This script is intended for the Data Assimilation NHF SWE reprocessing story:
  1. Read a gage list, e.g. USGS_gages.txt from icefabric.
  2. Filter to domains with SNODAS coverage: CONUS, Alaska, Hawaii.
  3. Retrieve each gage GeoPackage from the Icefabric API with source=nhf.
  4. Write per-domain manifests so failures can be retried or documented.

Example:
    python -m data_assimilation_engine.swe.SNODAS_preprocessing.fetch_nhf_gage_gpkgs \
      --gage-list USGS_gages.txt \
      --output-dir /tmp/nhf_gpkgs \
      --environment oe \
      --domains CONUS Alaska Hawaii \
      --manifest nhf_gpkg_fetch_manifest.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional

import httpx

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

DOMAIN_TO_API = {
    "conus": "CONUS",
    "CONUS": "CONUS",
    "ak": "Alaska",
    "alaska": "Alaska",
    "Alaska": "Alaska",
    "hi": "Hawaii",
    "hawaii": "Hawaii",
    "Hawaii": "Hawaii",
    "prvi": "Puerto_Rico",
    "puerto_rico": "Puerto_Rico",
    "Puerto_Rico": "Puerto_Rico",
    "gl": "Great_Lakes",
    "great_lakes": "Great_Lakes",
    "Great_Lakes": "Great_Lakes",
}

SNODAS_DOMAINS_DEFAULT = {"CONUS", "Alaska", "Hawaii"}


@dataclass
class GageRecord:
    gage_id: str
    domain: str
    agency: str = ""
    enabled: str = ""


@dataclass
class FetchResult:
    gage_id: str
    domain: str
    status: str
    output_file: str
    url: str
    note: str = ""


def normalize_domain(domain: str) -> str:
    value = DOMAIN_TO_API.get(str(domain).strip())
    if value is None:
        raise ValueError(f"Unsupported domain '{domain}'. Known domains: {sorted(DOMAIN_TO_API)}")
    return value


def read_gage_list(path: str | Path, domains: Optional[set[str]] = None) -> List[GageRecord]:
    """Read an icefabric-style gage list.

    Expected rows can be tab- or whitespace-separated, usually like:
        01021480    CONUS    USGS    true

    Lines starting with '#' and blank lines are skipped.
    """
    records: List[GageRecord] = []
    with open(path, "r", encoding="utf-8") as fp:
        for line_no, raw_line in enumerate(fp, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.replace(",", " ").split()
            if len(parts) < 2:
                raise ValueError(f"Invalid gage-list row {line_no}: {raw_line!r}")
            gage_id = parts[0].strip()
            domain = normalize_domain(parts[1].strip())
            agency = parts[2].strip() if len(parts) > 2 else ""
            enabled = parts[3].strip() if len(parts) > 3 else ""
            if domains and domain not in domains:
                continue
            records.append(GageRecord(gage_id=gage_id, domain=domain, agency=agency, enabled=enabled))
    return records


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
    timeout_note: str = "",
    overwrite: bool = False,
    layers: Optional[list[str]] = None,
) -> FetchResult:
    layers = layers or DEFAULT_LAYERS
    domain_dir = output_dir / record.domain
    domain_dir.mkdir(parents=True, exist_ok=True)

    # Icefabric/MSWM convention is gauge_<gage>.gpkg.  The SWE processor accepts both gauge_ and gages-.
    output_file = domain_dir / f"gauge_{record.gage_id}.gpkg"
    url = f"{icefabric_base_url(environment)}/{record.gage_id}/gpkg"

    if output_file.exists() and not overwrite and output_file.stat().st_size > 0:
        return FetchResult(
            gage_id=record.gage_id,
            domain=record.domain,
            status="exists",
            output_file=str(output_file),
            url=url,
            note="file already exists; use --overwrite to replace",
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
                record.domain,
                "empty_response",
                str(output_file),
                str(response.url),
                f"response size={len(content) if content else 0} bytes {timeout_note}",
            )
        output_file.write_bytes(content)
        return FetchResult(record.gage_id, record.domain, "downloaded", str(output_file), str(response.url), "")
    except httpx.TimeoutException as exc:
        return FetchResult(record.gage_id, record.domain, "timeout", str(output_file), url, str(exc))
    except httpx.HTTPStatusError as exc:
        return FetchResult(record.gage_id, record.domain, f"http_{exc.response.status_code}", str(output_file), str(exc.request.url), str(exc))
    except Exception as exc:  # noqa: BLE001 - manifest should capture all unexpected failures
        return FetchResult(record.gage_id, record.domain, "failed", str(output_file), url, repr(exc))


def write_manifest(path: str | Path, rows: Iterable[FetchResult]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True) if path.parent != Path(".") else None
    rows = list(rows)
    with open(path, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(asdict(rows[0]).keys()) if rows else ["gage_id", "domain", "status", "output_file", "url", "note"])
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch NHF gage GeoPackages from Icefabric API.")
    parser.add_argument("--gage-list", required=True, help="Path to USGS_gages.txt or equivalent whitespace-separated gage list.")
    parser.add_argument("--output-dir", required=True, help="Directory to write downloaded geopackages. Files are grouped by domain.")
    parser.add_argument("--environment", choices=["test", "oe"], default="oe", help="Icefabric API environment.")
    parser.add_argument("--source", choices=["hf", "nhf"], default="nhf", help="Hydrofabric source/version to request.")
    parser.add_argument("--domains", nargs="+", default=["CONUS", "Alaska", "Hawaii"], help="Domains to process. Default: CONUS Alaska Hawaii.")
    parser.add_argument("--manifest", default="nhf_gpkg_fetch_manifest.csv", help="CSV manifest output path.")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout seconds per request.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Optional sleep seconds between API calls.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of gages for testing.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing geopackages.")
    args = parser.parse_args()

    domains = {normalize_domain(d) for d in args.domains}
    # Keep the default story scope constrained to SNODAS-supported domains unless caller explicitly changes --domains.
    invalid_for_story = domains - SNODAS_DOMAINS_DEFAULT
    if invalid_for_story:
        print(f"WARNING: requested domains outside default SNODAS NHF story scope: {sorted(invalid_for_story)}")

    records = read_gage_list(args.gage_list, domains=domains)
    if args.limit is not None:
        records = records[: args.limit]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: List[FetchResult] = []
    with httpx.Client(timeout=args.timeout) as client:
        for i, record in enumerate(records, start=1):
            print(f"[{i}/{len(records)}] fetching {record.domain} gage {record.gage_id}")
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
        counts = {}
        for result in results:
            counts[result.status] = counts.get(result.status, 0) + 1
        print("Status counts:")
        for status, count in sorted(counts.items()):
            print(f"  {status}: {count}")


if __name__ == "__main__":
    main()
