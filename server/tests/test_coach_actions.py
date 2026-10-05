from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

from app import coach_actions
from app.api import coach_actions as actions_api
from app.checkins import CheckIn
from app.coach_actions import CoachAction
from app.models import CoachReport, NutritionEntry, SleepSession, StepsDaily


@pytest.fixture
def action_client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'actions.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(coach_actions, "engine", engine)
    monkeypatch.setattr(coach_actions, "local_today", lambda: date(2026, 10, 5))
    monkeypatch.setattr(coach_actions.settings, "watch_source_switch_date", date(2026, 9, 25))
    monkeypatch.setattr(coach_actions.settings, "watch_source_package", "garmin")
    monkeypatch.setattr(coach_actions.settings, "steps_source_package", "samsung")
    app = FastAPI()
    app.include_router(actions_api.router)
    with TestClient(app) as client:
        yield client
    engine.dispose()


def seed_action(start=date(2026, 9, 28), metric="steps"):
    with Session(coach_actions.engine) as session:
        row = CoachAction(action="Walk after lunch", metric=metric, starts_on=start,
                          ends_on=start + timedelta(days=6), accepted_at=datetime(2026, 9, 28),
                          updated_at=datetime(2026, 9, 28))
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def seed_steps(start: date, values: list[int]):
    with Session(coach_actions.engine) as session:
        for offset, value in enumerate(values):
            session.add(StepsDaily(day=start + timedelta(days=offset), steps=value, source="garmin"))
        session.commit()


def test_explicit_acceptance_and_feedback_preserve_other_fields(action_client):
    client = action_client
    assert client.get("/coach/actions").json()["entries"] == []
    result = client.post("/coach/actions", json={"action": "  Walk after lunch  ", "metric": "steps"})
    assert result.status_code == 201
    entry = result.json()
    assert entry["action"] == "Walk after lunch"
    assert entry["starts_on"] == "2026-10-05" and entry["ends_on"] == "2026-10-11"
    assert entry["status"] == "pending" and entry["phase"] == "running"
    assert entry["comparison"]["during"]["days"] == 0
    assert entry["comparison"]["during"]["end"] is None
    assert client.post("/coach/actions", json={"action": "Another action"}).status_code == 409
    path = f"/coach/actions/{entry['id']}"
    assert client.patch(path, json={"note": "  Some days  "}).json()["note"] == "Some days"
    updated = client.patch(path, json={"status": "partly"}).json()
    assert updated["note"] == "Some days" and updated["action"] == entry["action"]
    cleared = client.patch(path, json={"note": None}).json()
    assert cleared["note"] is None and cleared["status"] == "partly"
    assert client.patch(path, json={"status": "pending"}).json()["status"] == "pending"
    assert client.delete(path).status_code == 200
    assert client.delete(path).status_code == 200
    assert client.get("/coach/actions").json()["entries"] == []


@pytest.mark.parametrize("payload", [
    {}, {"action": " "}, {"action": "x" * 281}, {"action": "Walk", "metric": "bodyfat"},
    {"action": "Walk", "starts_on": "2026-10-08"}, {"action": "Walk", "status": "implemented"},
    {"action": "Walk", "source_report_id": True}, {"action": "Walk", "source_report_id": 0},
    {"action": "Walk", "source_report_id": 999},
])
def test_invalid_acceptance_never_writes(action_client, payload):
    assert action_client.post("/coach/actions", json=payload).status_code == 422
    assert action_client.get("/coach/actions").json()["entries"] == []


@pytest.mark.parametrize("payload", [
    {}, {"status": None}, {"status": "done"}, {"note": "x" * 301},
    {"action": "Changed"}, {"metric": "sleep"}, {"starts_on": "2099-01-01"},
])
def test_invalid_feedback_never_changes_accepted_plan(action_client, payload):
    entry_id = seed_action()
    assert action_client.patch(f"/coach/actions/{entry_id}", json=payload).status_code == 422
    row = action_client.get("/coach/actions").json()["entries"][0]
    assert row["status"] == "pending" and row["note"] is None and row["metric"] == "steps"


