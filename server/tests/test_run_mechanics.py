import copy
import json
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import garmin_activity, garmin_load
from app.api import run_mechanics as api
from app.metrics import run_mechanics as mechanics
from app.models import RunAnnotation, Workout, WorkoutSet
from test_garmin_activity import recording as raw_recording
from test_run_insights import recording


def mechanics_recording():
    summary, series = recording()
    for point in series:
        late = point["elapsed_seconds"] >= 1440
        point.update(step_speed_loss_pct=5 if late else 4, ground_contact_ms=290 if late else 280,
                     stride_length_cm=95, vertical_ratio_pct=8, ground_contact_balance_left_pct=50)
    return summary, series


def test_mechanics_pairs_are_distinct_and_descriptive():
    summary, series = mechanics_recording()
    result = mechanics.compare_mechanics(summary, series)
    metric = result["metrics"][0]
    assert metric["status"] == "observed" and metric["pairs"] == 14
    assert metric["early"] == pytest.approx(4.001, abs=.002)
    assert metric["late"] == 5
    assert metric["delta"] == pytest.approx(.999, abs=.002)
    assert metric["delta_min"] <= metric["delta"] <= metric["delta_max"]
    assert metric["pace_delta_seconds"] == 0
    assert "keine Mischung" in result["method"]
    assert "beweisen weder Ermüdung" in result["method"]


@pytest.mark.parametrize("problem", ["missing_channel", "faster", "pause", "gap", "missing_altitude", "excluded"])
def test_comparison_does_not_bridge_missing_or_incompatible_minutes(problem):
    summary, series = mechanics_recording()
    if problem == "missing_channel":
        for point in series:
            if point["elapsed_seconds"] >= 1440:
                point["step_speed_loss_pct"] = None
    elif problem == "faster":
        for point in series:
            if point["elapsed_seconds"] >= 1440:
                point["speed_m_s"] = 4
    elif problem in {"pause", "gap"}:
        for point in series:
            if point["elapsed_seconds"] >= 1440:
                point["gap"] = problem == "gap"
                point["timer_seconds"] = 1440 if problem == "pause" else point["timer_seconds"]
    elif problem == "missing_altitude":
        for point in series:
            point["altitude_m"] = None
    result = mechanics.compare_mechanics(summary, series, problem != "excluded")
    assert result["metrics"][0]["delta"] is None


def test_channel_coverage_does_not_inherit_heart_rate_coverage():
    summary, series = mechanics_recording()
    for point in series:
        if point["elapsed_seconds"] % 60 < 10:
            point["step_speed_loss_pct"] = None
    result = mechanics.compare_mechanics(summary, series)
    assert result["metrics"][0]["known_minutes"] == 0
    assert result["metrics"][1]["status"] == "observed"


def test_normalization_checks_optional_units_and_confirms_impact_scale():
    raw, details = raw_recording()
    raw["summaryDTO"].update(impactLoad=5400, stepSpeedLossPercent=4, stepSpeedLoss=.12)
    added = [("directGroundContactTime", "ms", 280), ("directStrideLength", "centimeter", 95),
             ("directStepSpeedLossPercent", "dimensionless", 4),
             ("directStepSpeedLoss", "meter", .12), ("directImpactLoadFactor", "dimensionless", 1)]
    for key, unit, value in added:
        index = len(details["metricDescriptors"])
        details["metricDescriptors"].append({"key": key, "metricsIndex": index, "unit": {"key": unit, "factor": 100}})
        for row in details["activityDetailMetrics"]:
            row["metrics"].append(value)
    summary = garmin_activity.normalize_summary(raw)
    series, quality = garmin_activity.normalize_recording(summary, details)
    assert series[100]["ground_contact_ms"] == 280
    assert series[100]["stride_length_cm"] == 95
    assert series[100]["step_speed_loss_pct"] == 4
    assert "step_speed_loss_cm_s" not in series[100]
    assert summary["impact_load_km"] == 5.4 and quality["impact_unit_verified"]
    wrong = copy.deepcopy(details)
    next(d for d in wrong["metricDescriptors"] if d["key"] == "directGroundContactTime")["unit"]["key"] = "second"
    assert garmin_activity.normalize_recording(garmin_activity.normalize_summary(raw), wrong)[0][100]["ground_contact_ms"] is None
    raw["summaryDTO"]["impactLoad"] = 5.4
    summary = garmin_activity.normalize_summary(raw)
    _, quality = garmin_activity.normalize_recording(summary, details)
    assert summary["impact_load_km"] is None and not quality["impact_unit_verified"]


