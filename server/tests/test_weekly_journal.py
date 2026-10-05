"""Completed local journal windows with canonical, synthetic inputs."""
from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.weekly_journal import router
from app.checkins import CheckIn
from app.metrics import body, running, sleep, weekly_journal as journal
from app.models import BodyMeasurement, ExerciseSession, SleepSession, StepsDaily, Workout


GARMIN = "com.garmin.android.apps.connectmobile"
SAMSUNG = "com.sec.android.app.shealth"
NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in
        (BodyMeasurement, ExerciseSession, SleepSession, StepsDaily, Workout, CheckIn)])
    for module in (journal, body, running, sleep):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(journal.settings, "timezone", "Europe/Berlin")
    monkeypatch.setattr(journal.settings, "watch_source_switch_date", date(2026, 9, 25))
    monkeypatch.setattr(journal.settings, "watch_source_package", GARMIN)
    monkeypatch.setattr(journal.settings, "steps_source_package", SAMSUNG)
    yield engine
    engine.dispose()


def save(engine, *rows):
    with Session(engine) as session:
        session.add_all(rows)
        session.commit()


def run(stamp, external_id, *, distance=6, exercise_type=33):
    return ExerciseSession(external_id=external_id, exercise_type=exercise_type, started_at=stamp,
                           ended_at=stamp + timedelta(minutes=36), distance_km=distance, source="garmin_direct")


def night(day, source, identifier, *, minutes=420, window=480, main=True):
    end = datetime.combine(day, datetime.min.time()) + timedelta(hours=8)
    return SleepSession(external_id=identifier, day=day, source_package=source, started_at=end - timedelta(minutes=window),
                        ended_at=end, duration_window_minutes=window, asleep_minutes=minutes,
                        stage_coverage=1 if minutes is not None else .5, main_sleep=main)


def test_empty_days_are_unknown_but_recorded_activity_totals_are_zero(db):
    value = journal.journal(now=NOW)
    assert value["from_date"] == "2026-09-28" and value["to_date"] == "2026-10-04"
    assert len(value["days"]) == 7
    assert all(day["runs"] == [] and day["strength"] == [] and day["sleep"] is None
               and day["steps"] is None and day["checkin"] is None for day in value["days"])
    assert value["summary"]["sleep_hours"] is None and value["summary"]["weight_delta_kg"] is None
    assert value["summary"]["running_km"] == 0 and value["summary"]["steps_avg"] is None


@pytest.mark.parametrize("now,first,last", [
    (datetime(2026, 3, 30, 22, 15, tzinfo=timezone.utc), "2026-03-24", "2026-03-30"),
    (datetime(2026, 10, 26, 0, 15, tzinfo=timezone.utc), "2026-10-19", "2026-10-25"),
    (datetime(2028, 3, 1, 12), "2028-02-23", "2028-02-29"),
])
def test_calendar_windows_use_configured_timezone_and_dst(db, now, first, last):
    value = journal.journal(now=now)
    assert (value["from_date"], value["to_date"]) == (first, last)
    older = journal.journal(1, now=now)
    assert date.fromisoformat(older["to_date"]) + timedelta(days=1) == date.fromisoformat(first)
    assert len({day["date"] for day in value["days"]}) == 7


def test_exact_local_boundaries_and_completed_days_filter_today(db):
    start = datetime(2026, 9, 28)
    end = datetime(2026, 10, 5)
    save(db, run(start, "first"), run(end - timedelta(microseconds=1), "last"), run(end, "today"),
         run(start - timedelta(microseconds=1), "previous"), run(start, "hc-strength", exercise_type=45),
         Workout(started_at=start, external_id="hevy-1"), Workout(started_at=end, external_id="hevy-today"),
         Workout(started_at=start, external_id="hc-mirror", source="health_connect"))
    value = journal.journal(now=NOW)
    assert value["summary"]["running_sessions"] == 2
    assert value["summary"]["running_km"] == 12 and value["summary"]["running_delta_km"] == 6
    assert value["summary"]["strength_sessions"] == 1
    assert len(value["days"][0]["runs"]) == 1 and len(value["days"][-1]["runs"]) == 1


