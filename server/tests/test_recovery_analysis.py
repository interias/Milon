"""Synthetic recovery associations: time ordering, missingness and day-level statistics."""
from datetime import date, datetime, timedelta, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.recovery_analysis import router
from app.checkins import CheckIn
from app.garmin_daily import GarminDaily, PACKAGE
from app.metrics import recovery_analysis as analysis, sleep
from app.models import ExerciseSession, RunAnnotation, SleepSession, Workout, WorkoutSet

DAY = date(2026, 10, 3)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(analysis, "engine", engine)
    monkeypatch.setattr(sleep, "engine", engine)
    monkeypatch.setattr(analysis.settings, "watch_source_switch_date", date(2026, 10, 1))
    monkeypatch.setattr(analysis.settings, "watch_source_package", PACKAGE)
    monkeypatch.setattr(analysis.settings, "steps_source_package", "old")
    monkeypatch.setattr(analysis.settings, "watch_source_legacy_session_ids", [])
    monkeypatch.setattr(analysis.settings, "timezone", "Europe/Berlin")
    yield engine
    engine.dispose()


def run(session, day=DAY, *, hour=16, suffix="", hr=150, excluded=False):
    start = datetime.combine(day, datetime.min.time()).replace(hour=hour)
    external_id = f"run-{day}-{suffix}"
    session.add(ExerciseSession(external_id=external_id, exercise_type=33, started_at=start,
                               ended_at=start + timedelta(minutes=30), distance_km=5, avg_hr=hr))
    if excluded:
        session.add(RunAnnotation(external_id=external_id, exclude=True))
    return external_id


def hrv(session, day=DAY, *, value=50, measured_at="default", sleep_end=None):
    measured_at = f"{day}T06:00:00+00:00" if measured_at == "default" else measured_at
    data = {"hrv": {"hrv_ms": value, "measured_at": measured_at}}
    if sleep_end is not None:
        data["sleep"] = {"ended_at_utc": sleep_end, "asleep_minutes": None, "main_sleep": True}
    session.add(GarminDaily(day=day, normalized_json=json.dumps(data)))


def energy(session, day=DAY, *, value=3, session_id=None, kind=None):
    session.add(CheckIn(day=day, energy=value, session_external_id=session_id, session_kind=kind,
                        updated_at=datetime(2026, 11, 1, 22, tzinfo=timezone.utc)))


def test_hrv_requires_prior_recorded_end_and_does_not_forward_fill(db):
    with Session(db) as session:
        run(session, DAY, hour=7, suffix="before")  # 06:00 UTC is 08:00 local.
        run(session, DAY, hour=8, suffix="equal")
        run(session, DAY, hour=16, suffix="after")
        run(session, DAY, hour=18, suffix="second")
        hrv(session)
        run(session, DAY + timedelta(days=1))  # No carry-forward from previous night.
        run(session, DAY + timedelta(days=2))
        hrv(session, DAY + timedelta(days=2), measured_at=None)
        session.commit()
    group = analysis.performance("hrv", today=DAY + timedelta(days=2))["groups"][0]
    assert group["n"] == 1
    assert group["points"][0]["session_count"] == 2
    assert group["points"][0]["measured_at"] == "2026-10-03T08:00:00"
    assert group["missing"]["after_training"] == 2
    assert group["missing"]["no_measurement"] == 1
    assert group["missing"]["unknown_timing"] == 1
    assert group["correlation"] is None


def test_hrv_can_use_same_nights_recorded_end_even_if_sleep_duration_unknown(db):
    with Session(db) as session:
        run(session)
        hrv(session, measured_at=None, sleep_end=f"{DAY}T06:00:00Z")
        next_day = DAY + timedelta(days=1)
        run(session, next_day)
        hrv(session, next_day, measured_at=None, sleep_end=f"{DAY}T06:00:00Z")
        session.commit()
    group = analysis.performance("hrv", today=next_day)["groups"][0]
    assert group["n"] == 1
    assert group["points"][0]["timing_source"] == "sleep_end"
    assert group["missing"]["unknown_timing"] == 1


def test_hrv_respects_watch_cutoff_and_exclusions(db, monkeypatch):
    previous = date(2026, 9, 30)
    with Session(db) as session:
        run(session, previous)
        hrv(session, previous)
        run(session, excluded=True)
        hrv(session)
        legacy = run(session, DAY + timedelta(days=1))
        hrv(session, DAY + timedelta(days=1))
        session.commit()
    monkeypatch.setattr(analysis.settings, "watch_source_legacy_session_ids", [legacy])
    groups = {group["package"]: group for group in analysis.performance("hrv", source="all", today=DAY + timedelta(days=1))["groups"]}
    assert groups["old"]["missing"]["no_measurement"] == 1
    assert groups[PACKAGE]["missing"]["excluded"] == 2
    assert all(group["n"] == 0 for group in groups.values())


def test_nap_end_cannot_stand_in_for_unknown_hrv_timing(db):
    with Session(db) as session:
        run(session)
        session.add(GarminDaily(day=DAY, normalized_json=json.dumps({
            "hrv": {"hrv_ms": 50}, "sleep": {"ended_at_utc": f"{DAY}T12:00:00Z", "main_sleep": False}})))
        session.commit()
    group = analysis.performance("hrv", today=DAY)["groups"][0]
    assert group["n"] == 0
    assert group["missing"]["unknown_timing"] == 1


