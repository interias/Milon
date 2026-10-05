import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.api import body_progress as api
from app.circumferences import CircumferenceEntry
from app.metrics import body_progress
from app.models import BodyMeasurement, Workout, WorkoutSet


TODAY = date(2026, 10, 5)
START = TODAY - timedelta(days=55)
CURRENT = TODAY - timedelta(days=13)


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'progress.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[CircumferenceEntry.__table__, BodyMeasurement.__table__,
                                               Workout.__table__, WorkoutSet.__table__])
    monkeypatch.setattr(body_progress, "engine", engine)
    monkeypatch.setattr(body_progress, "local_today", lambda: TODAY)
    yield engine
    engine.dispose()


def tape(db, day, abdomen=None, waist=None, protocol="standard", version="v1"):
    with Session(db) as session:
        values = {key: value for key, value in (("abdomen_navel", abdomen), ("waist_narrowest", waist)) if value is not None}
        session.add(CircumferenceEntry(measured_on=day, protocol=protocol,
                                      definition_version=version, values_json=json.dumps(values)))
        session.commit()


def weight(db, day, value, hour=8):
    with Session(db) as session:
        session.add(BodyMeasurement(measured_at=datetime.combine(day, datetime.min.time()).replace(hour=hour),
                                    weight_kg=value, source="health_connect"))
        session.commit()


def workout(db, day, exercises, set_type="normal", reps=8):
    with Session(db) as session:
        row = Workout(started_at=datetime.combine(day, datetime.min.time()), source="hevy")
        session.add(row)
        session.flush()
        for name, load in exercises.items():
            session.add(WorkoutSet(workout_id=row.id, exercise=name, weight_kg=load,
                                   reps=reps, set_type=set_type))
        session.commit()


def test_windows_are_identical_nonoverlapping_and_end_today(db):
    for weeks in (4, 8, 12):
        result = body_progress.progress(weeks)
        assert result["start"] == (TODAY - timedelta(days=7 * weeks - 1)).isoformat()
        assert result["end"] == TODAY.isoformat()
        assert result["baseline"]["end"] < result["current"]["start"]
        assert result["circumference"]["delta"] is None
        assert result["weight"]["delta"] is None
        assert result["strength"]["delta_pct"] is None


def test_tape_protocols_sites_and_future_measurements_do_not_mix(db):
    tape(db, START, abdomen=95, waist=87)
    tape(db, START + timedelta(days=7), abdomen=93, waist=85)
    tape(db, CURRENT, abdomen=91, waist=82)
    tape(db, CURRENT, abdomen=60, waist=60, protocol="unknown")
    tape(db, CURRENT + timedelta(days=1), abdomen=62, waist=62, version="v0")
    tape(db, TODAY + timedelta(days=1), abdomen=50, waist=50)
    belly = body_progress.progress()["circumference"]
    waist = body_progress.progress(measure="waist_narrowest")["circumference"]
    assert belly["baseline"]["value"] == 94
    assert belly["current"]["value"] == 91
    assert belly["delta"] == -3
    assert belly["ignored_measurements"] == 2
    assert waist["delta"] == -4


def test_stale_tape_is_not_carried_into_current_window(db):
    tape(db, START, abdomen=95)
    tape(db, CURRENT - timedelta(days=1), abdomen=91)
    result = body_progress.progress()["circumference"]
    assert result["baseline"]["value"] == 95
    assert result["current"]["count"] == 0
    assert result["delta"] is None


def test_weight_compares_daily_means_with_minimum_coverage(db):
    for offset in range(3):
        weight(db, START + timedelta(days=offset), 80)
        weight(db, CURRENT + timedelta(days=offset), 77)
    weight(db, START, 86, hour=9)
    weight(db, START - timedelta(days=1), 110)
    weight(db, TODAY + timedelta(days=1), 30)
    result = body_progress.progress()["weight"]
    assert result["baseline"]["value"] == 81  # (83 + 80 + 80) / 3; not all four samples.
    assert result["current"]["value"] == 77
    assert result["delta"] == -4
    assert result["baseline"]["count"] == result["current"]["count"] == 3