def test_report_link_and_new_action_after_seven_days(action_client):
    previous = seed_action()
    with Session(coach_actions.engine) as session:
        report = CoachReport(kind="weekly", content="Example", created_at=datetime(2026, 10, 5))
        session.add(report)
        session.commit()
        session.refresh(report)
        report_id = report.id
    result = action_client.post("/coach/actions", json={"action": "Earlier bedtime", "metric": "sleep", "source_report_id": report_id})
    assert result.status_code == 201 and result.json()["source_report_id"] == report_id
    entries = action_client.get("/coach/actions").json()["entries"]
    assert entries[1]["id"] == previous and entries[1]["phase"] == "finished"
    context = coach_actions.coach_context()
    assert context[0]["action"] == "Earlier bedtime"
    assert "accepted_at" not in context[0]
    assert action_client.patch("/coach/actions/999", json={"status": "partly"}).status_code == 404


def test_comparison_uses_exact_windows_missing_days_and_no_future(action_client, monkeypatch):
    monkeypatch.setattr(coach_actions, "local_today", lambda: date(2026, 10, 9))
    seed_action(date(2026, 10, 5))
    seed_steps(date(2026, 9, 27), [99000, 4000, 6000, 8000])
    seed_steps(date(2026, 10, 5), [8000, 10000, 12000, 10000, 99999, 99999])
    result = action_client.get("/coach/actions").json()["entries"][0]["comparison"]
    assert result["before"] == {"start": "2026-09-28", "end": "2026-10-04", "days": 7, "recorded_days": 3, "mean": 6000}
    assert result["during"] == {"start": "2026-10-05", "end": "2026-10-08", "days": 4, "recorded_days": 4, "mean": 10000}
    assert result["delta"] == 4000 and result["status"] == "observed"
    monkeypatch.setattr(coach_actions, "local_today", lambda: date(2026, 11, 1))
    seed_steps(date(2026, 10, 12), [999999])
    completed = action_client.get("/coach/actions").json()["entries"][0]["comparison"]
    assert completed["during"]["end"] == "2026-10-11" and completed["during"]["recorded_days"] == 6


def test_too_few_days_does_not_invent_zero_or_comparison(action_client):
    seed_action(metric="energy")
    with Session(coach_actions.engine) as session:
        session.add(CheckIn(day=date(2026, 9, 22), energy=2, updated_at=datetime(2026, 9, 22)))
        session.add(CheckIn(day=date(2026, 9, 29), energy=4, updated_at=datetime(2026, 9, 29)))
        session.add(CheckIn(day=date(2026, 9, 30), note="Fine", updated_at=datetime(2026, 9, 30)))
        session.commit()
    comparison = action_client.get("/coach/actions").json()["entries"][0]["comparison"]
    assert comparison["before"]["mean"] == 2 and comparison["during"]["mean"] == 4
    assert comparison["during"]["recorded_days"] == 1
    assert comparison["delta"] is None and comparison["status"] == "collecting"


def test_watch_change_withholds_delta_even_with_enough_days(action_client):
    seed_action()
    seed_steps(date(2026, 9, 21), [3000] * 7)
    seed_steps(date(2026, 9, 28), [5000] * 7)
    comparison = action_client.get("/coach/actions").json()["entries"][0]["comparison"]
    assert comparison["before"]["mean"] == 3000 and comparison["during"]["mean"] == 5000
    assert comparison["status"] == "source_changed" and comparison["delta"] is None


