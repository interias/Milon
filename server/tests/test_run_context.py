from datetime import date, datetime
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import checkins, garmin_weather as weather, run_context as context
from app.api import run_context as api
from app.garmin_activity import GarminActivity
from app.models import ExerciseSession


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'context.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(context, "engine", engine)
    monkeypatch.setattr(weather, "engine", engine)
    monkeypatch.setattr(checkins, "local_today", lambda: date(2026, 10, 5))
    with Session(engine) as session:
        for key, day in (("1", 2), ("2", 2), ("3", 6)):
            session.add(GarminActivity(activity_id=key, started_at=datetime(2026, 10, day, 10),
                canonical_external_id=f"run-{key}", summary_json=json.dumps({"started_at_utc": f"2026-10-{day:02}T08:00:00+00:00"}),
                series_json="[]", laps_json="[]", zones_json="[]", quality_json="{}", fingerprint="x", fetched_at=datetime(2026, 10, 5)))
            session.add(ExerciseSession(external_id=f"run-{key}", exercise_type=33, started_at=datetime(2026, 10, day, 10)))
        session.add(checkins.CheckIn(day=date(2026, 10, 2), energy=4, note="Keep this", updated_at=datetime(2026, 10, 2)))
        session.commit()
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        yield client
    engine.dispose()


def test_independent_intent_effort_and_existing_checkin(client):
    assert client.patch("/running/context/1", json={"intent": "easy"}).json()["intent"] == "easy"
    result = client.patch("/running/context/1", json={"training_effort": 2}).json()
    assert result["intent"] == "easy" and result["training_effort"] == 2
    assert client.patch("/running/context/1", json={"intent": None}).json()["training_effort"] == 2
    assert client.patch("/running/context/1", json={"training_effort": None}).status_code == 200
    with Session(context.engine) as session:
        entry = session.get(checkins.CheckIn, date(2026, 10, 2))
        assert (entry.energy, entry.note, entry.session_external_id) == (4, "Keep this", "run-1")


def test_other_session_conflict_never_overwrites_and_intent_still_works(client):
    client.patch("/running/context/1", json={"training_effort": 2})
    assert client.get("/running/context/2").json()["effort_conflict"]
    assert client.patch("/running/context/2", json={"intent": "long"}).status_code == 200
    assert client.patch("/running/context/2", json={"intent": "tempo", "training_effort": 5}).status_code == 409
    assert client.get("/running/context/2").json()["intent"] == "long"
    assert client.get("/running/context/1").json()["training_effort"] == 2


def test_unassigned_existing_effort_is_not_silently_assigned(client):
    with Session(context.engine) as session:
        entry = session.get(checkins.CheckIn, date(2026, 10, 2))
        entry.training_effort = 3
        session.add(entry)
        session.commit()
    assert client.get("/running/context/1").json()["training_effort"] is None
    assert client.patch("/running/context/1", json={"training_effort": 2}).status_code == 409


@pytest.mark.parametrize("body", [{}, {"intent": "race"}, {"training_effort": True}, {"training_effort": 0}, {"training_effort": 6}, {"training_effort": "3"}, {"note": "unknown"}])
def test_input_validation(client, body):
    assert client.patch("/running/context/1", json=body).status_code == 422


def test_future_missing_and_unmapped_activity(client):
    assert client.patch("/running/context/3", json={"intent": "easy"}).status_code == 422
    assert client.get("/running/context/99").status_code == 404
    with Session(context.engine) as session:
        row = session.get(GarminActivity, "1")
        row.canonical_external_id = None
        session.add(row)
        session.commit()
    assert not client.get("/running/context/1").json()["effort_editable"]
    assert client.patch("/running/context/1", json={"training_effort": 2}).status_code == 422


def test_weather_units_privacy_and_time_provenance(client):
    raw = {"temp": 50, "apparentTemp": 41, "windSpeed": 3, "windDirection": 190,
           "relativeHumidity": 80, "issueDate": "2026-10-02T07:30:00.000+0000",
           "latitude": 1, "longitude": 2, "weatherStationDTO": {"id": "private"}}
    normalized = weather.normalize(raw)
    assert normalized["temperature_c"] == 10 and normalized["feels_like_c"] == 5
    assert normalized["wind_speed_kmh"] is None
    assert not {"latitude", "longitude", "weatherStationDTO"} & normalized.keys()
    class Fake:
        calls = 0
        def get_activity_weather(self, key):
            self.calls += 1
            return raw
    fake = Fake()
    assert weather.sync_weather(fake, [{"activityId": 1}, {"activityId": 1}])["imported"] == 1
    assert weather.sync_weather(fake, [{"activityId": 1}])["skipped"] == 1
    assert fake.calls == 1
    result = client.get("/running/context/1").json()["weather"]
    assert result["offset_minutes"] == -30 and result["time_aligned"]


def test_optional_weather_failure_retains_last_good_value(client):
    class Fake:
        failure = False
        def get_activity_weather(self, key):
            if self.failure:
                raise ValueError("PRIVATE")
            return {"temp": 32}
    fake = Fake()
    weather.sync_weather(fake, [{"activityId": 1}])
    fake.failure = True
    assert weather.sync_weather(fake, [{"activityId": 1}], full=True)["errors"] == 1
    data = client.get("/running/context/1").json()["weather"]
    assert data["status"] == "error" and data["temperature_c"] == 0
    assert "PRIVATE" not in json.dumps(data)
    assert not data["time_aligned"]


@pytest.mark.parametrize("raw", [None, [], {}, {"temp": float("nan")}, {"temp": True}, {"temp": 1000}, {"windSpeed": 4}])
def test_invalid_or_empty_weather_stays_unknown(raw):
    assert weather.normalize(raw) == {}


def test_weather_failure_does_not_fail_core_import(client, monkeypatch):
    from app import garmin_activity, garmin_daily
    from app.ingest import garmin
    monkeypatch.setattr(garmin_activity, "sync_activities", lambda *a, **k: {"errors": 0, "imported": 1})
    monkeypatch.setattr(garmin_daily, "sync_daily", lambda *a, **k: {"errors": 0})
    def routes(api, full, collected):
        collected.append({"activityId": 1})
        return {"errors": 0, "imported": 1}
    monkeypatch.setattr(garmin, "_pull_routes", routes)
    class Unavailable:
        def get_activity_weather(self, key):
            raise RuntimeError("private remote failure")
    result = garmin._pull_all(Unavailable(), False)
    assert result["errors"] == 0 and result["activities"]["imported"] == 1
    assert result["weather"]["errors"] == 1
