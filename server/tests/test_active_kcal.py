"""Aktive Kalorien: Garmin-Basis + Laufband ohne Upload + Hevy-Gym (synthetisch, In-Memory-DB)."""
from datetime import date, datetime, timedelta, timezone
import json

import pandas as pd
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import garmin_daily, walkpad
from app.metrics import active_kcal
from app.models import Workout

NOW = datetime(2026, 10, 26, 18, tzinfo=timezone.utc)
DAY = date(2026, 10, 26)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for module in (garmin_daily, active_kcal):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(garmin_daily.settings, "timezone", "Europe/Berlin")
    monkeypatch.setattr(walkpad.settings, "walkpad_stride_m", 0.65)
    monkeypatch.setattr(walkpad, "_weights", lambda: pd.Series([80.0], index=[pd.Timestamp("2026-10-01")]))
    yield engine
    engine.dispose()


def _walk(sid, hour, status, watch):
    return walkpad.WalkpadSession(id=sid, started_at=datetime(2026, 10, 26, hour), started_at_utc=0, ended_at_utc=0,
                                  moving_s=3000, distance_m=3250, incline_pct=6, watch_steps=watch, garmin_status=status)


def test_garmin_base_plus_missing_walk_share_and_gym(db):
    with Session(db) as session:
        for day, total, everyday in [(DAY - timedelta(days=1), 100, 100), (DAY, 760, 400)]:
            raw = {"summary": {"calendarDate": day.isoformat(), "activeKilocalories": total,
                               "wellnessActiveKilocalories": everyday}}
            session.add(garmin_daily.GarminDaily(day=day, raw_json=json.dumps(raw)))
        session.add(_walk("up", 9, "uploaded", 0))       # already in Garmin's training part
        session.add(_walk("off", 14, "off", 1250))       # 5000 pad steps, watch counted a quarter
        session.add(Workout(external_id="h1", started_at=datetime(2026, 10, 26, 16), ended_at=datetime(2026, 10, 26, 17)))
        session.commit()
    value = active_kcal.daily(3, now=NOW)
    today = value["today"]
    walk = walkpad.energy(3250, 3000, 6, 80.0)["kcal"]
    assert today["walkpad"] == round(walk * 0.75)
    assert today["gym"] == round((active_kcal.GYM_MET - 1) * 80)
    assert today["total"] == 760 + today["walkpad"] + today["gym"]
    assert (today["everyday"], today["training"]) == (400, 360)
    assert value["avg7"] == 100 and value["avg7_days"] == 1  # only full past days with Garmin data


def test_day_without_garmin_still_shows_own_estimates(db):
    with Session(db) as session:
        session.add(Workout(external_id="h2", started_at=datetime(2026, 10, 26, 16), ended_at=datetime(2026, 10, 26, 16, 30)))
        session.commit()
    today = active_kcal.daily(2, now=NOW)["today"]
    assert today["garmin"] is False and today["everyday"] is None and today["total"] == today["gym"] == 100
