"""Body scale over Web Bluetooth: POST, dedupe, plausibility, merge into the weight series."""
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app import scale
from app.ingest import health_connect as hc
from app.models import BodyMeasurement

NOW = datetime(2026, 11, 23, 8, 0, 0)


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'scale.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(scale, "engine", engine)
    yield engine
    engine.dispose()


def reading(**kw):
    base = {"weightKg": 73.15, "r1": 512, "r2": 498, "source": "live", "protocolType": 255,
            "timestamp": "2026-11-23T06:30:12.345Z", "rawHex": "10 0b ff 1c 93 01 02 00 01 f2 c1"}
    base.update(kw)
    return base


def weights(engine):
    with Session(engine) as s:
        return sorted((r.measured_at, r.source, r.weight_kg) for r in s.exec(select(BodyMeasurement)).all())


def test_post_stores_raw_reading_and_feeds_weight_series(db):
    from app.main import app
    http = TestClient(app)
    r = http.post("/scale/measurements", json=reading())
    assert r.status_code == 201, r.text
    m = r.json()["measurement"]
    # UTC from the phone → local wall time (CET = UTC+1), second precision
    assert m["measured_at"] == "2026-11-23T07:30:12"
    assert (m["weight_kg"], m["r1"], m["r2"], m["source"], m["protocol_type"]) == (73.15, 512, 498, "live", 255)
    assert m["raw_hex"].startswith("10 0b ff")
    assert weights(db) == [(datetime(2026, 11, 23, 7, 30, 12), "scale_ble", 73.15)]
    listed = http.get("/scale/measurements?days=3660").json()["measurements"]
    assert [x["id"] for x in listed] == [m["id"]]


def test_dedupe_same_time_and_double_tap(db):
    from app.main import app
    http = TestClient(app)
    first = http.post("/scale/measurements", json=reading()).json()["measurement"]
    same_time = http.post("/scale/measurements", json=reading(weightKg=80))
    assert same_time.status_code == 200 and same_time.json()["duplicate"] is True
    assert same_time.json()["measurement"]["id"] == first["id"]
    # Same weight 90 s later (stored-record fallback or second tap) → same weighing
    tap = http.post("/scale/measurements", json=reading(timestamp="2026-11-23T06:31:42Z", source="stored"))
    assert tap.status_code == 200 and tap.json()["duplicate"] is True
    # Different weight within 2 min = a real second weighing (e.g. with clothes)
    other = http.post("/scale/measurements", json=reading(timestamp="2026-11-23T06:31:42Z", weightKg=74.0))
    assert other.status_code == 201
    # Same weight after 2 min → new reading
    later = http.post("/scale/measurements", json=reading(timestamp="2026-11-23T06:33:30Z"))
    assert later.status_code == 201
    assert len(weights(db)) == 3


@pytest.mark.parametrize("kg", [19.99, 250.01, 0, 7.0])
def test_plausibility(db, kg):
    from app.main import app
    r = TestClient(app).post("/scale/measurements", json=reading(weightKg=kg))
    assert r.status_code == 422
    assert weights(db) == []


def test_bounds_are_inclusive_and_bad_input_rejected(db):
    from app.main import app
    http = TestClient(app)
    assert http.post("/scale/measurements", json=reading(weightKg=20.0)).status_code == 201
    assert http.post("/scale/measurements", json=reading(weightKg=250.0, timestamp="2026-11-23T09:00:00Z")).status_code == 201
    assert http.post("/scale/measurements", json=reading(source="guess")).status_code == 422
    assert http.post("/scale/measurements", json=reading(rawHex="<script>")).status_code == 422
    assert http.post("/scale/measurements", json=reading(r1=-1)).status_code == 422


