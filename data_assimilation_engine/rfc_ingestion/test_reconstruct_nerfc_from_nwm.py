from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import netCDF4
import numpy as np
import pytest

from data_assimilation_engine.rfc_ingestion.reconstruct_nerfc_from_nwm import (
    SOURCE_LEADS,
    FeatureIndexStore,
    IssueTrajectory,
    ReconstructionError,
    SourcePoint,
    StationConfig,
    build_object_key,
    build_rfc_timeseries,
    classify_reservoir_status,
    crosscheck_station_config,
    derive_chunk_schedule,
    derive_required_output_issues,
    derive_required_source_dates,
    extract_outlet_streamflow,
    extract_source_points,
    lead_to_event_time,
    load_station_config,
    main,
    output_filename,
    select_issue_for_chunk,
    validate_forcing_directory,
    validate_rfc_netcdf,
    validate_with_troute_loader,
    write_rfc_netcdf,
)

UTC = timezone.utc
HERE = Path(__file__).resolve().parent
STATION = StationConfig("BNGM1", "Wyman Dam", 3318110, 3319188)


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def make_point(
    issue: datetime, lead: int, value: float, station=STATION
) -> SourcePoint:
    event = lead_to_event_time(issue, lead)
    return SourcePoint(
        nominal_issue_time_utc=issue,
        activation_time_utc=issue.replace(hour=18),
        event_time_utc=event,
        model_valid_time_utc=issue.replace(hour=18) + timedelta(hours=lead),
        gage=station.gage,
        reservoir_feature_id=station.reservoir_feature_id,
        outlet_channel_feature_id=station.outlet_channel_feature_id,
        member=1,
        lead=lead,
        channel_object_key=f"channel-f{lead:03d}",
        reservoir_object_key=f"reservoir-f{lead:03d}",
        reservoir_classification="rfc_active",
        discharge_cms=value,
        accepted=True,
        nwm_version_number="v3.0",
    )


def make_trajectories(
    output_issue: datetime,
) -> dict[tuple[datetime, str], IssueTrajectory]:
    trajectories = {}
    for days_before in range(3, -1, -1):
        issue = output_issue - timedelta(days=days_before)
        trajectory = IssueTrajectory(issue, issue.replace(hour=18), STATION)
        for lead in SOURCE_LEADS:
            point = make_point(issue, lead, issue.day * 10 + lead / 10)
            trajectory.points[point.event_time_utc] = point
        trajectories[(issue, STATION.gage)] = trajectory
    return trajectories


