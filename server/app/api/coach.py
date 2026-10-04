"""Coach-Endpunkte (Context-Injection): täglicher/wöchentlicher Report + Chat.
Ergebnisse werden in coach_reports gespeichert."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlmodel import Session

from ..coach import client, prompts, snapshot, tools, visuals
from ..db import engine
from ..models import CoachReport

router = APIRouter(prefix="/coach", tags=["coach"])


class ChatIn(BaseModel):
    message: str
    history: list[dict] | None = None


class ImageIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)

    @field_validator("prompt")
    @classmethod
    def trim_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Bitte ein Motiv eingeben.")
        return value.strip()


def _generate(kind: str, user_msg: str | None = None, history: list[dict] | None = None) -> dict:
    snap = snapshot.snapshot_text()
    messages = prompts.build_messages(kind, snap, user_msg=user_msg, history=history)
    try:
        content, usage = client.complete(messages)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Coach/LLM fehlgeschlagen: {e}")

    charts = visuals.build_visuals(kind, user_msg or "")
    with Session(engine) as s:
        from ..config import settings
        report = CoachReport(
            created_at=datetime.now(),
            kind=kind,
            content=content,
            prompt=json.dumps(messages, ensure_ascii=False),  # Prompt fuer spaetere Analyse
            model=settings.openrouter_model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            cost_usd=usage.get("cost"),
            visuals=json.dumps(charts, ensure_ascii=False),
        )
        s.add(report)
        s.commit()
        s.refresh(report)
        return {"id": report.id, "kind": kind, "content": content,
                "model": report.model, "created_at": report.created_at.isoformat(),
                "cost_usd": report.cost_usd, "visuals": charts}


@router.post("/daily")
def daily() -> dict:
    return _generate("daily")


@router.post("/weekly")
def weekly() -> dict:
    return _generate("weekly")


@router.post("/chat")
def chat(body: ChatIn) -> dict:
    return _generate("chat", user_msg=body.message, history=body.history)


@router.post("/ask")
def ask(body: ChatIn) -> dict:
    """Tool-Calling-Coach: das LLM ruft die Metrik-Tools selbst auf, bevor es antwortet (Phase 2b)."""
    system = (prompts.system_prompt() + "\n\nDu hast Werkzeuge, um die echten Kennzahlen abzufragen. "
              "Nutze sie gezielt, bevor du antwortest; erfinde keine Werte.")
    messages: list[dict] = [{"role": "system", "content": system}]
    for h in (body.history or []):
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": body.message})
    try:
        content, used, full, usage = client.complete_with_tools(messages, tools.TOOLS, tools.dispatch)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Coach/Tools fehlgeschlagen: {e}")
    charts = visuals.build_visuals("chat-tools", body.message, used)
    with Session(engine) as s:
        from ..config import settings
        rep = CoachReport(
            created_at=datetime.now(), kind="chat-tools", content=content,
            prompt=json.dumps(full, ensure_ascii=False, default=str), model=settings.openrouter_model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            cost_usd=usage.get("cost"),
            visuals=json.dumps(charts, ensure_ascii=False),
        )
        s.add(rep)
        s.commit()
        s.refresh(rep)
        return {"id": rep.id, "kind": rep.kind, "content": content,
                "tools_used": [u["name"] for u in used],
                "model": rep.model, "created_at": rep.created_at.isoformat(),
                "cost_usd": rep.cost_usd, "visuals": charts}


@router.post("/images")
def create_image(body: ImageIn) -> dict:
    try:
        return visuals.generate_image(body.prompt)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        detail = str(exc) if isinstance(exc, ValueError) else "Bildgenerierung fehlgeschlagen; bitte erneut versuchen."
        raise HTTPException(status_code=502, detail=detail) from exc


@router.get("/reports")
def reports(limit: int = 10) -> list[dict]:
    with Session(engine) as s:
        rows = s.execute(
            select(CoachReport).order_by(CoachReport.created_at.desc()).limit(limit)
        ).scalars().all()
        return [
            {"id": r.id, "kind": r.kind, "content": r.content, "model": r.model,
             "created_at": r.created_at.isoformat(), "cost_usd": r.cost_usd,
             "visuals": visuals.parse_visuals(r.visuals)}
            for r in rows
        ]


@router.get("/reports/{report_id}")
def report_detail(report_id: int) -> dict:
    """Voller Report inkl. gespeichertem Prompt (fuer Analyse)."""
    with Session(engine) as s:
        r = s.get(CoachReport, report_id)
        if not r:
            raise HTTPException(status_code=404, detail="Report nicht gefunden")
        return {"id": r.id, "kind": r.kind, "content": r.content, "prompt": r.prompt,
                "model": r.model, "created_at": r.created_at.isoformat(), "cost_usd": r.cost_usd,
                "visuals": visuals.parse_visuals(r.visuals)}


@router.get("/stats")
def stats() -> dict:
    """Kosten/Token-Statistik (OpenRouter) ueber alle Coach-Reports."""
    from ..config import settings
    with Session(engine) as s:
        rows = s.execute(select(CoachReport)).scalars().all()
    cutoff = datetime.now() - timedelta(days=7)
    last7 = [r for r in rows if r.created_at and r.created_at >= cutoff]

    def _cost(rs):
        return round(sum(r.cost_usd or 0 for r in rs), 4)

    def _tok(rs):
        return sum((r.prompt_tokens or 0) + (r.completion_tokens or 0) for r in rs)

    return {
        "model": settings.openrouter_model,
        "reports_total": len(rows),
        "tokens_total": _tok(rows),
        "cost_total_usd": _cost(rows),
        "cost_known": any(r.cost_usd is not None for r in rows),
        "reports_7d": len(last7),
        "cost_7d_usd": _cost(last7),
        "tokens_7d": _tok(last7),
    }


@router.get("/snapshot")
def snapshot_preview() -> dict:
    return {"text": snapshot.snapshot_text(), "data": snapshot.build_snapshot()}
