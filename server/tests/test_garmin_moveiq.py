"""Watch-detected rides (Move IQ): sync, overlap with recorded rides, active calories (synthetic, in-memory DB)."""
from datetime import date, datetime, timezone

import pandas as pd
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app import garmin_indoor, garmin_moveiq, garmin_routes, walkpad  # noqa: F401 -- register tables
from app.metrics import active_kcal, cycling, endurance, health, running
from app.models import ExerciseSession

NOW = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)
KG = 80.0


def _raw(start: str, end: str, kind: str = "cycling") -> dict:
    return {"startTimestampLocal": f"{start}:00.0", "endTimestampLocal": f"{end}:00.0", "activityType": kind,
            "startTimestampGMT": "ignored", "duration": 0}


class FakeApi:
    def __init__(self, events: dict[str, list[dict]], fail: set[str] = frozenset()):
        self.events, self.fail, self.calls = events, fail, []

    def get_all_day_events(self, day: str):
        self.calls.append(day)
        if day in self.fail:
            raise RuntimeError("boom")
        return self.events.get(day, [])


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for module in (garmin_moveiq, health, active_kcal):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(garmin_moveiq.settings, "timezone", "Europe/Berlin")
    monkeypatch.setattr(garmin_moveiq.settings, "watch_source_switch_date", date(2026, 10, 15))
    yield engine
    engine.dispose()


def test_sync_stores_all_types_refreshes_recent_days_and_throttles(db):
    api = FakeApi({"2026-10-16": [_raw("2026-10-16T15:47", "2026-10-16T15:59"), {"broken": True}],
                   "2026-10-19": [_raw("2026-10-19T08:41", "2026-10-19T09:21", "walking")]}, fail={"2026-10-17"})
    result = garmin_moveiq.sync_moveiq(api, now=NOW)
    assert api.calls == [f"2026-10-{d}" for d in range(15, 21)]
    assert (result["days"], result["events"], result["errors"]) == (5, 2, 1)
    rides = garmin_moveiq.detected_rides()
    assert len(rides) == 1 and rides.iloc[0]["minutes"] == 12.0                 # walking is stored, not read

    assert garmin_moveiq.sync_moveiq(api, now=NOW)["mode"] == "throttled"
    api.calls.clear()
    api.events["2026-10-19"] = []                                                 # Garmin dropped the event
    garmin_moveiq.sync_moveiq(api, now=datetime(2026, 10, 20, 20, tzinfo=timezone.utc))
    assert api.calls == ["2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20"]  # failed day + last 3 days
    with Session(db) as session:
        assert {e.activity_type for e in session.exec(select(garmin_moveiq.GarminMoveIq)).all()} == {"cycling"}


def _store(db, *windows: tuple[str, str]) -> None:
    with Session(db) as session:
        for start, end in windows:
            s, e = datetime.fromisoformat(start), datetime.fromisoformat(end)
            session.add(garmin_moveiq.GarminMoveIq(started_at=s, ended_at=e, day=s.date(), activity_type="cycling",
                                                   minutes=(e - s).total_seconds() / 60))
        session.commit()


def test_recorded_rides_win_over_detected_ones(db):
    _store(db, ("2026-10-16T15:47", "2026-10-16T15:59"), ("2026-10-16T17:00", "2026-10-16T17:30"),
           ("2026-10-17T10:00", "2026-10-17T11:00"), ("2026-10-18T09:00", "2026-10-18T09:40"))
    with Session(db) as session:
        session.add(garmin_routes.GarminRide(activity_id="r", started_at=datetime(2026, 10, 16, 17, 5),
                                             duration_seconds=1200, distance_km=6.0, title="Rad", point_count=0,
                                             segments_json="[]", synced_at=datetime(2026, 10, 16)))
        session.add(ExerciseSession(external_id="hc", exercise_type=health.BIKE, started_at=datetime(2026, 10, 17, 10, 10),
                                    ended_at=datetime(2026, 10, 17, 10, 50)))
        session.add(garmin_indoor.GarminIndoorRide(activity_id="z", title="Zwift", started_at=datetime(2026, 10, 18, 9, 0), synced_at=datetime(2026, 10, 18),
                                                   duration_seconds=2400))
        session.commit()
    rides = health._detected_rides()
    assert list(rides["started_at"]) == [pd.Timestamp("2026-10-16 15:47")]
    assert rides.iloc[0]["dur_min"] == 12.0


def test_detected_rides_add_net_calories_and_long_ones_count_as_training(db, monkeypatch):
    _store(db, ("2026-10-16T15:47", "2026-10-16T15:59"), ("2026-10-16T17:00", "2026-10-16T17:30"))
    monkeypatch.setattr(walkpad, "_weights", lambda: pd.Series([KG], index=[pd.Timestamp("2026-10-01")]))
    for module, name in ((running, "_runs"), (cycling, "indoor_rides"), (health, "_rides")):
        monkeypatch.setattr(module, name, lambda: pd.DataFrame())
    parts, _ = active_kcal.compute(date(2026, 10, 16), date(2026, 10, 16))
    assert parts[date(2026, 10, 16)]["ride"] == pytest.approx((4.0 - 1) * KG * 42 / 60)

    sessions = endurance.ride_sessions()
    assert list(sessions["minutes"]) == [30.0] and sessions.iloc[0]["title"] == "Rad (erkannt)"

    summary = health.cycling_summary(now=NOW)["detected"]
    assert summary == {"rides": 2, "minutes": 42, "last": {"date": "2026-10-16T17:00:00", "dur_min": 30}}
