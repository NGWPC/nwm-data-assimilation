#!/usr/bin/env python3
"""Reconstruct t-route RFC reservoir forcing from public NWM routing output.

The generated values are RFC-controlled outflows retained in NWM output. They are
not an archive of the original NERFC PI XML forecasts.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib
import json
import logging
import os
import platform
import re
import subprocess
import sys
import tempfile
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib.metadata import PackageNotFoundError, version as package_version
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

import netCDF4
import numpy as np
import requests

UTC = timezone.utc
LOGGER = logging.getLogger("nerfc_reconstruction")
DEFAULT_BUCKET = "national-water-model"
DEFAULT_HTTPS_BASE = "https://storage.googleapis.com/national-water-model"
DEFAULT_API_BASE = "https://storage.googleapis.com/storage/v1"
SOURCE_CONFIGURATION = "medium_range"
SOURCE_LEADS = (1, 6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66)
CMS_TO_CFS = 35.3146667215
MAX_TROUTE_DISCHARGE_CMS = 90_000.0
FORCING_NAME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{2}\.60min\.[A-Z0-9]{5}\.RFCTimeSeries\.ncdf$"
)
TIME_FORMAT = "%Y-%m-%d_%H:%M:%S"


@dataclass(frozen=True)
class StationConfig:
    gage: str
    name: str
    reservoir_feature_id: int
    outlet_channel_feature_id: int
    rfc: str = "NERFC"


@dataclass
class NwmObjectMetadata:
    object_key: str
    product: str
    source_date: str
    initialization_time_utc: str
    lead: int
    expected_valid_time_utc: str
    size: int | None = None
    md5_hash: str | None = None
    updated: str | None = None
    generation: str | None = None
    cache_path: str | None = None
    status: str = "planned"
    checksum_status: str = "not_checked"
    error: str | None = None


@dataclass
class SourcePoint:
    nominal_issue_time_utc: datetime
    activation_time_utc: datetime
    event_time_utc: datetime
    model_valid_time_utc: datetime
    gage: str
    reservoir_feature_id: int
    outlet_channel_feature_id: int
    member: int
    lead: int
    channel_object_key: str
    reservoir_object_key: str
    reservoir_classification: str
    discharge_cms: float | None
    accepted: bool
    rejection_reason: str | None = None
    nwm_version_number: str | None = None

    def as_manifest(self) -> dict[str, Any]:
        result = asdict(self)
        for key in (
            "nominal_issue_time_utc",
            "activation_time_utc",
            "event_time_utc",
            "model_valid_time_utc",
        ):
            result[key] = format_utc(result[key])
        result["discharge_cfs_reference"] = (
            None if self.discharge_cms is None else self.discharge_cms * CMS_TO_CFS
        )
        result["source_configuration"] = SOURCE_CONFIGURATION
        return result


@dataclass
class IssueTrajectory:
    nominal_issue_time_utc: datetime
    activation_time_utc: datetime
    station: StationConfig
    points: dict[datetime, SourcePoint] = field(default_factory=dict)

    @property
    def is_strictly_valid(self) -> bool:
        return len(self.points) == len(SOURCE_LEADS) and all(
            point.accepted for point in self.points.values()
        )


@dataclass
class HourlyValueProvenance:
    output_time_utc: datetime
    array_index: int
    discharge_cms: float
    phase: str
    source_issue_time_utc: datetime | None
    source_event_time_utc: datetime | None
    source_object_key: str | None
    source_lead: int | None
    synthetic_flag: int
    method: str

    def as_manifest(self, filename: str, station: str) -> dict[str, Any]:
        return {
            "output_filename": filename,
            "station": station,
            "output_time_utc": format_utc(self.output_time_utc),
            "array_index": self.array_index,
            "discharge_cms": self.discharge_cms,
            "phase": self.phase,
            "source_issue_time_utc": optional_format_utc(self.source_issue_time_utc),
            "source_event_time_utc": optional_format_utc(self.source_event_time_utc),
            "source_object_key": self.source_object_key,
            "source_lead": self.source_lead,
            "synthetic_flag": self.synthetic_flag,
            "hold_fill_method": self.method,
            "quality_flag": None,
        }


@dataclass
class BuiltSeries:
    station: StationConfig
    issue_time_utc: datetime
    start_time_utc: datetime
    discharges_cms: np.ndarray
    synthetic_values: np.ndarray
    hourly_provenance: list[HourlyValueProvenance]
    query_time_utc: datetime
    source_member: int = 1
    nwm_versions: tuple[str, ...] = ()


@dataclass
class IssueStationResult:
    issue_time_utc: datetime
    gage: str
    status: str
    output_filename: str | None
    reason: str | None = None
    reused: bool = False

    def as_manifest(self) -> dict[str, Any]:
        result = asdict(self)
        result["issue_time_utc"] = format_utc(self.issue_time_utc)
        return result


@dataclass(frozen=True)
class ValidationFinding:
    path: str
    severity: str
    message: str


class ReconstructionError(RuntimeError):
    """Raised when production reconstruction cannot safely continue."""


def _safe_int(value: Any, context: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ReconstructionError(f"invalid integer for {context}: {value!r}") from exc


def _safe_float(value: Any, context: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ReconstructionError(f"invalid number for {context}: {value!r}") from exc


def _package_version(name: str) -> str:
    try:
        return package_version(name)
    except PackageNotFoundError:
        return "unknown"


def parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = datetime.strptime(text, TIME_FORMAT)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_nwm_time(value: Any) -> datetime:
    if isinstance(value, np.ndarray):
        value = value.item()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    text = str(value).strip().replace(" UTC", "Z")
    for pattern in (
        "%Y-%m-%d_%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d_%H:%M:%S+00:00",
    ):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=UTC)
        except ValueError:
            pass
    return parse_utc(text)


def format_utc(value: datetime) -> str:
    return parse_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def optional_format_utc(value: datetime | None) -> str | None:
    return None if value is None else format_utc(value)


def issue_datetime(issue_date: date) -> datetime:
    return datetime(issue_date.year, issue_date.month, issue_date.day, 12, tzinfo=UTC)


def activation_datetime(issue_date: date, activation_hour: int = 18) -> datetime:
    return datetime(
        issue_date.year, issue_date.month, issue_date.day, activation_hour, tzinfo=UTC
    )


def derive_required_output_issues(
    simulation_start: datetime,
    simulation_end: datetime,
    activation_hour: int = 18,
) -> list[datetime]:
    """Return nominal 12Z issues usable during a half-open simulation interval."""
    start = parse_utc(simulation_start)
    end = parse_utc(simulation_end)
    if end <= start:
        raise ValueError("simulation end must be later than simulation start")
    if not 0 <= activation_hour <= 23:
        raise ValueError("activation hour must be in [0, 23]")

    first_date = start.date()
    if start.hour < activation_hour:
        first_date -= timedelta(days=1)
    last_instant = end - timedelta(microseconds=1)
    last_date = last_instant.date()
    if last_instant.hour < activation_hour:
        last_date -= timedelta(days=1)

    return [
        issue_datetime(first_date + timedelta(days=offset))
        for offset in range((last_date - first_date).days + 1)
    ]


def derive_required_source_dates(output_issues: Sequence[datetime]) -> list[date]:
    if not output_issues:
        return []
    issue_dates = sorted(parse_utc(value).date() for value in output_issues)
    first = issue_dates[0] - timedelta(days=3)
    last = issue_dates[-1]
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def derive_chunk_schedule(
    simulation_start: datetime,
    simulation_end: datetime,
    activation_hour: int = 18,
) -> list[tuple[datetime, datetime, datetime]]:
    start = parse_utc(simulation_start)
    end = parse_utc(simulation_end)
    issues = derive_required_output_issues(start, end, activation_hour)
    chunks: list[tuple[datetime, datetime, datetime]] = []
    cursor = start
    while cursor < end:
        available = [
            issue for issue in issues if issue.replace(hour=activation_hour) <= cursor
        ]
        selected = max(available)
        next_activation = selected.replace(hour=activation_hour) + timedelta(days=1)
        chunk_end = min(end, next_activation)
        chunks.append((cursor, chunk_end, selected))
        cursor = chunk_end
    return chunks


def lead_to_event_time(issue_time: datetime, lead: int) -> datetime:
    issue = parse_utc(issue_time)
    if lead not in SOURCE_LEADS:
        raise ValueError(f"unsupported source lead f{lead:03d}")
    initialization = issue.replace(hour=18)
    return initialization if lead == 1 else initialization + timedelta(hours=lead)


def lead_to_model_valid_time(issue_time: datetime, lead: int) -> datetime:
    return parse_utc(issue_time).replace(hour=18) + timedelta(hours=lead)


def build_object_key(source_date: date, member: int, product: str, lead: int) -> str:
    if product not in {"channel", "reservoir"}:
        raise ValueError(f"unknown NWM product: {product}")
    if lead <= 0:
        raise ValueError("lead must be positive")
    product_name = "channel_rt" if product == "channel" else "reservoir"
    return (
        f"nwm.{source_date:%Y%m%d}/medium_range_mem{member}/"
        f"nwm.t18z.medium_range.{product_name}_{member}.f{lead:03d}.conus.nc"
    )


def output_filename(issue_time: datetime, gage: str) -> str:
    issue = parse_utc(issue_time)
    return f"{issue:%Y-%m-%d_%H}.60min.{gage}.RFCTimeSeries.ncdf"


def normalize_bucket(bucket: str) -> str:
    return bucket.removeprefix("gs://").strip("/")


def planned_objects(
    source_dates: Sequence[date], member: int
) -> list[NwmObjectMetadata]:
    records: list[NwmObjectMetadata] = []
    for source_date in source_dates:
        nominal_issue = issue_datetime(source_date)
        for lead in SOURCE_LEADS:
            for product in ("channel", "reservoir"):
                records.append(
                    NwmObjectMetadata(
                        object_key=build_object_key(source_date, member, product, lead),
                        product=product,
                        source_date=source_date.isoformat(),
                        initialization_time_utc=format_utc(
                            nominal_issue.replace(hour=18)
                        ),
                        lead=lead,
                        expected_valid_time_utc=format_utc(
                            lead_to_model_valid_time(nominal_issue, lead)
                        ),
                    )
                )
    return records


def _metadata_url(api_base: str, bucket: str, object_key: str) -> str:
    encoded_key = quote(object_key, safe="")
    return f"{api_base.rstrip('/')}/b/{quote(normalize_bucket(bucket), safe='')}/o/{encoded_key}"


def fetch_object_metadata(
    record: NwmObjectMetadata,
    bucket: str = DEFAULT_BUCKET,
    api_base: str = DEFAULT_API_BASE,
    timeout: float = 30.0,
) -> NwmObjectMetadata:
    try:
        response = requests.get(
            _metadata_url(api_base, bucket, record.object_key), timeout=timeout
        )
        if response.status_code == 404:
            record.status = "missing"
            record.error = "object not found"
            return record
        response.raise_for_status()
        payload = response.json()
        record.size = int(payload["size"])
        record.md5_hash = payload.get("md5Hash")
        record.updated = payload.get("updated")
        record.generation = payload.get("generation")
        record.status = "available"
    except (requests.RequestException, KeyError, ValueError) as exc:
        record.status = "metadata_error"
        record.error = str(exc)
    return record


def list_object_metadata(
    prefix: str,
    bucket: str = DEFAULT_BUCKET,
    api_base: str = DEFAULT_API_BASE,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """List all public GCS metadata records beneath a prefix."""
    records: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params = {"prefix": prefix}
        if page_token:
            params["pageToken"] = page_token
        url = f"{api_base.rstrip('/')}/b/{quote(normalize_bucket(bucket), safe='')}/o"
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        records.extend(payload.get("items", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return records


def inventory_objects(
    records: Sequence[NwmObjectMetadata],
    bucket: str,
    api_base: str,
    max_workers: int,
) -> list[NwmObjectMetadata]:
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fetch_object_metadata, item, bucket, api_base): item
            for item in records
        }
        completed: list[NwmObjectMetadata] = []
        for future in as_completed(futures):
            item = future.result()
            completed.append(item)
            if item.status != "available":
                LOGGER.error("inventory %s: %s", item.object_key, item.error)
    return sorted(completed, key=lambda item: item.object_key)


def cache_path_for(cache_dir: Path, object_key: str) -> Path:
    relative = Path(object_key)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe object key: {object_key}")
    return cache_dir / relative


def file_md5_base64(path: Path, block_size: int = 1024 * 1024) -> str:
    # GCS exposes an MD5 checksum; this is an integrity check, not a security use.
    digest = hashlib.new("md5", usedforsecurity=False)
    with path.open("rb") as stream:
        while block := stream.read(block_size):
            digest.update(block)
    return base64.b64encode(digest.digest()).decode("ascii")


def verify_cached_object(path: Path, metadata: NwmObjectMetadata) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    if metadata.size is not None and path.stat().st_size != metadata.size:
        return False, "size_mismatch"
    if metadata.md5_hash and file_md5_base64(path) != metadata.md5_hash:
        return False, "md5_mismatch"
    return True, "verified"


def download_with_cache(
    metadata: NwmObjectMetadata,
    cache_dir: Path,
    https_base_url: str = DEFAULT_HTTPS_BASE,
    overwrite: bool = False,
    resume: bool = True,
    timeout: float = 120.0,
) -> NwmObjectMetadata:
    target = cache_path_for(cache_dir, metadata.object_key)
    metadata.cache_path = str(target)
    if not overwrite:
        valid, status = verify_cached_object(target, metadata)
        if valid:
            metadata.status = "cached"
            metadata.checksum_status = status
            return metadata

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    headers: dict[str, str] = {}
    mode = "wb"
    if resume and partial.exists() and partial.stat().st_size:
        headers["Range"] = f"bytes={partial.stat().st_size}-"
        mode = "ab"
    url = f"{https_base_url.rstrip('/')}/{quote(metadata.object_key, safe='/')}"
    try:
        with requests.get(
            url, headers=headers, stream=True, timeout=timeout
        ) as response:
            if response.status_code == 416:
                partial.replace(target)
            else:
                response.raise_for_status()
                if mode == "ab" and response.status_code != 206:
                    mode = "wb"
                with partial.open(mode) as stream:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            stream.write(chunk)
                partial.replace(target)
        valid, status = verify_cached_object(target, metadata)
        metadata.checksum_status = status
        if not valid:
            target.unlink(missing_ok=True)
            raise ReconstructionError(
                f"download verification failed ({status}): {metadata.object_key}"
            )
        metadata.status = "downloaded"
    except (OSError, requests.RequestException) as exc:
        metadata.status = "download_error"
        metadata.error = str(exc)
    return metadata


def download_objects(
    records: Sequence[NwmObjectMetadata],
    cache_dir: Path,
    https_base_url: str,
    overwrite: bool,
    resume: bool,
    max_workers: int,
) -> list[NwmObjectMetadata]:
    available = [
        record
        for record in records
        if record.status in {"available", "cached", "downloaded"}
    ]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                download_with_cache,
                record,
                cache_dir,
                https_base_url,
                overwrite,
                resume,
            ): record
            for record in available
        }
        completed: list[NwmObjectMetadata] = []
        for future in as_completed(futures):
            record = future.result()
            completed.append(record)
            if record.status == "download_error":
                LOGGER.error("download %s: %s", record.object_key, record.error)
    unavailable = [record for record in records if record not in available]
    return sorted(completed + unavailable, key=lambda item: item.object_key)


def load_station_config(path: Path) -> dict[str, StationConfig]:
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconstructionError(f"cannot load station config {path}: {exc}") from exc
    stations: dict[str, StationConfig] = {}
    for gage, values in payload.items():
        if not re.fullmatch(r"[A-Z0-9]{5}", gage):
            raise ReconstructionError(f"invalid five-character RFC gage: {gage}")
        stations[gage] = StationConfig(gage=gage, **values)
    if not stations:
        raise ReconstructionError("station configuration is empty")
    return stations


def crosscheck_station_config(
    stations: Mapping[str, StationConfig], crosswalk_path: Path
) -> None:
    with crosswalk_path.open(newline="", encoding="utf-8-sig") as stream:
        rows = {row["gage"]: row for row in csv.DictReader(stream)}
    errors: list[str] = []
    for gage, station in stations.items():
        row = rows.get(gage)
        if row is None:
            errors.append(f"{gage}: absent from {crosswalk_path}")
            continue
        outlet = _safe_int(row["lakeLink"], f"{gage} lakeLink")
        if outlet == 0:
            outlet = _safe_int(row["gagedFlowline"], f"{gage} gagedFlowline")
        expected = (
            _safe_int(row["NHDWaterbodyComID"], f"{gage} NHDWaterbodyComID"),
            outlet,
            row["RFC"],
        )
        actual = (
            station.reservoir_feature_id,
            station.outlet_channel_feature_id,
            station.rfc,
        )
        if actual != expected:
            errors.append(f"{gage}: config {actual!r} != crosswalk {expected!r}")
    if errors:
        raise ReconstructionError(
            "station crosswalk disagreement: " + "; ".join(errors)
        )


class FeatureIndexStore:
    """Persist and verify the stable requested-feature indices for NWM products."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {}
        if path.is_file():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                LOGGER.warning("ignoring unreadable feature index cache %s", path)

    def indices(
        self, dataset: netCDF4.Dataset, product: str, requested_ids: Iterable[int]
    ) -> tuple[dict[int, int], set[int]]:
        variable = dataset.variables.get("feature_id")
        if variable is None:
            raise ReconstructionError(f"{dataset.filepath()}: missing feature_id")
        requested = {
            _safe_int(value, f"{product} requested feature ID")
            for value in requested_ids
        }
        cached = self.data.get(product, {})
        cached_indices = {
            _safe_int(key, f"{product} cached feature ID"): _safe_int(
                value, f"{product} cached feature index"
            )
            for key, value in cached.get("indices", {}).items()
        }
        if cached.get("feature_count") == variable.size and requested <= set(
            cached_indices
        ):
            if all(
                _safe_int(
                    variable[cached_indices[value]],
                    f"{product} feature ID at cached index",
                )
                == value
                for value in requested
            ):
                return {value: cached_indices[value] for value in requested}, set()

        feature_ids = np.asarray(variable[:], dtype=np.int64).reshape(-1)
        selected = np.flatnonzero(np.isin(feature_ids, list(requested)))
        found = {
            _safe_int(feature_ids[index], f"{product} feature ID"): _safe_int(
                index, f"{product} feature index"
            )
            for index in selected
        }
        missing = requested - set(found)
        self.data[product] = {
            "feature_count": _safe_int(feature_ids.size, f"{product} feature count"),
            "indices": {str(key): value for key, value in found.items()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(self.path, json.dumps(self.data, indent=2, sort_keys=True))
        return found, missing


def _masked_scalar(variable: Any, index: int) -> tuple[float | int | None, bool]:
    value = np.ma.asarray(variable[index]).squeeze()
    if value.size != 1:
        raise ReconstructionError(
            f"expected one value from {variable.name}, got shape {value.shape}"
        )
    if np.ma.is_masked(value):
        return None, True
    scalar = value.item()
    try:
        finite = bool(np.isfinite(scalar))
    except TypeError:
        finite = False
    return (scalar if finite else None), not finite


def classify_reservoir_status(
    dataset: netCDF4.Dataset, reservoir_id: int, index: int | None = None
) -> str:
    if index is None:
        ids = np.asarray(dataset.variables["feature_id"][:], dtype=np.int64)
        locations = np.flatnonzero(ids == reservoir_id)
        if not locations.size:
            return "missing_reservoir"
        index = _safe_int(locations[0], "reservoir feature index")
    required = ("reservoir_type", "reservoir_assimilated_value", "outflow")
    if any(name not in dataset.variables for name in required):
        return "missing_value"
    type_value, type_masked = _masked_scalar(dataset.variables["reservoir_type"], index)
    _, assimilated_masked = _masked_scalar(
        dataset.variables["reservoir_assimilated_value"], index
    )
    _, outflow_masked = _masked_scalar(dataset.variables["outflow"], index)
    if type_masked and assimilated_masked and outflow_masked:
        return "rfc_active"
    if not type_masked and _safe_int(type_value, "reservoir_type") == 1:
        return "fallback_levelpool"
    if not type_masked:
        return "unexpected_reservoir_type"
    return "missing_value"


def extract_outlet_streamflow(
    dataset: netCDF4.Dataset, outlet_id: int, index: int | None = None
) -> tuple[float | None, str | None]:
    if index is None:
        ids = np.asarray(dataset.variables["feature_id"][:], dtype=np.int64)
        locations = np.flatnonzero(ids == outlet_id)
        if not locations.size:
            return None, "missing_outlet"
        index = _safe_int(locations[0], "outlet feature index")
    streamflow = dataset.variables.get("streamflow")
    if streamflow is None:
        return None, "missing_value"
    value, masked = _masked_scalar(streamflow, index)
    if masked or value is None:
        return None, "missing_value"
    discharge = _safe_float(value, "streamflow")
    if discharge < 0 or discharge >= MAX_TROUTE_DISCHARGE_CMS:
        return discharge, "invalid_value"
    return discharge, None


def _dataset_attr(dataset: netCDF4.Dataset, name: str) -> Any:
    if name not in dataset.ncattrs():
        raise ReconstructionError(
            f"{dataset.filepath()}: missing global attribute {name}"
        )
    return dataset.getncattr(name)


def validate_source_dataset_metadata(
    dataset: netCDF4.Dataset,
    issue_time: datetime,
    lead: int,
    product: str,
) -> str:
    expected_init = parse_utc(issue_time).replace(hour=18)
    expected_valid = lead_to_model_valid_time(issue_time, lead)
    actual_init = parse_nwm_time(_dataset_attr(dataset, "model_initialization_time"))
    actual_valid = parse_nwm_time(_dataset_attr(dataset, "model_output_valid_time"))
    if actual_init != expected_init:
        raise ReconstructionError(
            f"{dataset.filepath()}: initialization {actual_init} != {expected_init}"
        )
    if actual_valid != expected_valid:
        raise ReconstructionError(
            f"{dataset.filepath()}: valid time {actual_valid} != {expected_valid}"
        )
    configuration = str(_dataset_attr(dataset, "model_configuration")).lower()
    if SOURCE_CONFIGURATION not in configuration:
        raise ReconstructionError(
            f"{dataset.filepath()}: unexpected model_configuration {configuration!r}"
        )
    output_type = str(_dataset_attr(dataset, "model_output_type")).lower()
    expected_token = "channel" if product == "channel" else "reservoir"
    if expected_token not in output_type:
        raise ReconstructionError(
            f"{dataset.filepath()}: unexpected model_output_type {output_type!r}"
        )
    version = str(_dataset_attr(dataset, "NWM_version_number"))
    return version


def _missing_source_points(
    issue_time: datetime,
    lead: int,
    stations: Mapping[str, StationConfig],
    member: int,
    channel_key: str,
    reservoir_key: str,
    reason: str,
) -> list[SourcePoint]:
    return [
        SourcePoint(
            nominal_issue_time_utc=issue_time,
            activation_time_utc=issue_time.replace(hour=18),
            event_time_utc=lead_to_event_time(issue_time, lead),
            model_valid_time_utc=lead_to_model_valid_time(issue_time, lead),
            gage=station.gage,
            reservoir_feature_id=station.reservoir_feature_id,
            outlet_channel_feature_id=station.outlet_channel_feature_id,
            member=member,
            lead=lead,
            channel_object_key=channel_key,
            reservoir_object_key=reservoir_key,
            reservoir_classification=reason,
            discharge_cms=None,
            accepted=False,
            rejection_reason=reason,
        )
        for station in stations.values()
    ]


def extract_source_points(
    issue_time: datetime,
    lead: int,
    stations: Mapping[str, StationConfig],
    member: int,
    cache_dir: Path,
    index_store: FeatureIndexStore,
) -> list[SourcePoint]:
    source_date = parse_utc(issue_time).date()
    channel_key = build_object_key(source_date, member, "channel", lead)
    reservoir_key = build_object_key(source_date, member, "reservoir", lead)
    channel_path = cache_path_for(cache_dir, channel_key)
    reservoir_path = cache_path_for(cache_dir, reservoir_key)
    if not channel_path.is_file() or not reservoir_path.is_file():
        missing = (
            "missing_outlet" if not channel_path.is_file() else "missing_reservoir"
        )
        return _missing_source_points(
            issue_time,
            lead,
            stations,
            member,
            channel_key,
            reservoir_key,
            missing,
        )

    try:
        with (
            netCDF4.Dataset(channel_path) as channel,
            netCDF4.Dataset(reservoir_path) as reservoir,
        ):
            channel.set_auto_maskandscale(True)
            reservoir.set_auto_maskandscale(True)
            channel_version = validate_source_dataset_metadata(
                channel, issue_time, lead, "channel"
            )
            reservoir_version = validate_source_dataset_metadata(
                reservoir, issue_time, lead, "reservoir"
            )
            version = channel_version
            if channel_version != reservoir_version:
                raise ReconstructionError(
                    f"NWM version mismatch: {channel_key}={channel_version}, "
                    f"{reservoir_key}={reservoir_version}"
                )
            channel_indices, missing_channels = index_store.indices(
                channel,
                "channel",
                (station.outlet_channel_feature_id for station in stations.values()),
            )
            reservoir_indices, missing_reservoirs = index_store.indices(
                reservoir,
                "reservoir",
                (station.reservoir_feature_id for station in stations.values()),
            )
            points: list[SourcePoint] = []
            for station in stations.values():
                if station.reservoir_feature_id in missing_reservoirs:
                    classification = "missing_reservoir"
                else:
                    classification = classify_reservoir_status(
                        reservoir,
                        station.reservoir_feature_id,
                        reservoir_indices[station.reservoir_feature_id],
                    )
                if station.outlet_channel_feature_id in missing_channels:
                    discharge, flow_error = None, "missing_outlet"
                else:
                    discharge, flow_error = extract_outlet_streamflow(
                        channel,
                        station.outlet_channel_feature_id,
                        channel_indices[station.outlet_channel_feature_id],
                    )
                accepted = classification == "rfc_active" and flow_error is None
                rejection = None if accepted else flow_error or classification
                points.append(
                    SourcePoint(
                        nominal_issue_time_utc=parse_utc(issue_time),
                        activation_time_utc=parse_utc(issue_time).replace(hour=18),
                        event_time_utc=lead_to_event_time(issue_time, lead),
                        model_valid_time_utc=lead_to_model_valid_time(issue_time, lead),
                        gage=station.gage,
                        reservoir_feature_id=station.reservoir_feature_id,
                        outlet_channel_feature_id=station.outlet_channel_feature_id,
                        member=member,
                        lead=lead,
                        channel_object_key=channel_key,
                        reservoir_object_key=reservoir_key,
                        reservoir_classification=classification,
                        discharge_cms=discharge,
                        accepted=accepted,
                        rejection_reason=rejection,
                        nwm_version_number=version,
                    )
                )
            return points
    except (OSError, RuntimeError, ReconstructionError) as exc:
        LOGGER.error(
            "extract issue=%s lead=f%03d: %s", format_utc(issue_time), lead, exc
        )
        return _missing_source_points(
            issue_time,
            lead,
            stations,
            member,
            channel_key,
            reservoir_key,
            "missing_value",
        )


def extract_issue_trajectories(
    source_dates: Sequence[date],
    stations: Mapping[str, StationConfig],
    member: int,
    cache_dir: Path,
) -> tuple[dict[tuple[datetime, str], IssueTrajectory], list[SourcePoint]]:
    index_store = FeatureIndexStore(cache_dir / "feature_indices.json")
    trajectories: dict[tuple[datetime, str], IssueTrajectory] = {}
    all_points: list[SourcePoint] = []
    for source_date in source_dates:
        issue = issue_datetime(source_date)
        for station in stations.values():
            trajectories[(issue, station.gage)] = IssueTrajectory(
                nominal_issue_time_utc=issue,
                activation_time_utc=issue.replace(hour=18),
                station=station,
            )
        for lead in SOURCE_LEADS:
            points = extract_source_points(
                issue, lead, stations, member, cache_dir, index_store
            )
            all_points.extend(points)
            for point in points:
                trajectories[(issue, point.gage)].points[point.event_time_utc] = point
    return trajectories, all_points


def expand_six_hour_knots_to_hourly(
    trajectory: IssueTrajectory,
) -> dict[datetime, tuple[SourcePoint, bool]]:
    """Expand accepted knots by preceding-value hold through the final knot."""
    accepted = sorted(
        (time, point) for time, point in trajectory.points.items() if point.accepted
    )
    if not accepted:
        return {}
    start = trajectory.activation_time_utc
    end = max(trajectory.points) if trajectory.points else accepted[-1][0]
    result: dict[datetime, tuple[SourcePoint, bool]] = {}
    point_index = 0
    current: SourcePoint | None = None
    cursor = start
    while cursor <= end:
        while point_index < len(accepted) and accepted[point_index][0] <= cursor:
            current = accepted[point_index][1]
            point_index += 1
        if current is not None:
            result[cursor] = (current, cursor == current.event_time_utc)
        cursor += timedelta(hours=1)
    return result


def _select_reconstructed_value(
    valid_time: datetime,
    station: StationConfig,
    trajectories: Mapping[tuple[datetime, str], IssueTrajectory],
    excluded_issue: datetime | None = None,
) -> tuple[SourcePoint, bool] | None:
    candidates = sorted(
        (
            trajectory
            for (issue, gage), trajectory in trajectories.items()
            if gage == station.gage
            and trajectory.activation_time_utc <= valid_time
            and (excluded_issue is None or issue != excluded_issue)
        ),
        key=lambda item: item.activation_time_utc,
        reverse=True,
    )
    for trajectory in candidates:
        expanded = expand_six_hour_knots_to_hourly(trajectory)
        selected = expanded.get(valid_time)
        if selected is not None:
            return selected
    return None


def _nearest_preceding_reconstructed_point(
    valid_time: datetime,
    station: StationConfig,
    trajectories: Mapping[tuple[datetime, str], IssueTrajectory],
    excluded_issue: datetime | None = None,
) -> SourcePoint | None:
    candidates = [
        point
        for (issue, gage), trajectory in trajectories.items()
        if gage == station.gage
        and trajectory.activation_time_utc <= valid_time
        and (excluded_issue is None or issue != excluded_issue)
        for point in trajectory.points.values()
        if point.accepted
        and point.discharge_cms is not None
        and point.event_time_utc <= valid_time
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda point: (point.event_time_utc, point.activation_time_utc),
    )


def stitch_pre_issue_support(
    issue_time: datetime,
    station: StationConfig,
    trajectories: Mapping[tuple[datetime, str], IssueTrajectory],
) -> list[tuple[datetime, SourcePoint, bool, bool]]:
    issue = parse_utc(issue_time)
    cursor = issue - timedelta(hours=48)
    end = issue.replace(hour=18) - timedelta(hours=1)
    stitched: list[tuple[datetime, SourcePoint, bool, bool]] = []
    last_point: SourcePoint | None = None
    while cursor <= end:
        selected = _select_reconstructed_value(
            cursor, station, trajectories, excluded_issue=issue
        )
        if selected is None:
            if last_point is None:
                last_point = _nearest_preceding_reconstructed_point(
                    cursor, station, trajectories, excluded_issue=issue
                )
            if last_point is None:
                raise ReconstructionError(
                    f"{station.gage} {format_utc(issue)} has no preceding value at "
                    f"{format_utc(cursor)}"
                )
            stitched.append((cursor, last_point, False, True))
        else:
            last_point, direct = selected
            stitched.append((cursor, last_point, direct, False))
        cursor += timedelta(hours=1)
    return stitched


def build_rfc_timeseries(
    issue_time: datetime,
    station: StationConfig,
    trajectories: Mapping[tuple[datetime, str], IssueTrajectory],
    query_time: datetime | None = None,
    diagnostic_fill: bool = False,
) -> BuiltSeries:
    issue = parse_utc(issue_time)
    trajectory = trajectories.get((issue, station.gage))
    if trajectory is None:
        raise ReconstructionError(
            f"missing current trajectory for {station.gage} {issue}"
        )
    if not trajectory.is_strictly_valid and not diagnostic_fill:
        rejected = [
            f"f{point.lead:03d}:{point.rejection_reason}"
            for point in trajectory.points.values()
            if not point.accepted
        ]
        raise ReconstructionError("current forecast rejected: " + ", ".join(rejected))

    start = issue - timedelta(hours=48)
    end = issue + timedelta(days=10)
    final_knot_time = issue + timedelta(days=3)
    pre_issue = {
        time: (point, direct, gap_filled)
        for time, point, direct, gap_filled in stitch_pre_issue_support(
            issue, station, trajectories
        )
    }
    current_expanded = expand_six_hour_knots_to_hourly(trajectory)
    discharges: list[float] = []
    synthetic: list[int] = []
    provenance: list[HourlyValueProvenance] = []
    last_point: SourcePoint | None = None
    last_value: float | None = None
    cursor = start
    index = 0
    while cursor <= end:
        phase = "pre_issue" if cursor < issue else "current_forecast"
        selected: tuple[SourcePoint, bool] | None
        method: str
        if cursor < trajectory.activation_time_utc:
            pre_selected = pre_issue.get(cursor)
            selected = (
                None if pre_selected is None else (pre_selected[0], pre_selected[1])
            )
            if pre_selected and pre_selected[2]:
                method = "preceding_value_gap_fill"
            else:
                method = "direct_knot" if selected and selected[1] else "forward_hold"
        elif cursor <= final_knot_time:
            selected = current_expanded.get(cursor)
            if selected is None and diagnostic_fill:
                selected = _select_reconstructed_value(
                    cursor, station, trajectories, excluded_issue=issue
                )
                method = "diagnostic_prior_issue_fill"
            else:
                method = "direct_knot" if selected and selected[1] else "forward_hold"
        else:
            selected = None
            phase = "post_horizon_persistence"
            method = "final_value_persistence"

        if selected is not None:
            point, direct = selected
            if point.discharge_cms is None or point.discharge_cms < 0:
                raise ReconstructionError(
                    f"invalid selected value for {station.gage} at {format_utc(cursor)}"
                )
            last_point = point
            last_value = _safe_float(point.discharge_cms, "selected discharge")
            flag = 0 if direct and method == "direct_knot" else 1
        elif last_value is not None and cursor > final_knot_time:
            point = last_point
            flag = 1
        else:
            raise ReconstructionError(
                f"no reconstructed value for {station.gage} at {format_utc(cursor)}"
            )
        discharges.append(last_value)
        synthetic.append(flag)
        provenance.append(
            HourlyValueProvenance(
                output_time_utc=cursor,
                array_index=index,
                discharge_cms=last_value,
                phase=phase,
                source_issue_time_utc=(
                    None if last_point is None else last_point.nominal_issue_time_utc
                ),
                source_event_time_utc=(
                    None if last_point is None else last_point.event_time_utc
                ),
                source_object_key=(
                    None if last_point is None else last_point.channel_object_key
                ),
                source_lead=None if last_point is None else last_point.lead,
                synthetic_flag=flag,
                method=method,
            )
        )
        cursor += timedelta(hours=1)
        index += 1

    values = np.asarray(discharges, dtype=np.float64)
    flags = np.asarray(synthetic, dtype=np.int8)
    if values.size != 289 or flags.size != 289:
        raise ReconstructionError(
            f"internal series length is {values.size}, expected 289"
        )
    if (
        np.any(~np.isfinite(values))
        or np.any(values < 0)
        or np.any(values >= MAX_TROUTE_DISCHARGE_CMS)
    ):
        raise ReconstructionError(
            "constructed series violates t-route discharge bounds"
        )
    if np.all(flags == 1):
        raise ReconstructionError("constructed series is entirely synthetic")
    versions = tuple(
        sorted(
            {
                point.nwm_version_number
                for point in trajectory.points.values()
                if point.nwm_version_number
            }
        )
    )
    return BuiltSeries(
        station=station,
        issue_time_utc=issue,
        start_time_utc=start,
        discharges_cms=values,
        synthetic_values=flags,
        hourly_provenance=provenance,
        query_time_utc=parse_utc(query_time or datetime.now(UTC)),
        source_member=next(iter(trajectory.points.values())).member,
        nwm_versions=versions,
    )


def write_rfc_netcdf(
    series: BuiltSeries,
    output_path: Path,
    reconstruction_version: str = "unknown",
    source_bucket: str = f"gs://{DEFAULT_BUCKET}",
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=output_path.name + ".",
        suffix=".part",
        dir=output_path.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with netCDF4.Dataset(temporary_path, "w", format="NETCDF4") as dataset:
            dataset.createDimension("stationIdStrLen", 5)
            dataset.createDimension("timeStrLen", 19)
            dataset.createDimension("forecastInd", None)
            dataset.createDimension("nseries", 1)
            dataset.createDimension("zero", 0)

            station_id = dataset.createVariable("stationId", "S1", ("stationIdStrLen",))
            issue_time = dataset.createVariable(
                "issueTimeUTC", "S1", ("nseries", "timeStrLen")
            )
            discharges = dataset.createVariable(
                "discharges", "f4", ("nseries", "forecastInd")
            )
            synthetics = dataset.createVariable(
                "synthetic_values", "i1", ("nseries", "forecastInd")
            )
            total_counts = dataset.createVariable("totalCounts", "i2", ("nseries",))
            observed_counts = dataset.createVariable(
                "observedCounts", "i2", ("nseries",)
            )
            forecast_counts = dataset.createVariable(
                "forecastCounts", "i2", ("nseries",)
            )
            time_steps = dataset.createVariable("timeSteps", "i4", ("nseries",))
            qualities = dataset.createVariable(
                "discharge_qualities", "i2", ("nseries",)
            )
            query_time = dataset.createVariable("queryTime", "i8", ("nseries",))

            station_id.setncatts({"long_name": "Station Id", "units": "-"})
            issue_time.setncatts({"long_name": "Issue time", "unts": "UTC"})
            discharges.setncatts(
                {"long_name": "Reservoir discharge", "units": "m3 s-1"}
            )
            synthetics.setncatts(
                {"long_name": "Synthetic value indicator", "units": "-"}
            )
            qualities.setncatts(
                {
                    "long_name": "Discharge quality",
                    "units": "percent",
                    "multfactor": "0.01",
                }
            )
            query_time.setncatts({"units": "seconds since 1970-01-01 00:00:00 UTC"})

            dataset.setncatts(
                {
                    "fileUpdateTimeUTC": series.query_time_utc.strftime(TIME_FORMAT),
                    "sliceStartTimeUTC": series.start_time_utc.strftime(TIME_FORMAT),
                    "sliceTimeResolutionMinutes": "60",
                    "missingValue": "-999",
                    "newest_forecast": "0",
                    "NWM_version_number": "v3.0",
                    "source_NWM_version_numbers": ",".join(series.nwm_versions),
                    "reconstructed": "true",
                    "reconstruction_method": (
                        f"NWM medium_range_mem{series.source_member} outlet streamflow"
                    ),
                    "reconstruction_version": reconstruction_version,
                    "source_bucket": source_bucket,
                    "nominal_issue_time_utc": format_utc(series.issue_time_utc),
                    "assumed_activation_time_utc": format_utc(
                        series.issue_time_utc.replace(hour=18)
                    ),
                }
            )
            station_id[:] = np.frombuffer(
                series.station.gage.encode("ascii"), dtype="S1"
            )
            issue_bytes = series.issue_time_utc.strftime(TIME_FORMAT).encode("ascii")
            issue_time[0, :] = np.frombuffer(issue_bytes, dtype="S1")
            discharges[0, :] = series.discharges_cms.astype(np.float32)
            synthetics[0, :] = series.synthetic_values
            total_counts[:] = [289]
            observed_counts[:] = [48]
            forecast_counts[:] = [241]
            time_steps[:] = [3600]
            qualities[:] = [100]
            query_time[:] = [int(series.query_time_utc.timestamp())]
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _decode_chars(variable: Any) -> str:
    decoded = netCDF4.chartostring(variable[:])
    if isinstance(decoded, np.ndarray):
        decoded = decoded.item()
    if isinstance(decoded, bytes):
        return decoded.decode("ascii")
    return str(decoded)


def validate_rfc_netcdf(
    path: Path, expected_series: BuiltSeries | None = None
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []

    def error(message: str) -> None:
        findings.append(ValidationFinding(str(path), "error", message))

    if not FORCING_NAME_RE.fullmatch(path.name):
        error("filename does not match the t-route five-field convention")
        return findings
    try:
        with netCDF4.Dataset(path) as dataset:
            expected_dimensions = {
                "stationIdStrLen": 5,
                "timeStrLen": 19,
                "forecastInd": 289,
                "nseries": 1,
                "zero": 0,
            }
            for name, size in expected_dimensions.items():
                if (
                    name not in dataset.dimensions
                    or len(dataset.dimensions[name]) != size
                ):
                    error(f"dimension {name} is not {size}")
            required_variables = {
                "stationId": "S1",
                "issueTimeUTC": "S1",
                "discharges": "float32",
                "synthetic_values": "int8",
                "totalCounts": "int16",
                "observedCounts": "int16",
                "forecastCounts": "int16",
                "timeSteps": "int32",
                "discharge_qualities": "int16",
                "queryTime": "int64",
            }
            for name, dtype in required_variables.items():
                if name not in dataset.variables:
                    error(f"missing variable {name}")
                elif np.dtype(dataset.variables[name].dtype) != np.dtype(dtype):
                    error(
                        f"variable {name} has dtype {dataset.variables[name].dtype}, not {dtype}"
                    )
            if findings:
                return findings
            station = _decode_chars(dataset.variables["stationId"])
            issue = parse_nwm_time(_decode_chars(dataset.variables["issueTimeUTC"]))
            filename_fields = path.name.split(".")
            if station != filename_fields[2]:
                error(f"stationId {station!r} does not match filename")
            filename_issue = parse_nwm_time(filename_fields[0] + ":00:00")
            if issue != filename_issue:
                error("issueTimeUTC does not match filename")
            start = parse_nwm_time(dataset.getncattr("sliceStartTimeUTC"))
            if start != issue - timedelta(hours=48):
                error("sliceStartTimeUTC is not issue time minus 48 hours")
            scalar_expectations = {
                "totalCounts": 289,
                "observedCounts": 48,
                "forecastCounts": 241,
                "timeSteps": 3600,
                "discharge_qualities": 100,
            }
            for name, expected in scalar_expectations.items():
                if int(dataset.variables[name][0]) != expected:
                    error(f"{name} is not {expected}")
            values = np.asarray(dataset.variables["discharges"][0, :], dtype=float)
            flags = np.asarray(dataset.variables["synthetic_values"][0, :], dtype=int)
            if np.any(~np.isfinite(values)):
                error("discharges contain a non-finite value")
            if np.any(values < 0) or np.any(values >= MAX_TROUTE_DISCHARGE_CMS):
                error("discharges violate t-route bounds")
            if not set(np.unique(flags)).issubset({0, 1}):
                error("synthetic_values contains values other than 0 and 1")
            if np.all(flags == 1):
                error("all values are synthetic")
            if expected_series is not None:
                expected_values = expected_series.discharges_cms.astype(np.float32)
                if not np.array_equal(values.astype(np.float32), expected_values):
                    error("discharges differ from the reconstructed source series")
                if not np.array_equal(flags, expected_series.synthetic_values):
                    error("synthetic flags differ from the reconstructed source series")
            final_knot_index = 48 + 3 * 24
            if not np.all(values[final_knot_index:] == values[final_knot_index]):
                error("post-horizon values do not persist the final source knot")
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        error(f"cannot validate NetCDF: {exc}")
        return findings

    try:
        import xarray as xr

        with xr.open_dataset(path) as dataset:
            dataset.load()
    except (ImportError, OSError, ValueError) as exc:
        error(f"xarray could not open file: {exc}")
    return findings


def validate_with_troute(path: Path) -> list[ValidationFinding]:
    """Run t-route's production RFC data validator when the sibling repo exists."""
    troute_source = (
        Path(__file__).resolve().parents[3] / "t-route" / "src" / "troute-routing"
    )
    if not troute_source.is_dir():
        return [
            ValidationFinding(
                str(path), "warning", "sibling t-route validator is unavailable"
            )
        ]
    source_text = str(troute_source)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    try:
        module = importlib.import_module("troute.routing.fast_reach.reservoir_RFC_da")
        with netCDF4.Dataset(path) as dataset:
            values = np.asarray(dataset.variables["discharges"][0, :], dtype=float)
            flags = np.asarray(
                dataset.variables["synthetic_values"][0, :], dtype=np.int8
            )
            station = _decode_chars(dataset.variables["stationId"])
        accepted = module._validate_RFC_data(
            station,
            values,
            flags,
            str(path.parent),
            path.name,
            300,
            True,
        )
    except (ImportError, AttributeError, OSError, RuntimeError, KeyError) as exc:
        return [
            ValidationFinding(
                str(path), "warning", f"t-route validator unavailable: {exc}"
            )
        ]
    if not accepted:
        return [
            ValidationFinding(str(path), "error", "t-route rejected the forcing file")
        ]
    return []


def validate_forcing_directory(path: Path) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    if not path.is_dir():
        return [ValidationFinding(str(path), "error", "forcing directory is absent")]
    for entry in path.iterdir():
        if not entry.is_file() or not FORCING_NAME_RE.fullmatch(entry.name):
            findings.append(
                ValidationFinding(
                    str(entry),
                    "error",
                    "non-forcing entry in production forcing directory",
                )
            )
    return findings


def select_issue_for_chunk(
    chunk_start: datetime,
    gage: str,
    filenames: Iterable[str],
    lookback_hours: int = 28,
) -> datetime | None:
    start = parse_utc(chunk_start)
    candidates: list[datetime] = []
    for filename in filenames:
        fields = Path(filename).name.split(".")
        if len(fields) != 5 or fields[2] != gage:
            continue
        try:
            issue = parse_nwm_time(fields[0] + ":00:00")
        except ValueError:
            continue
        age = (start - issue).total_seconds() / 3600
        if 0 <= age <= lookback_hours:
            candidates.append(issue)
    return max(candidates) if candidates else None


def validate_chunk_selection(
    chunks: Sequence[tuple[datetime, datetime, datetime]],
    stations: Mapping[str, StationConfig],
    forcing_dir: Path,
) -> list[ValidationFinding]:
    filenames = (
        [entry.name for entry in forcing_dir.iterdir()] if forcing_dir.is_dir() else []
    )
    findings: list[ValidationFinding] = []
    for start, _, expected in chunks:
        for gage in stations:
            selected = select_issue_for_chunk(start, gage, filenames)
            expected_path = forcing_dir / output_filename(expected, gage)
            if expected_path.is_file() and selected != expected:
                findings.append(
                    ValidationFinding(
                        str(expected_path),
                        "error",
                        f"chunk {format_utc(start)} selected {selected}, expected {expected}",
                    )
                )
            if not expected_path.is_file() and selected is not None:
                findings.append(
                    ValidationFinding(
                        str(expected_path),
                        "error",
                        f"missing current issue selected stale issue {selected}",
                    )
                )
    return findings


def validate_with_troute_loader(
    chunks: Sequence[tuple[datetime, datetime, datetime]],
    stations: Mapping[str, StationConfig],
    forcing_dir: Path,
) -> list[ValidationFinding]:
    """Exercise t-route's file loader, crosswalk join, and issue selection."""
    workspace = Path(__file__).resolve().parents[3]
    source_roots = (
        workspace / "t-route" / "src" / "troute-network",
        workspace / "t-route" / "src" / "troute-routing",
    )
    if not all(path.is_dir() for path in source_roots):
        return [
            ValidationFinding(
                str(forcing_dir), "warning", "sibling t-route loader is unavailable"
            )
        ]
    for source_root in reversed(source_roots):
        source_text = str(source_root)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
    try:
        data_module = importlib.import_module("troute.DataAssimilation")
        crosswalk_module = importlib.import_module("troute.rfc_lake_gage_crosswalk")
    except (ImportError, AttributeError) as exc:
        return [
            ValidationFinding(
                str(forcing_dir), "warning", f"t-route loader unavailable: {exc}"
            )
        ]

    findings: list[ValidationFinding] = []
    for chunk_start, _, expected_issue in chunks:
        t0 = parse_utc(chunk_start).replace(tzinfo=None)
        search_dates = [
            (t0 - timedelta(hours=offset)).strftime("%Y-%m-%d_%H")
            for offset in range(28)
        ]
        expected_gages = {
            gage
            for gage in stations
            if (forcing_dir / output_filename(expected_issue, gage)).is_file()
        }
        try:
            loaded = data_module._read_timeseries_files(
                str(forcing_dir),
                search_dates,
                t0,
                t0 + timedelta(days=11),
            )
        except (AttributeError, IndexError, KeyError, OSError, ValueError) as exc:
            if expected_gages:
                findings.append(
                    ValidationFinding(
                        str(forcing_dir),
                        "error",
                        f"t-route loader failed at {format_utc(chunk_start)}: {exc}",
                    )
                )
            continue
        loaded_gages = set(loaded["stationId"].unique())
        if loaded_gages != expected_gages:
            findings.append(
                ValidationFinding(
                    str(forcing_dir),
                    "error",
                    f"t-route loaded {sorted(loaded_gages)} at "
                    f"{format_utc(chunk_start)}, expected {sorted(expected_gages)}",
                )
            )
            continue
        if not bool(loaded["use_rfc"].all()):
            findings.append(
                ValidationFinding(
                    str(forcing_dir),
                    "error",
                    f"t-route disabled loaded RFC data at {format_utc(chunk_start)}",
                )
            )
        expected_files = {
            output_filename(expected_issue, gage) for gage in expected_gages
        }
        if set(loaded["file"].unique()) != expected_files:
            findings.append(
                ValidationFinding(
                    str(forcing_dir),
                    "error",
                    f"t-route selected unexpected source files at {format_utc(chunk_start)}",
                )
            )
        crosswalk = crosswalk_module.get_rfc_lake_gage_crosswalk()
        try:
            with warnings.catch_warnings():
                # Current t-route uses pandas inplace fills that warn on pandas 2.x.
                warnings.simplefilter("ignore", FutureWarning)
                _, parameters = data_module.assemble_rfc_dataframes(
                    loaded,
                    crosswalk,
                    t0,
                    {"reservoir_rfc_forecast_persist_days": 11},
                )
        except (AttributeError, IndexError, KeyError, ValueError) as exc:
            findings.append(
                ValidationFinding(
                    str(forcing_dir),
                    "error",
                    f"t-route RFC assembly failed at {format_utc(chunk_start)}: {exc}",
                )
            )
            continue
        expected_lakes = {
            station.reservoir_feature_id
            for gage, station in stations.items()
            if gage in expected_gages
        }
        active_lakes = set(parameters.index[parameters["use_rfc"]])
        if not expected_lakes <= active_lakes:
            findings.append(
                ValidationFinding(
                    str(forcing_dir),
                    "error",
                    f"t-route crosswalk did not activate lakes "
                    f"{sorted(expected_lakes - active_lakes)}",
                )
            )
    return findings


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def write_inventory_csv(path: Path, records: Sequence[NwmObjectMetadata]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(NwmObjectMetadata.__dataclass_fields__)
    with tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(record) for record in records)
        temporary = Path(stream.name)
    os.replace(temporary, path)


def read_inventory_csv(path: Path) -> list[NwmObjectMetadata]:
    with path.open(newline="", encoding="utf-8") as stream:
        records: list[NwmObjectMetadata] = []
        for row in csv.DictReader(stream):
            records.append(
                NwmObjectMetadata(
                    object_key=row["object_key"],
                    product=row["product"],
                    source_date=row["source_date"],
                    initialization_time_utc=row["initialization_time_utc"],
                    lead=_safe_int(row["lead"], "inventory lead"),
                    expected_valid_time_utc=row["expected_valid_time_utc"],
                    size=(
                        _safe_int(row["size"], "inventory object size")
                        if row["size"]
                        else None
                    ),
                    md5_hash=row["md5_hash"] or None,
                    updated=row["updated"] or None,
                    generation=row["generation"] or None,
                    cache_path=row["cache_path"] or None,
                    status=row["status"],
                    checksum_status=row["checksum_status"],
                    error=row["error"] or None,
                )
            )
        return records


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    lines = (json.dumps(row, sort_keys=True, allow_nan=False) for row in rows)
    _atomic_write_text(path, "".join(line + "\n" for line in lines))


def write_issue_summary(path: Path, results: Sequence[IssueStationResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["issue_time_utc", "gage", "status", "output_filename", "reason", "reused"]
    with tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result.as_manifest() for result in results)
        temporary = Path(stream.name)
    os.replace(temporary, path)


def git_sha(repository: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def git_is_dirty(repository: Path) -> bool | None:
    try:
        status = subprocess.check_output(
            ["git", "-C", str(repository), "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return bool(status.strip())
    except (OSError, subprocess.CalledProcessError):
        return None


def git_version(repository: Path) -> str:
    sha = git_sha(repository)
    dirty = git_is_dirty(repository)
    return f"{sha}-dirty" if dirty else sha


def write_run_manifest(
    path: Path,
    args: argparse.Namespace,
    issues: Sequence[datetime],
    source_dates: Sequence[date],
    stations: Mapping[str, StationConfig],
    status: str,
) -> None:
    repository = Path(__file__).resolve().parents[2]
    payload = {
        "created_time_utc": format_utc(datetime.now(UTC)),
        "status": status,
        "simulation_interval": {
            "start_utc": format_utc(parse_utc(args.simulation_start)),
            "end_utc": format_utc(parse_utc(args.simulation_end)),
            "semantics": "half-open [start, end)",
        },
        "output_issues": [format_utc(issue) for issue in issues],
        "source_dates": [value.isoformat() for value in source_dates],
        "stations": {gage: asdict(station) for gage, station in stations.items()},
        "mapping_source": str(args.crosswalk),
        "source_bucket": f"gs://{normalize_bucket(args.source_bucket)}",
        "https_base_url": args.https_base_url,
        "member": args.member,
        "source_configuration": SOURCE_CONFIGURATION,
        "activation_hour_utc": args.activation_hour,
        "strict": args.strict,
        "diagnostic_fill": args.diagnostic_fill,
        "cms_to_cfs": CMS_TO_CFS,
        "software_git_sha": git_sha(repository),
        "software_worktree_dirty": git_is_dirty(repository),
        "command_line": sys.argv,
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "netCDF4": netCDF4.__version__,
            "numpy": np.__version__,
            "requests": _package_version("requests"),
        },
        "disclaimer": (
            "Reconstructed RFC-controlled outflows retained in public NWM routing "
            "output; not authoritative original NERFC forecast records."
        ),
    }
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def build_outputs(
    args: argparse.Namespace,
    issues: Sequence[datetime],
    source_dates: Sequence[date],
    stations: Mapping[str, StationConfig],
) -> tuple[list[IssueStationResult], list[ValidationFinding]]:
    output_root = Path(args.output_root)
    provenance_dir = output_root / "provenance"
    production_dir = output_root / "rfc_timeseries"
    diagnostic_dir = output_root / "diagnostic_rfc_timeseries"
    production_dir.mkdir(parents=True, exist_ok=True)
    trajectories, points = extract_issue_trajectories(
        source_dates, stations, args.member, Path(args.cache_dir)
    )
    write_jsonl(
        provenance_dir / "point_provenance.jsonl",
        (point.as_manifest() for point in points),
    )
    results: list[IssueStationResult] = []
    findings: list[ValidationFinding] = []
    hourly_rows: list[dict[str, Any]] = []
    reconstruction_version = git_version(Path(__file__).resolve().parents[2])
    query_time = datetime.now(UTC)
    for issue in issues:
        for station in stations.values():
            filename = output_filename(issue, station.gage)
            destination = production_dir / filename
            try:
                series = build_rfc_timeseries(
                    issue,
                    station,
                    trajectories,
                    query_time=query_time,
                    diagnostic_fill=False,
                )
                gap_count = sum(
                    item.method == "preceding_value_gap_fill"
                    for item in series.hourly_provenance
                )
                if gap_count:
                    LOGGER.warning(
                        "build issue=%s station=%s used %d pre-issue gap fills",
                        issue,
                        station.gage,
                        gap_count,
                    )
                reused = False
                existing_findings = (
                    validate_rfc_netcdf(destination, series)
                    if destination.exists() and not args.overwrite
                    else []
                )
                if (
                    destination.exists()
                    and not args.overwrite
                    and not existing_findings
                ):
                    reused = True
                else:
                    if destination.exists() and not args.overwrite:
                        raise ReconstructionError(
                            "existing output is invalid; use --overwrite: "
                            + "; ".join(item.message for item in existing_findings)
                        )
                    write_rfc_netcdf(
                        series,
                        destination,
                        reconstruction_version,
                        f"gs://{normalize_bucket(args.source_bucket)}",
                    )
                file_findings = validate_rfc_netcdf(destination, series)
                findings.extend(file_findings)
                status = "invalid" if file_findings else "written"
                results.append(
                    IssueStationResult(
                        issue,
                        station.gage,
                        status,
                        filename,
                        "; ".join(item.message for item in file_findings) or None,
                        reused,
                    )
                )
                hourly_rows.extend(
                    item.as_manifest(filename, station.gage)
                    for item in series.hourly_provenance
                )
            except ReconstructionError as exc:
                # Never retain a stale primary file for a newly rejected issue.
                destination.unlink(missing_ok=True)
                LOGGER.error("build issue=%s station=%s: %s", issue, station.gage, exc)
                results.append(
                    IssueStationResult(issue, station.gage, "rejected", None, str(exc))
                )
                if args.diagnostic_fill:
                    try:
                        diagnostic = build_rfc_timeseries(
                            issue,
                            station,
                            trajectories,
                            query_time=query_time,
                            diagnostic_fill=True,
                        )
                        diagnostic_path = diagnostic_dir / filename
                        write_rfc_netcdf(
                            diagnostic,
                            diagnostic_path,
                            reconstruction_version,
                            f"gs://{normalize_bucket(args.source_bucket)}",
                        )
                    except ReconstructionError as diagnostic_exc:
                        LOGGER.warning(
                            "diagnostic fill issue=%s station=%s failed: %s",
                            issue,
                            station.gage,
                            diagnostic_exc,
                        )
    write_issue_summary(provenance_dir / "issue_summary.csv", results)
    write_jsonl(provenance_dir / "hourly_provenance.jsonl", hourly_rows)
    findings.extend(validate_forcing_directory(production_dir))
    return results, findings


def validate_outputs(
    args: argparse.Namespace,
    issues: Sequence[datetime],
    stations: Mapping[str, StationConfig],
) -> list[ValidationFinding]:
    forcing_dir = Path(args.output_root) / "rfc_timeseries"
    findings = validate_forcing_directory(forcing_dir)
    if forcing_dir.is_dir():
        for path in sorted(forcing_dir.iterdir()):
            if path.is_file() and FORCING_NAME_RE.fullmatch(path.name):
                findings.extend(validate_rfc_netcdf(path))
                findings.extend(validate_with_troute(path))
    chunks = derive_chunk_schedule(
        parse_utc(args.simulation_start),
        parse_utc(args.simulation_end),
        args.activation_hour,
    )
    findings.extend(validate_chunk_selection(chunks, stations, forcing_dir))
    findings.extend(validate_with_troute_loader(chunks, stations, forcing_dir))
    expected = {output_filename(issue, gage) for issue in issues for gage in stations}
    actual = (
        {entry.name for entry in forcing_dir.iterdir()}
        if forcing_dir.is_dir()
        else set()
    )
    if args.strict:
        for missing in sorted(expected - actual):
            findings.append(
                ValidationFinding(
                    str(forcing_dir / missing), "error", "expected file missing"
                )
            )
        for unexpected in sorted(actual - expected):
            findings.append(
                ValidationFinding(
                    str(forcing_dir / unexpected), "error", "unexpected forcing file"
                )
            )
    report = {
        "created_time_utc": format_utc(datetime.now(UTC)),
        "valid": not any(item.severity == "error" for item in findings),
        "checked_files": len(actual),
        "expected_files": len(expected),
        "findings": [asdict(item) for item in findings],
    }
    _atomic_write_text(
        Path(args.output_root) / "provenance" / "validation_report.json",
        json.dumps(report, indent=2, sort_keys=True),
    )
    return findings


def print_dry_run(
    args: argparse.Namespace,
    issues: Sequence[datetime],
    source_dates: Sequence[date],
    stations: Mapping[str, StationConfig],
) -> None:
    objects = planned_objects(source_dates, args.member)
    channel_count = sum(record.product == "channel" for record in objects)
    reservoir_count = len(objects) - channel_count
    estimated_bytes = channel_count * 13_000_000 + reservoir_count * 130_000
    print("Required output issues:")
    for issue in issues:
        print(f"  {format_utc(issue)}")
    print(
        "Required seed/source dates: "
        f"{source_dates[0].isoformat()} through {source_dates[-1].isoformat()}"
    )
    print(f"Objects: {len(objects)} (estimated {estimated_bytes / 1e9:.2f} GB)")
    print("Expected output filenames:")
    for issue in issues:
        for gage in stations:
            print(f"  {output_filename(issue, gage)}")
    print("Chunk-to-issue selection:")
    for start, end, issue in derive_chunk_schedule(
        parse_utc(args.simulation_start),
        parse_utc(args.simulation_end),
        args.activation_hour,
    ):
        print(f"  [{format_utc(start)}, {format_utc(end)}) -> {format_utc(issue)}")


def _common_parser(parser: argparse.ArgumentParser, script_dir: Path) -> None:
    parser.add_argument("--simulation-start", required=True)
    parser.add_argument("--simulation-end", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument(
        "--station-config",
        type=Path,
        default=script_dir / "nerfc_reconstruction_stations.json",
    )
    parser.add_argument(
        "--crosswalk",
        type=Path,
        default=script_dir
        / "RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv",
    )
    parser.add_argument("--source-bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--https-base-url", default=DEFAULT_HTTPS_BASE)
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE)
    parser.add_argument("--member", type=int, default=1)
    parser.add_argument("--activation-hour", type=int, default=18)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument("--strict", action="store_true", default=True)
    policy.add_argument(
        "--diagnostic-fill", action="store_true", help="write fills outside production"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    script_dir = Path(__file__).resolve().parent
    for command, help_text in (
        ("inventory", "validate required public GCS object metadata"),
        ("download", "populate and verify the local NWM cache"),
        ("build", "build NetCDF forcing from an existing cache"),
        ("validate", "validate existing production forcing"),
        ("all", "run inventory, download, build, and validate"),
    ):
        subparser = subparsers.add_parser(command, help=help_text)
        _common_parser(subparser, script_dir)
    return parser


def _ensure_inventory(
    args: argparse.Namespace,
    source_dates: Sequence[date],
) -> list[NwmObjectMetadata]:
    inventory_path = Path(args.output_root) / "provenance" / "object_inventory.csv"
    if args.command in {"download", "build"} and inventory_path.is_file():
        records = read_inventory_csv(inventory_path)
    else:
        records = inventory_objects(
            planned_objects(source_dates, args.member),
            args.source_bucket,
            args.api_base_url,
            args.max_workers,
        )
        write_inventory_csv(inventory_path, records)
    return records


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args.strict = not args.diagnostic_fill
    start = parse_utc(args.simulation_start)
    end = parse_utc(args.simulation_end)
    issues = derive_required_output_issues(start, end, args.activation_hour)
    source_dates = derive_required_source_dates(issues)
    stations = load_station_config(Path(args.station_config))
    crosscheck_station_config(stations, Path(args.crosswalk))
    if args.dry_run:
        print_dry_run(args, issues, source_dates, stations)
        return 0

    provenance_dir = Path(args.output_root) / "provenance"
    provenance_dir.mkdir(parents=True, exist_ok=True)
    write_run_manifest(
        provenance_dir / "run.json", args, issues, source_dates, stations, "running"
    )
    failed = False
    records: list[NwmObjectMetadata] = []
    if args.command in {"inventory", "download", "all"}:
        records = _ensure_inventory(args, source_dates)
        failed |= any(record.status != "available" for record in records)
    if args.command in {"download", "all"}:
        records = download_objects(
            records,
            Path(args.cache_dir),
            args.https_base_url,
            args.overwrite,
            args.resume,
            args.max_workers,
        )
        write_inventory_csv(provenance_dir / "object_inventory.csv", records)
        failed |= any(
            record.status not in {"cached", "downloaded"} for record in records
        )
    if args.command in {"build", "all"}:
        results, findings = build_outputs(args, issues, source_dates, stations)
        failed |= any(result.status != "written" for result in results)
        failed |= any(finding.severity == "error" for finding in findings)
    if args.command in {"validate", "all"}:
        findings = validate_outputs(args, issues, stations)
        for finding in findings:
            LOGGER.log(
                logging.ERROR if finding.severity == "error" else logging.WARNING,
                "%s: %s",
                finding.path,
                finding.message,
            )
        failed |= any(finding.severity == "error" for finding in findings)
    write_run_manifest(
        provenance_dir / "run.json",
        args,
        issues,
        source_dates,
        stations,
        "failed" if failed else "complete",
    )
    return 1 if failed and args.strict else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ReconstructionError, OSError, ValueError) as exc:
        LOGGER.error("fatal: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
