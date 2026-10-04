from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

from app.api.sleep import router
from app.metrics import sleep
from app.models import ExerciseSession, RunAnnotation, SleepSession, Workout, WorkoutSet


def target_database(tmp_path):
    target = create_engine(f"sqlite:///{tmp_path / 'target.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(target)
    return target


def config():
    return SimpleNamespace(timezone="Europe/Berlin", steps_source_package="old", watch_source_package="new",
                           watch_source_switch_date=date(2026, 9, 25), watch_source_legacy_session_ids=[])


def add_night(session, day, asleep=420, package="new", nap=False, hour=7):
    end = datetime.combine(day, datetime.min.time()).replace(hour=hour)
    duration = 60 if nap else 480
    session.add(SleepSession(external_id=f"{day}-{hour}", started_at=end - timedelta(minutes=duration),
                             ended_at=end, day=day, duration_window_minutes=duration,
                             asleep_minutes=asleep, stage_coverage=1 if asleep is not None else 0,
                             source_package=package, main_sleep=not nap))


def add_run(session, day, suffix="", hour=16, hr=150, excluded=False):
    start = datetime.combine(day, datetime.min.time()).replace(hour=hour)
    external_id = f"run-{day}-{suffix}"
    session.add(ExerciseSession(external_id=external_id, exercise_type=33, started_at=start,
                                ended_at=start + timedelta(minutes=30), distance_km=5, avg_hr=hr))
    if excluded:
        session.add(RunAnnotation(external_id=external_id, exclude=True))


def test_unknown_nights_and_naps_do_not_inflate_sleep_summary(tmp_path):
    target = target_database(tmp_path)
    with Session(target) as session:
        add_night(session, date(2026, 10, 1), asleep=None)
        add_night(session, date(2026, 10, 2), asleep=420)
        add_night(session, date(2026, 10, 2), asleep=40, nap=True, hour=14)
        session.commit()
    with patch.object(sleep, "engine", target), patch.object(sleep, "settings", config()):
        result = sleep.overview(today=date(2026, 10, 3))
    assert result["summary"]["nights_7d"] == 2
    assert result["summary"]["known_asleep_nights_7d"] == 1
    assert result["summary"]["avg_asleep_hours_7d"] == 7
    assert result["summary"]["naps_7d"] == 1
    assert result["series"][0]["asleep_hours"] is None
    target.dispose()


def test_prior_night_pairing_counts_unique_nights_and_missing_reasons(tmp_path):
    target = target_database(tmp_path)
    with Session(target) as session:
        day = date(2026, 10, 1)
        add_night(session, day)
        add_run(session, day, "a")
        add_run(session, day, "b", hour=18)
        add_night(session, day + timedelta(days=1), asleep=None)
        add_run(session, day + timedelta(days=1))
        add_night(session, day + timedelta(days=2), asleep=45, nap=True, hour=14)
        add_run(session, day + timedelta(days=2))
        add_run(session, day + timedelta(days=3), hr=None)
        add_night(session, day + timedelta(days=4))
        add_run(session, day + timedelta(days=4), hour=6)  # Runs before waking must not pair.
        add_run(session, day + timedelta(days=5), excluded=True)
        session.commit()
    with patch.object(sleep, "engine", target), patch.object(sleep, "settings", config()):
        group = sleep.performance(today=date(2026, 10, 6))["groups"][0]
    assert group["n"] == 1
    assert group["points"][0]["session_count"] == 2
    assert group["points"][0]["value"] == pytest.approx(1.111111111)
    assert group["correlation"] is None
    assert group["missing"] == {"no_sleep": 2, "unknown_sleep": 1, "no_outcome": 1, "excluded": 1}
    target.dispose()


def test_sleep_correlation_never_pools_device_regimes(tmp_path):
    target = target_database(tmp_path)
    with Session(target) as session:
        for offset in range(23):
            day = date(2026, 9, 1) + timedelta(days=offset)
            add_night(session, day, asleep=300 + offset * 5, package="old")
            add_run(session, day, hr=160 - offset)
        for offset in range(3):
            day = date(2026, 9, 25) + timedelta(days=offset)
            add_night(session, day, asleep=420 + offset * 5)
            add_run(session, day, hr=140 - offset)
        session.commit()
    with patch.object(sleep, "engine", target), patch.object(sleep, "settings", config()):
        result = sleep.performance(source="all", today=date(2026, 9, 28))
    groups = {group["package"]: group for group in result["groups"]}
    assert groups["old"]["n"] == 23
    assert groups["old"]["correlation"] > 0.99
    assert len(groups["old"]["ci95"]) == 2
    assert groups["new"]["n"] == 3
    assert groups["new"]["correlation"] is None
    assert "correlation" not in result
    target.dispose()


def test_strength_pairs_same_exercise_changes_and_excludes_warmups(tmp_path):
    target = target_database(tmp_path)
    with Session(target) as session:
        for offset, weight in enumerate((50, 55)):
            day = date(2026, 9, 26) + timedelta(days=offset * 3)
            add_night(session, day)
            workout = Workout(external_id=f"gym-{offset}", started_at=datetime.combine(day, datetime.min.time()).replace(hour=16))
            session.add(workout)
            session.flush()
            session.add(WorkoutSet(workout_id=workout.id, exercise="Press", set_type="normal", weight_kg=weight, reps=8))
            session.add(WorkoutSet(workout_id=workout.id, exercise="Press", set_type="warmup", weight_kg=500, reps=8))
            if offset:
                # A new exercise and its high weight do not alter the comparable basket.
                session.add(WorkoutSet(workout_id=workout.id, exercise="Squat", set_type="normal", weight_kg=200, reps=8))
        session.commit()
    with patch.object(sleep, "engine", target), patch.object(sleep, "settings", config()):
        group = sleep.performance("strength", today=date(2026, 9, 30))["groups"][0]
    assert group["n"] == 1
    assert group["points"][0]["value"] == pytest.approx(10)
    assert group["missing"]["no_outcome"] == 1
    target.dispose()


def test_sleep_endpoints_validate_source_and_limit(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    monkeypatch.setattr(sleep, "overview", lambda days: {"days": days})
    monkeypatch.setattr(sleep, "performance", lambda kind, source, days: {"kind": kind, "source": source})
    assert client.get("/metrics/sleep/overview?days=90").json() == {"days": 90}
    assert client.get("/metrics/sleep/performance?kind=strength&source=legacy").status_code == 200
    assert client.get("/metrics/sleep/performance?source=other").status_code == 422
    assert client.get("/metrics/sleep/overview?days=0").status_code == 422
