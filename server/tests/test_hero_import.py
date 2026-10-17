"""Eigene Strecken per GPX: Verlies- und Spur-Import. Nur synthetische Strecken um eine Fantasie-Heimat."""
import json
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app import hero, hero_import, hero_world
from app.api import hero as hero_api
from app.config import settings
from app.garmin_routes import GarminRoute
from app.models import ExerciseSession

HOME = (51.66, 6.62)


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'own.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for mod in (hero_world, hero):
        monkeypatch.setattr(mod, "engine", engine)
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


def dense(points, step=20.0):
    out = []
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) // step))
        out += [(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(n)]
    return out + [points[-1]]


def add_route(engine, meters, start: datetime, rid: str):
    """Garmin-Lauf entlang einer Meter-Polylinie mit 3 m/s (start = UTC)."""
    seg, t, pts = [], 0.0, dense(meters)
    for i, (x, y) in enumerate(pts):
        if i:
            t += math.hypot(x - pts[i - 1][0], y - pts[i - 1][1]) / 3.0
        la, lo = hero_world._from_m(HOME, x, y)
        seg.append({"lat": la, "lon": lo, "altitude_m": None, "time": (start + timedelta(seconds=t)).isoformat()})
    local = start.astimezone(ZoneInfo(settings.timezone)).replace(tzinfo=None)
    with Session(engine) as s:
        s.add(GarminRoute(activity_id=rid, title="Lauf", started_at=local, point_count=len(seg),
                          segments_json=json.dumps([seg]), synced_at=datetime.now()))
        s.commit()


def gpx(meters, start: datetime | None = None, route=False, step=50.0) -> bytes:
    """Synthetische GPX-Datei (Track mit optionalen Zeitstempeln oder Route ohne)."""
    rows, t, pts = [], 0.0, dense(meters, step)
    for i, (x, y) in enumerate(pts):
        if i:
            t += math.hypot(x - pts[i - 1][0], y - pts[i - 1][1]) / 3.0
        la, lo = hero_world._from_m(HOME, x, y)
        tag = "rtept" if route else "trkpt"
        tm = f"<time>{(start + timedelta(seconds=t)).strftime('%Y-%m-%dT%H:%M:%SZ')}</time>" if start else ""
        rows.append(f'<{tag} lat="{la:.6f}" lon="{lo:.6f}">{tm}</{tag}>')
    body = f"<rte>{''.join(rows)}</rte>" if route else f"<trk><trkseg>{''.join(rows)}</trkseg></trk>"
    return f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">{body}</gpx>'.encode()


def base_world(engine):
    old = datetime.now(timezone.utc) - timedelta(days=30)
    for i in range(3):  # Heimat festlegen, deckt nur die Umgebung der Heimat auf
        add_route(engine, [(0, 0), (40, 0)], old + timedelta(hours=i), f"base{i}")


FAR = [(3000, 3000), (3000, 8000)]          # 5 km, weit weg vom Erkundeten
LOOP = [(-3000, -3000), (-3000, -5500), (-500, -5500)]  # 5 km, für Spuren


def upload(content: bytes, mode: str, name="strecke.gpx"):
    return client().post("/hero/world/own", files={"file": (name, content, "application/gpx+xml")}, data={"mode": mode})


def test_import_as_dungeon_sections_level_and_visibility(db):
    base_world(db)
    r = upload(gpx(FAR, route=True), "dungeon")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["kind"] == "dungeon" and out["own"] is True and out["segments"] == 3
    assert out["length_km"] == pytest.approx(5.0, abs=0.1)
    dg = next(d for d in hero_world.world()["dungeons"] if d["key"] == out["id"])
    xs = [p[0] for p in dense(FAR, 30)]
    ys = [p[1] for p in dense(FAR, 30)]
    dist = math.hypot(sum(xs) / len(xs), sum(ys) / len(ys))
    assert dg["level"] == hero_world.dungeon_level(dist, 5000) == out["level"]
    assert dg["own"] is True and dg["type_label"] == "Eigene Strecke" and dg["region"] == out["region"]
    assert len({s["boss"] for s in dg["segments"]}) == 3
    assert not dg["discovered"] and all(s["points"] == [] for s in dg["segments"])  # im Nebel
    assert hero_world.dungeon_route(out["id"]) is None
    assert client().get(f"/hero/world/dungeon/{out['id']}.gpx").status_code == 404
    # Ein Lauf vor dem Importtag deckt auf, bezwingt aber nichts (kein rückwirkender Sieg).
    add_route(db, FAR, datetime.now(timezone.utc) - timedelta(days=3), "before")
    dg = next(d for d in hero_world.world()["dungeons"] if d["key"] == out["id"])
    assert dg["discovered"] and not any(s["cleared"] for s in dg["segments"])
    assert client().get(f"/hero/world/dungeon/{out['id']}.gpx").status_code == 200
    assert client().get(f"/hero/world/dungeon/{out['id']}.fit").status_code == 200
    # Ein Lauf ab dem Importtag über die ganze Strecke: bezwungen und heroisch, wie bei OSM-Verliesen.
    add_route(db, FAR, datetime.now(timezone.utc) - timedelta(minutes=40), "after")
    dg = next(d for d in hero_world.world()["dungeons"] if d["key"] == out["id"])
    assert dg["cleared"] and dg["heroic"] and dg["loot"] == hero_world.dungeon_loot(dg["level"], True)


def test_dungeon_sections_follow_length(db):
    base_world(db)
    short = upload(gpx([(3000, 3000), (3000, 6000)], route=True), "dungeon").json()
    long = upload(gpx([(-4000, 3000), (-4000, 6000), (-9000, 6000)], route=True), "dungeon").json()
    assert short["segments"] == 2 and long["segments"] == 4


def test_import_as_track_reveals_and_garmin_wins(db):
    base_world(db)
    before = len(hero_world.world()["cells"])
    start = datetime.now(timezone.utc) - timedelta(days=5)
    r = upload(gpx(LOOP, start=start), "track")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["kind"] == "track" and out["superseded"] is False
    after = len(hero_world.world()["cells"])
    assert after > before + 50
    # Eine Garmin-Route im selben Zeitraum gewinnt: die Spur deckt nichts mehr auf.
    add_route(db, [(0, 0), (60, 0)], start + timedelta(minutes=5), "same-time")
    assert len(hero_world.world()["cells"]) == before
    own = client().get("/hero/world/own").json()
    assert own[0]["superseded"] is True


def test_track_is_not_a_run(db):
    base_world(db)
    upload(gpx(LOOP, start=datetime.now(timezone.utc) - timedelta(days=2)), "track")
    with Session(db) as s:  # weder Garmin-Route noch Trainingseinheit: zählt nirgends als Lauf
        assert len(s.exec(select(GarminRoute)).all()) == 3
        assert s.exec(select(ExerciseSession)).all() == []


@pytest.mark.parametrize("content,mode,needle", [
    (b"", "dungeon", "leer"),
    (b"<gpx><trk><trkseg><trkpt lat='1' lon='2'>", "dungeon", "GPX"),
    (b'<?xml version="1.0"?><!DOCTYPE gpx [<!ENTITY x "y">]><gpx>&x;</gpx>', "dungeon", "DTD"),
    (b"<kml></kml>", "dungeon", "GPX"),
    (None, "track", "Zeitstempel"),
    (None, "fly", "Modus"),
])
def test_rejects_broken_files(db, content, mode, needle):
    base_world(db)
    content = gpx(FAR) if content is None else content
    r = upload(content, mode)
    assert r.status_code == 422 and needle in r.json()["detail"]


def test_rejects_short_far_and_oversized(db):
    base_world(db)
    r = upload(gpx([(3000, 3000), (3000, 4500)]), "dungeon")
    assert r.status_code == 422 and "zu kurz" in r.json()["detail"]
    r = upload(gpx([(25000, 25000), (25000, 30000)]), "dungeon")
    assert r.status_code == 422 and "außerhalb" in r.json()["detail"]
    big = gpx(FAR) + b" " * (hero_import.MAX_GPX_BYTES + 10)
    r = upload(big, "dungeon")
    assert r.status_code == 422 and "zu groß" in r.json()["detail"]
    future = datetime.now(timezone.utc) + timedelta(days=3)
    r = upload(gpx(LOOP, start=future), "track")
    assert r.status_code == 422 and "Zukunft" in r.json()["detail"]


def test_requires_world_and_rejects_duplicates(db):
    assert upload(gpx(FAR), "dungeon").status_code == 422  # noch keine Heimat
    base_world(db)
    assert upload(gpx(FAR), "dungeon").status_code == 200
    assert upload(gpx(FAR), "dungeon").status_code == 409


def test_delete_own_dungeon_and_no_coordinates(db):
    base_world(db)
    out = upload(gpx(FAR, route=True), "dungeon").json()
    listing = client().get("/hero/world/own")
    text = listing.text + json.dumps(out)
    assert f"{HOME[0]:.2f}"[:4] not in text and "lat" not in text and "lon" not in text
    assert [x["id"] for x in listing.json()] == [out["id"]]
    assert any(d["key"] == out["id"] for d in hero_world.world()["dungeons"])
    assert client().delete(f"/hero/world/own/{out['id']}").status_code == 200
    assert not any(d["key"] == out["id"] for d in hero_world.world()["dungeons"])
    assert client().get("/hero/world/own").json() == []
    assert client().delete(f"/hero/world/own/{out['id']}").status_code == 404
