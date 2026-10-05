"""Compact comparisons and intensity summaries for recorded Garmin runs."""
from fastapi import APIRouter, HTTPException, Query

from ..metrics import run_cohort, run_insights

router = APIRouter(prefix="/metrics/running/insights", tags=["running"])


@router.get("/zones")
def zones(weeks: int = Query(default=8, ge=1, le=26)):
    return run_insights.weekly_zones(weeks)


@router.get("/compare")
def compare(first: str = Query(max_length=30, pattern=r"^[0-9]+$"),
            second: str = Query(max_length=30, pattern=r"^[0-9]+$")):
    result = run_insights.compare(first, second)
    if result is None:
        raise HTTPException(404, "Laufaufzeichnung nicht gefunden.")
    return result


@router.get("/cohort/{activity_id}")
def cohort(activity_id: str):
    result = run_cohort.comparison(activity_id)
    if result is None:
        raise HTTPException(404, "Laufaufzeichnung nicht gefunden.")
    return result


@router.get("/{activity_id}")
def insights(activity_id: str):
    return run_insights.activity_insights(activity_id)
