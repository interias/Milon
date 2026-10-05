"""Select and inspect the personal running route reference."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .. import run_reference

router = APIRouter(prefix="/running/reference", tags=["running"])


class ReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activity_id: str = Field(min_length=1, max_length=30, pattern=r"^[0-9]+$")


@router.get("")
def overview(days: int = Query(default=365, ge=30, le=730)):
    return run_reference.overview(days)


@router.get("/selection")
def selection(activity_id: str | None = Query(default=None, max_length=30, pattern=r"^[0-9]+$")):
    return run_reference.selection(activity_id)


@router.put("")
def choose(body: ReferenceInput):
    try:
        return run_reference.choose(body.activity_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.delete("")
def clear():
    return run_reference.clear()
