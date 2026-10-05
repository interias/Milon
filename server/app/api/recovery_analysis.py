"""Day-level recovery and subjective energy associations."""
from typing import Literal

from fastapi import APIRouter, Query

from ..metrics import recovery_analysis

router = APIRouter(prefix="/metrics/recovery", tags=["recovery"])


@router.get("/performance")
def performance(metric: Literal["sleep", "hrv", "energy"] = "sleep",
                kind: Literal["run", "strength"] = "run",
                source: Literal["current", "legacy", "all"] = "current",
                days: int = Query(180, ge=7, le=730)) -> dict:
    return recovery_analysis.performance(metric, kind, source, days)
