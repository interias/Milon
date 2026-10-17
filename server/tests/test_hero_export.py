import io
import json
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from garmin_fit_sdk import Decoder, Stream
from sqlmodel import Session, SQLModel, create_engine

from app import hero, hero_export, hero_world
from app.api import hero as hero_api
from app.garmin_routes import GarminRoute

GPX = "{http://www.topografix.com/GPX/1/1}"


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'export.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(hero_world, "engine", engine)
    monkeypatch.setattr(hero, "engine", engine)
    monkeypatch.setattr(hero_world.settings, "hero_live_token", "")
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


def add_route(engine, pts, rid, days_ago):
    start = datetime.now(timezone.utc) - timedelta(days=days_ago)
    seg = [{"lat": la, "lon": lo, "altitude_m": None, "time": (start + timedelta(seconds=i * 10)).isoformat()}
           for i, (la, lo) in enumerate(pts)]
    with Session(engine) as s:
        s.add(GarminRoute(activity_id=rid, title="Lauf", started_at=start.replace(tzinfo=None), point_count=len(seg),
                          segments_json=json.dumps([seg]), synced_at=datetime.now()))
        s.commit()


def auesee():
    return next(d for d in hero_world.dungeon_defs() if d["key"] == "auesee")


def discover_auesee(engine):
    """Zwei Läufe: einer legt die Heimat fest (10 Runden an einem Ort), einer läuft den ganzen Auesee."""
    dg = auesee()
    pts = [tuple(p) for seg in dg["segments"] for p in seg["points"]]
    home = (pts[0][0] + 0.01, pts[0][1])
    for i in range(3):
        add_route(engine, [(home[0], home[1] + k * 0.0005) for k in range(40)], f"home{i}", 20 + i)
    add_route(engine, [home] + pts, "see", 5)


def test_short_name_limits_and_folds():
    assert hero_export.short_name("Spiegel des Auesees") == "Spiegel Auesees"
    assert hero_export.short_name("Wächter") == "Waechter"
    assert hero_export.short_name("Kurz") == "Kurz"
    for dg in hero_world.dungeon_defs():
        n = hero_export.short_name(dg["name"])
        assert 0 < len(n) <= 15 and n.isascii(), dg["name"]
        for seg in dg["segments"]:
            assert 0 < len(hero_export.short_name(seg["boss"])) <= 15


def test_gpx_for_discovered_dungeon(db):
    discover_auesee(db)
    r = client().get("/hero/world/dungeon/auesee.gpx")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/gpx+xml")
    assert r.headers["content-disposition"] == 'attachment; filename="Spiegel_Auesees.gpx"'
    root = ET.fromstring(r.content)
    dg = auesee()
    trk = root.find(f"{GPX}trk")
    name = trk.find(f"{GPX}name").text
    assert name == "Spiegel Auesees" and len(name) <= 15
    pts, marks = hero_export.flatten(hero_world.dungeon_route("auesee"))
    trkpts = trk.findall(f"{GPX}trkseg/{GPX}trkpt")
    assert len(trkpts) == len(pts) > 100
    assert math.isclose(float(trkpts[0].get("lat")), dg["segments"][0]["points"][0][0], abs_tol=1e-5)
    wpts = root.findall(f"{GPX}wpt")
    assert [w.find(f"{GPX}name").text for w in wpts] == [s["boss"] for s in dg["segments"]]
    last = dg["segments"][-1]["points"][-1]
    assert math.isclose(float(wpts[-1].get("lat")), last[0], abs_tol=1e-5)


def test_fit_course_roundtrip(db):
    discover_auesee(db)
    r = client().get("/hero/world/dungeon/auesee.fit")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.ant.fit"
    assert r.headers["content-disposition"] == 'attachment; filename="Spiegel_Auesees.fit"'
    assert Decoder(Stream.from_bytes_io(io.BytesIO(r.content))).is_fit()
    assert Decoder(Stream.from_bytes_io(io.BytesIO(r.content))).check_integrity()
    msgs, errors = Decoder(Stream.from_bytes_io(io.BytesIO(r.content))).read()
    assert errors == []
    assert msgs["file_id_mesgs"][0]["type"] == "course"
    course = msgs["course_mesgs"][0]
    assert course["name"] == "Spiegel Auesees" and course["sport"] == "running"
    pts, marks = hero_export.flatten(hero_world.dungeon_route("auesee"))
    recs = msgs["record_mesgs"]
    assert len(recs) == len(pts)
    deg = 180 / 2 ** 31
    assert all(math.isclose(r_["position_lat"] * deg, p[0], abs_tol=1e-5) and math.isclose(r_["position_long"] * deg, p[1], abs_tol=1e-5)
               for r_, p in zip(recs, pts))
    assert recs[0]["distance"] == 0 and recs[-1]["distance"] > 5000
    assert all(a["timestamp"] < b["timestamp"] for a, b in zip(recs, recs[1:]) if a["distance"] < b["distance"])
    cps = msgs["course_point_mesgs"]
    assert [c["name"] for c in cps] == [hero_export.short_name(s["boss"]) for s in auesee()["segments"]]
    assert len(cps) == len(marks)
    assert cps[-1]["distance"] == pytest.approx(recs[-1]["distance"], abs=1)
    lap = msgs["lap_mesgs"][0]
    assert lap["total_distance"] == pytest.approx(recs[-1]["distance"], abs=1)


def test_undiscovered_and_unknown_are_404(db):
    discover_auesee(db)
    w = hero_world.world()
    hidden = next(d["key"] for d in w["dungeons"] if not d["discovered"] and not d.get("provisional"))
    c = client()
    for ext in ("gpx", "fit"):
        assert c.get(f"/hero/world/dungeon/{hidden}.{ext}").status_code == 404
        assert c.get(f"/hero/world/dungeon/gibtsnicht.{ext}").status_code == 404
    assert c.get("/hero/world/dungeon/auesee.gpx").status_code == 200


def test_no_world_is_404(db):
    assert client().get("/hero/world/dungeon/auesee.gpx").status_code == 404


def test_export_contains_only_public_route(db):
    discover_auesee(db)
    route = hero_world.dungeon_route("auesee")
    assert set(route) == {"name", "segments"}
    raw = hero_export.gpx_bytes(route).decode()
    home = hero_world._memo["home"]
    assert f"{home[0]:.5f}" not in raw  # nur Streckenpunkte, kein Heimatpunkt
    assert "Lauf" not in raw and "home" not in raw.lower()