def test_far_off_weight_is_rejected_once_there_is_history(db):
    """Real case 2026-11-25: a 23.75 kg record (no impedance) between 74 kg mornings pulled the 7-day mean to 69."""
    def put(day, kg):
        return scale.save(measured_at=datetime(2026, 11, day, 4, 30), weight_kg=kg, r1=4300, r2=200,
                          source="stored", protocol_type=255, raw_hex=None, now=NOW)
    put(20, 74.0)
    put(21, 73.8)
    put(22, 74.2)
    with pytest.raises(ValueError, match="jemand anderes"):
        put(23, 23.75)
    assert put(23, 72.5)[1] is True  # normal day-to-day change still passes
    assert [w for _, _, w in weights(db)] == [74.0, 73.8, 74.2, 72.5]


def test_future_timestamp_rejected(db):
    with pytest.raises(ValueError):
        scale.save(measured_at=datetime(2026, 11, 23, 9, 0), weight_kg=73, r1=None, r2=None,
                   source="live", protocol_type=None, raw_hex=None, now=NOW)


def test_ble_wins_over_other_source_and_hc_import(db, tmp_path):
    # Arboleaf → Health Connect already delivered the same weighing two minutes earlier
    with Session(db) as s:
        s.add(BodyMeasurement(measured_at=datetime(2026, 11, 23, 7, 28), weight_kg=73.2, source="health_connect"))
        s.add(BodyMeasurement(measured_at=datetime(2026, 11, 22, 7, 0), weight_kg=73.6, source="health_connect"))
        s.commit()
    scale.save(measured_at=datetime(2026, 11, 23, 7, 30), weight_kg=73.15, r1=1, r2=2, source="live",
               protocol_type=255, raw_hex=None, now=NOW)
    assert weights(db) == [(datetime(2026, 11, 22, 7, 0), "health_connect", 73.6),
                           (datetime(2026, 11, 23, 7, 30), "scale_ble", 73.15)]

    # A later HC import does not bring the shadowed row back (HC timestamps are UTC + offset)
    source = tmp_path / "export.db"
    with sqlite3.connect(source) as con:
        con.executescript("""
            CREATE TABLE application_info_table(row_id, package_name);
            INSERT INTO application_info_table VALUES (1, 'scale');
            CREATE TABLE weight_record_table(time, zone_offset, weight, app_info_id);
            CREATE TABLE body_fat_record_table(time, zone_offset, percentage, app_info_id);
            CREATE TABLE distance_record_table(start_time, end_time, distance, app_info_id);
            CREATE TABLE exercise_session_record_table(uuid, start_time, start_zone_offset,
                end_time, exercise_type, app_info_id);
            CREATE TABLE vo2_max_record_table(time, zone_offset, vo2_milliliters_per_minute_kilogram);
            CREATE TABLE steps_record_table(local_date, count, app_info_id);
        """)
        same = 1795415280000   # 2026-11-23 06:28 UTC = 07:28 local
        other = 1795500000000  # 2026-11-24 06:00 UTC = 07:00 local
        con.executemany("INSERT INTO weight_record_table VALUES (?, 3600, ?, 1)", [(same, 73200), (other, 72900)])
    con.close()
    config = SimpleNamespace(body_source_package="scale", steps_source_package="",
                             body_weight_min_kg=20, body_weight_max_kg=250)
    with patch.object(hc, "settings", config), patch.object(hc, "engine", db):
        hc.import_health_connect(source)
    got = weights(db)
    assert (datetime(2026, 11, 23, 7, 28), "health_connect", 73.2) not in got
    assert (datetime(2026, 11, 23, 7, 30), "scale_ble", 73.15) in got
    assert any(src == "health_connect" and day.date() == datetime(2026, 11, 24).date() for day, src, _ in got)


def test_delete_removes_reading_and_weight_row(db):
    from app.main import app
    http = TestClient(app)
    mid = http.post("/scale/measurements", json=reading()).json()["measurement"]["id"]
    assert http.delete(f"/scale/measurements/{mid}").status_code == 200
    assert weights(db) == []
    assert http.delete(f"/scale/measurements/{mid}").status_code == 404
