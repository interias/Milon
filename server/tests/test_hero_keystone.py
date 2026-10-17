import json
import math
import time
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app import hero, hero_keystone as ks, hero_world
from app.api import hero as hero_api
from app.garmin_routes import GarminRide, GarminRoute

HOME = (51.66, 6.62)
TOKEN = "s3cret"
H = {"X-Hero-Token": TOKEN}
PACE = 6.0  # min/km der lockeren Läufe (synthetisch)


@pytest.fixture
def ks_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'ks.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for mod in (hero_world, hero):
        monkeypatch.setattr(mod, "engine", engine)
    monkeypatch.setattr(hero_world.settings, "hero_live_token", TOKEN)
    today = datetime.now()
    runs = [{"started_at": today - timedelta(days=d), "pace": PACE, "avg_hr": 130.0} for d in range(1, 30, 3)]
    monkeypatch.setattr(ks, "_run_history", lambda: (runs, 180.0))
    monkeypatch.setattr(ks, "_weather_hours", lambda day: [])
    monkeypatch.setattr(ks, "today_debuffs", lambda day: [])
    hero_world._memo.clear()
    hero_world._live_memo.clear()
    yield engine
    hero_world._memo.clear()
    hero_world._live_memo.clear()
    engine.dispose()


def client():
    app = FastAPI()
    app.include_router(hero_api.router)
    return TestClient(app)


def dungeon(key="festungsring"):
    return next(d for d in hero_world.dungeon_defs() if d["key"] == key)


def path_m(dg):
    return [hero_world._to_m(HOME, la, lo) for seg in dg["segments"] for la, lo in seg["points"]]