def test_protein_sums_only_known_entries_and_preserves_zero(action_client):
    seed_action(metric="protein")
    with Session(coach_actions.engine) as session:
        for offset, protein in enumerate((20, 40, None, 0)):
            session.add(NutritionEntry(eaten_at=datetime(2026, 9, 29, offset), protein_g=protein, fddb_id=str(offset)))
        session.add(NutritionEntry(eaten_at=datetime(2026, 9, 30), protein_g=None))
        session.add(NutritionEntry(eaten_at=datetime(2026, 10, 1), protein_g=0))
        session.add(NutritionEntry(eaten_at=datetime(2026, 10, 2), protein_g=300, source="other"))
        session.commit()
    comparison = action_client.get("/coach/actions").json()["entries"][0]["comparison"]
    assert comparison["before"]["mean"] is None
    assert comparison["during"]["mean"] == 30 and comparison["during"]["recorded_days"] == 2
    assert comparison["delta"] is None


def test_sleep_keeps_source_and_longest_main_night(action_client):
    seed_action(metric="sleep")
    with Session(coach_actions.engine) as session:
        for index, (day, package, window, asleep, main) in enumerate([
            (29, "garmin", 480, 420, True), (29, "garmin", 120, 120, True),
            (29, "samsung", 600, 600, True), (30, "garmin", 480, None, True),
            (30, "garmin", 180, 170, True), (30, "garmin", 60, 60, False),
        ]):
            session.add(SleepSession(external_id=str(index), day=date(2026, 9, day),
                                     started_at=datetime(2026, 9, day - 1, 22), ended_at=datetime(2026, 9, day, 6),
                                     duration_window_minutes=window, asleep_minutes=asleep,
                                     main_sleep=main, source_package=package))
        session.commit()
    comparison = action_client.get("/coach/actions").json()["entries"][0]["comparison"]
    assert comparison["during"]["mean"] == 7 and comparison["during"]["recorded_days"] == 1


def test_coach_and_mcp_read_only_tools_return_user_approved_context(action_client):
    from app.coach import tools
    from app.mcp import server

    entry_id = seed_action(metric="energy")
    action_client.patch(f"/coach/actions/{entry_id}", json={"status": "not_tried", "note": "Travel week"})
    expected = coach_actions.coach_context()
    assert tools.dispatch("get_coach_actions", {}) == expected
    assert server.get_coach_actions() == expected
    definition = next(tool["function"] for tool in tools.TOOLS if tool["function"]["name"] == "get_coach_actions")
    assert definition["parameters"]["properties"] == {}
    assert expected[0]["status"] == "not_tried" and expected[0]["comparison"]["delta"] is None


def test_snapshot_exposes_action_feedback_without_inventing_results(monkeypatch):
    from app import garmin_daily
    from app.coach import snapshot

    for module, names in ((snapshot.body, ["summary", "adaptive_tdee", "weight_forecast", "bodyfat_forecast"]),
                          (snapshot.nutrition, ["summary"]), (snapshot.running, ["summary"]),
                          (snapshot.strength, ["summary", "strength_index"]),
                          (snapshot.health, ["steps_summary", "cycling_summary", "resting_hr_trend"])):
        for name in names:
            monkeypatch.setattr(module, name, lambda *args, **kwargs: {})
    for module, names in ((snapshot.running, ["weekly_volume"]),
                          (snapshot.strength, ["weekly_tonnage", "rpe_trend"])):
        for name in names:
            monkeypatch.setattr(module, name, lambda *args, **kwargs: [])
    monkeypatch.setattr(snapshot.sleep, "overview", lambda *args: {"summary": {}})
    monkeypatch.setattr(snapshot.checkins, "summary", lambda *args: {"count": 0, "days": 30, "energy_avg": None,
                        "energy_days": 0, "training_effort_avg": None, "training_effort_days": 0})
    monkeypatch.setattr(garmin_daily, "coach_summary", lambda *args: {})
    context = [{"action": "Walk after lunch", "status": "partly", "comparison": {"delta": None}}]
    monkeypatch.setattr(coach_actions, "coach_context", lambda: context)
    assert snapshot.build_snapshot()["wochenmassnahmen"] == context
    text = snapshot.snapshot_text()
    assert "Walk after lunch" in text and '"status": "partly"' in text and '"delta": null' in text
    assert "kein Wirkungsnachweis" in text
