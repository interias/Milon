"""Heldenreise (Gamification): Cockpit lesen, Wochentruhe wählen."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import hero

router = APIRouter(prefix="/hero", tags=["hero"])


class ClaimInput(BaseModel):
    week: str = Field(min_length=7, max_length=10)
    slot: int = Field(ge=0, le=2)


@router.get("")
def get_hero() -> dict:
    return hero.overview()


@router.post("/vault/claim")
def claim_vault(body: ClaimInput) -> dict:
    try:
        item = hero.claim(body.week, body.slot)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="Diese Truhe wurde bereits geöffnet.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"item": item}
