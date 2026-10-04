"""Optional daily self-reports, separate from imported watch and workout data."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlmodel import Field, Session, SQLModel

from .config import settings
from .db import engine
from .models import ExerciseSession, Workout


class CheckIn(SQLModel, table=True):
    __tablename__ = "checkins"

    day: date = Field(primary_key=True)
    energy: int | None = None
    training_effort: int | None = None
    note: str | None = None
    session_kind: str | None = None
    session_external_id: str | None = None
    updated_at: datetime


def local_today(now: datetime | None = None) -> date:
    zone = ZoneInfo(settings.timezone)
    if now is None:
        return datetime.now(zone).date()
    return (now.replace(tzinfo=zone) if now.tzinfo is None else now.astimezone(zone)).date()


def entry_dict(entry: CheckIn) -> dict:
    return entry.model_dump(mode="json")


def list_entries(days: int = 30, today: date | None = None) -> list[dict]:
    end = today if today is not None else local_today()
    start = end - timedelta(days=days - 1)
    with Session(engine) as session:
        rows = session.execute(select(CheckIn).where(CheckIn.day >= start, CheckIn.day <= end)
                               .order_by(CheckIn.day.desc())).scalars().all()
        return [entry_dict(row) for row in rows]


def summary(days: int = 30, today: date | None = None) -> dict:
    end = today if today is not None else local_today()
    entries = list_entries(days, end)
    energies = [entry["energy"] for entry in entries if entry["energy"] is not None]
    efforts = [entry["training_effort"] for entry in entries if entry["training_effort"] is not None]
    return {
        "from_date": (end - timedelta(days=days - 1)).isoformat(), "to_date": end.isoformat(),
        "days": days, "count": len(entries),
        "energy_avg": round(sum(energies) / len(energies), 1) if energies else None,
        "energy_days": len(energies),
        "training_effort_avg": round(sum(efforts) / len(efforts), 1) if efforts else None,
        "training_effort_days": len(efforts),
        "linked_sessions": sum(entry["session_external_id"] is not None for entry in entries),
        "last_day": entries[0]["day"] if entries else None, "latest": entries[:5],
        "caveat": "Freiwillige Selbstauskunft (1–5). Fehlende Tage sind unbekannt; Auswahl kann verzerrt sein.",
    }


def sessions_on(day: date) -> list[dict]:
    start, end = datetime.combine(day, datetime.min.time()), datetime.combine(day + timedelta(days=1), datetime.min.time())
    with Session(engine) as session:
        runs = session.execute(select(ExerciseSession).where(
            ExerciseSession.started_at >= start, ExerciseSession.started_at < end,
            ExerciseSession.exercise_type.in_([33, 58]), ExerciseSession.external_id.is_not(None),
        )).scalars().all()
        workouts = session.execute(select(Workout).where(
            Workout.started_at >= start, Workout.started_at < end, Workout.source == "hevy",
            Workout.external_id.is_not(None),
        )).scalars().all()
        items = [{"kind": "run", "external_id": run.external_id,
                  "started_at": run.started_at.isoformat(), "title": "Lauf",
                  "detail": f"{run.distance_km:.1f} km" if run.distance_km is not None else ""}
                 for run in runs]
        items += [{"kind": "strength", "external_id": workout.external_id,
                   "started_at": workout.started_at.isoformat(),
                   "title": workout.title or "Krafttraining", "detail": "Kraft"}
                  for workout in workouts]
    return sorted(items, key=lambda item: item["started_at"])


def valid_session(session: Session, day: date, kind: str, external_id: str) -> bool:
    model = ExerciseSession if kind == "run" else Workout
    row = session.execute(select(model).where(model.external_id == external_id)).scalar_one_or_none()
    if row is None or row.started_at is None or row.started_at.date() != day:
        return False
    return row.exercise_type in (33, 58) if kind == "run" else row.source == "hevy"
