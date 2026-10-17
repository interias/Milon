from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import config
from app.api import settings as settings_api
from app.coach import client
from app.models import CoachReport

NOW = datetime(2026, 10, 17, 12, 0)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Settings-API gegen temporaere .env und tmp-SQLite; Settings-Felder werden nach dem Test zurueckgesetzt."""
    env_file = tmp_path / ".env"
    env_file.write_text("# Kommentar\nOPENROUTER_MODEL=x/y\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    engine = create_engine(f"sqlite:///{tmp_path / 'coach.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(client, "engine", engine)
    for field in ("anthropic_model", "anthropic_effort", "llm_monthly_budget_usd", "openrouter_model"):
        monkeypatch.setattr(client.settings, field, getattr(client.settings, field))
    app = FastAPI()
    app.include_router(settings_api.router)
    yield TestClient(app), env_file, engine
    engine.dispose()


def add_report(engine, provider, cost, created=NOW):
    with Session(engine) as s:
        s.add(CoachReport(created_at=created, kind="chat", content="x", provider=provider, cost_usd=cost))
        s.commit()


def test_get_exposes_new_fields_and_masks_anthropic_key(env, monkeypatch):
    http, _, _ = env
    monkeypatch.setattr(client.settings, "anthropic_api_key", "sk-ant-secret1234")
    body = http.get("/settings").json()
    assert body["anthropic_model"] == "claude-opus-5-5" and body["anthropic_effort"] == "medium"
    assert body["llm_monthly_budget_usd"] == 100 and body["llm_provider"] == ""
    assert body["llm_provider_resolved"] == "anthropic"
    assert body["keys"]["anthropic_api_key"] == {"set": True, "hint": "…1234"}
    assert "sk-ant-secret" not in http.get("/settings").text


def test_put_applies_live_and_persists_to_env(env):
    http, env_file, _ = env
    r = http.put("/settings", json={"llm_provider": "openrouter", "anthropic_model": "claude-sonnet-5-5",
                                    "anthropic_effort": "high", "llm_monthly_budget_usd": 50,
                                    "anthropic_api_key": "sk-ant-new0001"})
    assert r.status_code == 200 and r.json()["anthropic_model"] == "claude-sonnet-5-5"
    # live: Anbieterwahl und Modell greifen sofort
    assert client.settings.resolved_llm_provider() == "openrouter"
    assert client.settings.anthropic_effort == "high" and client.settings.llm_monthly_budget_usd == 50
    text = env_file.read_text(encoding="utf-8")
    for line in ("LLM_PROVIDER=openrouter", "ANTHROPIC_MODEL=claude-sonnet-5-5", "ANTHROPIC_EFFORT=high",
                 "LLM_MONTHLY_BUDGET_USD=50", "ANTHROPIC_API_KEY=sk-ant-new0001", "# Kommentar"):
        assert line in text
    assert r.json()["keys"]["anthropic_api_key"]["hint"] == "…0001"
    # leerer Anbieter = automatisch (anthropic, weil Key gesetzt)
    http.put("/settings", json={"llm_provider": ""})
    assert "LLM_PROVIDER=\n" in env_file.read_text(encoding="utf-8")
    assert client.settings.resolved_llm_provider() == "anthropic"


@pytest.mark.parametrize("body", [
    {"llm_provider": "gpt"}, {"anthropic_model": "claude-unknown"},
    {"anthropic_effort": "max"}, {"llm_monthly_budget_usd": -1},
])
def test_put_rejects_invalid_values(env, body):
    http, env_file, _ = env
    assert http.put("/settings", json=body).status_code == 422
    assert "ANTHROPIC" not in env_file.read_text(encoding="utf-8")


def test_invalid_put_applies_nothing_live(env):
    http, env_file, _ = env
    before = (client.settings.llm_provider, client.settings.openrouter_model)
    r = http.put("/settings", json={"openrouter_model": "a/b", "llm_provider": "openrouter", "anthropic_model": "claude-unknown"})
    assert r.status_code == 422
    assert (client.settings.llm_provider, client.settings.openrouter_model) == before
    assert "a/b" not in env_file.read_text(encoding="utf-8")


def test_month_costs_sum_current_month_per_provider(env):
    _, _, engine = env
    add_report(engine, "anthropic", 1.5)
    add_report(engine, "anthropic", 0.25, created=datetime(2026, 10, 1, 0, 0))
    add_report(engine, "anthropic", 9.0, created=datetime(2026, 9, 30, 23, 59))  # Vormonat
    add_report(engine, "openrouter", 0.1)
    add_report(engine, None, 0.2)  # Altbestand ohne Provider = OpenRouter
    add_report(engine, "anthropic", None)
    assert client.month_costs(NOW) == {"anthropic": 1.75, "openrouter": 0.3}


def test_warning_at_80_percent_and_exceeded_at_100(env):
    _, _, engine = env
    add_report(engine, "anthropic", 79.0)
    add_report(engine, "openrouter", 500.0)  # zaehlt nicht gegen das Anthropic-Budget
    status = client.budget_status(NOW)
    assert (status["warn"], status["exceeded"], status["ratio"]) == (False, False, 0.79)
    add_report(engine, "anthropic", 1.0)
    status = client.budget_status(NOW)
    assert (status["warn"], status["exceeded"], status["ratio"]) == (True, False, 0.8)
    add_report(engine, "anthropic", 20.0)
    status = client.budget_status(NOW)
    assert (status["warn"], status["exceeded"]) == (True, True)


def test_zero_budget_means_no_limit(env, monkeypatch):
    _, _, engine = env
    add_report(engine, "anthropic", 999.0)
    monkeypatch.setattr(client.settings, "llm_monthly_budget_usd", 0)
    status = client.budget_status(NOW)
    assert (status["warn"], status["exceeded"]) == (False, False)


def test_exhausted_budget_routes_to_openrouter_with_note(env, monkeypatch):
    _, _, engine = env
    add_report(engine, "anthropic", 100.0, created=datetime.now())
    monkeypatch.setattr(client.settings, "anthropic_api_key", "sk-test")
    assert client._skip_reason() == "budget"

    class Unused:
        def __getattr__(self, name):
            raise AssertionError("Anthropic darf bei ausgeschoepftem Budget nicht aufgerufen werden")

    monkeypatch.setattr(client, "_anthropic_client", lambda: Unused())
    monkeypatch.setattr(client, "_openrouter_complete", lambda m, t: ("Ausweich.", client._empty("openrouter", "m")))
    text, usage = client.complete([{"role": "user", "content": "Hallo"}])
    assert text == "Ausweich." and usage["provider"] == "openrouter" and usage["fallback_reason"] == "budget"


def test_budget_below_limit_keeps_anthropic(env, monkeypatch):
    _, _, engine = env
    add_report(engine, "anthropic", 99.0, created=datetime.now())
    monkeypatch.setattr(client.settings, "anthropic_api_key", "sk-test")
    assert client._skip_reason() is None


def test_unreadable_cost_statistics_do_not_block_anthropic(env, monkeypatch):
    http, _, _ = env
    monkeypatch.setattr(client.settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(client, "engine", create_engine("sqlite://"))  # leer, ohne Tabelle coach_reports
    assert client._skip_reason() is None
    body = http.get("/settings").json()
    assert body["llm_budget"]["exceeded"] is False and body["llm_budget"]["spent"] == {"anthropic": 0.0, "openrouter": 0.0}
