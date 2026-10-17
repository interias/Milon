"""Rad-Erkundung (#57): Radspuren decken mit halber Sicht auf, finden Gebiete/Schreine/Schätze
für halbe Erkundungs-EP und -Gold, zählen aber nie für Verlies-Abschnitte."""
import json
import math
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import hero, hero_economy, hero_world
from app.garmin_routes import GarminRide, GarminRoute
from app.models import ExerciseSession

HOME = (51.66, 6.62)  # Fantasie-Heimat
NOW = datetime.now(timezone.utc)


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'rides.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for mod in (hero_world, hero):
        monkeypatch.setattr(mod, "engine", engine)
    hero_world._memo.clear()
    hero_world._live_memo.clear()
    yield engine
    hero_world._memo.clear()
    hero_world._live_memo.clear()
    engine.dispose()


def dense(points, step=20.0):
    out = []
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) // step))
        out += [(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(n)]
    return out + [points[-1]]


def add_track(engine, model, meters, start: datetime, rid: str):
    seg = []
    for x, y in dense(meters):
        la, lo = hero_world._from_m(HOME, x, y)
        seg.append({"lat": la, "lon": lo, "altitude_m": None, "time": start.isoformat()})
    with Session(engine) as s:
        s.add(model(activity_id=rid, title="Spur", started_at=start.replace(tzinfo=None), point_count=len(seg),
                    segments_json=json.dumps([seg]), synced_at=datetime.now()))
        s.commit()


def base_world(engine):
    old = NOW - timedelta(days=30)
    for i in range(3):  # Heimat festlegen
        add_track(engine, GarminRoute, [(0, 0), (40, 0)], old + timedelta(hours=i), f"base{i}")


LINE = [(-1500, 5000), (1500, 5000)]  # Zellmitten-Reihen j=32 (125 m), 33 (25 m), 34 (175 m), 31 (275 m), 35 (325 m)


def rows(cells, i=0):
    return {j for ci, j in cells if ci == i and 29 <= j <= 37}


def treasure():
    return next(p for p in hero_world.pois() if p["kind"] == "schatz" and p["km"] >= 2.5 and p["region"] != hero_world.CORE)


def test_ride_reveals_150m_and_finds_treasure(db):
    base_world(db)
    add_track(db, GarminRide, LINE, NOW - timedelta(days=2), "ride1")
    assert rows(hero_world.world()["cells"]) == {32, 33}
    p = treasure()
    add_track(db, GarminRide, [(p["x"] - 800, p["y"]), (p["x"] + 800, p["y"])], NOW - timedelta(days=2), "ride2")
    w = hero_world.world()
    place = next(q for q in w["pois"] if q["id"] == p["id"])
    assert place["found"] and place["via"] == "rad"
    assert len(w["rides"]) == 2 and len(w["routes"]) == 3  # Radspuren getrennt von den Laufspuren
    region = next(r for r in w["regions"] if r["name"] == p["region"])
    assert region["discovered"] and region["via"] == "rad"


def test_run_keeps_300m_sight(db):
    base_world(db)
    add_track(db, GarminRoute, LINE, NOW - timedelta(days=2), "run1")
    w = hero_world.world()
    assert rows(w["cells"]) == {31, 32, 33, 34}
    assert w["rides"] == []


def test_ride_does_not_move_home(db):
    base_world(db)
    home = hero_world._home(hero_world._routes())
    for k in range(5):  # viele Radfahrten mit fremdem Startpunkt
        add_track(db, GarminRide, [(4000, 4000), (4500, 4000)], NOW - timedelta(days=3, hours=k), f"r{k}")
    hero_world.world()
    assert hero_world._memo["home"] == home


def _segment_def():
    pts = [hero_world._from_m(HOME, x, 9000) for x in range(-1000, 1001, 50)]
    return {"key": "testweg", "name": "Testweg", "type": "feld", "desc": "", "length_m": 2000.0,
            "segments": [{"boss": "Testboss", "points": [list(p) for p in pts]}]}


def test_ride_over_dungeon_clears_nothing(db, monkeypatch):
    monkeypatch.setattr(hero_world, "dungeon_defs", lambda: [_segment_def()])
    base_world(db)
    add_track(db, GarminRide, [(-1000, 9000), (1000, 9000)], NOW - timedelta(days=2), "ride")
    dg = hero_world.world()["dungeons"][0]
    assert dg["discovered"]  # sichtbar zu Rad …
    assert not dg["segments"][0]["cleared"] and dg["segments"][0]["coverage"] == 0 and not dg["cleared"]  # … bezwungen nur zu Fuß
    add_track(db, GarminRoute, [(-1000, 9000), (1000, 9000)], NOW - timedelta(days=1), "run")
    assert hero_world.world()["dungeons"][0]["segments"][0]["cleared"]


@pytest.mark.parametrize("run_days, ride_days, via", [(2, 2, "fuss"), (1, 2, "rad"), (3, 2, "fuss")])
def test_double_find_earliest_wins_run_on_tie(db, run_days, ride_days, via):
    """Regel: der früheste Fund zählt; am selben Tag gewinnt der Lauf (volle Belohnung)."""
    base_world(db)
    p = treasure()
    line = [(p["x"] - 800, p["y"]), (p["x"] + 800, p["y"])]
    add_track(db, GarminRoute, line, NOW - timedelta(days=run_days), "run")
    add_track(db, GarminRide, line, NOW - timedelta(days=ride_days), "ride")
    place = next(q for q in hero_world.world()["pois"] if q["id"] == p["id"])
    assert place["via"] == via
    assert place["found_on"] == (NOW - timedelta(days=max(run_days, ride_days))).date().isoformat()


def test_ride_finds_give_half_xp_and_gold(db, monkeypatch):
    today = date(2026, 10, 16)
    for name, fn in (("_achievement_xp", lambda: []), ("_strength_series", lambda: []), ("_protein_days", lambda: {}),
                     ("_protein_target", lambda: None), ("_streak", lambda: 0)):
        monkeypatch.setattr(hero, name, fn)
    with Session(db) as s:
        s.add(ExerciseSession(exercise_type=33, started_at=datetime(2026, 10, 10, 7), ended_at=datetime(2026, 10, 10, 7, 40),
                              distance_km=6.0, avg_hr=140, max_hr=160, external_id="run-a"))
        s.commit()
    day = today.isoformat()
    world = {"available": True, "dungeons": [],
             "regions": [{"name": "Gebiet Rad", "xp": 50, "gold": 2, "discovered": True, "discovered_on": day, "via": "rad",
                          "pct": 1.0, "cells": 1, "total": 100},
                         {"name": "Gebiet Lauf", "xp": 50, "gold": 2, "discovered": True, "discovered_on": day, "via": "fuss",
                          "pct": 1.0, "cells": 1, "total": 100}],
             "pois": [{"id": "schatz:1", "kind": "schatz", "kind_label": "Schatz", "name": "Truhe Rad", "region": "Gebiet Rad",
                       "level": 10, "km": 3.0, "xp": 25, "gold": 3, "loot": None, "found": True, "found_on": day, "via": "rad"}]}
    monkeypatch.setattr(hero.hero_world, "world", lambda: world)
    data = hero._load(today)
    got = {e["name"]: e for e in data["entries"] if e["kind"] in ("erkundung", "schatz")}
    assert got["Gebiet Rad"]["xp"] == 25 and got["Gebiet Lauf"]["xp"] == 50 and got["Truhe Rad"]["xp"] == 12.5
    assert "zu Rad" in got["Gebiet Rad"]["label"] and "zu Rad" in got["Truhe Rad"]["label"]
    assert "zu Rad" not in got["Gebiet Lauf"]["label"]
    empty = pd.DataFrame(columns=["day", "distance_km"])
    gold = hero_economy.earnings({"runs": empty, "workouts": empty, "quest_weeks": [], "bosses": [], "dungeons": [],
                                  "events": [], "duels": [], "world": world}, today)
    src = [(c, s) for _, c, s in gold if s.startswith("Erkundung")]
    assert sorted(src) == sorted([(hero_economy.GOLD, "Erkundung zu Rad"), (2 * hero_economy.GOLD, "Erkundung"),
                                  (int(1.5 * hero_economy.GOLD), "Erkundung zu Rad")])