def test_checkin_is_explicitly_same_day_self_report_not_prior_predictor(db):
    with Session(db) as session:
        run(session, suffix="first", hr=140)
        run(session, hour=18, suffix="second", hr=160)
        energy(session, value=4)
        run(session, DAY + timedelta(days=1))
        session.commit()
    result = analysis.performance("energy", today=DAY + timedelta(days=1))
    group = result["groups"][0]
    assert result["timing"] == "same_day_self_report"
    assert "keine Vorhersage" in result["method"]
    assert group["n"] == 1
    assert group["points"][0]["session_count"] == 2
    assert group["points"][0]["measured_at"] is None
    assert group["points"][0]["value"] == pytest.approx(np.median([1000 / 6 / 140, 1000 / 6 / 160]))
    assert group["missing"]["no_measurement"] == 1


def test_linked_checkin_only_pairs_selected_session_and_kind(db):
    with Session(db) as session:
        selected = run(session, suffix="selected", hr=140)
        run(session, hour=18, suffix="other", hr=180)
        energy(session, session_id=selected, kind="run")
        second_day = DAY + timedelta(days=1)
        other_id = run(session, second_day)
        energy(session, second_day, session_id=other_id, kind="strength")
        third_day = DAY + timedelta(days=2)
        run(session, third_day)
        energy(session, third_day, session_id="deleted", kind="run")
        session.commit()
    group = analysis.performance("energy", today=third_day)["groups"][0]
    assert group["n"] == 1
    assert group["points"][0]["session_id"] == selected
    assert group["points"][0]["session_count"] == 1
    assert group["missing"]["other_session"] == 3


def test_strength_energy_compares_matching_exercises_without_new_exercise_bias(db):
    with Session(db) as session:
        for offset, weight in enumerate((50, 55)):
            day = DAY + timedelta(days=3 * offset)
            workout = Workout(external_id=f"gym-{offset}", started_at=datetime.combine(day, datetime.min.time()).replace(hour=16))
            session.add(workout)
            session.flush()
            session.add(WorkoutSet(workout_id=workout.id, exercise="Press", set_type="normal", weight_kg=weight, reps=8))
            session.add(WorkoutSet(workout_id=workout.id, exercise=f"New-{offset}", set_type="normal", weight_kg=500, reps=8))
            energy(session, day)
        session.commit()
    group = analysis.performance("energy", "strength", today=DAY + timedelta(days=3))["groups"][0]
    assert group["n"] == 1
    assert group["points"][0]["value"] == pytest.approx(10)
    assert group["missing"]["no_outcome"] == 1


def test_sleep_wrapper_keeps_source_groups_and_timing(db):
    with Session(db) as session:
        for day, package in [(date(2026, 9, 30), "old"), (DAY, PACKAGE)]:
            end = datetime.combine(day, datetime.min.time()).replace(hour=8)
            session.add(SleepSession(external_id=f"sleep-{day}", day=day, source_package=package,
                                     started_at=end - timedelta(hours=8), ended_at=end,
                                     duration_window_minutes=480, asleep_minutes=420, stage_coverage=1))
            run(session, day)
        session.commit()
    result = analysis.performance("sleep", source="all", today=DAY)
    assert sorted(group["n"] for group in result["groups"]) == [1, 1]
    assert all(group["points"][0]["predictor"] == 7 for group in result["groups"])


def points(n=30, gap=2):
    return [{"date": (DAY + timedelta(days=index * gap)).isoformat(), "predictor": float(index), "value": float(index)} for index in range(n)]


def test_shared_linear_trend_is_not_presented_as_time_adjusted_effect():
    result = analysis._statistics(points(), "hrv")
    assert result["correlation"] == 1
    assert result["detrended_correlation"] is None
    assert "zu wenig Streuung" in result["detrended_label"]


def test_time_adjusted_association_removes_common_trend():
    data = points(40)
    for index, point in enumerate(data):
        point["predictor"] = 20 * index + np.sin(index)
        point["value"] = 20 * index + np.cos(index)
    result = analysis._statistics(data, "hrv")
    assert result["correlation"] > .99
    assert abs(result["detrended_correlation"]) < .1


def test_small_samples_short_periods_and_constant_values_do_not_overclaim():
    assert analysis._statistics(points(9), "hrv")["correlation"] is None
    short = analysis._statistics(points(20, gap=1), "hrv")
    assert short["correlation"] == 1
    assert short["detrended_correlation"] is None
    flat = points(25)
    for point in flat:
        point["predictor"] = 3
    assert analysis._statistics(flat, "energy")["status"] == "no_variation"


def test_energy_uses_average_ranks_for_ties():
    assert list(analysis._rank(np.array([1, 1, 3, 5, 5]))) == [1.5, 1.5, 3, 4.5, 4.5]
    data = points(20)
    for index, point in enumerate(data):
        point["predictor"] = index % 5 + 1
        point["value"] = point["predictor"] ** 3
    result = analysis._statistics(data, "energy")
    assert result["statistic"] == "ρ"
    assert result["correlation"] == 1


def test_endpoint_validation_and_real_json_payload(db):
    with Session(db) as session:
        run(session)
        hrv(session)
        session.commit()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/metrics/recovery/performance?metric=hrv&kind=run&days=730")
    assert response.status_code == 200
    assert response.json()["timing"] == "prior_night"
    for query in ["metric=readiness", "kind=cycling", "source=unknown", "days=731", "days=0"]:
        assert client.get(f"/metrics/recovery/performance?{query}").status_code == 422
