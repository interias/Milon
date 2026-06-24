"""Einstellungen: liest/schreibt die Konfiguration (server/.env) zur Laufzeit.
Secrets werden maskiert ausgegeben; PUT aktualisiert nur übergebene, nicht-leere Werte
(live im Settings-Objekt UND persistent in server/.env)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

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
        "fddb_user_masked": _mask_user(settings.fddb_user),
        "keys": {f: _mask(getattr(settings, f)) for f in SECRET_FIELDS},
    }


@router.get("")
def get_settings() -> dict:
    return _current()


class SettingsIn(BaseModel):
    openrouter_model: str | None = None
    scheduler_enabled: bool | None = None
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

    if env_updates:
        update_env_file(env_updates)
    return _current()
