"""Historical estimates never gain measurements from later months."""
from datetime import date, datetime, timedelta, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.overview_history import router
from app.garmin_activity import GarminActivity
from app.garmin_routes import GarminRoute
from app.metrics import overview_history as history
from app.models import BodyMeasurement, ExerciseSession, Workout, WorkoutSet

NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(history, "engine", engine)
    monkeypatch.setattr(history.settings, "timezone", "Europe/Berlin")
    monkeypatch.setattr(history.settings, "watch_source_switch_date", date(2026, 9, 25))
    yield engine
    engine.dispose()


def save(engine, *rows):
    with Session(engine) as session:
        session.add_all(rows)
        session.commit()


def run(start, identifier, source="health_connect"):
    return ExerciseSession(external_id=identifier, started_at=start, ended_at=start + timedelta(hours=1),
                           distance_km=10, exercise_type=33, source=source)


def test_empty_month_keeps_missing_estimates_unknown(db):
    result = history.history(now=NOW)
    assert len(result["points"]) == 1
    point = result["points"][0]
    assert point["month"] == "2026-10" and point["partial"]
    assert all(point[key]["value"] is None for key in ("body", "running", "strength"))
    recap = history.monthly("2026-09", now=NOW)
    assert recap["runs"] == recap["strength_sessions"] == recap["training_days"] == 0
    assert recap["weight_delta_kg"] is None and recap["routes"] == []


def test_month_end_uses_only_then_available_weight_and_does_not_fill_gaps(db):
    save(db, BodyMeasurement(measured_at=datetime(2026, 7, 31, 8), weight_kg=80, source="health_connect"),
         BodyMeasurement(measured_at=datetime(2026, 9, 30, 8), weight_kg=75, source="health_connect"),
         BodyMeasurement(measured_at=datetime(2026, 10, 4, 8), weight_kg=74, source="health_connect"),
         BodyMeasurement(measured_at=datetime(2026, 10, 5, 23), weight_kg=200, source="health_connect"),
         BodyMeasurement(measured_at=datetime(2027, 1, 1, 8), weight_kg=300, source="health_connect"))
    points = {point["month"]: point for point in history.history(now=NOW)["points"]}
    assert points["2026-07"]["body"]["value"] == 80
    assert points["2026-08"]["body"]["value"] is None
    assert points["2026-09"]["body"]["value"] == 75
    assert points["2026-10"]["body"]["value"] == 74.5
    assert points["2026-09"]["body"]["change_to_now"] == -.5
    assert "2027-01" not in points


@pytest.mark.parametrize("now,month,day", [(datetime(2026, 3, 31, 22, 30, tzinfo=timezone.utc), "2026-04", "2026-04-01"),
    (datetime(2026, 10, 25, 23, 30, tzinfo=timezone.utc), "2026-10", "2026-10-26")])
def test_as_of_uses_local_calendar_including_dst(db, now, month, day):
    point = history.history(now=now)["points"][-1]
    assert (point["month"], point["as_of"]) == (month, day)


def test_strength_eligibility_is_bounded_before_backbone(db, monkeypatch):
    for index, stamp in enumerate([datetime(2026, 8, 1), datetime(2026, 8, 15), datetime(2026, 9, 1), datetime(2026, 10, 2)]):
        with Session(db) as session:
            workout = Workout(started_at=stamp, external_id=f"gym-{index}")
            session.add(workout); session.flush()
            for exercise in ("Squat", "Bench Press", "Row"):
                session.add(WorkoutSet(workout_id=workout.id, exercise=exercise, weight_kg=60 if index < 3 else 200, reps=8, set_type="normal"))
            session.commit()
    result = history.history(now=NOW)
    points = {point["month"]: point for point in result["points"]}
    assert points["2026-08"]["strength"]["value"] is None  # Only two training days then.
    assert points["2026-09"]["strength"]["value"] == 100
    with Session(db) as session:
        future = Workout(started_at=datetime(2028, 1, 1), external_id="future")
        session.add(future); session.flush()
        session.add(WorkoutSet(workout_id=future.id, exercise="Squat", weight_kg=500, reps=8, set_type="normal")); session.commit()
    assert history.history(now=NOW) == result


