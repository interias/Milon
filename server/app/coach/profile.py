"""Editable personal goals, their calendar status, and prompt context."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlmodel import Session

from ..config import settings
from ..db import engine
from ..models import CoachProfile


class Goal(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    target: str = Field(default="", max_length=2000)
    priority: Literal["high", "normal", "low"] = "normal"
    status: Literal["active", "achieved", "archived"] = "active"

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date and (not self.start_date or self.end_date < self.start_date):
            raise ValueError("Das Enddatum benötigt ein Startdatum und darf nicht davor liegen.")
        return self

    def effective_status(self, today: date) -> str:
        if self.status != "active":
            return self.status
        deadline = self.end_date or self.start_date
        return "past" if deadline and deadline < today else "active"


class Profile(BaseModel):
    context: str = Field(default="", max_length=8000)
    goals: list[Goal] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_ids(self):
        if len({goal.id for goal in self.goals}) != len(self.goals):
            raise ValueError("Ziele benötigen eindeutige IDs.")
        return self


def local_today() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def load() -> Profile:
    with Session(engine) as session:
        row = session.get(CoachProfile, 1)
        if row is not None:
            return Profile.model_validate_json(row.payload)
    # Keep existing installations usable until the first explicit profile save.
    return Profile(context=settings.coach_context)


def view(profile: Profile, today: date | None = None) -> dict:
    today = today or local_today()
    return {"context": profile.context,
            "goals": [{**goal.model_dump(mode="json"), "effective_status": goal.effective_status(today)}
                      for goal in profile.goals]}


def save(profile: Profile) -> dict:
    with Session(engine) as session:
        row = session.get(CoachProfile, 1)
        if row is None:
            row = CoachProfile(payload=profile.model_dump_json())
        else:
            row.payload = profile.model_dump_json()
        session.add(row)
        session.commit()
    return view(profile)


def context_text(today: date | None = None) -> str:
    today = today or local_today()
    profile = load()
    active = [goal for goal in profile.goals if goal.effective_status(today) == "active"]
    active.sort(key=lambda goal: ({"high": 0, "normal": 1, "low": 2}[goal.priority],
                                  goal.start_date or date.max))
    data = {
        "Rahmenbedingungen": profile.context.strip() or "Nicht angegeben; bei Bedarf nachfragen.",
        "Aktive Ziele": [goal.model_dump(mode="json", exclude={"id", "status"}) for goal in active],
        "Vergangene Termine (Erfolg unbekannt, keine Vorbereitung)": [
            {"name": goal.name, "Termin": (goal.end_date or goal.start_date).isoformat()}
            for goal in profile.goals if goal.effective_status(today) == "past"
        ],
    }
    return ("Persönliche Angaben (keine gemessenen Kennzahlen). Nur aktive Ziele für die Vorbereitung verwenden; "
            "Priorität high vor normal vor low, Termine für die zeitliche Planung berücksichtigen. "
            "Erreichte und archivierte Ziele sind ausgenommen. Leere aktive Ziele nicht ergänzen.\n"
            + json.dumps(data, ensure_ascii=False))
