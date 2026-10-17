import json
import math
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app import hero, hero_world
from app.api import hero as hero_api
from app.garmin_routes import GarminRoute
from app.hero import HeroLivePoint, HeroState

HOME = (51.66, 6.62)
TOKEN = "s3cret"


@pytest.fixture
def live_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'live.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(hero_world, "engine", engine)
    monkeypatch.setattr(hero, "engine", engine)
    monkeypatch.setattr(hero_world.settings, "hero_live_token", TOKEN)
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


def latlon(x, y):
    return hero_world._from_m(HOME, x, y)


def add_route(engine, pts, start: datetime, rid="r1", step_s=10):
    """Garmin-Route aus (lat, lon)-Punkten; start = UTC."""
    seg = [{"lat": la, "lon": lo, "altitude_m": None, "time": (start + timedelta(seconds=i * step_s)).isoformat()}
           for i, (la, lo) in enumerate(pts)]
    with Session(engine) as s:
        s.add(GarminRoute(activity_id=rid, title="Lauf", started_at=start.replace(tzinfo=None), point_count=len(seg),
                          segments_json=json.dumps([seg]), synced_at=datetime.now()))
        s.commit()


def base_route(engine, home=HOME):
    """Eine alte Garmin-Runde nach Osten legt die Heimat fest."""
    east = [(home[0], home[1] + i * 0.0005) for i in range(40)]
    add_route(engine, east, datetime.now(timezone.utc) - timedelta(days=10), rid="base")


def track(path_m, start_ms, speed=4.0, home=HOME):
    """Live-Punkte entlang einer Meter-Polylinie, alle ~25 m, mit realistischem Zeitabstand."""
    out, t = [], start_ms
    for (x1, y1), (x2, y2) in zip(path_m, path_m[1:]):
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) // 25))
        for i in range(n):
            x, y = x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n
            la, lo = hero_world._from_m(home, x, y)
            out.append({"ts": t, "lat": la, "lon": lo, "acc": 8})
            t += int(math.hypot(x2 - x1, y2 - y1) / n / speed * 1000)
    return out


def post(c, session, points, token=TOKEN):
    return c.post("/hero/live", json={"session": session, "points": points}, headers={"X-Hero-Token": token})


def test_live_endpoints_need_token(live_db, monkeypatch):
    c = client()
    pt = [{"ts": time.time(), "lat": HOME[0], "lon": HOME[1], "acc": 5}]
    assert c.post("/hero/live", json={"session": "a", "points": pt}).status_code == 401
    assert post(c, "a", pt, token="falsch").status_code == 401
    assert c.get("/hero/live/state", params={"session": "a"}).status_code == 401
    assert c.post("/hero/live/target", json={"kind": None}, headers={"X-Hero-Token": "x"}).status_code == 401
    assert post(c, "a", pt).status_code == 200
    monkeypatch.setattr(hero_world.settings, "hero_live_token", "")
    for r in (post(c, "a", pt), c.get("/hero/live/state", params={"session": "a"}, headers={"X-Hero-Token": TOKEN}),
              c.post("/hero/live/target", json={}, headers={"X-Hero-Token": TOKEN})):
        assert r.status_code == 403
    assert hero_world.world() == {"available": False}  # ohne Token keine Live-Punkte in der Welt


def test_plausibility_filter(live_db):
    now = int(time.time() * 1000)
    la, lo = HOME
    pts = [{"ts": now - 60_000, "lat": la, "lon": lo, "acc": 5},
           {"ts": now - 55_000, "lat": la + 30 / 110_540, "lon": lo, "acc": 150},     # ungenau
           {"ts": now - 50_000, "lat": la + 40 / 110_540, "lon": lo, "acc": 5},      # 4 m/s
           {"ts": now - 49_000, "lat": la + 2000 / 110_540, "lon": lo, "acc": 5},    # Sprung ~2 km/s
           {"ts": now - 49 * 3600_000, "lat": la, "lon": lo, "acc": 5},              # älter als 48 h
           {"ts": (now - 40_000) / 1000, "lat": la + 80 / 110_540, "lon": lo, "acc": 5}]  # Sekunden statt ms
    r = post(client(), "run-1", pts).json()
    assert r == {"session": "run-1", "accepted": 3, "rejected": 3}
    with Session(live_db) as s:
        assert [p.ts for p in s.exec(select(HeroLivePoint).order_by(HeroLivePoint.ts))] == [now - 60_000, now - 50_000, now - 40_000]
    # gleicher Zeitstempel erneut = Dublette
    assert post(client(), "run-1", pts[:1]).json()["accepted"] == 0


