from datetime import date
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

from app.api import settings as settings_api
from app.coach import profile, prompts
from app.config import settings


@pytest.fixture
def profile_client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'profile.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(profile, "engine", engine)
    monkeypatch.setattr(settings, "coach_context", "Legacy personal context")
    app = FastAPI()
    app.include_router(settings_api.router)
    with TestClient(app) as client:
        yield client
    engine.dispose()


def test_roundtrip_multiline_context_and_clear_never_resurrects_legacy(profile_client):
    client = profile_client
    assert client.get("/settings/coach").json() == {"context": "Legacy personal context", "goals": []}
    content = 'Düsseldorf #1\nDrei Trainingstage; "locker".\n${NO_INTERPOLATION}'
    goal = {"id": str(uuid4()), "name": "Halbmarathon", "start_date": "2027-04-18",
            "target": "Ankommen", "priority": "high"}
    saved = client.put("/settings/coach", json={"context": content, "goals": [goal]})
    assert saved.status_code == 200
    assert client.get("/settings/coach").json() == saved.json()
    assert profile.load().context == content
    assert profile.load().goals[0].name == "Halbmarathon"
    assert "Halbmarathon" in prompts.build_messages("daily", "snapshot")[0]["content"]
    assert client.put("/settings/coach", json={"goals": [], "context": ""}).status_code == 200
    assert client.get("/settings/coach").json() == {"goals": [], "context": ""}
    assert "Legacy personal context" not in prompts.system_prompt()
    assert "Halbmarathon" not in prompts.system_prompt()


@pytest.mark.parametrize("change", [
    {"name": "   "}, {"start_date": "2027-02-30"},
    {"end_date": "2027-01-01"}, {"start_date": "2027-06-13", "end_date": "2027-06-11"},
    {"priority": "urgent"}, {"status": "past"},
])
def test_invalid_goal_does_not_overwrite_saved_profile(profile_client, change):
    client = profile_client
    assert client.put("/settings/coach", json={"context": "Keep me"}).status_code == 200
    response = client.put("/settings/coach", json={"goals": [{"name": "Race", **change}]})
    assert response.status_code == 422
    assert client.get("/settings/coach").json()["context"] == "Keep me"


def test_duplicate_goal_ids_are_rejected(profile_client):
    goal = {"id": str(uuid4()), "name": "Race"}
    assert profile_client.put("/settings/coach", json={"goals": [goal, goal]}).status_code == 422


def test_expiry_uses_end_of_event_and_preserves_manual_status(monkeypatch):
    weekend = profile.Goal(name="Weekend", start_date=date(2027, 6, 11), end_date=date(2027, 6, 13))
    single = profile.Goal(name="Race", start_date=date(2027, 6, 13))
    undated = profile.Goal(name="Strength")
    assert weekend.effective_status(date(2027, 6, 13)) == "active"
    assert single.effective_status(date(2027, 6, 13)) == "active"
    assert weekend.effective_status(date(2027, 6, 14)) == "past"
    assert single.effective_status(date(2027, 6, 14)) == "past"
    assert undated.effective_status(date(2030, 1, 1)) == "active"
    for status in ("achieved", "archived"):
        weekend.status = status
        assert weekend.effective_status(date(2027, 6, 14)) == status


def test_prompt_excludes_archived_and_achieved_and_marks_past(monkeypatch):
    goals = [profile.Goal(name="Past", start_date=date(2027, 1, 1)),
             profile.Goal(name="Achieved", status="achieved"),
             profile.Goal(name="Archived", status="archived"),
             profile.Goal(name="Later high", start_date=date(2027, 6, 1), priority="high"),
             profile.Goal(name="Soon normal", start_date=date(2027, 4, 1)),
             profile.Goal(name="Ongoing")]
    monkeypatch.setattr(profile, "load", lambda: profile.Profile(goals=goals))
    text = profile.context_text(date(2027, 3, 1))
    assert '"Past"' in text
    assert '"Achieved"' not in text and '"Archived"' not in text
    assert text.index('"Later high"') < text.index('"Soon normal"')
    assert '"Ongoing"' in text
    assert "Erfolg unbekannt, keine Vorbereitung" in text