def test_missing_impact_factor_does_not_guess_summary_unit():
    raw, details = raw_recording()
    raw["summaryDTO"]["impactLoad"] = 5400
    summary = garmin_activity.normalize_summary(raw)
    _, quality = garmin_activity.normalize_recording(summary, details)
    assert summary["impact_load_km"] is None
    assert quality["complete"] and not quality["impact_unit_verified"]


def test_old_parser_refetches_without_full_import_and_preserves_canonical_id(db, monkeypatch):
    from app.models import ExerciseSession, RunBestEffort, RunMinute
    from test_garmin_activity import FakeApi
    SQLModel.metadata.create_all(db, tables=[ExerciseSession.__table__, RunBestEffort.__table__,
        RunMinute.__table__, garmin_activity.GarminActivityAlias.__table__])
    monkeypatch.setattr(garmin_activity, "engine", db)
    provider = FakeApi()
    assert garmin_activity.sync_activities(provider, provider.listing())["imported"] == 1
    with Session(db) as session:
        old = session.get(garmin_activity.GarminActivity, "123")
        canonical = old.canonical_external_id
        old.parser_version = "garmin-recording-v2"
        session.add(old); session.commit()
    provider.calls.clear()
    assert garmin_activity.sync_activities(provider, provider.listing())["imported"] == 1
    assert any(call[0] == "details" for call in provider.calls)
    with Session(db) as session:
        row = session.get(garmin_activity.GarminActivity, "123")
        assert row.canonical_external_id == canonical
        assert row.parser_version == garmin_activity.PARSER_VERSION


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'mechanics.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[garmin_activity.GarminActivity.__table__, RunAnnotation.__table__,
        Workout.__table__, WorkoutSet.__table__, garmin_load.GarminRunningTolerance.__table__])
    monkeypatch.setattr(mechanics, "engine", engine)
    monkeypatch.setattr(garmin_load, "engine", engine)
    monkeypatch.setattr(garmin_load.settings, "watch_source_switch_date", date(2026, 9, 25))
    monkeypatch.setattr(garmin_load.settings, "watch_source_package", "com.garmin.android.apps.connectmobile")
    monkeypatch.setattr(garmin_load.settings, "watch_source_legacy_session_ids", [])
    yield engine
    engine.dispose()


def save_run(session, id, impact=11, canonical=None, complete=True, verified=True):
    summary, series = mechanics_recording()
    summary.update(distance_km=10, impact_load_km=impact)
    session.add(garmin_activity.GarminActivity(activity_id=id, canonical_external_id=canonical or f"run-{id}",
        started_at=datetime(2026, 10, 2, 10), fetched_at=datetime(2026, 10, 3, 12),
        summary_json=json.dumps(summary), series_json=json.dumps(series), laps_json="[]", zones_json="[]",
        quality_json=json.dumps({"complete": complete, "canonical": complete, "impact_unit_verified": verified}), fingerprint="x"))


def test_load_compares_same_runs_only_deduplicates_and_keeps_leg_days_separate(db):
    with Session(db) as session:
        save_run(session, "1", canonical="same-run")
        save_run(session, "2", canonical="same-run")
        save_run(session, "3", impact=None)
        save_run(session, "4", impact=12, verified=False)
        save_run(session, "5", complete=False)
        workout = Workout(external_id="gym", source="hevy", started_at=datetime(2026, 10, 2, 17))
        session.add(workout); session.flush()
        for index in range(3):
            session.add(WorkoutSet(workout_id=workout.id, exercise="Leg Press", set_index=index, reps=10, weight_kg=100, set_type="normal"))
        session.commit()
    result = mechanics.load(2, date(2026, 10, 5))
    week = result["weeks"][0]
    assert week["runs"] == 3 and week["paired_runs"] == 1
    assert week["all_distance_km"] == 30 and week["distance_km"] == 10 and week["impact_load_km"] == 11
    assert week["leg_days"] == ["2026-10-02"] and week["excluded_runs"] == 1
    assert result["weeks"][1]["impact_load_km"] is None
    assert not result["tolerance"]["available"]


