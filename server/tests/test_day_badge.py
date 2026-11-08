"""Tages-Badge „Heute geschafft“: Quellen eines Tages + anonyme Linienform (synthetisch, In-Memory-DB)."""
import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import garmin_indoor, garmin_routes, walkpad  # noqa: F401 -- registriert die Tabellen
from app.main import app
from app.metrics import active_kcal, cycling, day_badge, health, running
from app.models import Workout, WorkoutSet

DAY = date(2026, 11, 8)
LAT0, LON0 = 50.123456, 7.654321   # Fantasie-Heimat


def _line(legs, start=(LAT0, LON0), step_m=20):
    """GPS-Punkte entlang von Teilstrecken [(Richtung 'n'|'e'|'s'|'w', Meter), …]."""
    lat, lon = start
    pts = [(lat, lon)]
    for direction, metres in legs:
        for _ in range(int(metres / step_m)):
            dlat = {"n": step_m, "s": -step_m}.get(direction, 0) / 110_540
            dlon = {"e": step_m, "w": -step_m}.get(direction, 0) / (111_320 * 0.6414)
            lat, lon = lat + dlat, lon + dlon
            pts.append((lat, lon))
    return pts


def _segments(points):
    return json.dumps([[{"lat": a, "lon": b} for a, b in points]])


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(day_badge, "engine", engine)
    monkeypatch.setattr(day_badge, "_today", lambda: DAY)
    monkeypatch.setattr(running, "_runs", lambda: pd.DataFrame())
    monkeypatch.setattr(health, "_rides", lambda: pd.DataFrame())
    monkeypatch.setattr(health, "_detected_rides", lambda: pd.DataFrame())
    monkeypatch.setattr(health, "_steps", lambda: pd.DataFrame())
    monkeypatch.setattr(cycling, "indoor_rides", lambda: pd.DataFrame())
    monkeypatch.setattr(active_kcal, "compute", lambda start, end: ({}, {}))
    yield engine
    engine.dispose()


def _route(engine, model, activity_id, start, points, km):
    with Session(engine) as session:
        session.add(model(activity_id=activity_id, title="Lauf in Musterstadt", started_at=start, distance_km=km,
                          duration_seconds=1800, point_count=len(points), segments_json=_segments(points),
                          synced_at=datetime(2026, 11, 8)))
        session.commit()


def test_shape_trims_privacy_zone_and_drops_short_routes():
    # 500 m nach Norden, 2 km nach Osten, 500 m nach Süden: nach dem Kürzen bleibt nur die Ost-Strecke.
    shape = day_badge.anonymize_shape(_line([("n", 500), ("e", 2000), ("s", 500)]))
    ys = {y for _, y in shape}
    assert max(ys) - min(ys) < 0.01                       # Nord-/Süd-Abschnitte (Start/Ende) sind weg
    assert min(x for x, _ in shape) == 0 and max(x for x, _ in shape) == 1
    assert len(shape) <= day_badge.MAX_SHAPE_POINTS + 1
    assert day_badge.anonymize_shape(_line([("e", 1400)])) is None    # kürzer als MIN_SHAPE_M
    assert day_badge.anonymize_shape([(LAT0, LON0)]) is None


