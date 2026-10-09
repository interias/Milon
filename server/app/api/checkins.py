"""Daily check-ins are opt-in; PUT replaces one day's self-report."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator
from sqlmodel import Session

from .. import checkins

router = APIRouter(prefix="/checkins", tags=["checkins"])


class CheckInInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    energy: StrictInt | None = Field(default=None, ge=1, le=5)
    training_effort: StrictInt | None = Field(default=None, ge=1, le=5)
    note: str | None = Field(default=None, max_length=500)
    session_kind: Literal["run", "strength"] | None = None
    session_external_id: str | None = Field(default=None, max_length=200)
    # Omitted = keep the stored value, so energy-only clients never clear a sick day.
    sick: StrictBool | None = None

    @field_validator("note", "session_external_id")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None

    @model_validator(mode="after")
    def validate_entry(self):
        if (self.session_kind is None) != (self.session_external_id is None):
            raise ValueError("Trainingsart und Trainings-ID müssen gemeinsam angegeben werden.")
        if (self.energy is None and self.training_effort is None and self.note is None
                and self.session_kind is None and not self.sick):
            raise ValueError("Mindestens Energie, Trainingsanstrengung, Krankheit, eine Notiz oder ein Training angeben.")
        return self


def _past_or_today(day: date) -> None:
    if day > checkins.local_today():
        raise HTTPException(status_code=422, detail="Check-ins können nicht in der Zukunft liegen.")


@router.get("")
def list_checkins(days: int = Query(30, ge=1, le=365)) -> dict:
    today = checkins.local_today()
    return {"today": today.isoformat(), "entries": checkins.list_entries(days, today),
            "summary": checkins.summary(days, today)}


@router.get("/sessions")
def list_sessions(day: date) -> list[dict]:
    _past_or_today(day)
    return checkins.sessions_on(day)


class SickRangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    end: date
    sick: StrictBool

    @model_validator(mode="after")
    def validate_range(self):
        if self.start > self.end:
            raise ValueError("Der Beginn muss vor dem Ende liegen.")
        if (self.end - self.start).days > 92:
            raise ValueError("Höchstens 93 Tage auf einmal.")
        return self


@router.put("/sick")
def save_sick_range(body: SickRangeInput) -> dict:
    """Mark or clear sick days; clearing removes entries that would otherwise be empty."""
    _past_or_today(body.end)
    now = datetime.now(timezone.utc)
    days = [body.start + timedelta(days=offset) for offset in range((body.end - body.start).days + 1)]
    with Session(checkins.engine) as session:
        for day in days:
            entry = session.get(checkins.CheckIn, day)
            if entry is None:
                if body.sick:
                    session.add(checkins.CheckIn(day=day, sick=True, updated_at=now))
                continue
            entry.sick = True if body.sick else None
            entry.updated_at = now
            empty = (entry.energy is None and entry.training_effort is None and entry.note is None
                     and entry.session_kind is None and not entry.sick)
            session.delete(entry) if empty else session.add(entry)
        session.commit()
    return {"start": body.start.isoformat(), "end": body.end.isoformat(), "sick": body.sick, "days": len(days)}


@router.get("/{day}")
def get_checkin(day: date) -> dict | None:
    _past_or_today(day)
    with Session(checkins.engine) as session:
        entry = session.get(checkins.CheckIn, day)
        return checkins.entry_dict(entry) if entry is not None else None


@router.put("/{day}")
def save_checkin(day: date, body: CheckInInput) -> dict:
    _past_or_today(day)
    with Session(checkins.engine) as session:
        entry = session.get(checkins.CheckIn, day)
        same_reference = entry is not None and (entry.session_kind, entry.session_external_id) == (
            body.session_kind, body.session_external_id)
        # Keep an existing reference if the imported workout has since been deleted.
        if body.session_kind and not same_reference and not checkins.valid_session(
                session, day, body.session_kind, body.session_external_id):
            raise HTTPException(status_code=422, detail="Das ausgewählte Training gehört nicht zu diesem Tag oder ist nicht verfügbar.")
        values = body.model_dump()
        if "sick" not in body.model_fields_set:
            values["sick"] = entry.sick if entry is not None else None
        if entry is None:
            entry = checkins.CheckIn(day=day, updated_at=datetime.now(timezone.utc), **values)
        else:
            for key, value in values.items():
                setattr(entry, key, value)
            entry.updated_at = datetime.now(timezone.utc)
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return checkins.entry_dict(entry)


@router.delete("/{day}")
def delete_checkin(day: date) -> dict:
    with Session(checkins.engine) as session:
        entry = session.get(checkins.CheckIn, day)
        if entry is not None:
            session.delete(entry)
            session.commit()
    return {"deleted": day.isoformat()}
