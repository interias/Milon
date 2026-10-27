"""Aktive Kalorien komplett aus lokalen Daten (synthetisch, In-Memory-DB, Leser gemockt)."""
from datetime import date, datetime, timezone
import json

import pandas as pd
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import garmin_daily, walkpad
from app.metrics import active_kcal, cycling, health, running
from app.models import StepsDaily, Workout

NOW = datetime(2026, 10, 26, 18, tzinfo=timezone.utc)
DAY = date(2026, 10, 26)
KG = 80.0


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for module in (garmin_daily, active_kcal):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(garmin_daily.settings, "timezone", "Europe/Berlin")
    monkeypatch.setattr(active_kcal.settings, "walkpad_stride_m", 0.65)
    monkeypatch.setattr(walkpad, "_weights", lambda: pd.Series([KG], index=[pd.Timestamp("2026-10-20")]))
    monkeypatch.setattr(running, "_runs", lambda: pd.DataFrame())
    monkeypatch.setattr(cycling, "indoor_rides", lambda: pd.DataFrame())
    monkeypatch.setattr(health, "_rides", lambda: pd.DataFrame())
    yield engine
    engine.dispose()


def test_each_source_is_net_and_steps_exclude_run_and_treadmill(db, monkeypatch):
    monkeypatch.setattr(running, "_runs", lambda: pd.DataFrame(
        [{"started_at": pd.Timestamp("2026-10-26 07:00"), "distance_km": 10.0, "dur_min": 60.0}]))
    monkeypatch.setattr(cycling, "indoor_rides", lambda: pd.DataFrame(
        [{"started_at": pd.Timestamp("2026-10-26 19:00"), "duration_seconds": 3600, "work_kj": 600.0},
         {"started_at": pd.Timestamp("2026-10-26 20:30"), "duration_seconds": 1800, "work_kj": None}]))
    monkeypatch.setattr(health, "_rides", lambda: pd.DataFrame(
        [{"started_at": pd.Timestamp("2026-10-26 12:00"), "dur_min": 30.0, "speed": 14.0}]))
    with Session(db) as session:
        session.add(StepsDaily(day=DAY, steps=20_000, source="garmin_direct"))
        session.add(walkpad.WalkpadSession(id="w", started_at=datetime(2026, 10, 26, 14), started_at_utc=0,
                                           ended_at_utc=0, moving_s=3000, distance_m=3250, incline_pct=6, watch_steps=1100))
        session.add(Workout(external_id="h", started_at=datetime(2026, 10, 26, 16), ended_at=datetime(2026, 10, 26, 17)))
        raw = {"summary": {"calendarDate": DAY.isoformat(), "activeKilocalories": 900, "wellnessActiveKilocalories": 400}}
        session.add(garmin_daily.GarminDaily(day=DAY, raw_json=json.dumps(raw)))
        session.commit()
    today = active_kcal.daily(1, now=NOW)["today"]
    assert today["run"] == round(0.2 * 10_000 * KG * 0.005)                     # ≈ 1 kcal/kg/km
    assert today["steps"] == 20_000 - 165 * 60 - 1100                           # run cadence + treadmill wrist steps out
    assert today["everyday"] == round(0.1 * today["steps"] * 0.65 * KG * 0.005)
    assert today["walkpad"] == walkpad.energy(3250, 3000, 6, KG)["kcal"]
    assert today["gym"] == round(2.5 * KG)
    indoor = 600 / (0.20 * 4.184) - KG + (6.8 - 1) * KG * 0.5
    outdoor = (4.0 - 1) * KG * 0.5
    assert today["ride"] == round(indoor + outdoor)
    assert today["total"] == sum(today[k] for k in active_kcal.PARTS)
    assert today["garmin"] == 900                                                 # comparison only


def test_average_uses_full_days_and_missing_weight_skips_kcal(db, monkeypatch):
    with Session(db) as session:
        for day, steps in [(date(2026, 10, 24), 8000), (date(2026, 10, 25), 4000), (DAY, 1000)]:
            session.add(StepsDaily(day=day, steps=steps))
        session.commit()
    value = active_kcal.daily(3, now=NOW)
    per_step = 0.1 * 0.65 * KG * 0.005
    assert value["avg7_days"] == 2 and value["avg7"] == round((round(8000 * per_step) + round(4000 * per_step)) / 2)
    monkeypatch.setattr(walkpad, "_weights", lambda: None)
    assert active_kcal.daily(1, now=NOW)["today"]["total"] == 0
