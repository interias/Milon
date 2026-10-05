"""Explicit weekly commitments and descriptive, calendar-bound follow-up."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from math import isfinite
from statistics import mean
from zoneinfo import ZoneInfo

from sqlmodel import Field, Session, SQLModel, select

from .checkins import CheckIn
from .config import settings, watch_source_for
from .db import engine
from .models import NutritionEntry, SleepSession, StepsDaily


class CoachAction(SQLModel, table=True):
    __tablename__ = "coach_actions"

    id: int | None = Field(default=None, primary_key=True)
    action: str
    starts_on: date = Field(index=True, unique=True)
    ends_on: date
    metric: str | None = None
    source_report_id: int | None = None
    status: str = "pending"
    note: str | None = None
    accepted_at: datetime
    updated_at: datetime


METRICS = {
    "sleep": {"label": "Schlafdauer", "unit": "h", "note": "Nur Hauptnächte mit bekannter Schlafdauer; getrennte Uhren werden nicht verglichen."},
    "steps": {"label": "Schritte", "unit": "/Tag", "note": "Nur erfasste Tage; ein Uhrenwechsel unterbricht den Vergleich."},
    "protein": {"label": "Protein", "unit": "g/Tag", "note": "FDDB-Tagessummen; Einträge belegen keine vollständige Erfassung."},
    "energy": {"label": "Tagesenergie", "unit": "/5", "note": "Freiwillige Check-ins; ausgelassene Tage bleiben unbekannt."},
}
STATUS_LABELS = {"pending": "Noch offen", "implemented": "Umgesetzt", "partly": "Teilweise", "not_tried": "Nicht ausprobiert"}


def local_today() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def _valid(value: float | None) -> bool:
    return value is not None and isfinite(value) and value >= 0


def _daily_values(session: Session, metric: str, start: date, end: date) -> dict[date, float]:
    if end < start:
        return {}
    if metric == "steps":
        rows = session.exec(select(StepsDaily).where(StepsDaily.day >= start, StepsDaily.day <= end)).all()
        return {row.day: float(row.steps) for row in rows if _valid(row.steps)}
    if metric == "energy":
        rows = session.exec(select(CheckIn).where(CheckIn.day >= start, CheckIn.day <= end)).all()
        return {row.day: float(row.energy) for row in rows if row.energy is not None and 1 <= row.energy <= 5}
    if metric == "sleep":
        rows = session.exec(select(SleepSession).where(SleepSession.day >= start, SleepSession.day <= end)).all()
        main: dict[date, SleepSession] = {}
        for row in rows:
            if row.source_package == watch_source_for(row.day, settings) and row.main_sleep:
                previous = main.get(row.day)
                if previous is None or row.duration_window_minutes > previous.duration_window_minutes:
                    main[row.day] = row
        return {day: row.asleep_minutes / 60 for day, row in main.items() if _valid(row.asleep_minutes)}
    rows = session.exec(select(NutritionEntry).where(
        NutritionEntry.eaten_at >= datetime.combine(start, datetime.min.time()),
        NutritionEntry.eaten_at < datetime.combine(end + timedelta(days=1), datetime.min.time()),
        NutritionEntry.source == "fddb",
    )).all()
    values: dict[date, list[float]] = defaultdict(list)
    for row in rows:
        if _valid(row.protein_g):
            values[row.eaten_at.date()].append(row.protein_g)
    return {day: sum(entries) for day, entries in values.items()}


def comparison(session: Session, row: CoachAction, today: date) -> dict | None:
    if row.metric not in METRICS:
        return None
    before_start, before_end = row.starts_on - timedelta(days=7), row.starts_on - timedelta(days=1)
    during_end = min(row.ends_on, today - timedelta(days=1))
    daily = _daily_values(session, row.metric, before_start, during_end)

    def window(start: date, end: date) -> dict:
        observations = {day: value for day, value in daily.items() if start <= day <= end}
        return {"start": start.isoformat(), "end": end.isoformat() if end >= start else None,
                "days": max(0, (end - start).days + 1), "recorded_days": len(observations),
                "mean": round(mean(observations.values()), 2) if observations else None}

    before, during = window(before_start, before_end), window(row.starts_on, during_end)
    switched = row.metric in {"sleep", "steps"} and watch_source_for(before_start, settings) != watch_source_for(max(before_start, during_end), settings)
    enough = before["recorded_days"] >= 3 and during["recorded_days"] >= 3
    status = "source_changed" if switched else "observed" if enough else "collecting"
    # Three days is a display threshold, not a significance or reliability test.
    delta = round(during["mean"] - before["mean"], 2) if enough and not switched else None
    return {"metric": row.metric, **METRICS[row.metric], "before": before, "during": during,
            "delta": delta, "status": status,
            "reason": "Uhrenwechsel im Vergleichszeitraum." if switched else
            "Beobachteter Unterschied, keine Aussage zur Ursache." if enough else
            "Für einen Unterschied sammeln wir mindestens drei erfasste Tage je Zeitraum.",
            "method": "Mittel der erfassten Tage: sieben Tage davor gegen die Maßnahmentage. "
                      "Heute bleibt als unvollständiger Tag ausgenommen. Fehlende Tage werden nicht mit null aufgefüllt. "
                      "Auch bei vollständigen Daten belegt eine Änderung keine Wirkung der Maßnahme."}


def entry_dict(session: Session, row: CoachAction, today: date) -> dict:
    return {**row.model_dump(mode="json"), "status_label": STATUS_LABELS[row.status],
            "phase": "running" if today <= row.ends_on else "finished",
            "comparison": comparison(session, row, today)}


def list_entries(limit: int = 20) -> dict:
    today = local_today()
    with Session(engine) as session:
        rows = session.exec(select(CoachAction).order_by(CoachAction.starts_on.desc()).limit(limit)).all()
        return {"today": today.isoformat(), "metrics": [{"key": key, **value} for key, value in METRICS.items()],
                "entries": [entry_dict(session, row, today) for row in rows]}


def coach_context() -> list[dict]:
    """Compact evidence for future reports; the model cannot accept or edit actions."""
    return [{key: value for key, value in entry.items() if key not in {"accepted_at", "updated_at"}}
            for entry in list_entries(3)["entries"]]
