"""Walking pad: FTMS parsing + session detection (host recorder), ingest, FIT export, Garmin, steps, hero."""
import io
import struct
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from garmin_fit_sdk import Decoder, Stream
from sqlmodel import Session, SQLModel, create_engine

from app import walkpad
from app.config import settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "walkpad"))
import ftms  # noqa: E402

T0 = datetime(2026, 10, 20, 7, 0, tzinfo=timezone.utc).timestamp()  # 09:00 Berlin


def packet(speed_kmh: float, dist_m: int, elapsed_s: int, kcal: int = 0, hr: int = 0) -> bytes:
    """Treadmill Data exactly like the sWalk Lite: flags 0x0584, 15 bytes."""
    return (struct.pack("<HH", 0x0584, round(speed_kmh * 100)) + dist_m.to_bytes(3, "little")
            + struct.pack("<HHB", kcal, 0, 0) + struct.pack("<B", hr) + struct.pack("<H", elapsed_s))


def walk(tracker, start: float, seconds: int, speed: float = 3.2, dist0: float = 0.0, el0: int = 0) -> float:
    """1-Hz packets of a steady walk; returns the pad distance at the end."""
    dist = dist0
    for i in range(seconds):
        dist += speed / 3.6
        tracker.packet(ftms.parse_treadmill_data(packet(speed, int(dist), el0 + i + 1, int(dist / 20))), start + i + 1)
    return dist