def test_live_points_reveal_provisionally_without_rewards(live_db):
    base_route(live_db)
    base = hero_world.world()
    target = min((p for p in base["pois"] if not p["found"]), key=lambda p: math.hypot(p["x"], p["y"]))
    now = int(time.time() * 1000)
    path = [(0, 0), (target["x"], target["y"])]
    assert post(client(), "run-1", track(path, now - 30 * 60_000)).json()["rejected"] == 0
    w = hero_world.world()
    poi = next(p for p in w["pois"] if p["id"] == target["id"])
    assert poi["provisional"] and not poi["found"] and poi["found_on"] is None  # markiert, aber kein Fund
    assert w["live"]["sessions"] == ["run-1"] and w["live"]["cells"] and w["live"]["km2"] > 0
    assert {tuple(c) for c in w["live"]["cells"]}.isdisjoint({tuple(c) for c in w["cells"]})  # Wahrheit unverändert
    assert w["cells"] == base["cells"] and w["explored_pct"] == base["explored_pct"]
    reg = next(r for r in w["regions"] if r["name"] == target["region"])
    assert reg.get("live_cells") and (reg["provisional"] or reg["discovered"])
    # die Wahrheitsfelder der Verbraucher (EP/Gold/Beute/Log) sehen keinen vorläufigen Fund
    assert not [p for p in w["pois"] if p["found"] and p["id"] == target["id"]]
    assert hero.map_loot(w, datetime.now().date() - timedelta(days=30)) == hero.map_loot(base, datetime.now().date() - timedelta(days=30))
    st = client().get("/hero/live/state", params={"session": "run-1"}, headers={"X-Hero-Token": TOKEN}).json()
    assert st["active"] and st["revealed"]["cells"] == len(w["live"]["cells"])
    assert any(f["id"] == target["id"] and f["provisional"] for f in st["finds"])
    assert all(f["provisional"] for f in st["finds"])


def test_live_loop_fills_inside(live_db):
    base_route(live_db)
    now = int(time.time() * 1000)
    square = [(0, -200), (0, -1700), (-1500, -1700), (-1500, -200), (0, -200)]
    post(client(), "loop", track(square, now - 40 * 60_000))
    cells = {tuple(c) for c in hero_world.world()["live"]["cells"]}
    assert (-5, -7) in cells  # Mitte der Runde (750 m von jeder Seite) ist vorläufig aufgedeckt


def test_dungeon_segment_progress_is_provisional(live_db):
    dg = next(d for d in hero_world.dungeon_defs() if d["key"] == "auesee")
    seg0 = [tuple(p) for p in dg["segments"][0]["points"]]
    home = (seg0[0][0] + 0.01, seg0[0][1])
    base_route(live_db, home)
    hero_world.world()
    path = [hero_world._to_m(hero_world._memo["home"], la, lo) for la, lo in [home] + seg0]
    now = int(time.time() * 1000)
    post(client(), "run-1", track(path, now - 50 * 60_000, home=hero_world._memo["home"]))
    c = client()
    assert c.post("/hero/live/target", json={"kind": "dungeon", "id": "dungeon:auesee"},
                  headers={"X-Hero-Token": TOKEN}).json() == {"session": "run-1", "kind": "dungeon", "id": "dungeon:auesee"}
    w = hero_world.world()
    d = next(x for x in w["dungeons"] if x["key"] == "auesee")
    assert d["provisional"] and not d["discovered"] and d["segments"][0]["points"]  # Strecke vorläufig sichtbar
    assert d["segments"][0]["provisional"] and not d["segments"][0]["cleared"] and d["segments"][0]["coverage"] == 0
    st = c.get("/hero/live/state", params={"session": "run-1"}, headers={"X-Hero-Token": TOKEN}).json()
    assert st["target"]["id"] == "dungeon:auesee" and st["target"]["chosen"]
    assert st["dungeon"]["segments"][0]["provisional"] and st["dungeon"]["segments"][0]["coverage"] >= 0.8
    assert not st["dungeon"]["segments"][1]["provisional"]
    assert any(f["kind"] == "abschnitt" for f in st["finds"])


