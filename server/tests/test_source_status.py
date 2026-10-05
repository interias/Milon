from datetime import date, datetime, timedelta, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import db as app_db
from app.api.source_status import router
from app.garmin_daily import GarminDaily
from app.metrics import source_status as module
from app.models import BodyMeasurement, NutritionEntry, RestingHrDaily, SyncState, Workout
from app.sync import scheduler

NOW = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)
LOCAL = datetime(2026, 10, 5, 12)


@pytest.fixture
def db(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(scheduler, "engine", engine)
    monkeypatch.setattr(module, "garmin_configured", lambda: True)
    monkeypatch.setattr(module, "INCOMING_DIR", tmp_path)
    monkeypatch.setattr(module.settings, "timezone", "Europe/Berlin")
    monkeypatch.setattr(module.settings, "hevy_api_key", "synthetic-key")
    monkeypatch.setattr(module.settings, "fddb_cookie", "synthetic-cookie")
    monkeypatch.setattr(module.settings, "hc_drive_file_id", "synthetic-drive-id")
    monkeypatch.setattr(module.settings, "body_source_package", "com.qingniu.arboleaf")
    yield engine
    engine.dispose()


def source(key):
    return next(row for row in module.source_status(now=NOW)["sources"] if row["key"] == key)


def test_successful_poll_without_workout_is_current(db):
    with Session(db) as session:
        session.add(SyncState(source="hevy", last_sync=LOCAL, last_success_at=LOCAL, status="ok", detail='{"events":0}'))
        session.add(Workout(started_at=datetime(2026, 9, 1), source="hevy"))
        session.commit()
    row = source("hevy")
    assert row["status"] == "ok"
    assert row["latest_data_date"] == "2026-09-01"
    assert row["last_success_at"] == NOW.isoformat()


def test_failure_keeps_success_separate_and_does_not_expose_raw_details(db):
    with Session(db) as session:
        session.add(SyncState(source="fddb", last_sync=LOCAL, last_success_at=LOCAL - timedelta(days=1), status="error", detail="cookie=private-secret https://provider/private-id"))
        session.commit()
    row = source("fddb")
    assert row["status"] == "error"
    assert row["last_attempt_at"] != row["last_success_at"]
    assert "private" not in json.dumps(module.source_status(now=NOW))


def test_record_sync_success_survives_error_and_not_configured(db):
    scheduler.record_sync("hevy", "ok", '{"events":0}')
    with Session(db) as session:
        success = session.get(SyncState, "hevy").last_success_at
    scheduler.record_sync("hevy", "error", "sensitive provider error")
    scheduler.record_sync("garmin", "ok", '{"mode":"not_configured"}')
    with Session(db) as session:
        assert session.get(SyncState, "hevy").last_success_at == success
        assert session.get(SyncState, "garmin").last_success_at is None


def test_empty_source_is_never_and_old_success_is_old(db):
    assert source("hevy")["status"] == "never"
    with Session(db) as session:
        session.add(SyncState(source="hevy", last_sync=LOCAL - timedelta(days=2), last_success_at=LOCAL - timedelta(days=2), status="ok"))
        session.commit()
    assert source("hevy")["status"] == "old"


def test_arboleaf_shares_hc_import_time_but_keeps_own_measurement_date(db):
    with Session(db) as session:
        session.add(SyncState(source="health_connect", last_sync=LOCAL, last_success_at=LOCAL, status="ok"))
        session.add(BodyMeasurement(measured_at=datetime(2026, 10, 1, 8), weight_kg=70, source="health_connect"))
        session.add(RestingHrDaily(day=date(2026, 10, 4), bpm=50, source="health_connect"))
        session.commit()
    assert source("health_connect")["latest_data_date"] == "2026-10-04"
    assert source("arboleaf")["latest_data_date"] == "2026-10-01"
    assert source("arboleaf")["last_success_at"] == source("health_connect")["last_success_at"]
    assert source("arboleaf")["status"] == "ok"


def test_garmin_partial_category_failure_retains_other_successes(db):
    status = {"summary": {"status": "available", "last_success_at": NOW.isoformat(), "attempted_at": NOW.isoformat()},
              "sleep": {"status": "error", "attempted_at": NOW.isoformat()},
              "vo2": {"status": "empty", "attempted_at": NOW.isoformat()}}
    with Session(db) as session:
        session.add(SyncState(source="garmin", last_sync=LOCAL, status="error", detail="secret"))
        session.add(GarminDaily(day=NOW.date(), status_json=json.dumps(status), normalized_json='{"summary":{"steps":0}}', synced_at=NOW.replace(tzinfo=None)))
        session.commit()
    row = source("garmin")
    assert row["status"] == "partial"
    categories = {category["key"]: category for category in row["categories"]}
    assert categories["sleep"]["status"] == "error"
    assert categories["vo2"]["status"] == "empty"
    assert row["latest_data_date"] == "2026-10-05"
    assert row["last_success_at"] is None


def test_not_configured_overrides_historical_success(db, monkeypatch):
    with Session(db) as session:
        session.add(SyncState(source="garmin", last_sync=LOCAL, last_success_at=LOCAL, status="ok"))
        session.commit()
    monkeypatch.setattr(module, "garmin_configured", lambda: False)
    assert source("garmin")["status"] == "not_configured"


def test_last_data_date_has_no_invented_measurement_time_and_api_is_safe(db):
    with Session(db) as session:
        session.add(NutritionEntry(eaten_at=datetime(2026, 10, 4, 18), description="private meal", kcal=500))
        session.commit()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        result = client.get("/metrics/sources")
    assert result.status_code == 200
    assert "private meal" not in result.text
    assert next(item for item in result.json()["sources"] if item["key"] == "fddb")["latest_data_date"] == "2026-10-04"


def test_migration_only_backfills_proven_success(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as con:
        con.exec_driver_sql("CREATE TABLE sync_state (source TEXT PRIMARY KEY,last_sync DATETIME,cursor TEXT,status TEXT,detail TEXT)")
        for key, status, detail in [("hevy", "ok", '{"events":0}'), ("fddb", "error", "private"), ("garmin", "ok", '{"mode":"not_configured"}')]:
            con.exec_driver_sql("INSERT INTO sync_state VALUES (?, ?, NULL, ?, ?)", (key, LOCAL, status, detail))
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(app_db, "engine", engine)
    app_db._run_migrations()
    app_db._run_migrations()
    with Session(engine) as session:
        assert session.get(SyncState, "hevy").last_success_at == LOCAL
        assert session.get(SyncState, "fddb").last_success_at is None
        assert session.get(SyncState, "garmin").last_success_at is None
    engine.dispose()
