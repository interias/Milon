"""Voluntary run intent and the existing daily exertion check-in."""
from datetime import datetime, timezone
import json

from fastapi import HTTPException
from sqlmodel import Field, Session, SQLModel

from . import checkins
from .db import engine
from .garmin_activity import GarminActivity
from .garmin_weather import weather_for


class RunIntent(SQLModel, table=True):
    __tablename__ = "run_intents"
    activity_id: str = Field(primary_key=True)
    intent: str
    updated_at: datetime


def _activity(session, activity_id):
    row = session.get(GarminActivity, activity_id)
    if row is None:
        raise HTTPException(404, "Lauf nicht verfügbar.")
    return row


def _effort_state(session, row):
    entry = session.get(checkins.CheckIn, row.started_at.date())
    linked = bool(entry and row.canonical_external_id and entry.session_kind == "run"
                  and entry.session_external_id == row.canonical_external_id)
    conflict = bool(entry and not linked and (entry.session_external_id or entry.training_effort is not None))
    return entry, linked, conflict


def context(activity_id):
    with Session(engine) as session:
        row = _activity(session, activity_id)
        intent = session.get(RunIntent, activity_id)
        entry, linked, conflict = _effort_state(session, row)
        summary = json.loads(row.summary_json)
        return {"activity_id": activity_id, "intent": intent.intent if intent else None,
                "training_effort": entry.training_effort if linked else None,
                "effort_editable": bool(row.canonical_external_id) and not conflict,
                "effort_conflict": conflict, "weather": weather_for(session, activity_id, summary.get("started_at_utc"))}


def update(activity_id, fields):
    with Session(engine) as session:
        row = _activity(session, activity_id)
        day = row.started_at.date()
        if day > checkins.local_today():
            raise HTTPException(422, "Der Lauf liegt in der Zukunft.")
        now = datetime.now(timezone.utc)
        if "training_effort" in fields:
            entry, linked, conflict = _effort_state(session, row)
            if conflict:
                raise HTTPException(409, "Der Check-in dieses Tages gehört bereits zu einem anderen Training oder ist noch nicht zugeordnet.")
            if not row.canonical_external_id or not checkins.valid_session(session, day, "run", row.canonical_external_id):
                raise HTTPException(422, "Der Lauf ist noch keiner vollständigen Trainingseinheit zugeordnet.")
            value = fields["training_effort"]
            if value is not None or linked:
                entry = entry or checkins.CheckIn(day=day, updated_at=now)
                entry.training_effort = value
                if value is not None:
                    entry.session_kind = "run"
                    entry.session_external_id = row.canonical_external_id
                entry.updated_at = now
                if value is None and entry.energy is None and not entry.note:
                    session.delete(entry)
                else:
                    session.add(entry)
        if "intent" in fields:
            existing = session.get(RunIntent, activity_id)
            value = fields["intent"]
            if value is None:
                if existing:
                    session.delete(existing)
            else:
                existing = existing or RunIntent(activity_id=activity_id, intent=value, updated_at=now)
                existing.intent, existing.updated_at = value, now
                session.add(existing)
        session.commit()
    return context(activity_id)
