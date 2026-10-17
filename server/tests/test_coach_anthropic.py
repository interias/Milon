from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app import db
from app.api import coach as coach_api
from app.coach import client
from app.models import CoachReport

TOOLS = [{"type": "function", "function": {
    "name": "get_weight_trend", "description": "Gewicht",
    "parameters": {"type": "object", "properties": {"days": {"type": "integer"}}, "required": []}}}]
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def usage(input_tokens=100, output_tokens=20, read=0, write=0):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           cache_read_input_tokens=read, cache_creation_input_tokens=write)


def message(*blocks, stop_reason="end_turn", u=None):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=u or usage())


def text_block(value="Kurz und belegt."):
    return SimpleNamespace(type="text", text=value)


def thinking_block():
    return SimpleNamespace(type="thinking", thinking="", signature="sig-1")


def tool_block(id_="toolu_1", name="get_weight_trend", input_=None):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_ if input_ is not None else {"days": 7})


class FakeAnthropic:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


class FakeOpenRouter:
    def __init__(self, content="Ausweichantwort."):
        self.calls = []
        self.content = content
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content, tool_calls=None))],
            model_dump=lambda: {"usage": {"prompt_tokens": 50, "completion_tokens": 10, "cost": 0.0005}})


@pytest.fixture
def providers(monkeypatch):
    def install(anthropic_responses=(), key="sk-test"):
        fake_a, fake_o = FakeAnthropic(anthropic_responses), FakeOpenRouter()
        monkeypatch.setattr(client.settings, "anthropic_api_key", key)
        monkeypatch.setattr(client.settings, "anthropic_model", "claude-opus-5-5")
        monkeypatch.setattr(client.settings, "anthropic_effort", "medium")
        monkeypatch.setattr(client.settings, "openrouter_model", "deepseek/deepseek-v4-flash-0731")
        monkeypatch.setattr(client, "_anthropic_client", lambda: fake_a)
        monkeypatch.setattr(client, "_client", lambda: fake_o)
        return fake_a, fake_o
    return install


def status_error(cls, status, body=None):
    return cls("boom", response=httpx2.Response(status, request=REQUEST), body=body)


@pytest.mark.parametrize("configured,key,expected", [
    ("", "sk-test", "anthropic"), ("", "", "openrouter"),
    ("openrouter", "sk-test", "openrouter"), ("ANTHROPIC", "", "anthropic"),
])
def test_provider_choice(monkeypatch, configured, key, expected):
    monkeypatch.setattr(client.settings, "llm_provider", configured)
    monkeypatch.setattr(client.settings, "anthropic_api_key", key)
    assert client.settings.resolved_llm_provider() == expected


def test_both_providers_return_the_same_shape(providers, monkeypatch):
    fake_a, _ = providers([message(thinking_block(), text_block())])
    msgs = [{"role": "system", "content": "SYS"}, {"role": "system", "content": "SNAPSHOT"},
            {"role": "user", "content": "Mein Trend?"}]
    a_text, a_usage = client.complete(msgs)
    monkeypatch.setattr(client.settings, "llm_provider", "openrouter")
    o_text, o_usage = client.complete(msgs)
    assert a_text == "Kurz und belegt." and o_text == "Ausweichantwort."
    assert a_usage.keys() == o_usage.keys()
    assert (a_usage["provider"], a_usage["model"], a_usage["fallback_reason"]) == ("anthropic", "claude-opus-5-5", None)
    assert (o_usage["provider"], o_usage["fallback_reason"]) == ("openrouter", None)
    call = fake_a.calls[0]
    assert call["system"] == [{"type": "text", "text": "SYS"},
                              {"type": "text", "text": "SNAPSHOT", "cache_control": {"type": "ephemeral"}}]
    assert call["messages"] == [{"role": "user", "content": "Mein Trend?"}]
    assert call["thinking"] == {"type": "adaptive"} and call["output_config"] == {"effort": "medium"}
    assert "temperature" not in call


