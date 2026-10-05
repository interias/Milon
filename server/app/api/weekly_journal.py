"""Recorded activity journal, without an LLM call."""
from fastapi import APIRouter, Query

from ..metrics.weekly_journal import journal

router = APIRouter(prefix="/metrics/activity", tags=["activity"])


@router.get("/journal")
def get_journal(offset: int = Query(default=0, ge=0, le=52)):
    return journal(offset)