def dense(points, step=20.0):
    out = []
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) // step))
        out += [(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(n)]
    return out + [points[-1]]


def add_route(engine, meters, start: datetime, rid: str, total_s: float | None = None):
    """Garmin-Lauf entlang einer Meter-Polylinie; Zeit gleichmäßig über die Strecke verteilt (start = UTC)."""
    pts = dense(meters)
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
    speed = length / total_s if total_s else 3.0
    seg, t = [], 0.0
    for i, (x, y) in enumerate(pts):
        if i:
            t += math.hypot(x - pts[i - 1][0], y - pts[i - 1][1]) / speed
        la, lo = hero_world._from_m(HOME, x, y)
        seg.append({"lat": la, "lon": lo, "altitude_m": None, "time": (start + timedelta(seconds=t)).isoformat()})
    with Session(engine) as s:
        s.add(GarminRoute(activity_id=rid, title="Lauf", started_at=start.replace(tzinfo=None), point_count=len(seg),
                          segments_json=json.dumps([seg]), synced_at=datetime.now()))
        s.commit()
    return length


def setup_world(engine, discover=True):
    old = datetime.now(timezone.utc) - timedelta(days=20)
    for i in range(3):  # Heimat festlegen
        add_route(engine, [(0, 0), (40, 0)], old + timedelta(hours=i), f"base{i}")
    if discover:
        add_route(engine, path_m(dungeon())[:20], old + timedelta(days=1), "discover")


def activate(session="run-1", level=2, affixes=(), dg="festungsring"):
    return client().post("/hero/live/keystone", json={"session": session, "dungeon": dg, "level": level,
                                                      "affixes": list(affixes)}, headers=H)


def base_s(dg):
    return PACE * 60 * dg["length_m"] / 1000


# --- reine Bausteine -----------------------------------------------------------------------------

def test_buffer_and_time_limit():
    assert ks.buffer_for(2) == pytest.approx(0.20)
    assert ks.buffer_for(10) == pytest.approx(0.05)
    assert ks.buffer_for(6) == pytest.approx(0.125)
    assert ks.buffer_for(15) == pytest.approx(0.05)
    assert ks.time_limit_s(6.0, 10_000, 2) == 4320  # 60 min × 1,2
    assert ks.time_limit_s(6.0, 10_000, 10) == 3780


def test_easy_pace_from_synthetic_history():
    today = date(2026, 10, 1)
    d = lambda n: datetime(2026, 10, 1) - timedelta(days=n)  # noqa: E731
    runs = [{"started_at": d(5), "pace": 6.5, "avg_hr": 130},   # locker (< 144 = 80 % von 180)
            {"started_at": d(10), "pace": 6.3, "avg_hr": 135},
            {"started_at": d(20), "pace": 6.9, "avg_hr": 140},
            {"started_at": d(30), "pace": 5.2, "avg_hr": 165},  # Tempo-Lauf: zählt nicht
            {"started_at": d(120), "pace": 8.0, "avg_hr": 120}]  # älter als 90 Tage
    assert ks.easy_pace(runs, today, 180) == {"pace": 6.5, "runs": 3, "source": "zonen"}
    no_hr = [{**r, "avg_hr": None} for r in runs]  # ohne Puls: langsamere Hälfte
    assert ks.easy_pace(no_hr, today, 180) == {"pace": 6.7, "runs": 2, "source": "langsame_haelfte"}
    assert ks.easy_pace([], today, 180)["source"] == "standard"


def test_week_affix_stable_per_week():
    monday = date(2026, 10, 12)
    assert {ks.week_affix(monday + timedelta(days=i)) for i in range(7)} == {ks.week_affix(monday)}
    weeks = {ks.week_affix(monday + timedelta(weeks=w)) for w in range(12)}
    assert len(weeks) > 1 and weeks <= set(ks.AFFIXES)


def test_weather_affixes_only_bonus():
    start = datetime(2026, 10, 17, 7, 10)
    hours = [{"time": "2026-10-17T07:00", "rain_mm": 0.0, "rain_prob": 10, "wind_kmh": 12, "is_day": False},
             {"time": "2026-10-17T08:00", "rain_mm": 0.6, "rain_prob": 80, "wind_kmh": 24, "is_day": True},
             {"time": "2026-10-17T12:00", "rain_mm": 3.0, "rain_prob": 90, "wind_kmh": 40, "is_day": True}]
    assert ks.weather_affixes(hours, start, 60) == ["regen", "sturm", "dunkelheit"]
    assert ks.weather_affixes(hours[:1], start, 30) == ["dunkelheit"]
    good = [{"time": "2026-10-17T10:00", "rain_mm": 0, "rain_prob": 0, "wind_kmh": 5, "is_day": True}]
    assert ks.weather_affixes(good, datetime(2026, 10, 17, 10, 5), 60) == []


def test_judge():
    assert ks.judge(700, 1000, True) == ("fast", 2)
    assert ks.judge(950, 1000, True) == ("timed", 1)
    assert ks.judge(1100, 1000, True) == ("slow", -1)
    assert ks.judge(500, 1000, False) == ("incomplete", 0)


# --- Aktivieren -----------------------------------------------------------------------------------

def test_activate_needs_token_and_discovered_dungeon(ks_db):
    setup_world(ks_db, discover=False)
    assert client().post("/hero/live/keystone", json={"session": "a", "dungeon": "festungsring", "level": 2}).status_code == 401
    assert activate().status_code == 404  # noch im Nebel
    assert activate(dg="gibtsnicht").status_code == 404
    assert client().get("/hero/live/keystone", params={"dungeon": "festungsring"}, headers=H).status_code == 404


def test_activate_allowed_levels_and_preview(ks_db):
    setup_world(ks_db)
    dg = dungeon()
    pv = client().get("/hero/live/keystone", params={"dungeon": "dungeon:festungsring"}, headers=H).json()
    assert pv["levels"] == [2] and pv["key_level"] == 2
    assert pv["suggested_level"]["level"] == 2
    assert pv["time_limits"]["2"] == round(base_s(dg) * 1.2)
    assert pv["week_affix"]["key"] == ks.week_affix(datetime.now().date())
    assert activate(level=3).status_code == 422          # Start: höchstens +2
    assert activate(level=1).status_code == 422
    assert activate(affixes=["unbekannt"]).status_code == 422
    r = activate(level=2, affixes=["pausenlos"]).json()
    assert r["level"] == 2 and r["time_limit_s"] == pv["time_limits"]["2"] and r["affixes"] == ["pausenlos"]
    assert r["weather_affixes"] == [] and r["provisional"]
    assert hero_world._get_target("run-1")["id"] == "dungeon:festungsring"  # Stein setzt das Live-Ziel


def test_weather_affix_from_mocked_weather(ks_db, monkeypatch):
    setup_world(ks_db)
    now = datetime.now()
    hours = [{"time": (now + timedelta(hours=h)).strftime("%Y-%m-%dT%H:00"), "rain_mm": 1.0, "rain_prob": 90,
              "wind_kmh": 8, "is_day": True} for h in range(-1, 4)]
    monkeypatch.setattr(ks, "_weather_hours", lambda day: hours)
    assert activate().json()["weather_affixes"] == ["regen"]

    def broken(day):
        raise RuntimeError("Open-Meteo weg")
    monkeypatch.setattr(ks, "_weather_hours", broken)
    assert activate(session="run-2").json()["weather_affixes"] == []  # Wetter fehlt = kein Bonus, kein Fehler


def test_suggestion_uses_debuffs_but_never_restricts(ks_db, monkeypatch):
    setup_world(ks_db)
    assert ks.briefing_recommendation(date.today()) is None  # Morgenbriefing noch nicht vorhanden
    monkeypatch.setattr(ks, "today_debuffs", lambda day: ["uebermuedet"])
    s = ks.suggest(5, date.today())
    assert s == {"level": 2, "source": "debuffs", "reason": "Übermüdet – heute lieber eine niedrige Stufe"}
    monkeypatch.setattr(ks, "briefing_recommendation", lambda day: "locker")
    assert ks.suggest(5, date.today())["source"] == "morgenbriefing"
    monkeypatch.setattr(ks, "briefing_recommendation", lambda day: None)
    monkeypatch.setattr(ks, "today_debuffs", lambda day: [])
    assert ks.suggest(5, date.today()) == {"level": 5, "source": "stand", "reason": "Aktuelle Steinstufe dieses Verlieses"}


# --- Ergebnis aus der Garmin-Spur -------------------------------------------------------------------

def run_keystone(engine, ratio, level=2, affixes=(), path=None, rid="ks", ago_h=3):
    """Aktiviert einen Stein vor ago_h Stunden und legt eine Garmin-Spur mit ratio × Basiszeit an."""
    dg = dungeon()
    act = datetime.now(timezone.utc) - timedelta(hours=ago_h)
    act_ms = int(act.timestamp() * 1000)
    ks.activate(rid, "festungsring", level, list(affixes), now_ms=act_ms)
    limit = ks.time_limit_s(PACE, dg["length_m"], level)
    pts = path or path_m(dg)
    # Zielzeit gilt für die Verlies-Strecke; die Spur ist genau die Strecke
    add_route(engine, pts, act + timedelta(minutes=5), rid, total_s=ratio * limit)
    ks.resolve_pending()
    return next(r for r in ks.results("festungsring") if r["session"] == rid), limit


def test_results_from_simulated_garmin_tracks(ks_db):
    setup_world(ks_db)
    res, limit = run_keystone(ks_db, 0.7, rid="a", ago_h=10)          # deutlich schneller: +2
    assert res["status"] == "fast" and res["delta"] == 2
    assert res["result"]["all_segments"] and res["result"]["elapsed_s"] <= 0.8 * limit
    h = ks.history([k for k in Session(ks_db).exec(select(ks.HeroKeystone))])["festungsring"]
    assert h == {"key_level": 4, "max_level": 4, "runs": 1, "timed": 1}
    assert activate(level=4).status_code == 200 and ks.abort("run-1")  # jetzt bis +4 wählbar; Abbruch kostet nichts
    assert activate(level=5).status_code == 422

    res, limit = run_keystone(ks_db, 0.95, level=4, rid="b", ago_h=8)  # in der Zeit: +1
    assert (res["status"], res["delta"]) == ("timed", 1)
    res, _ = run_keystone(ks_db, 1.3, level=5, rid="c", ago_h=6)      # zu langsam: −1
    assert (res["status"], res["delta"]) == ("slow", -1)
    pv = ks.preview("festungsring")
    assert pv["key_level"] == 4 and pv["max_level"] == 5 and pv["levels"] == [2, 3, 4, 5]


def test_slow_never_below_two_and_incomplete_costs_nothing(ks_db):
    setup_world(ks_db)
    res, _ = run_keystone(ks_db, 1.5, rid="a", ago_h=10)
    assert res["status"] == "slow" and ks.preview("festungsring")["key_level"] == 2
    half = path_m(dungeon())[:len(path_m(dungeon())) // 2]
    res, _ = run_keystone(ks_db, 0.5, path=half, rid="b", ago_h=6)    # nur die Hälfte: kein Ergebnis, keine Kosten
    assert res["status"] == "incomplete" and res["delta"] == 0 and res["result"]["loot_bonus"] == 0
    assert ks.preview("festungsring")["key_level"] == 2


def test_affix_bonus_and_expiry(ks_db):
    setup_world(ks_db)
    res, _ = run_keystone(ks_db, 0.7, affixes=["zeitdruck", "pausenlos", "negativ"], rid="a", ago_h=10)
    done = res["result"]["affixes_done"]
    assert done["zeitdruck"] and done["pausenlos"] and not done["negativ"]  # gleichmäßiges Tempo: kein Negativ-Split
    assert res["result"]["loot_bonus"] == sum(done.values())
    # Stein ohne Garmin-Spur verfällt nach 24 h kostenlos
    ks.activate("old", "festungsring", 2, [], now_ms=int(time.time() * 1000) - 25 * 3600 * 1000)
    ks.resolve_pending()
    old = next(r for r in ks.results() if r["status"] == "expired")
    assert old["delta"] == 0


def test_rides_or_unrelated_runs_do_not_count(ks_db):
    setup_world(ks_db)
    act = datetime.now(timezone.utc) - timedelta(hours=2)
    ks.activate("x", "festungsring", 2, [], now_ms=int(act.timestamp() * 1000))
    add_route(ks_db, path_m(dungeon()), act - timedelta(hours=5), "vorher", total_s=1000)  # Lauf VOR der Aktivierung
    add_route(ks_db, path_m(dungeon()), act + timedelta(minutes=5), "rad", total_s=1000)
    with Session(ks_db) as s:  # dieselbe Spur nach der Aktivierung als Radfahrt: zählt nie
        r = s.get(GarminRoute, "rad")
        s.add(GarminRide(activity_id="rad", title="Rad", started_at=r.started_at, point_count=r.point_count,
                         segments_json=r.segments_json, synced_at=r.synced_at))
        s.delete(r)
        s.commit()
    ks.resolve_pending()
    assert ks.results() == []  # noch aktiv, nichts gewertet


# --- Live -------------------------------------------------------------------------------------------

def live_points(meters, start_ms, speed=3.0):
    out, t = [], start_ms
    pts = dense(meters, 25)
    for i, (x, y) in enumerate(pts):
        if i:
            t += int(math.hypot(x - pts[i - 1][0], y - pts[i - 1][1]) / speed * 1000)
        la, lo = hero_world._from_m(HOME, x, y)
        out.append({"ts": t, "lat": la, "lon": lo, "acc": 8})
    return out


def test_live_state_reports_active_keystone(ks_db):
    setup_world(ks_db)
    c = client()
    st = c.get("/hero/live/state", params={"session": "run-1"}, headers=H).json()
    assert st["keystone"] is None  # ohne Stein wie bisher
    now = int(time.time() * 1000)
    ks.activate("run-1", "festungsring", 2, ["negativ"], now_ms=now - 25 * 60_000)
    first_seg = [hero_world._to_m(HOME, la, lo) for la, lo in dungeon()["segments"][0]["points"]]
    pts = live_points(first_seg, now - 20 * 60_000)
    assert c.post("/hero/live", json={"session": "run-1", "points": pts}, headers=H).json()["rejected"] == 0
    st = c.get("/hero/live/state", params={"session": "run-1"}, headers=H).json()
    k = st["keystone"]
    assert k["level"] == 2 and k["provisional"] and k["clock_started"]
    assert {a["kind"] for a in k["affixes"]} >= {"gewaehlt", "woche"}
    assert k["segments_total"] == 4 and k["segments_cleared"] == 1 and k["segments"][0]["cleared"]
    assert 0 < k["remaining_s"] < k["time_limit_s"]
    assert st["target"]["id"] == "dungeon:festungsring"
    assert "lat" not in json.dumps(k) and "lon" not in json.dumps(k)
    assert c.post("/hero/live/keystone/abort", json={"session": "run-1"}, headers=H).json()["aborted"]
    assert c.get("/hero/live/state", params={"session": "run-1"}, headers=H).json()["keystone"] is None