def test_sleep_uses_main_night_and_correct_watch_across_switch(db):
    # Offset one contains both historical Samsung and current Garmin nights.
    before, after = date(2026, 9, 24), date(2026, 9, 25)
    save(db, night(before, SAMSUNG, "before", minutes=360), night(before, GARMIN, "wrong-before", minutes=600),
         night(after, GARMIN, "after", minutes=480), night(after, SAMSUNG, "wrong-after", minutes=100),
         night(after, GARMIN, "shorter-main", minutes=150, window=180),
         night(after, GARMIN, "nap", minutes=30, window=30, main=False),
         night(date(2026, 9, 26), GARMIN, "unknown", minutes=None))
    value = journal.journal(1, now=NOW)
    assert value["summary"]["sleep_hours"] == 7 and value["summary"]["sleep_nights"] == 2
    assert value["sources"] == ["Garmin", "Samsung"]
    assert value["days"][3]["sleep"]["label"] == "Samsung"
    assert value["days"][4]["sleep"]["hours"] == 8
    assert value["days"][5]["sleep"]["hours"] is None


def test_optional_checkin_does_not_turn_missing_energy_into_zero(db):
    save(db, CheckIn(day=date(2026, 9, 28), energy=4, updated_at=NOW),
         CheckIn(day=date(2026, 9, 29), training_effort=2, updated_at=NOW),
         CheckIn(day=date(2026, 10, 5), energy=5, updated_at=NOW),
         StepsDaily(day=date(2026, 9, 28), steps=0), StepsDaily(day=date(2026, 9, 29), steps=10000))
    value = journal.journal(now=NOW)
    assert value["summary"]["checkin_days"] == 2
    assert value["days"][1]["checkin"] == {"energy": None, "training_effort": 2}
    assert value["days"][2]["checkin"] is None
    assert value["days"][0]["steps"] == 0 and value["days"][2]["steps"] is None
    assert value["summary"]["steps_avg"] == 5000 and value["summary"]["steps_days"] == 2


def test_weight_delta_needs_three_days_per_window_not_three_measurements(db):
    save(db, *[BodyMeasurement(measured_at=datetime(2026, 9, day, 8), weight_kg=80, source="health_connect")
               for day in (21, 23, 25)],
         *[BodyMeasurement(measured_at=datetime(2026, 9, 28, hour), weight_kg=79, source="health_connect")
           for hour in (8, 9, 10)])
    value = journal.journal(now=NOW)
    assert value["summary"]["weight_delta_kg"] is None and value["summary"]["weight_days"] == 1
    save(db, BodyMeasurement(measured_at=datetime(2026, 9, 29, 8), weight_kg=79, source="health_connect"),
         BodyMeasurement(measured_at=datetime(2026, 9, 30, 8), weight_kg=79, source="health_connect"))
    assert journal.journal(now=NOW)["summary"]["weight_delta_kg"] == -1


def test_runs_use_existing_canonical_sanity_filter(db):
    save(db, run(datetime(2026, 9, 28, 8), "valid"), run(datetime(2026, 9, 29, 8), "bad-distance", distance=100),
         run(datetime(2026, 9, 30, 8), "bad-pace", distance=1))
    value = journal.journal(now=NOW)
    assert value["summary"]["running_km"] == 6 and value["summary"]["running_sessions"] == 1


def test_api_offset_validation(db):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/metrics/activity/journal?offset=0").status_code == 200
    assert client.get("/metrics/activity/journal?offset=52").status_code == 200
    assert client.get("/metrics/activity/journal?offset=-1").status_code == 422
    assert client.get("/metrics/activity/journal?offset=53").status_code == 422
