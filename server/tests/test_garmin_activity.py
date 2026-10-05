import copy
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlmodel import SQLModel, Session, create_engine, select

from app import garmin_activity as activity
from app.api import garmin_activity as activity_api
from app.models import ExerciseSession, RunAnnotation, RunBestEffort, RunMinute


START = datetime(2026, 10, 2, 10)
UTC = START.replace(hour=8, tzinfo=timezone.utc)
KEYS = ["directTimestamp", "sumElapsedDuration", "sumDuration", "sumDistance", "directHeartRate",
        "directSpeed", "directDoubleCadence", "directRunCadence", "directElevation", "directPower"]


def recording(seconds=1800, pause=0):
    raw = {"activityId": 123, "activityName": "Synthetic run", "activityTypeDTO": {"typeKey": "running"}, "summaryDTO": {
        "startTimeGMT": "2026-10-02T08:00:00.000", "startTimeLocal": "1999-01-01T01:00:00",
        "distance": seconds * 3, "duration": seconds, "elapsedDuration": seconds + pause,
        "averageHR": 150, "maxHR": 160, "averageRunCadence": 170, "averageSpeed": 3,
        "averagePower": 250, "elevationGain": 10, "trainingEffect": 2.5}}
    descriptors = [{"key": key, "metricsIndex": index,
                    "unit": {"factor": 1000 if "Duration" in key else .1}}
                   for index, key in enumerate(KEYS)]
    metrics = []
    for second in range(seconds + 1):
        elapsed = second + (pause if second > seconds // 2 else 0)
        metrics.append({"metrics": [UTC.timestamp() * 1000 + elapsed * 1000, elapsed, second,
                                    second * 3, 150, 3, 170, 85, 100, 250]})
    details = {"metricDescriptors": descriptors, "activityDetailMetrics": metrics,
               "metricsCount": len(metrics), "totalMetricsCount": len(metrics),
               "detailsAvailable": True, "pendingData": False}
    return raw, details


class FakeApi:
    def __init__(self, raw=None, details=None):
        original, recording_details = recording()
        self.raw, self.details = raw or original, details or recording_details
        self.calls = []
        self.failure = False
        self.optional_failure = False

    def get_activity(self, activity_id):
        self.calls.append(("summary", activity_id))
        if self.failure:
            raise RuntimeError("sensitive remote response")
        return copy.deepcopy(self.raw)

    def get_activity_details(self, activity_id, **kwargs):
        self.calls.append(("details", kwargs))
        return copy.deepcopy(self.details)

    def get_activity_splits(self, activity_id):
        if self.optional_failure:
            raise RuntimeError("private")
        return {"lapDTOs": [{"lapIndex": 1, "distance": 1000, "duration": 333.3, "averageHR": 150}]}

    def get_activity_hr_in_timezones(self, activity_id):
        if self.optional_failure:
            raise RuntimeError("private")
        return [{"zoneNumber": 1, "zoneLowBoundary": 90, "secsInZone": 30},
                {"zoneNumber": 2, "zoneLowBoundary": 110, "secsInZone": 120}]

    def listing(self):
        return [{"activityId": self.raw["activityId"], "activityName": self.raw["activityName"], **self.raw["summaryDTO"]}]


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'activity.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[activity.GarminActivity.__table__,
        activity.GarminActivityAlias.__table__, ExerciseSession.__table__, RunMinute.__table__,
        RunBestEffort.__table__, RunAnnotation.__table__])
    monkeypatch.setattr(activity, "engine", engine)
    monkeypatch.setattr(activity.settings, "watch_source_switch_date", date(2026, 9, 25))
    monkeypatch.setattr(activity.settings, "watch_source_package", activity.GARMIN_PACKAGE)
    monkeypatch.setattr(activity.settings, "watch_source_legacy_session_ids", [])
    monkeypatch.setattr(activity.settings, "timezone", "Europe/Berlin")
    yield engine
    engine.dispose()


def hc_run(external_id="hc-existing", start=START, distance=5.4, duration=1800):
    return {"external_id": external_id, "exercise_type": 33, "started_at": start,
            "ended_at": start + timedelta(seconds=duration), "distance_km": distance,
            "source": "health_connect", "avg_hr": 145}