def test_thin_last_strength_link_is_missing_instead_of_a_carried_index(db):
    for index, stamp in enumerate([datetime(2026, 8, 1), datetime(2026, 8, 15), datetime(2026, 8, 20), datetime(2026, 9, 1)]):
        with Session(db) as session:
            workout = Workout(started_at=stamp, external_id=f"thin-{index}")
            session.add(workout); session.flush()
            for exercise in (("Squat", "Bench Press", "Row") if index < 3 else ("Squat", "Row")):
                session.add(WorkoutSet(workout_id=workout.id, exercise=exercise, weight_kg=60, reps=8, set_type="normal"))
            session.commit()
    points = {point["month"]: point for point in history.history(now=NOW)["points"]}
    value = points["2026-09"]["strength"]
    assert value["comparable_exercises"] == 2 and value["value"] is None and value["change_to_now"] is None
    assert "drei gemeinsame Übungen" in value["note"]


def test_run_inputs_filter_sensor_future_and_cross_midnight_finish(db, monkeypatch):
    save(db, run(datetime(2026, 9, 24, 12), "old-watch"), run(datetime(2026, 9, 26, 12), "new-watch"),
         run(datetime(2026, 9, 30, 23, 30), "finishes-next-month"), run(datetime(2026, 10, 3, 12), "october"))
    from app.models import RunMinute
    save(db, RunMinute(external_id="new-watch", minute=15, speed_m_min=166, hr_bpm=140, coverage=1, steady=True, source="test"))
    calls = []
    original = history.run_standardization._prepare
    def prepare(windows, sessions, day):
        calls.append((day, set(sessions.external_id)))
        return original(windows, sessions, day)
    monkeypatch.setattr(history.run_standardization, "_prepare", prepare)
    history.history(now=NOW)
    assert calls[0] == (date(2026, 9, 30), {"new-watch"})
    assert calls[1][1] == {"new-watch", "finishes-next-month", "october"}


def test_monthly_totals_use_canonical_sessions_and_only_hevy(db):
    save(db, run(datetime(2026, 9, 1), "start"), run(datetime(2026, 9, 30, 12), "end", "garmin_direct"),
         run(datetime(2026, 10, 1), "next"), Workout(started_at=datetime(2026, 9, 1), external_id="gym"),
         Workout(started_at=datetime(2026, 9, 2), external_id="mirror", source="health_connect"),
         Workout(started_at=datetime(2026, 10, 1), external_id="next-gym"))
    result = history.monthly("2026-09", now=NOW)
    assert result["running_km"] == 20 and result["runs"] == 2
    assert result["strength_sessions"] == 1 and result["training_days"] == 2
    assert result["partial"] is False and result["to_date"] == "2026-09-30"


def test_recap_assigns_a_completed_cross_midnight_run_to_its_start_month(db):
    save(db, run(datetime(2026, 9, 30, 23, 30), "midnight"), run(datetime(2026, 10, 5, 13, 30), "still-running"))
    assert history.monthly("2026-09", now=NOW)["runs"] == 1
    assert history.monthly("2026-10", now=NOW)["runs"] == 0


def test_monthly_weight_counts_days_and_requires_separate_windows(db):
    for day in (1, 2, 3, 28, 29, 30):
        save(db, BodyMeasurement(measured_at=datetime(2026, 9, day, 8), weight_kg=80 if day < 10 else 79, source="health_connect"))
    result = history.monthly("2026-09", now=NOW)
    assert result["weight_delta_kg"] == -1
    assert result["weight_first_days"] == result["weight_last_days"] == 3
    assert history.monthly("2026-10", now=NOW)["weight_delta_kg"] is None


def test_route_contours_deduplicate_garmin_aliases(db):
    for index in (1, 2):
        save(db, GarminActivity(activity_id=str(index), canonical_external_id="one-run", started_at=datetime(2026, 9, 29),
             fetched_at=datetime(2026, 10, index), fingerprint=f"test-{index}", summary_json="{}", quality_json="{}", series_json="[]", laps_json="[]", zones_json="[]"),
             GarminRoute(activity_id=str(index), title="Local run", started_at=datetime(2026, 9, 29), synced_at=datetime(2026, 10, index),
                         point_count=2, segments_json=json.dumps([[{"lat": 50, "lon": 8}, {"lat": 50.01, "lon": 8.01}]])))
    result = history.monthly("2026-09", now=NOW)
    assert result["route_count"] == 1 and result["routes"][0]["activity_id"] == "2"
    assert "lat" not in json.dumps(result["routes"]) and result["routes"][0]["contour"]


def test_api_rejects_future_or_malformed_months(db):
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        for value in ("2026-13", "bad", "9999-12", "0000-01"):
            assert client.get("/metrics/overview/monthly", params={"month": value}).status_code == 422
        assert client.get("/metrics/overview/history").status_code == 200
