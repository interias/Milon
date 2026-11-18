"""eGym-Pauschale: Eintragen, Kalorien, Heldenreise, Wochenplan (synthetisch, In-Memory-DB)."""
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app import hero, walkpad
from app.api.metrics import router
from app.metrics import active_kcal, activity, cycling, day_badge, egym, gym_cardio, health, running, strength_plan, week_plan
from app.models import Workout

NOW = datetime(2026, 11, 18, 19, 30)
TODAY = NOW.date()


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for module in (egym, active_kcal, gym_cardio, activity, hero, week_plan, strength_plan):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(egym, "_now", lambda: NOW)
    monkeypatch.setattr(walkpad, "_weights", lambda: pd.Series([80.0], index=[pd.Timestamp("2026-11-01")]))
    monkeypatch.setattr(running, "_runs", lambda: pd.DataFrame())
    monkeypatch.setattr(cycling, "indoor_rides", lambda: pd.DataFrame())
    monkeypatch.setattr(health, "_rides", lambda: pd.DataFrame())
    monkeypatch.setattr(health, "_detected_rides", lambda: pd.DataFrame())
    yield engine
    engine.dispose()


def test_button_logs_one_hour_ending_now_once_per_day(db):
    egym.add()
    result = egym.add()
    assert result["done_today"] and result["total"] == 1 and result["days"] == [TODAY.isoformat()]
    with Session(db) as session:
        row = session.exec(select(Workout)).one()
    assert (row.source, row.title) == ("egym", "eGym")
    assert (row.started_at, row.ended_at) == (NOW - timedelta(hours=1), NOW)


def test_backfill_and_remove(db):
    day = TODAY - timedelta(days=2)
    assert egym.add(day)["days"] == [day.isoformat()]
    assert not egym.listing()["done_today"]
    assert egym.remove(day)["total"] == 0
    assert egym.remove(day) is None
    with pytest.raises(ValueError):
        egym.add(TODAY + timedelta(days=1))


def test_counts_flat_kcal_as_gym_without_met_estimate(db):
    egym.add()
    parts, _ = active_kcal.compute(TODAY, TODAY)
    assert parts[TODAY]["gym"] == egym.KCAL


def test_hero_counts_a_normal_training_and_hevy_stays_unchanged(db):
    egym.add()
    with Session(db) as session:
        session.add(Workout(external_id="h", started_at=NOW - timedelta(days=1), ended_at=NOW - timedelta(days=1)))
        session.commit()
    sets = dict(zip(hero._workouts()["source"], hero._workouts()["sets"]))
    assert sets == {"hevy": 0, "egym": egym.HERO_SETS}


def test_week_plan_sees_the_session_without_a_program(db):
    egym.add()
    row = week_plan._workouts(TODAY, TODAY)[0]
    assert (row["source"], row["title"], row["program"], row["minutes"]) == ("egym", "eGym", None, 60)


def test_day_badge_shows_no_invented_sets(db, monkeypatch):
    monkeypatch.setattr(day_badge, "engine", db)
    egym.add()
    row = day_badge._strength(TODAY)[0]
    assert (row["title"], row["minutes"], row["sets"], row["exercises"]) == ("eGym", 60, 0, 0)


def test_api(db):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.post("/metrics/strength/egym", json={}).json()["done_today"] is True
    future = (TODAY + timedelta(days=1)).isoformat()
    assert client.post("/metrics/strength/egym", json={"day": future}).status_code == 422
    assert client.get("/metrics/strength/egym").json()["total"] == 1
    assert client.delete(f"/metrics/strength/egym/{TODAY}").json()["total"] == 0
    assert client.delete(f"/metrics/strength/egym/{date(2026, 1, 1)}").status_code == 404
