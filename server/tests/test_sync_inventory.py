"""Sync feedback uses stable, deduplicated identities without exposing health values."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import sync_inventory as api
from app.garmin_activity import GarminActivity
from app.models import BodyMeasurement, ExerciseSession, NutritionEntry, SleepSession, Workout

GARMIN = "com.garmin.android.apps.connectmobile"
SAMSUNG = "com.sec.android.app.shealth"


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in
        (BodyMeasurement, ExerciseSession, NutritionEntry, SleepSession, Workout, GarminActivity)])
    monkeypatch.setattr(api, "engine", engine)
    monkeypatch.setattr(api.settings, "watch_source_switch_date", date(2026, 9, 25))
    monkeypatch.setattr(api.settings, "watch_source_package", GARMIN)
    monkeypatch.setattr(api.settings, "steps_source_package", SAMSUNG)
    yield engine
    engine.dispose()


def save(engine, *rows):
    with Session(engine) as session:
        session.add_all(rows)
        session.commit()


def test_canonical_link_and_stable_external_identity_survive_row_replacement(db):
    start = datetime(2026, 9, 30, 12)
    save(db, ExerciseSession(id=5, external_id="run-stable", exercise_type=33, started_at=start,
                            ended_at=start + timedelta(minutes=60), distance_km=10),
         GarminActivity(activity_id="123", canonical_external_id="run-stable", started_at=start,
                        summary_json="{}", series_json="[]", laps_json="[]", zones_json="[]",
                        quality_json="{}", fingerprint="test", fetched_at=start))
    before = api.inventory()
    assert before["runs"] == [{"id": "run-stable", "date": "2026-09-30", "href": "/laufen/123"}]
    with Session(db) as session:
        row = session.get(ExerciseSession, 5)
        session.delete(row)
        session.commit()
    save(db, ExerciseSession(id=77, external_id="run-stable", exercise_type=33, started_at=start,
                            ended_at=start + timedelta(minutes=59), distance_km=10))
    assert api.inventory() == before


def test_only_valid_runs_and_hevy_workouts_are_counted(db):
    start = datetime(2026, 9, 30, 12)
    save(db, ExerciseSession(external_id="bad", exercise_type=33, started_at=start,
                            ended_at=start + timedelta(minutes=1), distance_km=10),
         ExerciseSession(external_id="future", exercise_type=33, started_at=datetime(2099, 1, 1),
                         ended_at=datetime(2099, 1, 1, 1), distance_km=10),
         Workout(external_id="hevy-1", started_at=start),
         Workout(external_id="hc-mirror", started_at=start, source="health_connect"))
    value = api.inventory()
    assert value["runs"] == []
    assert value["workouts"] == [{"id": "hevy-1", "date": "2026-09-30", "href": "/kraft"}]


def test_daily_measurements_are_unique_and_bodyfat_only_is_not_a_weigh_day(db):
    day = datetime(2026, 9, 30)
    save(db, BodyMeasurement(measured_at=day, weight_kg=75, source="scale"),
         BodyMeasurement(measured_at=day + timedelta(hours=1), weight_kg=76, source="scale"),
         BodyMeasurement(measured_at=day + timedelta(days=1), body_fat_pct=20, source="scale"),
         NutritionEntry(eaten_at=day, kcal=500), NutritionEntry(eaten_at=day + timedelta(hours=1), kcal=200))
    value = api.inventory()
    assert value["weights"] == [{"id": "2026-09-30", "date": "2026-09-30", "href": "/koerper"}]
    assert len(value["nutrition"]) == 1


def test_nights_observe_watch_switch_and_exclude_naps(db):
    def night(day, package, identifier, main=True):
        end = datetime.combine(day, datetime.min.time()) + timedelta(hours=8)
        return SleepSession(external_id=identifier, day=day, source_package=package,
                            started_at=end - timedelta(hours=8), ended_at=end,
                            duration_window_minutes=480, asleep_minutes=420, main_sleep=main)
    before, after = date(2026, 9, 24), date(2026, 9, 25)
    save(db, night(before, SAMSUNG, "old"), night(before, GARMIN, "wrong-old"),
         night(after, GARMIN, "new"), night(after, SAMSUNG, "wrong-new"),
         night(date(2026, 9, 26), GARMIN, "nap", False))
    value = api.inventory()
    assert {row["id"] for row in value["nights"]} == {"2026-09-24", "2026-09-25"}
    assert next(row["href"] for row in value["nights"] if row["id"] == "2026-09-25") == "/gesundheit?night=2026-09-25"
