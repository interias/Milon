"""Common comparison windows for circumference, weight and strength."""
from typing import Literal

from fastapi import APIRouter, Query

from ..metrics import body_progress

router = APIRouter(prefix="/metrics/body", tags=["metrics"])


@router.get("/progress")
def progress(weeks: int = Query(8, ge=4, le=12, multiple_of=4),
             measure: Literal["abdomen_navel", "waist_narrowest"] = "abdomen_navel") -> dict:
    return body_progress.progress(weeks, measure)
