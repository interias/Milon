"""Heldenreise (Gamification): Cockpit lesen, Wochentruhe wählen."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import hero

router = APIRouter(prefix="/hero", tags=["hero"])


class ClaimInput(BaseModel):
    week: str = Field(min_length=7, max_length=10)
    slot: int = Field(ge=0, le=2)


class EquipInput(BaseModel):
    item_id: str = Field(min_length=3, max_length=200)


class UnequipInput(BaseModel):
    slot: str = Field(min_length=2, max_length=20)


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


@router.post("/equip")
def equip_item(body: EquipInput) -> dict:
    try:
        return {"item": hero.equip(body.item_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Gegenstand nicht im Inventar.") from exc


@router.post("/unequip")
def unequip_slot(body: UnequipInput) -> dict:
    try:
        hero.unequip(body.slot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unbekannter Ausrüstungsplatz.") from exc
    return {"slot": body.slot}


@router.post("/equip-best")
def equip_best() -> dict:
    return {"equipped": hero.equip_best()}
