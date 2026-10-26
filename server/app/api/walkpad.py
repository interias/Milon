"""Walking pad: sessions from the host recorder (token-guarded) + overview for the UI."""
from __future__ import annotations

import hmac
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from .. import walkpad
from ..config import settings
from ..ingest import garmin

router = APIRouter(prefix="/walkpad", tags=["walkpad"])


class InclineInput(BaseModel):
    incline_pct: float = Field(ge=0, le=15)


class ManualInput(BaseModel):
    started_at: datetime  # local wall time
    minutes: float = Field(ge=2, le=720)
    speed_kmh: float = Field(ge=0.5, le=8)
    incline_pct: float | None = Field(default=None, ge=0, le=15)


def recorder_token(x_walkpad_token: str | None = Header(default=None)) -> None:
    """Off (403) without WALKPAD_TOKEN, 401 for a missing or wrong X-Walkpad-Token."""
    token = settings.walkpad_token
    if not token:
        raise HTTPException(status_code=403, detail="Laufband-Schnittstelle ist aus (WALKPAD_TOKEN nicht gesetzt).")
    if not x_walkpad_token or not hmac.compare_digest(x_walkpad_token.encode(), token.encode()):
        raise HTTPException(status_code=401, detail="Ungültiger Laufband-Token.")


@router.post("/sessions", dependencies=[Depends(recorder_token)])
def post_session(background: BackgroundTasks, payload: dict[str, Any] = Body(...)) -> dict:
    try:
        session, created = walkpad.ingest(payload)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    if created and session["garmin_status"] is None:
        background.add_task(garmin.upload_walkpad)
    return {"created": created, "session": session}


@router.post("/manual")
def post_manual(body: ManualInput, background: BackgroundTasks) -> dict:
    try:
        session = walkpad.add_manual(body.started_at, body.minutes, body.speed_kmh, body.incline_pct)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    if session["garmin_status"] is None:
        background.add_task(garmin.upload_walkpad)
    return session


@router.delete("/sessions/{sid}")
def delete_session(sid: str) -> dict:
    done = walkpad.delete_manual(sid)
    if done is None:
        raise HTTPException(404, "Unbekannte Session")
    if not done:
        raise HTTPException(409, "Nur manuell eingetragene Walks lassen sich löschen.")
    return {"deleted": sid}


@router.get("")
def overview(weeks: int = 12) -> dict:
    return walkpad.overview(weeks=max(1, min(weeks, 104)))


@router.get("/sessions/{sid}")
def session_detail(sid: str) -> dict:
    out = walkpad.detail(sid)
    if out is None:
        raise HTTPException(404, "Unbekannte Session")
    return out


@router.put("/sessions/{sid}/incline")
def put_incline(sid: str, body: InclineInput) -> dict:
    out = walkpad.set_incline(sid, body.incline_pct)
    if out is None:
        raise HTTPException(404, "Unbekannte Session")
    return out