def test_badge_collects_every_source_without_coordinates(db, monkeypatch):
    run_start = pd.Timestamp("2026-11-08 07:00:30")
    monkeypatch.setattr(running, "_runs", lambda: pd.DataFrame([
        {"started_at": run_start, "distance_km": 5.0, "dur_min": 30.0, "avg_hr": 140.0},
        {"started_at": pd.Timestamp("2026-11-07 07:00"), "distance_km": 8.0, "dur_min": 50.0, "avg_hr": 150.0}]))
    _route(db, garmin_routes.GarminRoute, "r1", datetime(2026, 11, 8, 7, 0), _line([("e", 2500), ("n", 2500)]), 5.0)
    _route(db, garmin_routes.GarminRoute, "r2", datetime(2026, 11, 8, 18, 0), _line([("w", 3000)]), 3.0)
    _route(db, garmin_routes.GarminRide, "b1", datetime(2026, 11, 8, 12, 0), _line([("s", 4000)]), 4.0)
    monkeypatch.setattr(health, "_rides", lambda: pd.DataFrame(
        [{"started_at": pd.Timestamp("2026-11-08 12:01"), "distance_km": 4.0, "dur_min": 15.0, "speed": 16.0}]))
    monkeypatch.setattr(health, "_detected_rides", lambda: pd.DataFrame(
        [{"started_at": pd.Timestamp("2026-11-08 14:00"), "ended_at": pd.Timestamp("2026-11-08 14:12"), "dur_min": 12.0}]))
    monkeypatch.setattr(cycling, "indoor_rides", lambda: pd.DataFrame([
        {"activity_id": "z1", "started_at": pd.Timestamp("2026-11-08 19:00"), "duration_seconds": 3600,
         "distance_km": 30.0, "world": "Watopia", "avg_power_w": 150.0, "elevation_gain_m": 300.0}]))
    with Session(db) as session:
        session.add(garmin_indoor.GarminIndoorRide(
            activity_id="z1", title="Zwift", started_at=datetime(2026, 11, 8, 19),
            track_json=json.dumps({"world": "watopia", "segments": [[[0.2, 0.2], [0.4, 0.3], [0.6, 0.2]]]}),
            synced_at=datetime(2026, 11, 8)))
        session.add(walkpad.WalkpadSession(id="w", started_at=datetime(2026, 11, 8, 6, 30), started_at_utc=0,
                                           ended_at_utc=0, moving_s=1800, distance_m=2000, incline_pct=6))
        workout = Workout(external_id="h", title="Milon OK", started_at=datetime(2026, 11, 8, 9),
                          ended_at=datetime(2026, 11, 8, 10))
        session.add(workout)
        session.commit()
        for kind, kg, reps, exercise in [("warmup", 20, 10, "Rudern"), ("normal", 50, 10, "Rudern"),
                                         ("normal", 50, 8, "Rudern"), ("normal", 10, 12, "Seitheben")]:
            session.add(WorkoutSet(workout_id=workout.id, exercise=exercise, set_type=kind, weight_kg=kg, reps=reps))
        session.commit()
    monkeypatch.setattr(health, "_steps", lambda: pd.DataFrame([{"day": pd.Timestamp(DAY), "steps": 12_345}]))
    monkeypatch.setattr(active_kcal, "compute", lambda s, e: ({DAY: {"run": 400.0, "gym": 200.4}}, {}))

    result = day_badge.badge()
    assert result["is_today"] and result["weekday"] == "Sonntag" and not result["empty"]
    assert result["steps"] == 12_345 and result["active_kcal"] == 600
    assert [r["km"] for r in result["runs"]] == [5.0, 3.0]          # gestriger Lauf fehlt, Route ohne Session dazu
    assert result["runs"][0]["pace_s"] == 360 and result["runs"][0]["shape"]
    assert result["runs"][1]["shape"] and result["runs"][1]["avg_hr"] is None
    kinds = {r["kind"]: r for r in result["rides"]}
    assert kinds["outdoor"]["shape"] and kinds["indoor"]["world"] == "Watopia" and kinds["indoor"]["shape"]
    assert kinds["detected"]["minutes"] == 12 and kinds["detected"]["shape"] is None
    assert result["strength"] == [{"time": "09:00", "title": "Milon OK", "minutes": 60.0, "sets": 3,
                                   "exercises": 2, "tonnage_kg": 50 * 18 + 120}]
    assert result["walks"][0]["km"] == 2.0 and result["walks"][0]["incline_pct"] == 6
    assert result["km"] == {"run": 8.0, "ride": 4.0, "zwift": 30.0, "walk": 2.0}
    assert result["sessions"] == 7 and result["active_minutes"] == round(30 + 30 + 15 + 12 + 60 + 60 + 30)

    raw = json.dumps(result)
    assert '"lat"' not in raw and '"lon"' not in raw and "Musterstadt" not in raw
    assert "50.12" not in raw and "7.65" not in raw
    for item in result["runs"] + result["rides"]:
        assert all(0 <= v <= 1 for point in item["shape"] or [] for v in point)


def test_empty_day_and_api(db):
    result = day_badge.badge(DAY - timedelta(days=3))
    assert result["empty"] and not result["is_today"] and result["sessions"] == 0 and result["steps"] is None
    client = TestClient(app)
    assert client.get("/metrics/activity/day-badge").json()["date"] == DAY.isoformat()
    assert client.get("/metrics/activity/day-badge?day=2026-11-05").json()["weekday"] == "Donnerstag"
    assert client.get("/metrics/activity/day-badge?day=2026-11-09").status_code == 422
