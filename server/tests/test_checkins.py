from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app import checkins
from app.api import checkins as checkins_api
from app.models import ExerciseSession, Workout


@pytest.fixture
def checkin_client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'checkins.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(checkins, "engine", engine)
    monkeypatch.setattr(checkins, "local_today", lambda: date(2026, 10, 4))
    with Session(engine) as session:
        session.add(ExerciseSession(external_id="run-1", exercise_type=33, started_at=datetime(2026, 10, 3, 10), distance_km=5))
        session.add(ExerciseSession(external_id="cycling-1", exercise_type=4, started_at=datetime(2026, 10, 3, 10)))
        session.add(Workout(external_id="hevy-1", title="Gym", started_at=datetime(2026, 10, 3, 18)))
        session.add(Workout(external_id="other-1", source="other", started_at=datetime(2026, 10, 3, 18)))
        session.commit()
    app = FastAPI()
    app.include_router(checkins_api.router)
    with TestClient(app) as client:
        yield client
    engine.dispose()


def test_daily_roundtrip_replace_and_delete(checkin_client):
    client = checkin_client
    assert client.get("/checkins/2026-10-03").json() is None
    assert client.put("/checkins/2026-10-03", json={"energy": 4, "note": "  Quite good  "}).status_code == 200
    saved = client.put("/checkins/2026-10-03", json={"training_effort": 3, "session_kind": "strength", "session_external_id": "hevy-1"})
    assert saved.status_code == 200
    assert saved.json()["energy"] is None and saved.json()["note"] is None
    assert client.get("/checkins/2026-10-03").json()["session_external_id"] == "hevy-1"
    result = client.get("/checkins").json()
    assert result["today"] == "2026-10-04"
    assert len(result["entries"]) == 1
    assert result["summary"]["energy_avg"] is None
    assert result["summary"]["training_effort_avg"] == 3
    assert result["summary"]["linked_sessions"] == 1
    assert client.delete("/checkins/2026-10-03").status_code == 200
    assert client.delete("/checkins/2026-10-03").status_code == 200
    assert client.get("/checkins").json()["entries"] == []


@pytest.mark.parametrize("body", [
    {}, {"note": "   "}, {"energy": 0}, {"energy": 6}, {"energy": True}, {"energy": "4"},
    {"energy": 4.5}, {"training_effort": -1}, {"note": "x" * 501},
    {"energy": 3, "session_kind": "run"}, {"energy": 3, "session_external_id": "run-1"},
    {"energy": 3, "session_kind": "unknown", "session_external_id": "run-1"},
    {"energy": 3, "session_kind": "run", "session_external_id": "missing"},
    {"energy": 3, "session_kind": "run", "session_external_id": "cycling-1"},
    {"energy": 3, "session_kind": "strength", "session_external_id": "run-1"},
    {"energy": 3, "session_kind": "strength", "session_external_id": "other-1"},
])
def test_invalid_input_does_not_create_or_overwrite(checkin_client, body):
    client = checkin_client
    assert client.put("/checkins/2026-10-03", json={"energy": 5}).status_code == 200
    assert client.put("/checkins/2026-10-03", json=body).status_code == 422
    assert client.get("/checkins/2026-10-03").json()["energy"] == 5


def test_session_day_and_future_date_validation(checkin_client):
    client = checkin_client
    ref = {"energy": 3, "session_kind": "run", "session_external_id": "run-1"}
    assert client.put("/checkins/2026-10-02", json=ref).status_code == 422
    assert client.put("/checkins/2026-10-03", json=ref).status_code == 200
    assert client.put("/checkins/2026-10-05", json={"energy": 3}).status_code == 422
    assert client.get("/checkins/sessions?day=2026-10-03").json() == [
        {"kind": "run", "external_id": "run-1", "started_at": "2026-10-03T10:00:00", "title": "Lauf", "detail": "5.0 km"},
        {"kind": "strength", "external_id": "hevy-1", "started_at": "2026-10-03T18:00:00", "title": "Gym", "detail": "Kraft"},
    ]


def test_energy_edit_preserves_deleted_training_reference_and_other_fields(checkin_client):
    client = checkin_client
    values = {"energy": 1, "training_effort": 4, "note": "Hard session",
              "session_kind": "strength", "session_external_id": "hevy-1"}
    assert client.put("/checkins/2026-10-03", json=values).status_code == 200
    with Session(checkins.engine) as session:
        workout = session.exec(select(Workout).where(Workout.external_id == "hevy-1")).one()
        session.delete(workout)
        session.commit()
    values["energy"] = 5
    changed = client.put("/checkins/2026-10-03", json=values)
    assert changed.status_code == 200
    assert {key: changed.json()[key] for key in values} == values
    for reference in (("strength", "missing"), ("run", "hevy-1")):
        invalid = {**values, "session_kind": reference[0], "session_external_id": reference[1]}
        assert client.put("/checkins/2026-10-03", json=invalid).status_code == 422
    assert client.put("/checkins/2026-10-04", json=values).status_code == 422
    assert client.get("/checkins/2026-10-03").json()["note"] == "Hard session"
    assert client.get("/checkins/2026-10-03").json()["energy"] == 5


def test_energy_undo_keeps_training_association_without_inventing_self_report(checkin_client):
    client = checkin_client
    reference = {"session_kind": "strength", "session_external_id": "hevy-1"}
    assert client.put("/checkins/2026-10-03", json={**reference, "energy": 3}).status_code == 200
    with Session(checkins.engine) as session:
        workout = session.exec(select(Workout).where(Workout.external_id == "hevy-1")).one()
        session.delete(workout)
        session.commit()
    undone = client.put("/checkins/2026-10-03", json={**reference, "energy": None})
    assert undone.status_code == 200
    assert undone.json()["session_external_id"] == "hevy-1"
    summary = checkins.summary(7, date(2026, 10, 4))
    assert summary["linked_sessions"] == 1 and summary["count"] == 1
    assert summary["energy_days"] == 0 and summary["energy_avg"] is None
    assert summary["training_effort_days"] == 0 and summary["training_effort_avg"] is None
    assert client.put("/checkins/2026-10-03", json={}).status_code == 422
    assert client.put("/checkins/2026-10-03", json={**reference, "session_external_id": "missing"}).status_code == 422


def test_summary_excludes_missing_values_and_respects_calendar_window(checkin_client):
    client = checkin_client
    for day, values in (("2026-09-04", {"energy": 1}), ("2026-09-27", {"energy": 1}),
                        ("2026-09-28", {"energy": 5}), ("2026-10-02", {"note": "Fine"}),
                        ("2026-10-04", {"training_effort": 4})):
        assert client.put(f"/checkins/{day}", json=values).status_code == 200
    short = checkins.summary(7, date(2026, 10, 4))
    assert short["from_date"] == "2026-09-28"
    assert short["count"] == 3 and short["energy_days"] == 1 and short["energy_avg"] == 5
    assert short["training_effort_days"] == 1 and short["training_effort_avg"] == 4
    assert checkins.summary(30, date(2026, 10, 4))["count"] == 4
    assert client.get("/checkins?days=0").status_code == 422


def test_today_uses_local_calendar_day():
    assert checkins.local_today(datetime(2026, 10, 3, 23, tzinfo=timezone.utc)) == date(2026, 10, 4)
