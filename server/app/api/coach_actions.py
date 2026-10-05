"""User-approved weekly actions; writes are never exposed as coach tools."""
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from sqlalchemy import text
from sqlmodel import Session, select

from .. import coach_actions
from ..coach_actions import CoachAction
from ..models import CoachReport

router = APIRouter(prefix="/coach/actions", tags=["coach-actions"])


class ActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(min_length=1, max_length=280)
    metric: Literal["sleep", "steps", "protein", "energy"] | None = None
    source_report_id: StrictInt | None = Field(default=None, gt=0)

    @field_validator("action")
    @classmethod
    def clean_action(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Bitte eine konkrete Maßnahme eintragen.")
        return value


class ActionFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "implemented", "partly", "not_tried"] | None = None
    note: str | None = Field(default=None, max_length=300)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def has_update(self):
        if not self.model_fields_set:
            raise ValueError("Keine Rückmeldung angegeben.")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("Ein Status darf nicht leer sein.")
        return self


@router.get("")
def list_actions(limit: int = Query(default=20, ge=1, le=100)):
    return coach_actions.list_entries(limit)


@router.post("", status_code=201)
def accept_action(payload: ActionInput):
    today = coach_actions.local_today()
    now = datetime.now(timezone.utc)
    with Session(coach_actions.engine) as session:
        # Serialise the overlap check and write for the single local SQLite database.
        session.execute(text("BEGIN IMMEDIATE"))
        if session.exec(select(CoachAction).where(CoachAction.ends_on >= today)).first():
            raise HTTPException(409, "Es läuft bereits eine Wochenmaßnahme. Du kannst sie zuerst entfernen oder ihren Zeitraum abwarten.")
        if payload.source_report_id is not None and session.get(CoachReport, payload.source_report_id) is None:
            raise HTTPException(422, "Der ausgewählte Coach-Bericht existiert nicht mehr.")
        row = CoachAction(**payload.model_dump(), starts_on=today, ends_on=today + timedelta(days=6),
                          accepted_at=now, updated_at=now)
        session.add(row)
        session.commit()
        session.refresh(row)
        return coach_actions.entry_dict(session, row, today)


@router.patch("/{action_id}")
def record_feedback(action_id: int, payload: ActionFeedback):
    with Session(coach_actions.engine) as session:
        row = session.get(CoachAction, action_id)
        if row is None:
            raise HTTPException(404, "Maßnahme nicht gefunden.")
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        row.updated_at = datetime.now(timezone.utc)
        session.add(row)
        session.commit()
        session.refresh(row)
        return coach_actions.entry_dict(session, row, coach_actions.local_today())


@router.delete("/{action_id}")
def remove_action(action_id: int):
    with Session(coach_actions.engine) as session:
        row = session.get(CoachAction, action_id)
        if row is not None:
            session.delete(row)
            session.commit()
    return {"ok": True}
