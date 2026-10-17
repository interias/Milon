"""Automatischer Wochenbericht (#53): Auslöser, Idempotenz je ISO-Woche, Prompt-Inhalt, API — gemocktes LLM, tmp-SQLite."""
from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import coach as coach_api
from app.coach import briefing, weekly_auto
from app.models import CoachReport

TZ = ZoneInfo("Europe/Berlin")
USAGE = {"prompt_tokens": 3000, "completion_tokens": 300, "cost": 0.03, "cache_read_tokens": 0,
         "provider": "anthropic", "model": "claude-opus-5-5", "fallback_reason": None}
SUNDAY = date(2026, 10, 18)       # Woche 2026-W42 endet; Mo 12.10. bis So 18.10.


def at(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for module in (weekly_auto, briefing):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(weekly_auto.settings, "timezone", "Europe/Berlin")
    yield engine
    engine.dispose()


@pytest.fixture
def llm(monkeypatch):
    calls = []

    def complete(messages, temperature=0.4):
        calls.append(messages)
        return "**Woche:** solide Woche\n- **Körper:** …", dict(USAGE)

    monkeypatch.setattr(weekly_auto.client, "complete", complete)
    monkeypatch.setattr(weekly_auto.prompts, "system_prompt", lambda: "SYSTEM")
    monkeypatch.setattr(weekly_auto.snapshot, "snapshot_text", lambda: "SNAPSHOT")
    monkeypatch.setattr(weekly_auto, "_week_lines", lambda first, last: [f"BERICHTSWOCHE: {first} bis {last}"])
    return calls


def reports(engine):
    with Session(engine) as s:
        return s.exec(select(CoachReport)).all()


def test_last_cutoff_is_sunday_2330():
    assert weekly_auto.last_cutoff(at(SUNDAY, 23, 29)) == datetime(2026, 10, 11, 23, 30)
    assert weekly_auto.last_cutoff(at(SUNDAY, 23, 30)) == datetime(2026, 10, 18, 23, 30)
    assert weekly_auto.last_cutoff(at(SUNDAY + timedelta(days=1), 6)) == datetime(2026, 10, 18, 23, 30)
    assert weekly_auto.last_cutoff(at(SUNDAY - timedelta(days=3), 12)) == datetime(2026, 10, 11, 23, 30)
    assert weekly_auto.week_of(datetime(2026, 10, 18, 23, 30)) == (date(2026, 10, 12), date(2026, 10, 18))


def test_not_due_before_sunday_night_when_week_already_done(db, llm):
    # Bericht der Vorwoche liegt vor -> bis Sonntag 23:30 nichts Neues
    with Session(db) as s:
        s.add(CoachReport(created_at=datetime(2026, 10, 11, 23, 31), kind="weekly-auto", content="alt"))
        s.commit()
    assert weekly_auto.maybe_run(at(SUNDAY, 12)) is None
    assert weekly_auto.maybe_run(at(SUNDAY, 23, 29)) is None
    assert llm == []


def test_sunday_2330_generates_once_per_iso_week(db, llm):
    first = weekly_auto.maybe_run(at(SUNDAY, 23, 30))
    assert first and first["kind"] == "weekly-auto" and first["cost_usd"] == 0.03
    assert weekly_auto.maybe_run(at(SUNDAY, 23, 45)) is None
    assert weekly_auto.maybe_run(at(SUNDAY + timedelta(days=1), 7)) is None
    rows = reports(db)
    assert len(rows) == 1 and len(llm) == 1
    assert rows[0].created_at == datetime(2026, 10, 18, 23, 30)
    assert rows[0].provider == "anthropic" and rows[0].prompt_tokens == 3000
    assert json.loads(rows[0].prompt) == llm[0]                    # Prompt gespeichert


def test_missed_sunday_is_caught_up_while_new_week_runs(db, llm):
    got = weekly_auto.maybe_run(at(SUNDAY + timedelta(days=2), 9))   # Dienstag, Server war Sonntag aus
    assert got and weekly_auto.maybe_run(at(SUNDAY + timedelta(days=3), 9)) is None
    assert "2026-10-12 bis 2026-10-18" in llm[0][-1]["content"]      # die abgelaufene Woche, nicht die laufende


def test_next_week_gets_its_own_report(db, llm):
    assert weekly_auto.maybe_run(at(SUNDAY, 23, 30))
    assert weekly_auto.maybe_run(at(SUNDAY + timedelta(days=7), 23, 30))
    assert len(reports(db)) == 2


def test_prompt_covers_five_areas_and_at_most_three_proposals(db, llm):
    weekly_auto.maybe_run(at(SUNDAY, 23, 30))
    messages = llm[0]
    assert [m["role"] for m in messages] == ["system", "system", "user"]
    assert messages[1]["content"].endswith("SNAPSHOT")             # Snapshot im letzten System-Block (Cache)
    user = messages[-1]["content"]
    for area in ("Körper", "Laufen", "Kraft", "Ernährung", "Schlaf"):
        assert f"**{area}:**" in user
    assert "Höchstens drei Vorschläge für die kommende Woche" in user
    assert "Du liest nur und schlägst vor" in user and "Heldenreise" in user and "höchstens mit einem Halbsatz" in user


def boom(*args, **kwargs):
    raise RuntimeError("boom")


def test_week_lines_survive_missing_metrics(monkeypatch):
    from app.metrics import activity, running
    for module, name in ((activity, "weekly_review"), (running, "pace_at_hr")):   # nie gegen data/tracker.db
        monkeypatch.setattr(module, name, boom)
    monkeypatch.setattr(weekly_auto, "_nutrition_line", boom)
    assert weekly_auto._week_lines(date(2026, 10, 12), date(2026, 10, 18)) == [
        "BERICHTSWOCHE: 2026-10-12 (Mo) bis 2026-10-18 (So)"]


def test_week_review_window_is_monday_to_sunday(monkeypatch):
    from app.metrics import activity, running
    seen = []
    monkeypatch.setattr(activity, "weekly_review", lambda now: seen.append(now) or {})
    monkeypatch.setattr(weekly_auto, "_nutrition_line", lambda a, b: "ERNÄHRUNG")
    monkeypatch.setattr(running, "pace_at_hr", lambda: {})
    monkeypatch.setattr(running, "easy_hr_trend", lambda: {})
    weekly_auto._week_lines(date(2026, 10, 12), date(2026, 10, 18))
    assert seen[0].date() == date(2026, 10, 19) and (seen[0].hour, seen[0].minute) == (0, 0)  # Montag 00:00 -> Mo–So


def test_api_current_returns_report_only_while_new_week_runs(db, monkeypatch):
    app = FastAPI()
    app.include_router(coach_api.router)
    api = TestClient(app)
    monkeypatch.setattr(briefing, "_now", lambda: at(SUNDAY + timedelta(days=1), 8))
    assert api.get("/coach/weekly-auto/current").json() == {"week_from": "2026-10-12", "week_to": "2026-10-18", "report": None}
    with Session(db) as s:
        s.add(CoachReport(created_at=datetime(2026, 10, 11, 23, 31), kind="weekly-auto", content="vorwoche"))
        s.add(CoachReport(created_at=datetime(2026, 10, 19, 9, 0), kind="weekly", content="manuell"))
        s.add(CoachReport(created_at=datetime(2026, 10, 18, 23, 31), kind="weekly-auto", content="**Woche:** gut",
                          cost_usd=0.03, provider="anthropic", model="claude-opus-5-5"))
        s.commit()
    body = api.get("/coach/weekly-auto/current").json()
    assert body["report"]["content"] == "**Woche:** gut" and body["report"]["cost_usd"] == 0.03
    monkeypatch.setattr(briefing, "_now", lambda: at(SUNDAY + timedelta(days=7), 23, 40))   # neue Woche beendet, kein neuer Bericht
    assert api.get("/coach/weekly-auto/current").json()["report"] is None
