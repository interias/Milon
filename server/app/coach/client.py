"""LLM-Anbindung des Coaches: Claude (offizielles anthropic-SDK) als Standard, OpenRouter
(OpenAI-SDK mit anderer Base-URL) als Ausweichweg. Anbieter per LLM_PROVIDER, siehe config.
Erfasst Token-/Kosten-Usage fuer die Coach-Statistik; beide Anbieter liefern dieselbe Form:
usage = {prompt_tokens, completion_tokens, cost, cache_read_tokens, provider, model, fallback_reason}."""
from __future__ import annotations

import json

import anthropic
from openai import OpenAI

from ..config import settings

BASE_URL = "https://openrouter.ai/api/v1"
_EXTRA = {"usage": {"include": True}}  # OpenRouter liefert damit die Kosten im usage-Objekt

# USD pro Mio. Token. Cache-Write (5 min TTL) = 1,25 x Input. Haiku-Preise gelten bis 100K Prompt-Token.
PRICES = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
}
MAX_TOKENS = 16000


class AnthropicFailed(Exception):
    """Anthropic-Aufruf gescheitert, der Rueckfall auf OpenRouter greift. `usage` = bereits angefallene Kosten."""

    def __init__(self, reason: str, usage: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.usage = usage


def _empty(provider: str, model: str) -> dict:
    return {"prompt_tokens": 0, "completion_tokens": 0, "cost": None, "cache_read_tokens": 0,
            "provider": provider, "model": model, "fallback_reason": None}


def _add(a: dict, b: dict) -> dict:
    cost = None
    if a.get("cost") is not None or b.get("cost") is not None:
        cost = (a.get("cost") or 0) + (b.get("cost") or 0)
    return {
        **a,
        "prompt_tokens": a["prompt_tokens"] + b["prompt_tokens"],
        "completion_tokens": a["completion_tokens"] + b["completion_tokens"],
        "cost": cost,
        "cache_read_tokens": a.get("cache_read_tokens", 0) + b.get("cache_read_tokens", 0),
    }


# --- OpenRouter -------------------------------------------------------------------------

def _client() -> OpenAI:
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY fehlt in server/.env")
    return OpenAI(
        base_url=BASE_URL,
        api_key=settings.openrouter_api_key,
        default_headers={"HTTP-Referer": "http://localhost:3000", "X-Title": "Milon"},
    )


def _usage(resp) -> dict:
    try:
        u = resp.model_dump().get("usage") or {}
    except Exception:  # noqa: BLE001
        u = {}
    return {
        **_empty("openrouter", settings.openrouter_model),
        "prompt_tokens": int(u.get("prompt_tokens") or 0),
        "completion_tokens": int(u.get("completion_tokens") or 0),
        "cost": u.get("cost"),  # USD, kann None sein wenn der Provider es nicht liefert
    }


def _request_options(temperature: float) -> dict:
    if settings.openrouter_model == "openai/gpt-6-luna":
        # GPT-6 Luna requires reasoning off for Chat Completions function calling.
        return {"reasoning_effort": "none", "extra_body": {**_EXTRA, "verbosity": "low"}}
    return {"temperature": temperature, "extra_body": _EXTRA}


def _openrouter_complete(messages: list[dict], temperature: float) -> tuple[str, dict]:
    client = _client()
    resp = client.chat.completions.create(
        model=settings.openrouter_model, messages=messages, **_request_options(temperature),
    )
    return (resp.choices[0].message.content or "").strip(), _usage(resp)


def _openrouter_tools(messages: list[dict], tools: list[dict], dispatch,
                      max_rounds: int, temperature: float) -> tuple[str, list[dict], list[dict], dict]:
    client = _client()
    used: list[dict] = []
    total = _empty("openrouter", settings.openrouter_model)
    for _ in range(max_rounds):
        resp = client.chat.completions.create(
            model=settings.openrouter_model, messages=messages,
            tools=tools, tool_choice="auto", **_request_options(temperature),
        )
        total = _add(total, _usage(resp))
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return (msg.content or "").strip(), used, messages, total
        messages.append({
            "role": "assistant", "content": msg.content or "",
            "tool_calls": [{"id": tc.id, "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                           for tc in msg.tool_calls],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _run_tool(dispatch, tc.function.name, args)
            used.append({"name": tc.function.name, "args": args})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    resp = client.chat.completions.create(
        model=settings.openrouter_model, messages=messages, **_request_options(temperature),
    )
    total = _add(total, _usage(resp))
    return (resp.choices[0].message.content or "").strip(), used, messages, total


# --- Anthropic --------------------------------------------------------------------------

def _anthropic_client() -> anthropic.Anthropic:
    # Kurzer Timeout, kein SDK-Retry: 429/5xx/Timeout fallen ohnehin auf OpenRouter zurueck, bevor der Next-Proxy (120 s) abbricht.
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=60.0, max_retries=0)


def _skip_reason() -> str | None:
    """Grund, Anthropic gar nicht erst zu versuchen (Einhaengepunkt z. B. fuer ein Budget-Limit)."""
    if not settings.anthropic_api_key:
        return "no_key"
    return None


def _failure_reason(exc: Exception) -> str | None:
    """Fehlerarten, bei denen derselbe Aufruf ueber OpenRouter laeuft; None = echter Fehler, weiterreichen."""
    if isinstance(exc, anthropic.APITimeoutError):
        return "timeout"
    if isinstance(exc, anthropic.APIConnectionError):
        return "connection"
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return "auth"
    if isinstance(exc, anthropic.RateLimitError):
        return "rate_limit"
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code == 402 or getattr(exc, "type", None) == "billing_error":
            return "billing"
        if exc.status_code >= 500:
            return "server_error"
    return None


def _cost(model: str, u) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    return (u.input_tokens * price["input"] + u.output_tokens * price["output"]
            + (u.cache_read_input_tokens or 0) * price["cache_read"]
            + (u.cache_creation_input_tokens or 0) * price["cache_write"]) / 1_000_000


def _anthropic_usage(resp) -> dict:
    u = resp.usage
    read = u.cache_read_input_tokens or 0
    return {
        **_empty("anthropic", settings.anthropic_model),
        # prompt_tokens = gesamter Prompt (ungecacht + Cache-Write + Cache-Read), wie bei OpenRouter
        "prompt_tokens": u.input_tokens + (u.cache_creation_input_tokens or 0) + read,
        "completion_tokens": u.output_tokens,
        "cost": _cost(settings.anthropic_model, u),
        "cache_read_tokens": read,
    }


def _to_anthropic(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """OpenAI-Messages -> (system-Bloecke, messages). Der letzte System-Block (Datensnapshot bzw.
    System-Prompt) bekommt den Cache-Breakpoint: tools + system werden so gecacht."""
    system = [{"type": "text", "text": m["content"]} for m in messages if m["role"] == "system" and m.get("content")]
    if system:
        system[-1]["cache_control"] = {"type": "ephemeral"}
    turns = [{"role": m["role"], "content": m["content"]} for m in messages
             if m["role"] in ("user", "assistant") and m.get("content")]
    while turns and turns[0]["role"] != "user":  # Anthropic verlangt eine User-Nachricht am Anfang
        turns.pop(0)
    return system, turns


def _anthropic_tools(tools: list[dict]) -> list[dict]:
    return [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
             "input_schema": t["function"].get("parameters") or {"type": "object", "properties": {}}}
            for t in tools]


def _text(resp) -> str:
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _anthropic_create(client, spent: dict, **kwargs):
    try:
        resp = client.messages.create(
            model=settings.anthropic_model, max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"}, output_config={"effort": settings.anthropic_effort}, **kwargs,
        )
    except anthropic.APIError as e:
        reason = _failure_reason(e)
        if reason is None:
            raise
        raise AnthropicFailed(reason, spent) from e
    spent = _add(spent, _anthropic_usage(resp))
    if resp.stop_reason == "refusal":
        raise AnthropicFailed("refusal", spent)
    return resp, spent


def _anthropic_complete(messages: list[dict]) -> tuple[str, dict]:
    system, turns = _to_anthropic(messages)
    resp, total = _anthropic_create(_anthropic_client(), _empty("anthropic", settings.anthropic_model),
                                    system=system, messages=turns)
    return _text(resp), total


def _anthropic_tool_loop(messages: list[dict], tools: list[dict], dispatch,
                         max_rounds: int) -> tuple[str, list[dict], list[dict], dict]:
    """Tool-Loop ueber Anthropic-Tool-Use. `messages` (OpenAI-Form) wird als Trace fortgeschrieben,
    damit Prompt + Tool-Trace in coach_reports dieselbe Form haben wie bei OpenRouter."""
    client = _anthropic_client()
    system, turns = _to_anthropic(messages)
    schema = _anthropic_tools(tools)
    used: list[dict] = []
    total = _empty("anthropic", settings.anthropic_model)
    # Auto-Breakpoint am Ende: im Loop liest jede Runde die vorige aus dem Cache.
    params = {"system": system, "tools": schema, "cache_control": {"type": "ephemeral"}} if schema \
        else {"system": system}
    for _ in range(max_rounds):
        resp, total = _anthropic_create(client, total, messages=turns, **params)
        calls = [b for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason != "tool_use" or not calls:
            return _text(resp), used, messages, total
        turns.append({"role": "assistant", "content": resp.content})  # inkl. Thinking-Bloecke unveraendert
        messages.append({
            "role": "assistant", "content": _text(resp),
            "tool_calls": [{"id": b.id, "type": "function",
                            "function": {"name": b.name, "arguments": json.dumps(b.input, ensure_ascii=False)}}
                           for b in calls],
        })
        results = []
        for b in calls:
            args = b.input if isinstance(b.input, dict) else {}
            result = _run_tool(dispatch, b.name, args)
            used.append({"name": b.name, "args": args})
            messages.append({"role": "tool", "tool_call_id": b.id, "content": result})
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": result})
        turns.append({"role": "user", "content": results})  # alle Ergebnisse in EINER Nachricht
    final = {**params, "tool_choice": {"type": "none"}} if schema else params
    resp, total = _anthropic_create(client, total, messages=turns, **final)
    return _text(resp), used, messages, total


# --- Gemeinsame Schnittstelle -----------------------------------------------------------

def _run_tool(dispatch, name: str, args: dict) -> str:
    try:
        result = dispatch(name, args)
    except Exception as e:  # noqa: BLE001
        result = {"error": str(e)}
    return json.dumps(result, ensure_ascii=False, default=str)


def current_model() -> str:
    """Modell des konfigurierten Anbieters (ohne Rueckfall)."""
    return settings.anthropic_model if settings.resolved_llm_provider() == "anthropic" else settings.openrouter_model


def report_fields(usage: dict) -> dict:
    """usage -> CoachReport-Felder (Anbieter, Modell, Rueckfall, Token, Kosten)."""
    return {"provider": usage.get("provider"), "model": usage.get("model"),
            "fallback_reason": usage.get("fallback_reason"),
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "cache_read_tokens": usage.get("cache_read_tokens"), "cost_usd": usage.get("cost")}


def _with_fallback(primary, fallback):
    """Anthropic zuerst (falls gewaehlt), bei Ausfall derselbe Aufruf ueber OpenRouter.
    Das Ergebnis-Tupel endet immer mit dem usage-Dict; der Rueckfall wird dort vermerkt."""
    if settings.resolved_llm_provider() != "anthropic":
        return fallback()
    reason, spent = _skip_reason(), None
    if reason is None:
        try:
            return primary()
        except AnthropicFailed as e:
            reason, spent = e.reason, e.usage
    result = fallback()
    usage = result[-1]
    if spent:  # bereits angefallene Anthropic-Runden (Token + Kosten) mitzaehlen
        usage = _add(usage, spent)
    usage["fallback_reason"] = reason
    return (*result[:-1], usage)


def complete(messages: list[dict], temperature: float = 0.4) -> tuple[str, dict]:
    """Einzelner Aufruf. `temperature` gilt nur fuer OpenRouter (Claude mit Thinking nimmt keine an)."""
    return _with_fallback(lambda: _anthropic_complete(messages),
                          lambda: _openrouter_complete(messages, temperature))


def complete_with_tools(messages: list[dict], tools: list[dict], dispatch,
                        max_rounds: int = 5, temperature: float = 0.4) -> tuple[str, list[dict], list[dict], dict]:
    """Tool-Loop: LLM -> Tool-Calls ausfuehren -> Ergebnisse zurueck -> ... bis finale Antwort.
    Liefert (antwort, genutzte_tools, vollstaendige_messages, usage)."""
    original = list(messages)
    return _with_fallback(lambda: _anthropic_tool_loop(list(original), tools, dispatch, max_rounds),
                          lambda: _openrouter_tools(list(original), tools, dispatch, max_rounds, temperature))
