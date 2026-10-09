"""Tageswetter für die Übersicht (Open-Meteo, 20 min gecacht)."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException

from .. import weather

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("")
def get_weather() -> dict:
    try:
        return weather.today()
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Wetterdienst nicht erreichbar.") from exc
