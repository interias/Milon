"""Read-only overview time travel and local monthly recap."""
from fastapi import APIRouter, HTTPException, Query

from ..metrics import overview_history

router = APIRouter(prefix="/metrics/overview", tags=["overview"])


@router.get("/history")
def history():
    return overview_history.history()


@router.get("/monthly")
def monthly(month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")):
    try:
        return overview_history.monthly(month)
    except (ValueError, OverflowError) as error:
        raise HTTPException(422, "Dieser Monat ist nicht verfügbar.") from error
