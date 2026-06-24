"""OpenRouter-Anbindung (OpenAI-SDK mit anderer Base-URL). Modell aus server/.env.
Erfasst Token-/Kosten-Usage (OpenRouter `usage.include`) fuer die Coach-Statistik."""
from __future__ import annotations

import json

from openai import OpenAI

from ..config import settings

BASE_URL = "https://openrouter.ai/api/v1"
_EXTRA = {"usage": {"include": True}}  # OpenRouter liefert damit die Kosten im usage-Objekt


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
        "prompt_tokens": int(u.get("prompt_tokens") or 0),
        "completion_tokens": int(u.get("completion_tokens") or 0),
        "cost": u.get("cost"),  # USD, kann None sein wenn der Provider es nicht liefert
    }


def _add(a: dict, b: dict) -> dict:
    cost = None
    if a.get("cost") is not None or b.get("cost") is not None:
        cost = (a.get("cost") or 0) + (b.get("cost") or 0)
    return {
        "prompt_tokens": a["prompt_tokens"] + b["prompt_tokens"],
        "completion_tokens": a["completion_tokens"] + b["completion_tokens"],
        "cost": cost,
    }


def complete(messages: list[dict], temperature: float = 0.4) -> tuple[str, dict]:
    client = _client()
    resp = client.chat.completions.create(
        model=settings.openrouter_model, messages=messages, temperature=temperature, extra_body=_EXTRA,
    )
    return (resp.choices[0].message.content or "").strip(), _usage(resp)


def complete_with_tools(messages: list[dict], tools: list[dict], dispatch,
                        max_rounds: int = 5, temperature: float = 0.4) -> tuple[str, list[dict], list[dict], dict]:
    """Tool-Loop: LLM -> Tool-Calls ausfuehren -> Ergebnisse zurueck -> ... bis finale Antwort.
    Liefert (antwort, genutzte_tools, vollstaendige_messages, usage)."""
    client = _client()
    used: list[dict] = []
    total = {"prompt_tokens": 0, "completion_tokens": 0, "cost": None}
    for _ in range(max_rounds):
        resp = client.chat.completions.create(
            model=settings.openrouter_model, messages=messages,
            tools=tools, tool_choice="auto", temperature=temperature, extra_body=_EXTRA,
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
            try:
                result = dispatch(tc.function.name, args)
            except Exception as e:  # noqa: BLE001
                result = {"error": str(e)}
            used.append({"name": tc.function.name, "args": args})
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, ensure_ascii=False, default=str)})
    resp = client.chat.completions.create(
        model=settings.openrouter_model, messages=messages, temperature=temperature, extra_body=_EXTRA,
    )
    total = _add(total, _usage(resp))
    return (resp.choices[0].message.content or "").strip(), used, messages, total