@pytest.fixture
def db(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pad.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(walkpad, "engine", engine)
    monkeypatch.setattr(settings, "walkpad_stride_m", 0.65)
    monkeypatch.setattr(settings, "walkpad_incline_pct", 0.0)
    monkeypatch.setattr(settings, "walkpad_garmin_upload", True)
    monkeypatch.setattr(walkpad, "_weights", lambda: pd.Series(dtype=float))  # no weight → pad kcal only
    yield engine
    engine.dispose()


def recorded(minutes: int = 30, speed: float = 3.2) -> dict:
    t = ftms.SessionTracker(device="sWalk Lite-682")
    walk(t, T0, minutes * 60, speed)
    t.tick(T0 + minutes * 60 + ftms.DISCONNECT_END_S + 1)
    return t.finished[0]


# ---------------- recorder side ----------------
def test_parse_swalk_packet():
    raw = bytes.fromhex("8405" + "4001" + "e80300" + "2d00" "0000" "00" + "00" + "5802")
    assert len(raw) == 15
    d = ftms.parse_treadmill_data(raw)
    assert d["speed_kmh"] == pytest.approx(3.2)
    assert d["distance_m"] == 1000 and d["kcal"] == 45 and d["elapsed_s"] == 600
    assert d["hr_bpm"] is None  # 0 = no contact


def test_tracker_session_ends_on_counter_reset():
    t = ftms.SessionTracker()
    dist = walk(t, T0, 600)
    t.packet(ftms.parse_treadmill_data(packet(0, 0, 0)), T0 + 605)  # pad stopped and reset
    assert len(t.finished) == 1
    s = t.finished[0]
    assert s["id"] == f"wp-{int(T0)}"
    assert s["distance_m"] == int(dist) and s["elapsed_s"] == 600
    assert s["ended_at"] - s["started_at"] == pytest.approx(600, abs=1)
    assert s["samples"][-1][2] == int(dist)


def test_tracker_mid_walk_connect_backdates_start():
    t = ftms.SessionTracker()
    walk(t, T0 + 300, 300, dist0=267, el0=300)  # recorder joins after 5 min
    t.flush()
    assert t.finished[0]["started_at"] == pytest.approx(T0, abs=1)
    assert t.finished[0]["distance_m"] > 500


def test_tracker_idle_end_and_pause_without_reset():
    t = ftms.SessionTracker()
    dist = walk(t, T0, 600)
    for i in range(ftms.IDLE_END_S + 2):  # belt stopped, counters kept
        t.packet(ftms.parse_treadmill_data(packet(0, int(dist), 600)), T0 + 601 + i)
    assert len(t.finished) == 1
    resume = T0 + 600 + ftms.IDLE_END_S + 100
    walk(t, resume, 600, dist0=dist, el0=600)
    t.flush()
    second = t.finished[1]
    assert second["id"] != t.finished[0]["id"]
    assert second["distance_m"] == pytest.approx(533, abs=3)  # only the part after the pause
    assert second["elapsed_s"] == 600
    assert second["started_at"] == pytest.approx(resume, abs=1)


def test_tracker_drops_tiny_sessions_and_disconnect_ends():
    t = ftms.SessionTracker()
    walk(t, T0, 60)
    t.tick(T0 + 60 + ftms.DISCONNECT_END_S)
    assert t.finished == [] and t.active is None
    walk(t, T0 + 1000, 300)
    t.tick(T0 + 1300 + ftms.DISCONNECT_END_S)
    assert len(t.finished) == 1


# ---------------- server side ----------------
def test_ingest_idempotent_and_validated(db):
    s = recorded()
    row, created = walkpad.ingest(s)
    assert created and row["distance_km"] == pytest.approx(1.6, abs=0.01)
    assert row["minutes"] == pytest.approx(30, abs=0.2)
    assert row["steps"] == round(s["distance_m"] / 0.65) and row["steps_provisional"]
    assert row["started_at"].startswith("2026-10-20T09:00")
    again, created = walkpad.ingest(s)
    assert not created and again["id"] == row["id"]
    with pytest.raises(ValueError):
        walkpad.ingest({**s, "id": "wp-short", "ended_at": s["started_at"] + 60})
    with pytest.raises(ValueError):
        walkpad.ingest({**s, "id": "wp-fast", "distance_m": 9000, "samples": []})
    with pytest.raises(ValueError):
        walkpad.ingest({**s, "id": "wp-future", "started_at": 4_000_000_000, "ended_at": 4_000_003_600})


def test_fit_activity_decodes(db):
    walkpad.ingest({**recorded(), "kcal": 80})
    with Session(db) as ses:
        row = ses.get(walkpad.WalkpadSession, f"wp-{int(T0)}")
    raw = walkpad.fit_activity_bytes(row)
    dec = Decoder(Stream.from_bytes_io(io.BytesIO(raw)))
    assert dec.is_fit() and Decoder(Stream.from_bytes_io(io.BytesIO(raw))).check_integrity()
    msgs, errors = Decoder(Stream.from_bytes_io(io.BytesIO(raw))).read()
    assert not errors
    sess = msgs["session_mesgs"][0]
    assert sess["sport"] == "walking" and sess["sub_sport"] == "indoor_walking"
    assert sess["total_distance"] == pytest.approx(row.distance_m, abs=0.1)
    assert sess["total_calories"] == 80
    assert msgs["file_id_mesgs"][0]["type"] == "activity"
    assert len(msgs["record_mesgs"]) > 300 and len(msgs["activity_mesgs"]) == 1


def test_watch_steps_overlap_weighting():
    buckets = [{"startGMT": "2026-10-20T07:00:00.0", "endGMT": "2026-10-20T07:15:00.0", "steps": 300},
               {"startGMT": "2026-10-20T07:15:00.0", "endGMT": "2026-10-20T07:30:00.0", "steps": 900}]
    assert walkpad.watch_steps_in(buckets, T0 + 450, T0 + 1350) == 150 + 450


class FakeGarmin:
    def __init__(self, fail: str | None = None):
        self.fail, self.uploads, self.step_days = fail, [], []

    def upload_activity(self, path):
        self.uploads.append(Path(path).read_bytes()[8:12])
        if self.fail:
            raise RuntimeError(self.fail)
        return {"detailedImportResult": {"successes": [{"internalId": 4711}], "failures": []}}

    def get_steps_data(self, day):
        self.step_days.append(day)
        return [{"startGMT": "2026-10-20T07:00:00.0", "endGMT": "2026-10-20T07:30:00.0", "steps": 400}]


def test_sync_garmin_uploads_and_fills_watch_steps(db):
    walkpad.ingest(recorded())
    api = FakeGarmin()
    out = walkpad.sync_garmin(api, now=datetime(2026, 10, 20, 12, 0))
    assert out == {"uploaded": 1, "upload_errors": 0, "watch_days": 1}
    assert api.uploads == [b".FIT"] and api.step_days == ["2026-10-20"]
    row = walkpad.detail(f"wp-{int(T0)}")
    assert row["garmin_status"] == "uploaded" and row["garmin_activity_id"] == "4711"
    assert row["watch_steps"] == 400 and row["extra_steps"] == row["steps"] - 400
    assert walkpad.sync_garmin(api, now=datetime(2026, 10, 20, 12, 15))["uploaded"] == 0  # no re-upload


def test_sync_garmin_duplicate_and_retry(db):
    walkpad.ingest(recorded())
    walkpad.sync_garmin(FakeGarmin("409 Conflict: Duplicate Activity"), now=datetime(2026, 10, 20, 12))
    assert walkpad.detail(f"wp-{int(T0)}")["garmin_status"] == "duplicate"
    walkpad.ingest({**recorded(), "id": "wp-other"})
    for _ in range(walkpad.MAX_UPLOAD_ATTEMPTS + 2):
        walkpad.sync_garmin(FakeGarmin("500"), now=datetime(2026, 10, 20, 12))
    with Session(db) as ses:
        assert ses.get(walkpad.WalkpadSession, "wp-other").garmin_attempts == walkpad.MAX_UPLOAD_ATTEMPTS


def test_watch_steps_wait_for_watch_sync(db):
    walkpad.ingest(recorded())
    api = FakeGarmin()
    walkpad.sync_garmin(api, now=datetime(2026, 10, 20, 9, 35))  # walk ended 09:30, watch not synced yet
    assert api.step_days == [] and walkpad.detail(f"wp-{int(T0)}")["steps_provisional"]


def test_extra_steps_added_to_steps_daily(db):
    walkpad.ingest(recorded())
    with db.connect() as con:
        df = pd.DataFrame({"day": pd.to_datetime(["2026-10-19", "2026-10-20"]), "steps": [8000, 3000]})
        out = walkpad.with_extra_steps(df, con)
        assert list(out["steps"]) == [8000, 3000 + round(1600 / 0.65)]
        only_pad = walkpad.with_extra_steps(df[df["day"] < "2026-10-20"], con)
        assert only_pad.iloc[-1]["day"] == pd.Timestamp("2026-10-20")


def test_api_token_and_overview(db, monkeypatch):
    from app.ingest import garmin
    from app.main import app
    monkeypatch.setattr(garmin, "upload_walkpad", lambda: None)
    http = TestClient(app)
    s = recorded()
    assert http.post("/walkpad/sessions", json=s).status_code == 403
    monkeypatch.setattr(settings, "walkpad_token", "secret")
    assert http.post("/walkpad/sessions", json=s, headers={"X-Walkpad-Token": "nope"}).status_code == 401
    r = http.post("/walkpad/sessions", json=s, headers={"X-Walkpad-Token": "secret"})
    assert r.status_code == 200 and r.json()["created"]
    assert http.post("/walkpad/sessions", json=s, headers={"X-Walkpad-Token": "secret"}).json()["created"] is False
    bad = http.post("/walkpad/sessions", json={**s, "id": "wp-x", "distance_m": 10}, headers={"X-Walkpad-Token": "secret"})
    assert bad.status_code == 422
    sid = s["id"]
    assert http.put(f"/walkpad/sessions/{sid}/incline", json={"incline_pct": 6}).json()["elevation_m"] == 96
    ov = http.get("/walkpad").json()
    assert ov["total_sessions"] == 1 and ov["recorder_enabled"]
    assert http.get(f"/walkpad/sessions/{sid}").json()["samples"]
    assert http.get("/walkpad/sessions/unknown").status_code == 404


def test_hero_counts_pad_minutes_as_everyday_and_drops_mirror(db, monkeypatch, tmp_path):
    from app import hero
    from app.metrics import health
    from app.models import ExerciseSession
    monkeypatch.setattr(hero, "engine", db)
    monkeypatch.setattr(health, "engine", db)
    walkpad.ingest(recorded())
    with Session(db) as ses:  # Garmin Connect → HC mirror of the uploaded walk
        ses.add(ExerciseSession(external_id="hc-mirror", exercise_type=53, source="health_connect",
                                started_at=datetime(2026, 10, 20, 9, 0), ended_at=datetime(2026, 10, 20, 9, 30)))
        ses.add(ExerciseSession(external_id="hc-walk", exercise_type=53, source="health_connect",
                                started_at=datetime(2026, 10, 20, 18, 0), ended_at=datetime(2026, 10, 20, 18, 20)))
        ses.commit()
    minutes = hero._other_minutes()
    assert minutes[date(2026, 10, 20)] == pytest.approx(30 + 20, abs=0.5)


def test_acsm_energy_incline_share():
    e = walkpad.energy(3033, 52 * 60, 6, 73.7)  # the walk of 2026-10-26: 3.5 km/h, 6 %, 73.7 kg
    flat = walkpad.energy(3033, 52 * 60, 0, 73.7)
    assert e["kcal"] == 232 and e["kcal_gross"] == 300  # active only; gross keeps the resting 3.5 ml/kg/min
    assert e["kcal_flat"] == flat["kcal"] and flat["kcal_incline"] == 0
    assert e["kcal_incline"] / e["kcal_flat"] == pytest.approx(1.08, abs=0.01)  # incline doubles the active cost
    assert e["kcal_gross"] / flat["kcal_gross"] == pytest.approx(1.68, abs=0.01)
    assert walkpad.energy(3033, 3120, 6, None)["kcal"] is None


def test_manual_entry_then_recorder_replaces_it(db, monkeypatch):
    monkeypatch.setattr(walkpad, "_weights", lambda: pd.Series([80.0], index=[pd.Timestamp("2026-10-01")]))
    m = walkpad.add_manual(datetime(2026, 10, 20, 9, 0), 52, 3.5)
    assert m["source"] == "manual" and m["incline_pct"] == 0 and m["distance_km"] == pytest.approx(3.03, abs=0.01)
    assert m["kcal"] and m["kcal_pad"] is None
    six = walkpad.add_manual(datetime(2026, 10, 20, 18, 0), 52, 3.5, incline_pct=6)
    assert six["elevation_m"] == 182 and six["kcal_incline"] > 0
    with pytest.raises(ValueError):
        walkpad.add_manual(datetime(2026, 10, 20, 9, 30), 10, 3.5)  # overlaps
    with Session(db) as ses:  # manual one already in Garmin
        row = ses.get(walkpad.WalkpadSession, m["id"])
        row.garmin_status, row.garmin_activity_id = "uploaded", "99"
        ses.add(row)
        ses.commit()
    rec, created = walkpad.ingest(recorded())  # 09:00–09:30 recorder session
    assert created and rec["garmin_status"] == "uploaded" and rec["garmin_activity_id"] == "99"
    assert walkpad.detail(m["id"]) is None
    assert walkpad.delete_manual(rec["id"]) is False and walkpad.delete_manual(six["id"]) is True


def test_manual_api(db, monkeypatch):
    from app.ingest import garmin
    from app.main import app
    monkeypatch.setattr(garmin, "upload_walkpad", lambda: None)
    http = TestClient(app)
    r = http.post("/walkpad/manual", json={"started_at": "2026-10-20T09:30:00", "minutes": 52, "speed_kmh": 3.5, "incline_pct": 6})
    assert r.status_code == 200 and r.json()["source"] == "manual"
    assert http.post("/walkpad/manual", json={"started_at": "2026-10-20T09:40:00", "minutes": 10, "speed_kmh": 3.5}).status_code == 422
    assert http.delete(f"/walkpad/sessions/{r.json()['id']}").status_code == 200
    assert http.delete("/walkpad/sessions/nope").status_code == 404


def test_tdee_today_takes_window_walks_out_and_today_in(monkeypatch):
    from app.metrics import body
    walks = {date(2026, 10, d): 210.0 for d in range(1, 15)}  # 14 walk days inside the 28-day window
    walks[date(2026, 10, 26)] = 232.0                           # today, after the TDEE's last weight day
    monkeypatch.setattr(body, "_walk_kcal", lambda: walks)
    monkeypatch.setattr(body, "_intake_daily", lambda: pd.Series([1800.0], index=[pd.Timestamp("2026-10-26")]))
    out = body._today_with_walks(3000, date(2026, 10, 21), 14, 14, today=date(2026, 10, 26))
    assert out["walk_kcal_avg"] == 105 and out["tdee_base"] == 2895     # 14 × 210 / 28 days
    assert out["walk_kcal_today"] == 232 and out["tdee_today"] == 3127 and out["intake_today"] == 1800
    rest = body._today_with_walks(3000, date(2026, 10, 21), 14, 14, today=date(2026, 10, 27))
    assert rest["tdee_today"] == 2895  # walk-free day: below the adaptive mean
    monkeypatch.setattr(body, "_walk_kcal", lambda: {})
    assert body._today_with_walks(3000, date(2026, 10, 21), 14, 14, today=date(2026, 10, 26))["tdee_today"] == 3000