def _numbers(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _numbers(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _numbers(v, path)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield path, obj


def test_state_has_no_coordinates_and_target_api(live_db):
    base_route(live_db)
    c = client()
    h = {"X-Hero-Token": TOKEN}
    assert c.post("/hero/live/target", json={"kind": "poi", "id": "schrein:0"}, headers=h).status_code == 409  # keine Session
    now = int(time.time() * 1000)
    post(c, "run-1", track([(0, 0), (0, 2000)], now - 20 * 60_000))
    st = c.get("/hero/live/state", params={"session": "run-1"}, headers=h).json()
    text = json.dumps(st)
    assert '"lat"' not in text and '"lon"' not in text
    nums = [(k, v) for k, v in _numbers(st) if k not in ("first_ts", "last_ts")]
    assert nums and all(abs(v) < hero_world.WORLD_RADIUS_M for _, v in nums)
    assert str(round(HOME[0], 3)) not in text and str(round(HOME[1], 3)) not in text
    auto = st["target"]
    assert auto and not auto["chosen"] and 0 <= auto["bearing_deg"] < 360 and 0 < auto["distance_m"] < hero_world.WORLD_RADIUS_M
    # gewähltes Ziel: Richtung/Entfernung zum Ort
    poi = next(p for p in hero_world.pois() if p["region"] == hero_world.CORE)
    assert c.post("/hero/live/target", json={"session": "run-1", "kind": "poi", "id": poi["id"]}, headers=h).status_code == 200
    st = c.get("/hero/live/state", params={"session": "run-1"}, headers=h).json()
    assert st["target"]["id"] == poi["id"] and st["target"]["chosen"] and st["dungeon"] is None
    assert c.post("/hero/live/target", json={"kind": "poi", "id": "schrein:9999"}, headers=h).status_code == 404
    assert c.post("/hero/live/target", json={"kind": "poi"}, headers=h).status_code == 422
    assert c.post("/hero/live/target", json={"session": "run-1"}, headers=h).status_code == 200  # Ziel löschen
    assert not c.get("/hero/live/state", params={"session": "run-1"}, headers=h).json()["target"]["chosen"]
    unknown = c.get("/hero/live/state", params={"session": "nie"}, headers=h).json()
    assert unknown["available"] and not unknown["active"] and unknown["target"] is None


def test_live_points_deleted_after_garmin_route_covers_session(live_db):
    base_route(live_db)
    c = client()
    start = datetime.now(timezone.utc) - timedelta(minutes=40)
    start_ms = int(start.timestamp() * 1000)
    north = [(0, 0), (0, 2500)]
    post(c, "run-1", track(north, start_ms))
    c.post("/hero/live/target", json={"kind": "dungeon", "id": "dungeon:auesee"}, headers={"X-Hero-Token": TOKEN})
    post(c, "run-2", track([(0, 0), (-2000, 0)], start_ms - 6 * 3600_000))  # Vormittag, keine Garmin-Route dazu
    assert hero_world.world()["live"]["sessions"] == ["run-1", "run-2"]
    # Garmin-Sync liefert den Lauf: dessen Zeitraum überlappt run-1
    add_route(live_db, [latlon(0, y) for y in range(0, 2600, 100)], start + timedelta(minutes=1), rid="garmin-1", step_s=60)
    w = hero_world.world()
    assert w["live"]["sessions"] == ["run-2"]
    with Session(live_db) as s:
        assert {p.session for p in s.exec(select(HeroLivePoint))} == {"run-2"}
        assert s.get(HeroState, hero_world.TARGET_PREFIX + "run-1") is None
    assert {tuple(c) for c in w["cells"]} >= {(0, 10)}  # jetzt echte Aufdeckung aus der Garmin-Spur


def test_live_points_expire_after_48h(live_db):
    base_route(live_db)
    old = int(time.time() * 1000) - 49 * 3600_000
    with Session(live_db) as s:
        for i in range(5):
            s.add(HeroLivePoint(session="alt", ts=old + i * 5000, lat=HOME[0] + i * 1e-4, lon=HOME[1], acc=5, received_at=datetime.now()))
        s.add(HeroState(key=hero_world.TARGET_PREFIX + "alt", value=json.dumps({"kind": "poi", "id": "schrein:0", "set_at": old})))
        s.commit()
    assert hero_world.purge_live() == ["alt"]
    with Session(live_db) as s:
        assert not s.exec(select(HeroLivePoint)).all() and s.get(HeroState, hero_world.TARGET_PREFIX + "alt") is None
    assert hero_world.world()["live"] is None


def test_world_with_live_points_stays_fast(live_db):
    base_route(live_db)
    now = int(time.time() * 1000)
    loop = [(0, 0), (0, 3000), (3000, 3000), (3000, 0), (0, 0)]
    pts = track(loop, now - 60 * 60_000, speed=4.0)
    assert len(pts) >= 400
    post(client(), "run-1", pts)
    t0 = time.perf_counter()
    w = hero_world.world()
    first = time.perf_counter() - t0
    t0 = time.perf_counter()
    assert hero_world.world() is w  # Memo greift
    again = time.perf_counter() - t0
    assert first < 1.0 and again < 0.2, (first, again)
