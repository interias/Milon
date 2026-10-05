"""Recorded running mechanics and optional Garmin impact context."""
from fastapi import APIRouter, HTTPException, Query

from ..metrics import run_mechanics

router = APIRouter(prefix="/metrics/running/mechanics", tags=["running"])


@router.get("/load")
def load(weeks: int = Query(default=12, ge=1, le=26)):
    return run_mechanics.load(weeks)


@router.get("/{activity_id}")
def activity(activity_id: str):
    result = run_mechanics.activity(activity_id)
    if result is None:
        raise HTTPException(404, "Laufaufzeichnung nicht gefunden.")
    return result
