"""Nacharbeit #54: /coach/reports zeigt Anbieter und Rückfallgrund; server/.env.example lädt."""
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import coach as coach_api
from app.config import Settings
from app.models import CoachReport


def test_reports_expose_provider_and_fallback_reason(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(coach_api, "engine", engine)
    with Session(engine) as s:
        s.add(CoachReport(created_at=datetime(2026, 10, 16, 7, 0), kind="briefing", content="a",
                          provider="anthropic", model="claude-opus-5-5"))
        s.add(CoachReport(created_at=datetime(2026, 10, 17, 7, 0), kind="briefing", content="b",
                          provider="openrouter", model="openai/gpt-6-luna", fallback_reason="Monatsbudget erreicht"))
        s.commit()
    app = FastAPI()
    app.include_router(coach_api.router)
    api = TestClient(app)

    rows = api.get("/coach/reports").json()
    assert [(r["provider"], r["fallback_reason"]) for r in rows] == [
        ("openrouter", "Monatsbudget erreicht"), ("anthropic", None)]
    detail = api.get(f"/coach/reports/{rows[0]['id']}").json()
    assert detail["provider"] == "openrouter" and detail["fallback_reason"] == "Monatsbudget erreicht"
    engine.dispose()


def test_env_example_loads_with_defaults(monkeypatch):
    for key in ("LLM_PROVIDER", "ANTHROPIC_MODEL", "ANTHROPIC_EFFORT", "LLM_MONTHLY_BUDGET_USD", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    example = Path(__file__).resolve().parents[1] / ".env.example"
    text = example.read_text(encoding="utf-8")
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_EFFORT", "LLM_PROVIDER", "LLM_MONTHLY_BUDGET_USD"):
        assert key in text
    s = Settings(_env_file=example)
    assert s.anthropic_model == "claude-opus-5-5" and s.anthropic_effort == "medium"
    assert s.llm_monthly_budget_usd == 100.0 and s.anthropic_api_key == ""