def test_tolerance_daily_fields_are_positive_bounded_and_not_weekly_totals():
    raw = [{"calendarDate": "2026-10-02", "acuteTolerance": "50000", "acuteImpactLoad": 18000, "acuteDistance": 16000},
           {"calendarDate": "2026-10-03", "tolerance": 70000, "totalImpactLoad": 30000},
           {"calendarDate": "2026-10-04", "acuteTolerance": 0},
           {"calendarDate": "2026-10-05", "acuteTolerance": float("inf")},
           {"calendarDate": "2026-10-06", "acuteTolerance": 40000}]
    result = garmin_load.normalize(raw, date(2026, 9, 25), date(2026, 10, 5))
    assert result == [{"date": "2026-10-02", "tolerance_km": 50, "acute_load_km": 18, "distance_km": 16}]
    assert garmin_load.normalize([], date(2026, 9, 25), date(2026, 10, 5)) == []
    for bad in (None, {}, [0] * 101):
        with pytest.raises(ValueError):
            garmin_load.normalize(bad, date(2026, 9, 25), date(2026, 10, 5))


def test_tolerance_empty_is_not_error_and_failed_optional_read_preserves_values(db):
    class Api:
        raw = []
        calls = 0
        failure = False
        def get_running_tolerance(self, start, end, aggregation):
            assert start == "2026-09-25" and end == "2026-10-05" and aggregation == "daily"
            self.calls += 1
            if self.failure:
                raise RuntimeError("private payload")
            return self.raw
    api = Api(); now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    assert garmin_load.sync_tolerance(api, now=now)["status"] == "empty"
    assert garmin_load.sync_tolerance(api, now=now)["status"] == "throttled" and api.calls == 1
    api.raw = [{"calendarDate": "2026-10-05", "acuteTolerance": 40000}]
    assert garmin_load.sync_tolerance(api, now=now, force=True)["status"] == "available"
    api.failure = True
    assert garmin_load.sync_tolerance(api, now=now, force=True)["status"] == "error"
    with Session(db) as session:
        status = garmin_load.tolerance_status(session, date(2026, 10, 5))
    assert status["available"] and status["stale"] and status["tolerance_km"] == 40
    assert "private" not in json.dumps(status)


def test_optional_tolerance_failure_does_not_fail_running_or_daily_sync(monkeypatch):
    from app import garmin_daily, garmin_weather
    from app.ingest import garmin
    monkeypatch.setattr(garmin, "_pull_routes", lambda *args: {"errors": 0, "imported": 0})
    monkeypatch.setattr(garmin_activity, "sync_activities", lambda *args, **kwargs: {"errors": 0})
    monkeypatch.setattr(garmin_daily, "sync_daily", lambda *args, **kwargs: {"errors": 0})
    monkeypatch.setattr(garmin_weather, "sync_weather", lambda *args, **kwargs: {"errors": 0})
    monkeypatch.setattr(garmin_load, "sync_tolerance", lambda *args, **kwargs: {"status": "error", "errors": 1})
    result = garmin._pull_all(object(), False)
    assert result["errors"] == 0 and result["running_tolerance"]["errors"] == 1


def test_endpoint_uses_local_recording_and_unknown_id_is_404(db):
    with Session(db) as session:
        save_run(session, "1"); session.commit()
    app = FastAPI(); app.include_router(api.router)
    client = TestClient(app)
    response = client.get("/metrics/running/mechanics/1")
    assert response.status_code == 200 and response.json()["metrics"][0]["status"] == "observed"
    assert client.get("/metrics/running/mechanics/missing").status_code == 404
    assert client.get("/metrics/running/mechanics/load?weeks=0").status_code == 422