def test_normalization_uses_utc_and_si_values_not_descriptor_factors(db):
    raw, details = recording()
    summary = activity.normalize_summary(raw)
    series, quality = activity.normalize_recording(summary, details)
    assert summary["started_at"] == START.isoformat()
    assert quality["complete"] and quality["hr_coverage"] == 1
    assert series[10]["speed_m_s"] == 3
    assert series[10]["distance_m"] == 30
    assert series[10]["cadence_spm"] == 170
    assert series[10]["timer_seconds"] == 10
    assert "latitude" not in json.dumps(series).lower()


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(totalMetricsCount=2000),
    lambda d: d.update(metricsCount=10),
    lambda d: d.update(pendingData=True),
    lambda d: d.update(detailsAvailable=False),
    lambda d: d["activityDetailMetrics"][20]["metrics"].__setitem__(0, None),
    lambda d: d["activityDetailMetrics"][-1]["metrics"].__setitem__(3, 54),
    lambda d: d["activityDetailMetrics"][-1]["metrics"].__setitem__(2, 18),
])
def test_incomplete_recording_never_claims_complete(db, mutate):
    raw, details = recording()
    mutate(details)
    _, quality = activity.normalize_recording(activity.normalize_summary(raw), details)
    assert not quality["complete"] and quality["reason"]


def test_dense_initial_samples_do_not_disguise_a_large_missing_time_span(db):
    raw, details = recording()
    details["activityDetailMetrics"] = details["activityDetailMetrics"][:1000] + details["activityDetailMetrics"][-2:]
    details["metricsCount"] = details["totalMetricsCount"] = len(details["activityDetailMetrics"])
    _, quality = activity.normalize_recording(activity.normalize_summary(raw), details)
    assert not quality["complete"]
    assert quality["hr_coverage"] < .6


def test_invalid_values_remain_missing_and_single_leg_cadence_is_not_used(db):
    raw, details = recording()
    for row in details["activityDetailMetrics"]:
        row["metrics"][6] = None
    details["activityDetailMetrics"][50]["metrics"][4] = float("nan")
    series, _ = activity.normalize_recording(activity.normalize_summary(raw), details)
    assert all(point["cadence_spm"] is None for point in series)
    assert series[50]["hr_bpm"] is None
    windows = activity.minute_windows(series, "run", 1800)
    assert windows[0]["coverage"] < 1


def test_pauses_remain_elapsed_time_and_break_minute_interpolation(db):
    raw, details = recording(seconds=1800, pause=9)
    summary = activity.normalize_summary(raw)
    series, quality = activity.normalize_recording(summary, details)
    assert quality["complete"]
    assert sum(point["gap"] for point in series) == 1
    windows = activity.minute_windows(series, "run", summary["elapsed_seconds"])
    assert windows[15]["coverage"] < .9
    assert not windows[15]["steady"]
    assert windows[0]["speed_m_min"] == 180
    assert windows[0]["hr_bpm"] == 150
    assert activity.best_efforts(series)[5000] == pytest.approx(5000 / 3 + 9, abs=.1)


def test_best_efforts_do_not_bridge_unknown_gaps_or_use_gps(db):
    raw, details = recording()
    series, _ = activity.normalize_recording(activity.normalize_summary(raw), details)
    series = series[:900] + series[1000:]
    result = activity.best_efforts(series)
    assert 5000 not in result
    assert result[1000] == pytest.approx(1000 / 3, abs=.1)


def test_hc_first_preserves_ids_annotations_and_updates_source_owned_inputs(db):
    with Session(db) as session:
        session.add(ExerciseSession(**hc_run()))
        session.add(RunAnnotation(external_id="hc-existing", category="easy", exclude=True))
        session.add(RunMinute(external_id="hc-existing", minute=.5, speed_m_min=100, hr_bpm=100,
                              coverage=.5, steady=False))
        session.commit()
    api = FakeApi()
    result = activity.sync_activities(api, api.listing())
    assert result == {"imported": 1, "skipped": 0, "canonical": 1, "incomplete": 0, "errors": 0}
    with Session(db) as session:
        runs = session.exec(select(ExerciseSession)).all()
        assert len(runs) == 1 and runs[0].external_id == "hc-existing" and runs[0].source == activity.SOURCE
        assert session.get(RunAnnotation, "hc-existing").exclude
        windows = session.exec(select(RunMinute)).all()
        assert len(windows) == 30 and all(row.source == activity.SOURCE for row in windows)
        assert len(session.exec(select(RunBestEffort)).all()) == 2
    assert activity.activity_detail("123")["canonical_external_id"] == "hc-existing"


