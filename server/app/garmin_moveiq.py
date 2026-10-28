"""Move IQ events: activities the watch detected on its own (≥ ~10 min) without a recording.

Garmin keeps them only on the day timeline (`get_all_day_events`): type, start, end, minutes —
no GPS, heart rate, distance or calories. All types are stored locally; only cycling is read
(`detected_rides`), because walking is already in the daily steps and runs are recorded anyway.
Overlap with recorded rides is resolved by the readers (metrics/health.py)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import delete, inspect
from sqlmodel import Field, Session, SQLModel, select

from .config import settings
from .db import engine

REFRESH_DAYS = 3          # Garmin may still add events to the last days
THROTTLE = timedelta(hours=1)


class GarminMoveIq(SQLModel, table=True):
    __tablename__ = "garmin_moveiq"

    started_at: datetime = Field(primary_key=True)  # naive local wall time
    activity_type: str = Field(primary_key=True)
    day: date = Field(index=True)
    ended_at: datetime
    minutes: float


class GarminMoveIqDay(SQLModel, table=True):
    __tablename__ = "garmin_moveiq_days"

    day: date = Field(primary_key=True)
    fetched_at: datetime


def _event(raw: dict, day: date) -> GarminMoveIq | None:
    try:
        start = datetime.fromisoformat(str(raw["startTimestampLocal"]))
        end = datetime.fromisoformat(str(raw["endTimestampLocal"]))
        kind = str(raw.get("activityType") or "").strip().lower()
    except (KeyError, TypeError, ValueError):
        return None
    minutes = (end - start).total_seconds() / 60
    if not kind or not 0 < minutes <= 600:
        return None
    return GarminMoveIq(started_at=start, activity_type=kind, day=day, ended_at=end, minutes=round(minutes, 1))


def sync_moveiq(api, full: bool = False, *, now: datetime | None = None) -> dict:
    """Fetch unseen days plus the last REFRESH_DAYS; each fetched day replaces its stored events."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp, today = now.replace(tzinfo=None), now.astimezone(ZoneInfo(settings.timezone)).date()
    start = settings.watch_source_switch_date or today - timedelta(days=89)
    if not full:
        start = max(start, today - timedelta(days=89))
    with Session(engine) as session:
        fetched = {row.day: row.fetched_at for row in session.exec(select(GarminMoveIqDay)).all()}
    if not full and fetched and max(fetched.values()) > stamp - THROTTLE:
        return {"mode": "throttled", "days": 0, "events": 0, "errors": 0}
    days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    days = [d for d in days if full or d not in fetched or d > today - timedelta(days=REFRESH_DAYS)]
    result = {"mode": "full" if full else "incremental", "days": 0, "events": 0, "errors": 0}
    for day in days:
        try:
            payload = api.get_all_day_events(day.isoformat())
            if not isinstance(payload, list):
                raise ValueError
        except Exception:  # noqa: BLE001 -- only counts leave this boundary, never payloads
            result["errors"] += 1
            continue
        events = {(e.started_at, e.activity_type): e for raw in payload if isinstance(raw, dict)
                  if (e := _event(raw, day))}
        with Session(engine) as session:
            session.exec(delete(GarminMoveIq).where(GarminMoveIq.day == day))
            session.add_all(events.values())
            session.merge(GarminMoveIqDay(day=day, fetched_at=stamp))
            session.commit()
        result["days"] += 1
        result["events"] += len(events)
    return result


def detected_rides() -> pd.DataFrame:
    """Detected cycling windows (started_at, ended_at, minutes); recorded rides are not removed here."""
    with engine.connect() as con:
        if not inspect(con).has_table("garmin_moveiq"):
            return pd.DataFrame(columns=["started_at", "ended_at", "minutes"])
        df = pd.read_sql("SELECT started_at, ended_at, minutes FROM garmin_moveiq WHERE activity_type = 'cycling'",
                         con, parse_dates=["started_at", "ended_at"])
    return df.dropna(subset=["started_at", "ended_at"]).sort_values("started_at").reset_index(drop=True)
