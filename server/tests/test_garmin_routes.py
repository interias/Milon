from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app import garmin_routes
from app.api import garmin_routes as routes_api
from app.models import BodyMeasurement, ExerciseSession, RunMinute, SyncState


PATH = "/metrics/running/routes"
START = datetime(2026, 10, 3, 10)
SUMMARY = {"activity_id": "12345", "title": "Synthetic run", "started_at": START,
           "started_at_utc": "2026-10-03T08:00:00Z", "distance_km": 5,
           "duration_seconds": 1800, "elapsed_duration_seconds": 2100, "elevation_gain_m": 12}
POINTS = [[{"lat": 51.0, "lon": 7.0, "altitude_m": 100.0, "time": "2026-10-03T08:00:00+00:00"},
           {"lat": 51.001, "lon": 7.001, "altitude_m": None, "time": None}]]


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'routes.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[garmin_routes.GarminRoute.__table__,
                                               ExerciseSession.__table__, BodyMeasurement.__table__,
                                               RunMinute.__table__, SyncState.__table__])
    monkeypatch.setattr(garmin_routes, "engine", engine)
    monkeypatch.setattr(routes_api.garmin, "configured", lambda: False)
    monkeypatch.setattr(garmin_routes.settings, "timezone", "Europe/Berlin")
    app = FastAPI()
    app.include_router(routes_api.router)
    with TestClient(app) as test_client:
        yield test_client
    garmin_routes.engine.dispose()


def add_run(external_id="hc-original", start=START, distance=5, duration=2100, exercise_type=33):
    with Session(garmin_routes.engine) as session:
        session.add(ExerciseSession(external_id=external_id, started_at=start,
                                    ended_at=start + timedelta(seconds=duration) if duration is not None else None,
                                    distance_km=distance, exercise_type=exercise_type, avg_hr=145))
        session.commit()


def test_gpx_keeps_tracks_segments_and_invalid_coordinate_gaps():
    content = b'''<?xml version="1.0"?>
    <gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
      <trkpt lat="51" lon="7"><ele>100.5</ele><time>2026-10-03T10:00:00+02:00</time></trkpt>
      <trkpt lat="51.1" lon="7.1"><ele>NaN</ele><time>bad</time></trkpt>
      <trkpt lat="91" lon="7.2"/>
      <trkpt lat="51.2" lon="7.2"/>
      <trkpt lat="NaN" lon="7.3"/>
      <trkpt lat="51.3" lon="7.3"><time>2026-10-03T10:00:30</time></trkpt>
    </trkseg><trkseg><trkpt lat="-90" lon="180"/></trkseg></trk>
    <trk><trkseg><trkpt lat="0" lon="0"/></trkseg></trk></gpx>'''
    segments = garmin_routes.parse_gpx(content)
    assert [len(segment) for segment in segments] == [2, 1, 1, 1, 1]
    assert segments[0][0] == {"lat": 51, "lon": 7, "altitude_m": 100.5, "time": "2026-10-03T08:00:00+00:00"}
    assert segments[0][1]["altitude_m"] is None and segments[0][1]["time"] is None
    assert segments[2][0]["time"] is None
    assert all(set(point) == {"lat", "lon", "altitude_m", "time"} for segment in segments for point in segment)


def test_gpx_routes_and_utf16_are_supported_without_joining_them():
    document = '<gpx><rte><rtept lat="1" lon="2"/></rte><rte><rtept lat="3" lon="4"/></rte></gpx>'
    assert [len(segment) for segment in garmin_routes.parse_gpx(document.encode("utf-16"))] == [1, 1]


@pytest.mark.parametrize("content", [b"", b"<gpx>", b"<other/>", b"<gpx/>",
                                      b'<gpx><wpt lat="1" lon="2"/></gpx>',
                                      b'<gpx><trk><trkseg><trkpt lat="inf" lon="1"/></trkseg></trk></gpx>',
                                      b'<gpx><trk><trkseg><trkpt lat="1" lon="-181"/></trkseg></trk></gpx>'])
def test_invalid_gpx_is_rejected(content):
    with pytest.raises(ValueError):
        garmin_routes.parse_gpx(content)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32"])
def test_dtd_and_entities_are_rejected_before_expansion(encoding):
    content = '''<!DOCTYPE gpx [<!ENTITY route "private">]>
    <gpx><trk><name>&route;</name><trkseg><trkpt lat="1" lon="2"/></trkseg></trk></gpx>'''
    with pytest.raises(ValueError, match="DTD"):
        garmin_routes.parse_gpx(content.encode(encoding))


