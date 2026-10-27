"""Compact, source-labelled Garmin recovery context."""
from fastapi import APIRouter, Query

from ..garmin_daily import active_calories, recovery

router = APIRouter(prefix="/metrics/garmin", tags=["Garmin"])


@router.get("/recovery")
def get_recovery(days: int = Query(default=30, ge=1, le=365)):
    return recovery(days)


@router.get("/active-calories")
def get_active_calories(days: int = Query(default=14, ge=1, le=365)):
    return active_calories(days)
