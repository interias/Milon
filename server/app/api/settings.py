"""Einstellungen: liest/schreibt die Konfiguration (server/.env) zur Laufzeit.
Secrets werden maskiert ausgegeben; PUT aktualisiert nur übergebene, nicht-leere Werte
(live im Settings-Objekt UND persistent in server/.env)."""
from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import weather
from ..coach import profile
from ..config import settings, update_env_file
from ..sync import scheduler

router = APIRouter(prefix="/settings", tags=["settings"])

SECRET_FIELDS = ["openrouter_api_key", "hevy_api_key", "fddb_pw", "fddb_cookie", "fddb_phpsessid"]
TEXT_FIELDS = ["openrouter_model", "openrouter_api_key", "hevy_api_key",
               "fddb_user", "fddb_pw", "fddb_cookie", "fddb_phpsessid"]


def _mask(v: str | None) -> dict:
    v = v or ""
    return {"set": bool(v), "hint": ("…" + v[-4:]) if len(v) >= 4 else ("gesetzt" if v else "")}


def _mask_user(v: str | None) -> str:
    if not v:
        return ""
    if "@" in v:
        name, dom = v.split("@", 1)
        return f"{name[:2]}…@{dom}"
    return f"{v[:2]}…"


def _current() -> dict:
    return {
        "openrouter_model": settings.openrouter_model,
        "timezone": settings.timezone,
        "scheduler_enabled": settings.scheduler_enabled,
        "run_hr_max": settings.run_hr_max,
        "weather_places": [item["place"] for item in weather.places()],
        "fddb_user_masked": _mask_user(settings.fddb_user),
        "keys": {f: _mask(getattr(settings, f)) for f in SECRET_FIELDS},
    }


@router.get("")
def get_settings() -> dict:
    return _current()


@router.get("/coach")
def get_coach_profile() -> dict:
    return profile.view(profile.load())


@router.put("/coach")
def update_coach_profile(body: profile.Profile) -> dict:
    return profile.save(body)


class SettingsIn(BaseModel):
    openrouter_model: str | None = None
    scheduler_enabled: bool | None = None
    run_hr_max: float | None = None
    weather_places: list[str] | None = None  # Reihenfolge = Blätter-Reihenfolge; [] = Wetter aus
    openrouter_api_key: str | None = None
    hevy_api_key: str | None = None
    fddb_user: str | None = None
    fddb_pw: str | None = None
    fddb_cookie: str | None = None
    fddb_phpsessid: str | None = None


@router.put("")
def update_settings(body: SettingsIn) -> dict:
    env_updates: dict[str, str] = {}

    for f in TEXT_FIELDS:
        val = getattr(body, f)
        if val is not None and val != "":
            setattr(settings, f, val)
            env_updates[f.upper()] = val

    if body.scheduler_enabled is not None:
        settings.scheduler_enabled = body.scheduler_enabled
        env_updates["SCHEDULER_ENABLED"] = "true" if body.scheduler_enabled else "false"
        if body.scheduler_enabled:
            scheduler.start_scheduler()
        else:
            scheduler.shutdown_scheduler()

    # Maximalpuls (Zonen-Basis): 0 = wieder aus Daten ableiten; negatives ignorieren.
    if body.run_hr_max is not None and body.run_hr_max >= 0:
        settings.run_hr_max = body.run_hr_max
        env_updates["RUN_HR_MAX"] = str(body.run_hr_max)

    if body.weather_places is not None:
        names = [name.strip() for name in body.weather_places if name.strip()]
        if len(names) > 8:
            raise HTTPException(status_code=422, detail="Höchstens 8 Orte.")
        known = {item["place"].casefold(): item for item in weather.places()}
        resolved: list[dict] = []
        for name in names:
            hit = known.get(name.casefold())  # bereits geocodierte Orte nicht erneut suchen
            if hit is None:
                try:
                    hit = weather.geocode(name)
                except httpx.HTTPError as exc:
                    raise HTTPException(status_code=502, detail="Ortssuche nicht erreichbar.") from exc
                if hit is None:
                    raise HTTPException(status_code=422, detail=f"Ort „{name}“ nicht gefunden.")
            if all(hit["place"] != item["place"] for item in resolved):
                resolved.append(hit)
        settings.weather_places = resolved
        settings.weather_place, settings.weather_lat, settings.weather_lon = "", None, None
        env_updates.update({"WEATHER_PLACES": json.dumps(resolved, ensure_ascii=False),
                            "WEATHER_PLACE": "", "WEATHER_LAT": "", "WEATHER_LON": ""})

    if env_updates:
        update_env_file(env_updates)
    return _current()
