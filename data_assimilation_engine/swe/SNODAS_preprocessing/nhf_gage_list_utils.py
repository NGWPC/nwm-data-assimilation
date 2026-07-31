#!/usr/bin/env python3
"""Utilities for reading NHF gage lists from multiple providers.

Supported examples:
  USGS/ENVCA style:  01021480   CONUS   USGS   true
  TXDOT style:       08030530
  CADWR style:       MPD 20  E CONUS   CADWR  true

The parser intentionally treats the domain token as the boundary between the
identifier and provider metadata so provider IDs may contain spaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

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

API_DOMAIN_VALUES = set(DOMAIN_TO_API.values())


@dataclass(frozen=True)
class GageRecord:
    gage_id: str
    domain: str
    agency: str = ""
    enabled: str = ""
    source_file: str = ""
    raw_line: str = ""


def normalize_domain(domain: str) -> str:
    value = DOMAIN_TO_API.get(str(domain).strip())
    if value is None:
        raise ValueError(
            f"Unsupported domain '{domain}'. Known domains: {sorted(DOMAIN_TO_API)}"
        )
    return value


def safe_file_id(gage_id: str) -> str:
    """Return a filesystem-safe representation while keeping common IDs unchanged."""
    return "_".join(str(gage_id).strip().split())


def parse_gage_line(
    raw_line: str,
    *,
    default_domain: str = "CONUS",
    default_agency: str = "",
    source_file: str = "",
) -> Optional[GageRecord]:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None

    parts = line.replace(",", " ").split()
    if not parts:
        return None

    # Find the first domain token. Everything before it is the provider ID.
    domain_idx: Optional[int] = None
    for i, part in enumerate(parts):
        if part in DOMAIN_TO_API:
            domain_idx = i
            break

    if domain_idx is None:
        # One-column provider lists, e.g. TXDOT_gages.txt.
        gage_id = parts[0]
        domain = normalize_domain(default_domain)
        agency = default_agency
        enabled = ""
    else:
        if domain_idx == 0:
            raise ValueError(f"Invalid gage-list row; missing gage id: {raw_line!r}")
        domain = normalize_domain(parts[domain_idx])
        agency = parts[domain_idx + 1].strip() if len(parts) > domain_idx + 1 else default_agency
        enabled = parts[domain_idx + 2].strip() if len(parts) > domain_idx + 2 else ""

        # CADWR rows look like:
        #   MPD 20 E CONUS CADWR true
        # NHF/Icefabric gages layer stores the site_no as only the first token:
        #   MPD
        # The middle tokens are CADWR metadata, not part of the NHF gage_id.
        if agency.upper() == "CADWR":
            gage_id = parts[0].strip()
        else:
            gage_id = " ".join(parts[:domain_idx]).strip()

    if not gage_id:
        raise ValueError(f"Invalid gage-list row; empty gage id: {raw_line!r}")

    return GageRecord(
        gage_id=gage_id,
        domain=domain,
        agency=agency,
        enabled=enabled,
        source_file=str(source_file),
        raw_line=line,
    )


def read_gage_lists(
    paths: Iterable[str | Path],
    *,
    domains: Optional[set[str]] = None,
    default_domain: str = "CONUS",
    default_agency: str = "",
    enabled_only: bool = False,
    limit: Optional[int] = None,
) -> list[GageRecord]:
    normalized_domains = {normalize_domain(d) for d in domains} if domains else None
    records: list[GageRecord] = []
    seen: set[tuple[str, str, str]] = set()

    for path in paths:
        path = Path(path)
        inferred_agency = default_agency or path.stem.replace("_gages", "").upper()
        with open(path, "r", encoding="utf-8") as fp:
            for raw in fp:
                record = parse_gage_line(
                    raw,
                    default_domain=default_domain,
                    default_agency=inferred_agency,
                    source_file=str(path),
                )
                if record is None:
                    continue
                if normalized_domains and record.domain not in normalized_domains:
                    continue
                if enabled_only and record.enabled and record.enabled.lower() not in {"true", "1", "yes", "y"}:
                    continue

                key = (record.gage_id, record.domain, record.agency)
                if key in seen:
                    continue
                seen.add(key)
                records.append(record)
                if limit is not None and len(records) >= limit:
                    return records

    return records