def test_tool_loop_runs_over_anthropic_tool_use(providers):
    thinking = thinking_block()
    fake_a, fake_o = providers([
        message(thinking, tool_block("t1"), tool_block("t2", input_={"days": 30}), stop_reason="tool_use"),
        message(text_block("72 kg im Mittel."), u=usage(read=900)),
    ])
    calls = []

    def dispatch(name, args):
        calls.append((name, args))
        return {"weight": 72}

    answer, used, trace, total = client.complete_with_tools(
        [{"role": "system", "content": "SYS"}, {"role": "user", "content": "Gewicht?"}], TOOLS, dispatch)
    assert answer == "72 kg im Mittel."
    assert used == [{"name": "get_weight_trend", "args": {"days": 7}},
                    {"name": "get_weight_trend", "args": {"days": 30}}]
    assert not fake_o.calls
    first, second = fake_a.calls
    assert first["tools"] == [{"name": "get_weight_trend", "description": "Gewicht",
                               "input_schema": TOOLS[0]["function"]["parameters"]}]
    assert first["cache_control"] == {"type": "ephemeral"} and "tool_choice" not in first
    assistant, results = second["messages"][1:]
    assert assistant["content"][0] is thinking  # thinking blocks go back unchanged
    assert [r["tool_use_id"] for r in results["content"]] == ["t1", "t2"]
    assert all(r["type"] == "tool_result" and '"weight": 72' in r["content"] for r in results["content"])
    # Trace keeps the OpenAI form stored in coach_reports.prompt
    assert trace[2]["role"] == "assistant" and trace[2]["tool_calls"][1]["function"]["arguments"] == '{"days": 30}'
    assert [m["role"] for m in trace[3:]] == ["tool", "tool"]
    assert total["prompt_tokens"] == 100 + 1000 and total["cache_read_tokens"] == 900


def test_tool_limit_final_request_disables_tools(providers):
    fake_a, _ = providers([message(tool_block(), stop_reason="tool_use"), message(text_block())])
    client.complete_with_tools([{"role": "user", "content": "Hallo"}], TOOLS, lambda *_: {}, max_rounds=1)
    assert fake_a.calls[-1]["tool_choice"] == {"type": "none"}


@pytest.mark.parametrize("error,reason", [
    (lambda: status_error(anthropic.AuthenticationError, 401), "auth"),
    (lambda: status_error(anthropic.PermissionDeniedError, 403), "auth"),
    (lambda: status_error(anthropic.APIStatusError, 402, {"type": "error", "error": {"type": "billing_error"}}), "billing"),
    (lambda: status_error(anthropic.RateLimitError, 429), "rate_limit"),
    (lambda: status_error(anthropic.InternalServerError, 500), "server_error"),
    (lambda: status_error(anthropic.OverloadedError, 529), "server_error"),
    (lambda: anthropic.APITimeoutError(request=REQUEST), "timeout"),
    (lambda: anthropic.APIConnectionError(request=REQUEST), "connection"),
    (lambda: message(text_block(""), stop_reason="refusal"), "refusal"),
])
def test_failures_fall_back_to_openrouter(providers, error, reason):
    fake_a, fake_o = providers([error()])
    content, used_usage = client.complete([{"role": "user", "content": "Hallo"}])
    assert content == "Ausweichantwort." and len(fake_o.calls) == 1
    assert used_usage["provider"] == "openrouter" and used_usage["fallback_reason"] == reason
    if reason == "refusal":  # the declined Anthropic call was billed and is counted
        assert used_usage["cost"] == pytest.approx(0.0005 + (100 * 4 + 20 * 20) / 1e6)


