"""Einstellungen: liest/schreibt die Konfiguration (server/.env) zur Laufzeit.
Secrets werden maskiert ausgegeben; PUT aktualisiert nur übergebene, nicht-leere Werte
(live im Settings-Objekt UND persistent in server/.env)."""
from __future__ import annotations

import json
from datetime import date, datetime

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from .. import weather
from ..coach import client, profile
from ..config import settings, update_env_file
from ..sync import scheduler

router = APIRouter(prefix="/settings", tags=["settings"])

SECRET_FIELDS = ["anthropic_api_key", "openrouter_api_key", "hevy_api_key", "fddb_pw", "fddb_cookie", "fddb_phpsessid"]
TEXT_FIELDS = ["openrouter_model", "anthropic_api_key", "openrouter_api_key", "hevy_api_key",
               "fddb_user", "fddb_pw", "fddb_cookie", "fddb_phpsessid"]


LLM_PROVIDERS = ("anthropic", "openrouter")
ANTHROPIC_EFFORTS = ("low", "medium", "high")


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


def _budget() -> dict:
    try:
        return client.budget_status()
    except SQLAlchemyError:  # Statistik nicht lesbar: Einstellungen bleiben bedienbar
        return {"month": datetime.now().strftime("%Y-%m"), "budget_usd": settings.llm_monthly_budget_usd,
                "spent": {"anthropic": 0.0, "openrouter": 0.0}, "ratio": 0.0, "warn": False, "exceeded": False}


