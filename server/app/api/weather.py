"""Tageswetter für die Übersicht (Open-Meteo, 20 min gecacht)."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query

from .. import weather

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("")
def get_weather(index: int = Query(0, ge=0), day: int = Query(0, ge=0, le=6)) -> dict:
    try:
        return weather.today(index, day)
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Wetterdienst nicht erreichbar.") from exc