def test_tool_loop_falls_back_with_the_same_call(providers):
    fake_a, fake_o = providers([message(tool_block(), stop_reason="tool_use"),
                                status_error(anthropic.RateLimitError, 429)])
    answer, used, trace, total = client.complete_with_tools(
        [{"role": "system", "content": "SYS"}, {"role": "user", "content": "Gewicht?"}], TOOLS, lambda *_: {"w": 1})
    assert answer == "Ausweichantwort." and used == []
    assert fake_o.calls[0]["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "Gewicht?"}]
    assert total["fallback_reason"] == "rate_limit" and total["prompt_tokens"] == 50 + 100


def test_bad_request_is_not_hidden_by_a_fallback(providers):
    providers([status_error(anthropic.BadRequestError, 400)])
    with pytest.raises(anthropic.BadRequestError):
        client.complete([{"role": "user", "content": "Hallo"}])


def test_missing_key_with_explicit_anthropic_falls_back(providers, monkeypatch):
    fake_a, fake_o = providers(key="")
    monkeypatch.setattr(client.settings, "llm_provider", "anthropic")
    _, used_usage = client.complete([{"role": "user", "content": "Hallo"}])
    assert not fake_a.calls and used_usage["fallback_reason"] == "no_key"


def test_cost_uses_model_prices_including_cache(providers):
    providers([message(text_block(), u=usage(input_tokens=1000, output_tokens=500, read=10_000, write=2000))])
    _, u = client.complete([{"role": "system", "content": "SYS"}, {"role": "user", "content": "Hallo"}])
    assert u["cost"] == pytest.approx((1000 * 4 + 500 * 20 + 10_000 * 0.20 + 2000 * 5.0) / 1e6)
    assert u["prompt_tokens"] == 13_000 and u["completion_tokens"] == 500 and u["cache_read_tokens"] == 10_000


def test_unknown_model_has_no_invented_cost(providers, monkeypatch):
    providers([message(text_block())])
    monkeypatch.setattr(client.settings, "anthropic_model", "claude-unknown")
    assert client.complete([{"role": "user", "content": "Hallo"}])[1]["cost"] is None


def test_leading_assistant_history_is_dropped_for_anthropic():
    system, turns = client._to_anthropic([{"role": "system", "content": "S"}, {"role": "assistant", "content": "Hi"},
                                          {"role": "user", "content": "Frage"}])
    assert turns == [{"role": "user", "content": "Frage"}]


def test_ask_stores_provider_model_fallback_and_cache(tmp_path, monkeypatch, providers):
    engine = create_engine(f"sqlite:///{tmp_path / 'coach.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(coach_api, "engine", engine)
    monkeypatch.setattr(coach_api.prompts, "system_prompt", lambda: "SYS")
    monkeypatch.setattr(coach_api.visuals, "build_visuals", lambda *a, **k: [])
    providers([message(text_block("Antwort."), u=usage(read=800))])
    app = FastAPI()
    app.include_router(coach_api.router)
    body = TestClient(app).post("/coach/ask", json={"message": "Wie stehe ich?"}).json()
    assert body["provider"] == "anthropic" and body["fallback_reason"] is None
    with Session(engine) as s:
        row = s.exec(select(CoachReport)).one()
    assert (row.provider, row.model, row.cache_read_tokens, row.prompt_tokens) == ("anthropic", "claude-opus-5-5", 800, 900)
    assert row.cost_usd == pytest.approx((100 * 4 + 20 * 20 + 800 * 0.20) / 1e6)
    assert '"Wie stehe ich?"' in row.prompt
    engine.dispose()


def test_migration_adds_report_columns(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    monkeypatch.setattr(db, "engine", engine)
    SQLModel.metadata.create_all(engine)
    with engine.begin() as con:
        for col in ("provider", "fallback_reason", "cache_read_tokens"):
            con.execute(text(f"ALTER TABLE coach_reports DROP COLUMN {col}"))
    db._run_migrations()
    with engine.begin() as con:
        cols = {row[1] for row in con.exec_driver_sql("PRAGMA table_info(coach_reports)").fetchall()}
    assert {"provider", "fallback_reason", "cache_read_tokens"} <= cols
    engine.dispose()
