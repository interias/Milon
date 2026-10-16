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


class SpecInput(BaseModel):
    spec: str | None = Field(default=None, max_length=20)


class TalentInput(BaseModel):
    row: int = Field(ge=10, le=80)
    choice: str | None = Field(default=None, max_length=30)


class TitleInput(BaseModel):
    key: str | None = Field(default=None, max_length=40)


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


@router.post("/spec")
def choose_spec(body: SpecInput) -> dict:
    try:
        hero.choose_spec(body.spec)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail="Unbekannte Spezialisierung.") from exc
    return {"spec": body.spec}


@router.post("/talent")
def choose_talent(body: TalentInput) -> dict:
    try:
        hero.choose_talent(body.row, body.choice)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail="Unbekanntes Talent.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"row": body.row, "choice": body.choice}


@router.post("/title")
def choose_title(body: TitleInput) -> dict:
    try:
        hero.choose_title(body.key)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail="Unbekannter Titel.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"key": body.key}


@router.post("/disenchant")
def disenchant_item(body: EquipInput) -> dict:
    try:
        return {"dust": hero.disenchant(body.item_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Gegenstand nicht im Inventar.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/upgrade")
def upgrade_item(body: EquipInput) -> dict:
    try:
        return {"item": hero.upgrade(body.item_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Gegenstand nicht im Inventar.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