def test_direct_first_then_hc_records_alias_and_full_hc_cannot_erase_it(db):
    api = FakeApi()
    activity.sync_activities(api, api.listing())
    with Session(db) as session:
        session.add(RunAnnotation(external_id="garmin:123", category="easy"))
        protected = activity.protected_hc_ids(session, [hc_run("hc-later")])
        assert protected == {"garmin:123", "hc-later"}
        # HC's source-based full reconcile only removes its own canonical data.
        for model in (ExerciseSession, RunMinute, RunBestEffort):
            session.execute(delete(model).where(model.source == "health_connect"))
        session.commit()
        assert len(session.exec(select(ExerciseSession)).all()) == 1
        assert session.get(RunAnnotation, "garmin:123").category == "easy"
        assert session.get(activity.GarminActivityAlias, "hc-later").canonical_external_id == "garmin:123"
        assert activity.protected_hc_ids(session, []) == protected


def test_repeated_and_forced_import_are_idempotent(db):
    api = FakeApi()
    activity.sync_activities(api, api.listing())
    assert activity.sync_activities(api, api.listing())["skipped"] == 1
    assert len(api.calls) == 2
    assert activity.sync_activities(api, api.listing(), full=True)["canonical"] == 1
    with Session(db) as session:
        assert len(session.exec(select(ExerciseSession)).all()) == 1
        assert len(session.exec(select(RunMinute)).all()) == 30
        assert len(session.exec(select(RunBestEffort)).all()) == 2


def test_summary_edit_refreshes_canonical_and_keeps_identity(db):
    api = FakeApi()
    activity.sync_activities(api, api.listing())
    api.raw["activityName"] = "Edited title"
    assert activity.sync_activities(api, api.listing())["imported"] == 1
    assert activity.activity_detail("123")["summary"]["title"] == "Edited title"
    assert activity.activity_detail("123")["canonical_external_id"] == "garmin:123"


def test_bad_refresh_preserves_last_successful_recording(db):
    api = FakeApi()
    activity.sync_activities(api, api.listing())
    previous = activity.activity_detail("123")
    api.details["totalMetricsCount"] += 100
    assert activity.sync_activities(api, api.listing(), full=True)["incomplete"] == 1
    current = activity.activity_detail("123")
    assert current["series"] == previous["series"]
    assert current["quality"]["complete"] and current["quality"]["last_issue"]


def test_incomplete_first_import_keeps_hc_metrics_and_displays_quality(db):
    with Session(db) as session:
        session.add(ExerciseSession(**hc_run()))
        session.commit()
    api = FakeApi()
    api.details["totalMetricsCount"] += 1
    assert activity.sync_activities(api, api.listing())["incomplete"] == 1
    with Session(db) as session:
        run = session.exec(select(ExerciseSession)).one()
        assert run.source == "health_connect" and run.avg_hr == 145
        assert activity.protected_hc_ids(session, [hc_run()]) == set()
    assert activity.activity_detail("123")["quality"]["canonical"] is False


@pytest.mark.parametrize("condition", ["historical", "ambiguous", "legacy"])
def test_uncertain_ownership_does_not_create_or_replace_canonical_sessions(db, monkeypatch, condition):
    with Session(db) as session:
        session.add(ExerciseSession(**hc_run()))
        if condition == "ambiguous":
            session.add(ExerciseSession(**hc_run("other")))
        session.commit()
    if condition == "historical":
        monkeypatch.setattr(activity.settings, "watch_source_switch_date", date(2026, 11, 1))
    if condition == "legacy":
        monkeypatch.setattr(activity.settings, "watch_source_legacy_session_ids", ["hc-existing"])
    api = FakeApi()
    assert activity.sync_activities(api, api.listing())["canonical"] == 0
    with Session(db) as session:
        assert all(row.source == "health_connect" for row in session.exec(select(ExerciseSession)).all())
    assert activity.activity_detail("123")["quality"]["reason"]


@pytest.mark.parametrize("kind", ["treadmill_running", "indoor_running", "virtual_run", "unknown", None])
def test_unsupported_run_subtypes_do_not_duplicate_or_replace_hc_treadmill_sessions(db, kind):
    incoming = hc_run()
    incoming["exercise_type"] = 58
    with Session(db) as session:
        session.add(ExerciseSession(**incoming))
        session.commit()
    api = FakeApi()
    api.raw["activityTypeDTO"]["typeKey"] = kind
    assert activity.sync_activities(api, api.listing())["canonical"] == 0
    with Session(db) as session:
        original = session.exec(select(ExerciseSession)).one()
        assert original.exercise_type == 58 and original.source == "health_connect"
        assert activity.protected_hc_ids(session, [incoming]) == set()
    details = activity.activity_detail("123")
    assert details["available"] and details["series"]
    assert details["quality"]["complete"] and not details["quality"]["canonical"]
    assert "Aktivitätstyp" in details["quality"]["reason"]


