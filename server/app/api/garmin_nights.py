"""Garmin sleep rhythm and source-owned night observations."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from ..metrics import garmin_nights

router = APIRouter(prefix="/metrics/garmin/nights", tags=["Garmin"])


@router.get("")
def get_nights(days: Literal["14", "30"] = Query(default="14"), end: date | None = None):
    return garmin_nights.nights(int(days), end=end)


@router.get("/{day}")
def get_night(day: date):
    value = garmin_nights.night(day)
    if value is None:
        raise HTTPException(404, "Keine Garmin-Hauptschlafphase für diesen Tag verfügbar.")
    return value