def test_two_weight_days_remain_insufficient(db):
    for offset in range(2):
        weight(db, START + timedelta(days=offset), 80)
        weight(db, CURRENT + timedelta(days=offset), 77)
    assert body_progress.progress()["weight"]["delta"] is None


def test_strength_uses_fixed_cohort_and_ignores_new_exercises_and_warmups(db):
    first = {"Bench Press": 80, "Squat": 100, "Lat Pulldown": 60, "Old Curl": 20}
    last = {"Bench Press": 88, "Squat": 110, "Lat Pulldown": 66, "New Curl": 100}
    for offset in (0, 7):
        workout(db, START + timedelta(days=offset), first)
        workout(db, CURRENT + timedelta(days=offset), last)
        workout(db, CURRENT + timedelta(days=offset), {name: 300 for name in last}, set_type="warmup")
    result = body_progress.progress()["strength"]
    assert result["delta_pct"] == 10
    assert {row["exercise"] for row in result["exercises"]} == {"Bench Press", "Squat", "Lat Pulldown"}
    assert result["unmatched_exercises"] == result["changed_exercises"] == 2
    assert result["baseline_exercises"] == result["current_exercises"] == 4
    assert all(row["baseline"]["count"] == row["current"]["count"] == 2 for row in result["exercises"])


def test_strength_requires_repeated_days_not_multiple_sets_or_workouts_same_day(db):
    exercises = {"Bench Press": 80, "Squat": 100, "Lat Pulldown": 60}
    for _ in range(3):
        workout(db, START, exercises)
        workout(db, CURRENT, exercises)
    result = body_progress.progress()["strength"]
    assert result["delta_pct"] is None
    assert result["exercises"] == []


def test_program_switch_does_not_create_overall_strength_claim(db):
    for offset in (0, 7):
        workout(db, START + timedelta(days=offset), {"Bench Press": 80, "Squat": 100, "Lat Pulldown": 60})
        workout(db, CURRENT + timedelta(days=offset), {"Dumbbell Press": 80, "Leg Press": 100, "Cable Row": 60})
    result = body_progress.progress()["strength"]
    assert result["delta_pct"] is None
    assert result["changed_exercises"] == 6


def test_one_muscle_group_remains_a_partial_view(db):
    exercises = {"Bench Press": 80, "Chest Press": 90, "Chest Fly": 25}
    for offset in (0, 7):
        workout(db, START + timedelta(days=offset), exercises)
        workout(db, CURRENT + timedelta(days=offset), exercises)
    result = body_progress.progress()["strength"]
    assert len(result["exercises"]) == 3
    assert result["groups"] == 1
    assert result["delta_pct"] is None


def test_strength_caps_repetitions_like_existing_index_and_uses_daily_peaks(db):
    exercises = {"Bench Press": 80, "Squat": 100, "Lat Pulldown": 60}
    for offset in (0, 7):
        workout(db, START + timedelta(days=offset), exercises, reps=12)
        workout(db, CURRENT + timedelta(days=offset), exercises, reps=20)
        workout(db, CURRENT + timedelta(days=offset), {name: value / 2 for name, value in exercises.items()}, reps=20)
    result = body_progress.progress()["strength"]
    assert result["delta_pct"] == 0
    assert all(row["baseline"]["value"] == row["current"]["value"] for row in result["exercises"])


def test_api_validates_window_and_measure_without_writing(db):
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        result = client.get("/metrics/body/progress?weeks=4&measure=waist_narrowest")
        assert result.status_code == 200
        assert result.json()["circumference"]["key"] == "waist_narrowest"
        for query in ("weeks=5", "weeks=0", "weeks=16", "measure=hip_widest"):
            assert client.get(f"/metrics/body/progress?{query}").status_code == 422