def write_source_fixture(
    path: Path,
    product: str,
    issue: datetime,
    lead: int,
    feature_ids: list[int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with netCDF4.Dataset(path, "w") as dataset:
        dataset.createDimension("feature_id", len(feature_ids))
        ids = dataset.createVariable("feature_id", "i8", ("feature_id",))
        ids[:] = feature_ids
        dataset.model_initialization_time = issue.replace(hour=18).strftime(
            "%Y-%m-%d_%H:%M:%S"
        )
        dataset.model_output_valid_time = (
            issue.replace(hour=18) + timedelta(hours=lead)
        ).strftime("%Y-%m-%d_%H:%M:%S")
        dataset.model_configuration = "medium_range"
        dataset.model_output_type = (
            "channel_rt" if product == "channel" else "reservoir"
        )
        dataset.NWM_version_number = "v3.0"
        if product == "channel":
            flow = dataset.createVariable("streamflow", "f4", ("feature_id",))
            flow[:] = [85.47 for _ in feature_ids]
        else:
            reservoir_type = dataset.createVariable(
                "reservoir_type", "i4", ("feature_id",), fill_value=-9999
            )
            assimilated = dataset.createVariable(
                "reservoir_assimilated_value",
                "f4",
                ("feature_id",),
                fill_value=-9999.0,
            )
            outflow = dataset.createVariable(
                "outflow", "f4", ("feature_id",), fill_value=-9999.0
            )
            reservoir_type[:] = np.ma.masked_all(len(feature_ids), dtype=np.int32)
            assimilated[:] = np.ma.masked_all(len(feature_ids), dtype=np.float32)
            outflow[:] = np.ma.masked_all(len(feature_ids), dtype=np.float32)


def test_required_issue_and_source_schedule() -> None:
    issues = derive_required_output_issues(utc(2023, 12, 10, 0), utc(2023, 12, 21, 0))
    assert len(issues) == 12
    assert issues[0] == utc(2023, 12, 9)
    assert issues[-1] == utc(2023, 12, 20)
    source_dates = derive_required_source_dates(issues)
    assert source_dates == [date(2023, 12, day) for day in range(6, 21)]


def test_half_open_schedule_and_chunks() -> None:
    chunks = derive_chunk_schedule(utc(2023, 12, 10, 0), utc(2023, 12, 11, 0))
    assert chunks == [
        (utc(2023, 12, 10, 0), utc(2023, 12, 10, 18), utc(2023, 12, 9)),
        (utc(2023, 12, 10, 18), utc(2023, 12, 11, 0), utc(2023, 12, 10)),
    ]


def test_object_keys_and_lead_event_alignment() -> None:
    assert build_object_key(date(2023, 12, 10), 1, "channel", 1) == (
        "nwm.20231210/medium_range_mem1/"
        "nwm.t18z.medium_range.channel_rt_1.f001.conus.nc"
    )
    issue = utc(2023, 12, 10)
    assert lead_to_event_time(issue, 1) == utc(2023, 12, 10, 18)
    assert lead_to_event_time(issue, 6) == utc(2023, 12, 11, 0)
    assert lead_to_event_time(issue, 66) == utc(2023, 12, 13, 12)


def test_station_config_matches_repository_crosswalk() -> None:
    stations = load_station_config(HERE / "nerfc_reconstruction_stations.json")
    assert stations["STDM1"].outlet_channel_feature_id == 6724973
    crosscheck_station_config(
        stations,
        HERE / "RFC_Reservoir_Locations_for_Forecast_Ingest_into_NWM_All_RFCs.csv",
    )


def test_masked_rfc_and_visible_levelpool_classification(tmp_path: Path) -> None:
    path = tmp_path / "reservoir.nc"
    with netCDF4.Dataset(path, "w") as dataset:
        dataset.createDimension("feature_id", 2)
        ids = dataset.createVariable("feature_id", "i8", ("feature_id",))
        ids[:] = [10, 20]
        reservoir_type = dataset.createVariable(
            "reservoir_type", "i4", ("feature_id",), fill_value=-9999
        )
        assimilated = dataset.createVariable(
            "reservoir_assimilated_value", "f4", ("feature_id",), fill_value=-9999
        )
        outflow = dataset.createVariable(
            "outflow", "f4", ("feature_id",), fill_value=-9999
        )
        reservoir_type[:] = [-9999, 1]
        assimilated[:] = [-9999, 3.0]
        outflow[:] = [-9999, 4.0]
    with netCDF4.Dataset(path) as dataset:
        assert classify_reservoir_status(dataset, 10) == "rfc_active"
        assert classify_reservoir_status(dataset, 20) == "fallback_levelpool"
        assert classify_reservoir_status(dataset, 30) == "missing_reservoir"


def test_streamflow_bounds_and_missing(tmp_path: Path) -> None:
    path = tmp_path / "channel.nc"
    with netCDF4.Dataset(path, "w") as dataset:
        dataset.createDimension("feature_id", 4)
        ids = dataset.createVariable("feature_id", "i8", ("feature_id",))
        ids[:] = [1, 2, 3, 4]
        flow = dataset.createVariable(
            "streamflow", "f4", ("feature_id",), fill_value=-9999
        )
        flow[:] = [85.47, -1, 90000, -9999]
    with netCDF4.Dataset(path) as dataset:
        assert extract_outlet_streamflow(dataset, 1)[1] is None
        assert extract_outlet_streamflow(dataset, 2)[1] == "invalid_value"
        assert extract_outlet_streamflow(dataset, 3)[1] == "invalid_value"
        assert extract_outlet_streamflow(dataset, 4)[1] == "missing_value"
        assert extract_outlet_streamflow(dataset, 5)[1] == "missing_outlet"


def test_extract_source_point_and_metadata(tmp_path: Path) -> None:
    issue = utc(2023, 12, 10)
    channel_key = build_object_key(issue.date(), 1, "channel", 1)
    reservoir_key = build_object_key(issue.date(), 1, "reservoir", 1)
    write_source_fixture(
        tmp_path / channel_key,
        "channel",
        issue,
        1,
        [STATION.outlet_channel_feature_id],
    )
    write_source_fixture(
        tmp_path / reservoir_key,
        "reservoir",
        issue,
        1,
        [STATION.reservoir_feature_id],
    )
    point = extract_source_points(
        issue,
        1,
        {STATION.gage: STATION},
        1,
        tmp_path,
        FeatureIndexStore(tmp_path / "indices.json"),
    )[0]
    assert point.accepted
    assert point.reservoir_classification == "rfc_active"
    assert point.discharge_cms == pytest.approx(85.47, abs=1e-5)
    assert point.event_time_utc == utc(2023, 12, 10, 18)
    assert point.model_valid_time_utc == utc(2023, 12, 10, 19)


def test_hourly_hold_stitch_and_no_lookahead() -> None:
    issue = utc(2023, 12, 10)
    trajectories = make_trajectories(issue)
    series = build_rfc_timeseries(
        issue, STATION, trajectories, query_time=utc(2024, 1, 1, 0)
    )
    assert len(series.discharges_cms) == 289
    assert series.start_time_utc == utc(2023, 12, 8)
    # At nominal issue time, the previous day's already activated trajectory is used.
    assert series.discharges_cms[48] == pytest.approx(9 * 10 + 18 / 10)
    assert series.synthetic_values[48] == 0
    assert series.discharges_cms[53] == series.discharges_cms[48]
    assert series.synthetic_values[53] == 1
    # The current issue becomes usable at 18Z, six hours after nominal issue time.
    assert series.discharges_cms[54] == pytest.approx(10 * 10 + 1 / 10)
    assert series.synthetic_values[54] == 0
    assert series.discharges_cms[55] == series.discharges_cms[54]
    assert series.synthetic_values[55] == 1
    # f066 is at index 120 and is persisted to the inclusive file end.
    assert series.discharges_cms[120] == pytest.approx(10 * 10 + 66 / 10)
    assert np.all(series.discharges_cms[120:] == series.discharges_cms[120])
    assert np.all(series.synthetic_values[121:] == 1)


def test_pre_issue_gap_at_file_start_uses_nearest_preceding_value() -> None:
    output_issue = utc(2023, 12, 12)
    trajectories = {}
    for day in range(6, 13):
        issue = utc(2023, 12, day)
        trajectory = IssueTrajectory(issue, issue.replace(hour=18), STATION)
        for lead in SOURCE_LEADS:
            point = make_point(issue, lead, day * 10 + lead / 10)
            if day not in {6, 12}:
                point.accepted = False
                point.rejection_reason = "fallback_levelpool"
                point.reservoir_classification = "fallback_levelpool"
            trajectory.points[point.event_time_utc] = point
        trajectories[(issue, STATION.gage)] = trajectory

    series = build_rfc_timeseries(output_issue, STATION, trajectories)
    assert series.discharges_cms[0] == pytest.approx(6 * 10 + 66 / 10)
    assert series.synthetic_values[0] == 1
    assert series.hourly_provenance[0].method == "preceding_value_gap_fill"
    assert series.discharges_cms[54] == pytest.approx(12 * 10 + 1 / 10)


def test_current_fallback_rejects_complete_issue() -> None:
    issue = utc(2023, 12, 10)
    trajectories = make_trajectories(issue)
    point = trajectories[(issue, STATION.gage)].points[lead_to_event_time(issue, 24)]
    point.accepted = False
    point.rejection_reason = "fallback_levelpool"
    with pytest.raises(ReconstructionError, match="fallback_levelpool"):
        build_rfc_timeseries(issue, STATION, trajectories)


def test_netcdf_contract_and_t_route_selection(tmp_path: Path) -> None:
    issue = utc(2023, 12, 10)
    series = build_rfc_timeseries(issue, STATION, make_trajectories(issue))
    path = tmp_path / output_filename(issue, STATION.gage)
    write_rfc_netcdf(series, path, "test-sha")
    assert validate_rfc_netcdf(path, series) == []
    with netCDF4.Dataset(path) as dataset:
        assert dataset.dimensions["forecastInd"].isunlimited()
        assert dataset.getncattr("reconstructed") == "true"
        assert dataset.getncattr("NWM_version_number") == "v3.0"
        assert int(dataset.variables["queryTime"][0]) > 0
    filenames = [
        output_filename(utc(2023, 12, 9), STATION.gage),
        path.name,
    ]
    # Selection happens once, at each planned chunk start. A midnight start cannot
    # see the current issue; the 18Z restart can.
    assert select_issue_for_chunk(utc(2023, 12, 10, 0), STATION.gage, filenames) == utc(
        2023, 12, 9
    )
    assert (
        select_issue_for_chunk(utc(2023, 12, 10, 18), STATION.gage, filenames) == issue
    )
    assert (
        select_issue_for_chunk(
            utc(2023, 12, 10, 18),
            STATION.gage,
            [output_filename(utc(2023, 12, 9), STATION.gage)],
        )
        is None
    )
    chunks = [(utc(2023, 12, 10, 18), utc(2023, 12, 11, 18), issue)]
    assert validate_with_troute_loader(chunks, {STATION.gage: STATION}, tmp_path) == []


def test_forcing_directory_rejects_nonforcing_artifacts(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("not allowed", encoding="utf-8")
    findings = validate_forcing_directory(tmp_path)
    assert len(findings) == 1
    assert findings[0].severity == "error"


def test_target_dry_run(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code = main(
        [
            "all",
            "--simulation-start",
            "2023-12-10T00:00:00Z",
            "--simulation-end",
            "2023-12-21T00:00:00Z",
            "--output-root",
            str(tmp_path / "output"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--dry-run",
        ]
    )
    output = capsys.readouterr().out
    assert code == 0
    assert "2023-12-09T12:00:00Z" in output
    assert "2023-12-20T12:00:00Z" in output
    assert "2023-12-06 through 2023-12-20" in output
    assert "Objects: 360" in output
    assert output.count("RFCTimeSeries.ncdf") == 60


@pytest.mark.skipif(
    not os.environ.get("NERFC_NWM_CACHE"),
    reason="set NERFC_NWM_CACHE to a cache populated by the reconstruction utility",
)
def test_december_10_public_nwm_pilot_values() -> None:
    cache = Path(os.environ["NERFC_NWM_CACHE"])
    stations = load_station_config(HERE / "nerfc_reconstruction_stations.json")
    points = extract_source_points(
        utc(2023, 12, 10),
        1,
        stations,
        1,
        cache,
        FeatureIndexStore(cache / "feature_indices.json"),
    )
    expected = {
        "BNGM1": 85.47,
        "STDM1": 7.65,
        "RKWM1": 34.04,
        "SCIR1": 2.57,
        "STVC3": 171.09,
    }
    assert all(point.accepted for point in points)
    for point in points:
        assert point.discharge_cms == pytest.approx(expected[point.gage], abs=0.02)
        assert point.model_valid_time_utc == utc(2023, 12, 10, 19)