def test_optional_data_failure_preserves_laps_and_zones(db):
    api = FakeApi()
    activity.sync_activities(api, api.listing())
    previous = activity.activity_detail("123")
    api.optional_failure = True
    assert activity.sync_activities(api, api.listing(), full=True)["canonical"] == 1
    current = activity.activity_detail("123")
    assert current["laps"] == previous["laps"]
    assert current["zones"] == previous["zones"]
    assert current["zones"][0]["hr_high"] == 109


def test_remote_failure_is_counted_without_exposing_response(db):
    api = FakeApi()
    api.failure = True
    result = activity.sync_activities(api, api.listing())
    assert result["errors"] == 1
    assert "sensitive" not in json.dumps(result)


@pytest.mark.parametrize("total,expected_limits", [(21000, [20000, 21000]), (100001, [20000])])
def test_detail_request_adapts_once_with_a_hard_cap(db, total, expected_limits):
    api = FakeApi()
    api.details["totalMetricsCount"] = total
    result = activity.sync_activities(api, api.listing())
    assert result["incomplete"] == 1 and result["canonical"] == 0
    assert [arguments["maxchart"] for name, arguments in api.calls if name == "details"] == expected_limits


@pytest.mark.parametrize("hc_first", [False, True])
@pytest.mark.parametrize("full", [False, True])
def test_actual_hc_import_preserves_direct_sessions_minutes_and_efforts(db, monkeypatch, hc_first, full):
    from app import garmin_daily
    from app.ingest import health_connect

    SQLModel.metadata.create_all(db)
    incoming = hc_run()
    if hc_first:
        with Session(db) as session:
            session.add(ExerciseSession(**incoming))
            session.commit()
    api = FakeApi()
    activity.sync_activities(api, api.listing())
    data = {"body": {}, "sessions": [incoming], "vo2": [], "steps": [], "resting": [],
            "best_efforts": [{"external_id": incoming["external_id"], "distance_m": 1000,
                              "seconds": 90, "started_at": START, "source": "health_connect"}],
            "best_efforts_invalid_ids": [incoming["external_id"]], "skipped_body": 0,
            "sleep": {"rows": [], "stages_available": False, "available": False},
            "run_windows": {"available": True, "session_ids": [incoming["external_id"]],
                            "rows": [{"external_id": incoming["external_id"], "minute": .5,
                                      "speed_m_min": 999, "hr_bpm": 220, "coverage": 1,
                                      "steady": True, "source": "health_connect"}]}}
    monkeypatch.setattr(health_connect, "engine", db)
    monkeypatch.setattr(health_connect, "read_health_connect", lambda path: copy.deepcopy(data))
    monkeypatch.setattr(garmin_daily, "apply_daily", lambda session: None)
    health_connect.import_health_connect("unused", full=full)
    health_connect.import_health_connect("unused", full=full)
    with Session(db) as session:
        canonical = session.exec(select(ExerciseSession)).one()
        assert canonical.source == activity.SOURCE
        assert canonical.external_id == ("hc-existing" if hc_first else "garmin:123")
        minutes = session.exec(select(RunMinute)).all()
        assert len(minutes) == 30 and all(row.source == activity.SOURCE for row in minutes)
        assert minutes[0].speed_m_min == 180
        efforts = session.exec(select(RunBestEffort)).all()
        assert len(efforts) == 2 and all(row.source == activity.SOURCE for row in efforts)
        assert next(row for row in efforts if row.distance_m == 1000).seconds == pytest.approx(333.3)


def test_display_bound_keeps_pause_and_missing_channels_visible(db):
    raw, details = recording(pause=9)
    details["activityDetailMetrics"][40]["metrics"][4] = None
    api = FakeApi(raw, details)
    activity.sync_activities(api, api.listing())
    detail = activity.activity_detail("123")
    assert len(detail["series"]) <= 600
    assert any(point["gap"] for point in detail["series"])
    assert any(point["hr_bpm"] is None for point in detail["series"])
    assert all("timer_seconds" not in point for point in detail["series"])


def test_api_before_and_after_import(db):
    app = FastAPI()
    app.include_router(activity_api.router)
    with TestClient(app) as client:
        empty = client.get("/metrics/running/activities/123")
        assert empty.status_code == 200 and empty.json()["available"] is False
        api = FakeApi()
        activity.sync_activities(api, api.listing())
        complete = client.get("/metrics/running/activities/123")
        assert complete.status_code == 200
        assert complete.json()["available"] and complete.json()["quality"]["canonical"]
        assert complete.json()["zone_source"] == "garmin_recorded"


def test_legacy_hc_test_databases_without_staging_tables_are_unchanged():
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        assert activity.protected_hc_ids(session, [hc_run()]) == set()
    engine.dispose()
