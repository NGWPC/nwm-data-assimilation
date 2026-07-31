# Reconstruct NERFC Forcing from Public NWM Output

## Overview

`reconstruct_nerfc_from_nwm.py` reconstructs RFC reservoir forcing for five
NERFC reservoirs. The script reads RFC-controlled outlet flows from public NWM
routing output and writes NetCDF files that can be used by T-Route.

Each generated file is organized around a nominal 12Z RFC issue and begins 48
hours before that issue. The T-Route file format uses those first 48 hourly
values as historical support. Because the original NERFC observations are not
available, the script reconstructs this support from overlapping NWM
medium-range forecast cycles. For each hour, it uses the newest cycle
if it is available for that time rather than using overlapping forecasts from an
older medium-range cycle.

The reconstruction samples each source trajectory at six-hour event intervals
and persists each sampled value forward in between intervals to produce hourly values. The
selected portion of a source trajectory covers about 66 hours, so consecutive
daily cycles overlap enough to provide the 48-hour support period. Array hour
48 is the nominal issue boundary in the T-Route file, not the source-cycle
switch. The current 18Z NWM cycle becomes available six hours later, so the
previous cycle continues through 17Z and the source-cycle switch occurs at 18Z.

These files are not original NERFC PI XML records and should not be used as an
authoritative NERFC archive. The historical support contains reconstructed
operational forcing, not recovered `RQOT observed` data.

## Prerequisites

- Python 3.11
- `netCDF4`, `numpy`, `requests`, and `xarray`
- Approximately 2-3 GB of local storage for the December 2023 source cache
- Network access to the public Google Cloud Storage URLs

Google credentials are not required when the default public HTTPS transport is
used.

## Station Configuration

The station mappings are stored in `nerfc_reconstruction_stations.json`.

| Gage | Reservoir feature | Outlet channel feature |
| --- | ---: | ---: |
| BNGM1 | 3318110 | 3319188 |
| STDM1 | 6719717 | 6724973 |
| RKWM1 | 166195943 | 1022652 |
| SCIR1 | 6127281 | 6130387 |
| STVC3 | 120052268 | 7718286 |

The script compares this configuration with
`RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv` each time it
starts. For STDM1, the CSV has `lakeLink=0`, so the script uses
`gagedFlowline=6724973`. The script exits if the station configuration and CSV
do not agree.

## Source Data

The target source data are from the NWM v3.0 `medium_range_mem1` simulation
initialized at 18Z. The script reads channel and reservoir files for leads
`f001`, `f006`, `f012`, `f018`, `f024`, `f030`, `f036`, `f042`, `f048`, `f054`,
`f060`, and `f066`.

The NWM medium-range product extends beyond `f066`, but this reconstruction uses
only the listed leads. `f066` means forecast hour 66 from the 18Z model
initialization. It is valid at 12Z three days later, which is 72 hours after the
nominal 12Z RFC issue time. The script uses no later lead in that issue's file
and repeats the `f066` value through issue time plus 10 days.

The `f001` file has a model valid time of 19Z but is assigned to the 18Z RFC
event. Leads `f006` through `f066` use their exact six-hour event times. The
script holds each source value forward between events instead of interpolating.

For an output issue `D 12Z`, the file starts at `D-2 12Z`. Array indices 0-47
contain the required 48 hours of support from earlier, already activated source
cycles. Index 48 is the nominal issue time `D 12Z`, but the current source cycle
is not treated as available until `D 18Z`. The latest earlier cycle therefore
also supplies indices 48-53. At index 54, the file switches to the current
issue's `f001` event.

At each hour before the current issue activates, the script selects the newest
already activated source cycle whose reconstructed trajectory covers that hour.
After activation, a production file follows the current issue and does not
splice in future issue cycles. During routing, daily 18Z restarts select newer issue files
as they become available. This prevents lookahead while allowing the simulation
to advance through successive daily forecasts.

The script validates initialization time, valid time, model configuration, and
output type using NetCDF metadata. It also requires the channel and reservoir
files in each pair to contain the same `NWM_version_number`. This confirms
version consistency between a file pair but does not require the value to be
v3.0. The December 2023 source files used by this workflow report v3.0.

A station and issue are written to the production directory only when all 12
current forecast points meet both of these conditions:

- The reservoir is classified as RFC-active.
- The outlet flow is finite and in the range `[0, 90000)` CMS.

A reservoir is classified as RFC-active when `reservoir_type`,
`reservoir_assimilated_value`, and `outflow` are all masked for one of the five
configured reservoirs. A visible `reservoir_type=1` is classified as level-pool
fallback and is not used as RFC forcing.

## Script Usage

Run commands from the repository root.

### Check the Target Run

Use `--dry-run` to inspect the planned source objects, output files, and T-Route
chunks without using the network or writing output files.

```bash
python data_assimilation_engine/rfc_ingestion/reconstruct_nerfc_from_nwm.py all \
  --simulation-start 2023-12-10T00:00:00Z \
  --simulation-end 2023-12-21T00:00:00Z \
  --output-root /data/reconstructed_nerfc \
  --cache-dir /data/nwm_cache \
  --strict \
  --dry-run
```

