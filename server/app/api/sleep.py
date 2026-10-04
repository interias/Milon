"""Sleep and exploratory performance analysis endpoints."""
from typing import Literal

from fastapi import APIRouter, Query

from ..metrics import sleep

router = APIRouter(prefix="/metrics/sleep", tags=["sleep"])


@router.get("/overview")
def overview(days: int = Query(default=90, ge=7, le=730)) -> dict:
    return sleep.overview(days)


@router.get("/performance")
def performance(kind: Literal["run", "strength"] = "run",
                source: Literal["current", "legacy", "all"] = "current",
                days: int = Query(default=180, ge=7, le=730)) -> dict:
    return sleep.performance(kind, source, days)