def test_parser_limits_apply_to_invalid_points_too(monkeypatch):
    monkeypatch.setattr(garmin_routes, "MAX_GPX_BYTES", 40)
    with pytest.raises(ValueError, match="10 MiB"):
        garmin_routes.parse_gpx(b" " * 41)
    monkeypatch.setattr(garmin_routes, "MAX_GPX_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr(garmin_routes, "MAX_ROUTE_POINTS", 2)
    with pytest.raises(ValueError, match="viele"):
        garmin_routes.parse_gpx(b'<gpx><trk><trkseg><trkpt/><trkpt/><trkpt/></trkseg></trk></gpx>')


def test_upsert_reopen_pagination_and_no_health_metric_mutation(client, monkeypatch):
    add_run()
    with Session(garmin_routes.engine) as session:
        session.add(BodyMeasurement(measured_at=START, weight_kg=75, source="synthetic"))
        session.add(RunMinute(external_id="hc-original", minute=1, speed_m_min=170,
                              hr_bpm=145, coverage=1, steady=True))
        session.commit()
        before = {model.__tablename__: [row.model_dump() for row in session.exec(select(model)).all()]
                  for model in (ExerciseSession, BodyMeasurement, RunMinute)}
    assert client.get(PATH).json() == {"items": [], "total": 0, "configured": False, "sync": None}
    saved = garmin_routes.save_route(SUMMARY, POINTS)
    assert saved["matched_external_id"] == "hc-original"
    assert saved["duration_seconds"] == 1800 and saved["point_count"] == 2
    updated = garmin_routes.save_route({**SUMMARY, "title": "Changed"}, [POINTS[0][:1]])
    assert updated["title"] == "Changed" and updated["point_count"] == 1
    assert client.get(PATH).json()["total"] == 1
    assert client.get(f"{PATH}/12345").json()["segments"] == [POINTS[0][:1]]
    with Session(garmin_routes.engine) as session:
        row = session.get(garmin_routes.GarminRoute, "12345")
        assert row.started_at_utc == "2026-10-03T08:00:00+00:00" and row.elapsed_duration_seconds == 2100
        assert row.synced_at is not None
        after = {model.__tablename__: [row.model_dump() for row in session.exec(select(model)).all()]
                 for model in (ExerciseSession, BodyMeasurement, RunMinute)}
    assert before == after
    url = str(garmin_routes.engine.url)
    garmin_routes.engine.dispose()
    monkeypatch.setattr(garmin_routes, "engine", create_engine(url, connect_args={"check_same_thread": False}))
    assert client.get(f"{PATH}/12345").json()["title"] == "Changed"
    garmin_routes.save_route({**SUMMARY, "activity_id": "67890", "started_at": START + timedelta(days=1)}, POINTS)
    page = client.get(PATH, params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 2 and page["items"][0]["activity_id"] == "12345"
    assert "segments" not in page["items"][0]
    assert client.get(PATH, params={"offset": 100}).json() == {"items": [], "total": 2, "configured": False, "sync": None}
    assert client.get(f"{PATH}/missing").status_code == 404


def test_matching_uses_elapsed_duration_and_stable_id_after_reconciliation(client):
    add_run()
    saved = garmin_routes.save_route({**SUMMARY, "duration_seconds": 1200}, POINTS)
    assert saved["matched_external_id"] == "hc-original"
    with Session(garmin_routes.engine) as session:
        original = session.exec(select(ExerciseSession)).one()
        session.delete(original)
        session.commit()
        session.add(ExerciseSession(id=99, external_id="hc-original", started_at=START,
                                    ended_at=START + timedelta(seconds=2100), distance_km=5, exercise_type=33))
        session.commit()
    assert garmin_routes.route_detail("12345")["matched_external_id"] == "hc-original"
    add_run(external_id="second-candidate", start=START + timedelta(seconds=60))
    assert garmin_routes.route_detail("12345")["matched_external_id"] is None


@pytest.mark.parametrize("patch", [{"start": START + timedelta(seconds=121)}, {"distance": 6},
                                    {"duration": 2400}, {"distance": None}, {"duration": None},
                                    {"exercise_type": 53}, {"external_id": None}])
def test_matching_requires_all_three_checks_and_a_stable_id(client, patch):
    add_run(**patch)
    assert garmin_routes.save_route(SUMMARY, POINTS)["matched_external_id"] is None


def test_matching_tolerances_are_inclusive_and_duration_falls_back(client):
    add_run(start=START + timedelta(seconds=120), distance=5.5, duration=1980)
    saved = garmin_routes.save_route({**SUMMARY, "elapsed_duration_seconds": None}, POINTS)
    assert saved["matched_external_id"] == "hc-original"


@pytest.mark.parametrize("patch", [{"distance_km": float("nan")}, {"duration_seconds": float("inf")},
                                    {"elapsed_duration_seconds": -1}, {"elevation_gain_m": True},
                                    {"activity_id": ""}, {"started_at": "bad"},
                                    {"started_at_utc": "2026-10-03T08:00:00"}])
def test_invalid_metadata_cannot_replace_a_saved_route(client, patch):
    garmin_routes.save_route(SUMMARY, POINTS)
    before = garmin_routes.route_detail("12345")
    with pytest.raises(ValueError):
        garmin_routes.save_route({**SUMMARY, **patch}, POINTS)
    assert garmin_routes.route_detail("12345") == before


@pytest.mark.parametrize("segments", [[], [[]], [[{"lat": True, "lon": 0}]], [[{"lat": 91, "lon": 0}]],
                                       [[{"lat": 0, "lon": float("nan")}]],
                                       [[{"lat": 0, "lon": 0, "time": "bad"}]]])
def test_invalid_geometry_cannot_replace_a_saved_route(client, segments):
    garmin_routes.save_route(SUMMARY, POINTS)
    with pytest.raises(ValueError):
        garmin_routes.save_route(SUMMARY, segments)
    assert garmin_routes.route_detail("12345")["segments"] == POINTS


def test_aware_start_is_converted_to_configured_local_time(client):
    saved = garmin_routes.save_route({**SUMMARY, "started_at": "2026-10-03T08:00:00Z"}, POINTS)
    assert saved["started_at"] == "2026-10-03T10:00:00"


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_api_pagination_bounds(client, params):
    assert client.get(PATH, params=params).status_code == 422
