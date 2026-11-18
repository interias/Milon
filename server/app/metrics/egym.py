"""eGym-Training als Pauschale: ein Knopfdruck je Tag, solange es keinen Datenzugang gibt.

Gespeichert als `workouts`-Zeile mit source='egym' ohne Sätze. So zählt der Tag als Krafttraining
(Serie, Wochenplan, Heldenreise), ohne Stärke-Index, Volumen oder Progression zu berühren.
Pauschal: 60 min, 200 aktive kcal (netto über Ruhe, Teil „gym“ in `active_kcal`)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from ..config import settings
from ..db import engine
from ..models import Workout

SOURCE = "egym"
SOURCES_SQL = "('hevy', 'egym')"   # Quellen, die als Krafttraining-Einheit zählen
TITLE = "eGym"
MINUTES = 60
KCAL = 200
HERO_SETS = 20                     # Heldenreise rechnet in Sätzen: entspricht einem normalen Training
BACKDATED_START = time(17, 0)      # nachgetragene Tage: Uhrzeit unbekannt


def _now() -> datetime:
    return datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None, microsecond=0)


def _key(day: date) -> str:
    return f"egym:{day.isoformat()}"


def listing() -> dict:
    today = _now().date()
    with Session(engine) as db:
        rows = db.exec(select(Workout).where(Workout.source == SOURCE).order_by(Workout.started_at.desc())).all()
    days = [w.started_at.date().isoformat() for w in rows]
    return {"today": today.isoformat(), "done_today": today.isoformat() in days,
            "minutes": MINUTES, "kcal": KCAL, "total": len(days), "days": days}


def add(day: date | None = None) -> dict:
    """Training eintragen (je Tag höchstens eins; doppelt drücken ändert nichts). Heute endet es jetzt."""
    now = _now()
    day = day or now.date()
    if day > now.date():
        raise ValueError("Der Tag liegt in der Zukunft.")
    if day == now.date():
        start = max(now - timedelta(minutes=MINUTES), datetime.combine(day, time.min))
    else:
        start = datetime.combine(day, BACKDATED_START)
    with Session(engine) as db:
        if not db.exec(select(Workout).where(Workout.external_id == _key(day))).first():
            db.add(Workout(external_id=_key(day), title=TITLE, started_at=start,
                           ended_at=start + timedelta(minutes=MINUTES), source=SOURCE))
            db.commit()
    return listing()


def remove(day: date) -> dict | None:
    """Eintrag löschen; None = an dem Tag gibt es keinen."""
    with Session(engine) as db:
        row = db.exec(select(Workout).where(Workout.external_id == _key(day))).first()
        if not row:
            return None
        db.delete(row)
        db.commit()
    return listing()