For this period, the dry run reports:

- 12 output issues from December 9 through December 20 at 12Z
- Source dates from December 6 through December 20
- 360 source objects
- 60 expected forcing files
- A half-open T-Route chunk schedule

### Run the Complete Workflow

Remove `--dry-run` to run inventory, download, build, and validation.

```bash
python data_assimilation_engine/rfc_ingestion/reconstruct_nerfc_from_nwm.py all \
  --simulation-start 2023-12-10T00:00:00Z \
  --simulation-end 2023-12-21T00:00:00Z \
  --output-root /data/reconstructed_nerfc \
  --cache-dir /data/nwm_cache \
  --max-workers 4 \
  --resume \
  --strict
```

The individual stages are `inventory`, `download`, `build`, and `validate`.
Each stage accepts the same simulation schedule, output directory, cache
directory, and source configuration arguments.

Downloads are written to `*.part` files and renamed after completion. With a
fresh GCS inventory, cached files are checked against the expected size. The GCS
MD5 is also checked when the inventory contains `md5Hash`. Use `--overwrite` to
replace valid cache or output files. Invalid existing forcing files are not
silently reused.

Use `--diagnostic-fill` only for investigation. If the current forecast is
invalid, the script omits it from `rfc_timeseries/`. When a diagnostic fill can
be created, it is written to `diagnostic_rfc_timeseries/` and is not production
forcing.

## Output

A complete run writes the following directory structure:

```text
<output-root>/
  rfc_timeseries/
  diagnostic_rfc_timeseries/      # created only when diagnostic output is written
  provenance/
    run.json
    object_inventory.csv
    issue_summary.csv
    point_provenance.jsonl
    hourly_provenance.jsonl
    validation_report.json
```

Only T-Route forcing files should be placed in `rfc_timeseries/`. Do not add
README files, manifests, logs, XML, or hidden metadata to this directory. The
validator rejects entries that do not match this filename pattern:

```text
YYYY-MM-DD_12.60min.GAGE.RFCTimeSeries.ncdf
```

Each forcing file contains 289 hourly CMS values from issue time minus 48 hours
through issue time plus 10 days, inclusive. The file has the following count and
time settings:

- `totalCounts=289`
- `observedCounts=48`
- `forecastCounts=241`
- Issue time at array index 48
- `timeSteps=3600`
- `discharge_qualities=100`

`discharge_qualities=100` is a compatibility value and is not recovered source
quality. A `synthetic_values` value of `0` identifies a direct source point.
Hourly holds, gap fills, and persistence after the forecast horizon use a value
of `1`.

The output attribute `NWM_version_number` is set to `v3.0` for this workflow.
The version values read from the source files are recorded separately in
`source_NWM_version_numbers`.

## Validation

The validator opens each forcing file with netCDF4 and xarray. It checks the
schema, data types, counts, discharge bounds, synthetic flags, timestamps,
filename fields, and final-value persistence.

When a sibling T-Route checkout is available, validation also runs T-Route's
`_validate_RFC_data()` function and exercises the T-Route file loader, reservoir
crosswalk, and issue selection.

## T-Route Configuration

Use one T-Route invocation for each half-open chunk and carry the normal restart
state into the next chunk. Do not route the shared endpoint in both chunks.

```yaml
reservoir_rfc_da:
    reservoir_rfc_forecasts: true
    reservoir_rfc_forecasts_time_series_path: /data/reconstructed_nerfc/rfc_timeseries
    reservoir_rfc_forecasts_lookback_hours: 28
    reservoir_rfc_forecasts_offset_hours: 0
    reservoir_rfc_forecast_persist_days: 11
```

The routing period must not exceed 3600 seconds. The normal 300-second routing
period is valid.

The schedule starts as follows:

```text
[2023-12-10 00Z, 2023-12-10 18Z) -> 2023-12-09 12Z issue
[2023-12-10 18Z, 2023-12-11 18Z) -> 2023-12-10 12Z issue
```

At each later 18Z restart, issue `D 12Z` becomes active. If the current issue is
missing, the 28-hour lookback does not select the previous issue because it is
30 hours old. T-Route uses level pool for that reservoir instead.

## Testing

Run the network-free tests from the repository root:

```bash
pytest -q data_assimilation_engine/rfc_ingestion/test_reconstruct_nerfc_from_nwm.py
```

Set `NERFC_NWM_CACHE` to run the optional December 10 public-data regression
with an existing source cache:

```bash
NERFC_NWM_CACHE=/data/nwm_cache \
pytest -q data_assimilation_engine/rfc_ingestion/test_reconstruct_nerfc_from_nwm.py
```

The repository does not include the multi-gigabyte NWM source files. The
production workflow writes NetCDF files directly and does not reconstruct PI
XML. This avoids the missing-value behavior in the legacy forecast-only PI XML
path.
