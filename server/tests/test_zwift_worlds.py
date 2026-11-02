"""Zwift world maps: rides as positions on the map image, never as coordinates; cached map images."""
import io
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import zwift_worlds
from app.api import metrics as metrics_api
from app.ingest import garmin

from test_garmin_indoor import CANARY_LAT, CANARY_LON, db, details_for, stored, synced, zwift  # noqa: F401


def _http():
    app = FastAPI()
    app.include_router(metrics_api.router)
    return TestClient(app)


def test_import_keeps_map_positions_and_names_the_world(synced):
    synced.api.rides.append(zwift(7, start="2025-01-04 17:00:00", title="Zwift - Neues Workout"))
    synced.api.details["7"] = details_for("2025-01-04T17:00:00", 600, power=lambda s: 180.0, hr=lambda s: 130.0)
    garmin.import_garmin()
    ride = stored(synced.engine, "7")
    track = json.loads(ride.track_json)
    assert track["world"] == "watopia" and ride.world == "Watopia"  # world from the map, not the title
    assert ride.route is None  # "Neues Workout" is a workout, not a Watopia route
    x, y = track["segments"][0][0]
    assert 0 <= x <= 1 and 0 <= y <= 1
    assert f"{CANARY_LAT:.3f}" not in ride.track_json and f"{CANARY_LON:.3f}" not in ride.track_json


def test_ride_outside_every_world_keeps_no_track(synced):
    details = details_for("2025-01-04T17:00:00", 600, power=lambda s: 180.0, hr=lambda s: 130.0)
    lat_i, lon_i = 7, 8
    for s, row in enumerate(details["activityDetailMetrics"]):
        row["metrics"][lat_i], row["metrics"][lon_i] = 10.0 + s * 1e-5, 10.0  # nowhere near a Zwift world
    synced.api.rides.append(zwift(7, start="2025-01-04 17:00:00", title="Indoor Cycling"))
    synced.api.details["7"] = details
    garmin.import_garmin()
    ride = stored(synced.engine, "7")
    assert ride.track_json == "{}" and ride.world is None


def test_track_thins_points_and_splits_jumps():
    lat1, lon1 = zwift_worlds.BY_SLUG["watopia"][2]
    lat2, lon2 = zwift_worlds.BY_SLUG["watopia"][3]
    at = lambda x, y: (lat1 + y * (lat2 - lat1), lon1 + x * (lon2 - lon1))  # noqa: E731
    points = [at(0.1 + i * 0.001, 0.5) for i in range(50)] + [at(0.1 + 49 * 0.001, 0.5)] * 5 \
        + [at(0.8 + i * 0.001, 0.2) for i in range(50)]
    track = zwift_worlds.track(points)
    assert track["world"] == "watopia" and len(track["segments"]) == 2
    assert sum(len(s) for s in track["segments"]) == 100  # duplicates dropped
    assert zwift_worlds.track(points[:3] + [(10.0, 10.0)] * 10) == {}  # mostly outside → nothing


def test_map_image_is_fetched_once_and_cached(tmp_path, monkeypatch):
    from PIL import Image

    png = io.BytesIO()
    Image.new("P", (80, 60)).save(png, "PNG")
    calls = []

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        return Reply(png.getvalue())

    monkeypatch.setattr(zwift_worlds, "MAP_DIR", tmp_path / "maps")
    monkeypatch.setattr(zwift_worlds.urllib.request, "urlopen", fake_urlopen)
    http = _http()
    first = http.get("/metrics/cycling/map/watopia.jpg")
    assert first.status_code == 200 and first.headers["content-type"] == "image/jpeg"
    assert http.get("/metrics/cycling/map/watopia.jpg").content == first.content
    assert calls == ["https://cdn.zwift.com/static/images/maps/MiniMap_Watopia_2.png"]
    assert (tmp_path / "maps" / "watopia.jpg").exists()
    assert http.get("/metrics/cycling/map/atlantis.jpg").status_code == 404


def test_track_endpoints(synced):
    garmin.import_garmin()
    http = _http()
    world = http.get("/metrics/cycling/tracks/watopia").json()
    assert world["name"] == "Watopia" and 1.3 < world["aspect"] < 1.35
    assert [r["activity_id"] for r in world["rides"]] == ["6", "5"] and world["rides"][0]["segments"]
    assert http.get("/metrics/cycling/tracks/atlantis").status_code == 404
    detail = http.get("/metrics/cycling/ride/5").json()
    assert detail["track"]["world"] == "watopia" and detail["track"]["segments"]
    worlds = http.get("/metrics/cycling/worlds").json()["worlds"]
    assert worlds[0]["slug"] == "watopia" and worlds[0]["tracks"] == 2
    for body in (world, detail):
        assert not any(k in json.dumps(body) for k in ('"lat', '"lon', "Latitude", "Longitude"))
