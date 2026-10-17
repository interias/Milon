"""Heldenreise (Gamification): Cockpit lesen, Wochentruhe wählen."""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .. import hero, hero_export, hero_world
from ..config import settings

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


SESSION_PATTERN = r"^[A-Za-z0-9_.:-]{1,64}$"


class LivePointInput(BaseModel):
    ts: float = Field(gt=0)  # epoch seconds or milliseconds (UTC)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    acc: float = Field(ge=0)  # GPS accuracy in m; > 100 m is dropped, not rejected


class LiveInput(BaseModel):
    session: str = Field(pattern=SESSION_PATTERN)
    points: list[LivePointInput] = Field(max_length=2000)


class LiveTargetInput(BaseModel):
    session: str | None = Field(default=None, pattern=SESSION_PATTERN)
    kind: str | None = Field(default=None, pattern="^(poi|dungeon)$")
    id: str | None = Field(default=None, max_length=80)


def live_token(x_hero_token: str | None = Header(default=None)) -> None:
    """Live endpoints: off (403) without HERO_LIVE_TOKEN, 401 for a missing or wrong X-Hero-Token."""
    token = settings.hero_live_token
    if not token:
        raise HTTPException(status_code=403, detail="Live-Schnittstelle ist aus (HERO_LIVE_TOKEN nicht gesetzt).")
    if not x_hero_token or not hmac.compare_digest(x_hero_token.encode(), token.encode()):
        raise HTTPException(status_code=401, detail="Ungültiger Live-Token.")


@router.post("/live", dependencies=[Depends(live_token)])
def live_points(body: LiveInput) -> dict:
    return hero_world.ingest_live(body.session, [p.model_dump() for p in body.points])


@router.get("/live/state", dependencies=[Depends(live_token)])
def live_state(session: str = Query(pattern=SESSION_PATTERN)) -> dict:
    return hero_world.live_state(session)


@router.post("/live/target", dependencies=[Depends(live_token)])
def live_target(body: LiveTargetInput) -> dict:
    if (body.kind is None) != (body.id is None):
        raise HTTPException(status_code=422, detail="kind und id nur gemeinsam angeben.")
    try:
        session = hero_world.set_live_target(body.session, body.kind, body.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unbekanntes Ziel.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"session": session, "kind": body.kind, "id": body.id}


@router.get("")
def get_hero() -> dict:
    return hero.overview()


@router.get("/world/tiles")
def world_tiles(x0: float, y0: float, x1: float, y1: float, px: int = Query(1000, ge=100, le=8000)) -> dict:
    return hero_world.tiles(x0, y0, x1, y1, px)


@router.get("/world/tile/{key}")
def world_tile(key: str) -> Response:
    try:
        data = hero_world.tile_png(key)
    except OSError as e:
        raise HTTPException(502, f"Kachel nicht ladbar: {e}") from e
    if data is None:
        raise HTTPException(404, "Kachel nicht im aufgedeckten Bereich")
    return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})


def _dungeon_file(key: str, ext: str) -> Response:
    route = hero_world.dungeon_route(key)
    if route is None:
        raise HTTPException(404, "Verlies unbekannt oder noch im Nebel")
    if ext == "gpx":
        data, media = hero_export.gpx_bytes(route), "application/gpx+xml"
    else:
        data, media = hero_export.fit_bytes(route), "application/vnd.ant.fit"
    name = f"{hero_export.file_stem(route['name'])}.{ext}"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/world/dungeon/{key}.gpx")
def dungeon_gpx(key: str) -> Response:
    return _dungeon_file(key, "gpx")


@router.get("/world/dungeon/{key}.fit")
def dungeon_fit(key: str) -> Response:
    return _dungeon_file(key, "fit")


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


@router.post("/mount")
def choose_mount(body: TitleInput) -> dict:
    try:
        hero.choose_mount(body.key)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail="Unbekanntes Reittier.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"key": body.key}


@router.get("/saga")
def get_saga() -> dict:
    from .. import hero_saga
    return {"saga": hero_saga.latest(), "week": hero_saga.saga_week(hero.local_today()).isoformat()}


@router.post("/saga")
def write_saga() -> dict:
    from .. import hero_saga
    try:
        return {"saga": hero_saga.generate(hero.overview(), hero.local_today())}
    except Exception as exc:  # noqa: BLE001 -- LLM/Netz/fehlender Key
        raise HTTPException(status_code=502, detail=f"Saga konnte nicht geschrieben werden: {exc}") from exc


@router.post("/sell")
def sell_item(body: EquipInput) -> dict:
    try:
        return {"gold": hero.sell(body.item_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Gegenstand nicht im Inventar.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class BuyInput(BaseModel):
    kind: str = Field(pattern="^(listing|potion)$")
    ref: str = Field(min_length=1, max_length=20)


class DrinkInput(BaseModel):
    key: str = Field(min_length=2, max_length=20)


@router.post("/buy")
def buy(body: BuyInput) -> dict:
    try:
        return hero.buy(body.kind, body.ref)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Angebot nicht gefunden.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/drink")
def drink(body: DrinkInput) -> dict:
    try:
        hero.drink(body.key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unbekannter Trank.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"key": body.key}
