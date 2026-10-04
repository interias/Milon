"""CRUD for manual body circumferences and their display preferences."""
import re
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator

from .. import circumferences


router = APIRouter(prefix="/body-circumferences", tags=["body-circumferences"])


class EntryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    protocol: Literal["standard", "unknown"]
    # Validate numbers in the service so a non-finite JSON input cannot leak
    # into FastAPI's validation error payload, which itself must be valid JSON.
    values: dict[str, Any]

    @field_validator("date", mode="before")
    @classmethod
    def require_iso_date(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Bitte ein Messdatum im Format YYYY-MM-DD angeben.")
        return value


class PreferencesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visible_keys: list[str]
    layout: Literal["rows", "atlas"]
    period: Literal["1m", "3m", "6m", "12m", "all"]


@router.get("")
def get_circumferences() -> dict:
    return circumferences.overview()


def _save(body: EntryInput, entry_id: int | None = None) -> dict:
    try:
        return circumferences.save_entry(body.date, body.protocol, body.values, entry_id)
    except circumferences.EntryNotFound as failure:
        raise HTTPException(status_code=404, detail=str(failure)) from failure
    except circumferences.DuplicateEntry as failure:
        raise HTTPException(status_code=409, detail=str(failure)) from failure
    except ValueError as failure:
        raise HTTPException(status_code=422, detail=str(failure)) from failure


@router.post("")
def create_entry(body: EntryInput) -> dict:
    return _save(body)


@router.put("/preferences")
def update_preferences(body: PreferencesInput) -> dict:
    try:
        return circumferences.save_preferences(body.visible_keys, body.layout, body.period)
    except ValueError as failure:
        raise HTTPException(status_code=422, detail=str(failure)) from failure


@router.put("/{entry_id}")
def update_entry(entry_id: int, body: EntryInput) -> dict:
    return _save(body, entry_id)


@router.delete("/{entry_id}")
def delete_entry(entry_id: int) -> dict:
    try:
        return circumferences.delete_entry(entry_id)
    except circumferences.EntryNotFound as failure:
        raise HTTPException(status_code=404, detail=str(failure)) from failure