def _current() -> dict:
    return {
        "openrouter_model": settings.openrouter_model,
        "llm_provider": settings.llm_provider.strip().lower(),  # "" = automatisch
        "llm_provider_resolved": settings.resolved_llm_provider(),
        "anthropic_model": settings.anthropic_model,
        "anthropic_effort": settings.anthropic_effort,
        "llm_monthly_budget_usd": settings.llm_monthly_budget_usd,
        "llm_budget": _budget(),
        "timezone": settings.timezone,
        "scheduler_enabled": settings.scheduler_enabled,
        "run_hr_max": settings.run_hr_max,
        "body_height_cm": settings.body_height_cm,
        "birth_date": settings.birth_date.isoformat() if settings.birth_date else None,
        "bike_ftp": settings.bike_ftp,
        "walkpad_stride_m": settings.walkpad_stride_m,
        "walkpad_incline_pct": settings.walkpad_incline_pct,
        "walkpad_garmin_upload": settings.walkpad_garmin_upload,
        "walkpad_max_speed_kmh": settings.walkpad_max_speed_kmh,
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
    llm_provider: str | None = None  # "" = automatisch; None = unveraendert
    anthropic_model: str | None = None
    anthropic_effort: str | None = None
    llm_monthly_budget_usd: float | None = None
    anthropic_api_key: str | None = None
    scheduler_enabled: bool | None = None
    run_hr_max: float | None = None
    body_height_cm: float | None = None
    birth_date: date | None = None
    bike_ftp: float | None = None  # 0 = automatisch (eFTP)
    walkpad_stride_m: float | None = None
    walkpad_incline_pct: float | None = None
    walkpad_garmin_upload: bool | None = None
    walkpad_max_speed_kmh: float | None = None
    weather_places: list[str] | None = None  # Reihenfolge = Blätter-Reihenfolge; [] = Wetter aus
    openrouter_api_key: str | None = None
    hevy_api_key: str | None = None
    fddb_user: str | None = None
    fddb_pw: str | None = None
    fddb_cookie: str | None = None
    fddb_phpsessid: str | None = None


def _validate_llm(body: SettingsIn) -> None:
    """Coach-Anbieter-Werte pruefen, bevor irgendetwas live oder in die .env geht (kein halb angewendetes PUT)."""
    if body.llm_provider is not None and body.llm_provider.strip().lower() not in ("", *LLM_PROVIDERS):
        raise HTTPException(status_code=422, detail="Anbieter: anthropic, openrouter oder leer (automatisch).")
    if body.anthropic_model is not None and body.anthropic_model not in client.PRICES:
        raise HTTPException(status_code=422, detail="Unbekanntes Anthropic-Modell.")
    if body.anthropic_effort is not None and body.anthropic_effort not in ANTHROPIC_EFFORTS:
        raise HTTPException(status_code=422, detail="Effort: low, medium oder high.")
    if body.llm_monthly_budget_usd is not None and not 0 <= body.llm_monthly_budget_usd < float("inf"):
        raise HTTPException(status_code=422, detail="Budget muss eine Zahl ≥ 0 sein (0 = kein Limit).")
    if body.bike_ftp is not None and not 0 <= body.bike_ftp <= 1000:
        raise HTTPException(status_code=422, detail="FTP muss zwischen 0 und 1000 W liegen (0 = automatisch).")
    if body.body_height_cm is not None and not 100 < body.body_height_cm < 250:
        raise HTTPException(status_code=422, detail="Größe muss zwischen 100 und 250 cm liegen.")
    if body.birth_date is not None and not date(1900, 1, 1) < body.birth_date < date.today():
        raise HTTPException(status_code=422, detail="Ungültiges Geburtsdatum.")
    if body.walkpad_stride_m is not None and not 0.2 < body.walkpad_stride_m <= 1.5:
        raise HTTPException(status_code=422, detail="Schrittlänge muss zwischen 0,2 und 1,5 m liegen.")
    if body.walkpad_incline_pct is not None and not 0 <= body.walkpad_incline_pct <= 15:
        raise HTTPException(status_code=422, detail="Steigung muss zwischen 0 und 15 % liegen.")
    if body.walkpad_max_speed_kmh is not None and not 1 <= body.walkpad_max_speed_kmh <= 6:
        raise HTTPException(status_code=422, detail="Höchsttempo muss zwischen 1 und 6 km/h liegen.")


@router.put("")
def update_settings(body: SettingsIn) -> dict:
    _validate_llm(body)
    env_updates: dict[str, str] = {}

    for f in TEXT_FIELDS:
        val = getattr(body, f)
        if val is not None and val != "":
            setattr(settings, f, val)
            env_updates[f.upper()] = val

    if body.llm_provider is not None:
        provider = body.llm_provider.strip().lower()
        settings.llm_provider = provider
        env_updates["LLM_PROVIDER"] = provider
    if body.anthropic_model is not None:
        settings.anthropic_model = body.anthropic_model
        env_updates["ANTHROPIC_MODEL"] = body.anthropic_model
    if body.anthropic_effort is not None:
        settings.anthropic_effort = body.anthropic_effort
        env_updates["ANTHROPIC_EFFORT"] = body.anthropic_effort
    if body.llm_monthly_budget_usd is not None:
        settings.llm_monthly_budget_usd = body.llm_monthly_budget_usd
        env_updates["LLM_MONTHLY_BUDGET_USD"] = str(body.llm_monthly_budget_usd)

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

    # Körpermaße für den Ruheumsatz in der Energiebilanz.
    if body.body_height_cm is not None:
        settings.body_height_cm = body.body_height_cm
        env_updates["BODY_HEIGHT_CM"] = str(body.body_height_cm)
    if body.birth_date is not None:
        settings.birth_date = body.birth_date
        env_updates["BIRTH_DATE"] = body.birth_date.isoformat()

    # Rad-FTP: 0 = wieder automatisch (eFTP aus den Fahrten).
    if body.bike_ftp is not None:
        settings.bike_ftp = body.bike_ftp
        env_updates["BIKE_FTP"] = str(body.bike_ftp)

    # Laufband: Schrittlänge wirkt auf alle Walks (beim Lesen), Steigung nur auf neue Sessions.
    if body.walkpad_stride_m is not None:
        settings.walkpad_stride_m = body.walkpad_stride_m
        env_updates["WALKPAD_STRIDE_M"] = str(body.walkpad_stride_m)
    if body.walkpad_incline_pct is not None:
        settings.walkpad_incline_pct = body.walkpad_incline_pct
        env_updates["WALKPAD_INCLINE_PCT"] = str(body.walkpad_incline_pct)
    if body.walkpad_garmin_upload is not None:
        settings.walkpad_garmin_upload = body.walkpad_garmin_upload
        env_updates["WALKPAD_GARMIN_UPLOAD"] = "true" if body.walkpad_garmin_upload else "false"
    if body.walkpad_max_speed_kmh is not None:
        settings.walkpad_max_speed_kmh = round(body.walkpad_max_speed_kmh, 1)
        env_updates["WALKPAD_MAX_SPEED_KMH"] = str(settings.walkpad_max_speed_kmh)

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
