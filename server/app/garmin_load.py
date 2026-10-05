"""Bounded optional Garmin running-tolerance reads; retain the last valid result."""
from datetime import date, datetime, timedelta, timezone
import json
import math
from zoneinfo import ZoneInfo

from sqlmodel import Field, Session, SQLModel

from .config import settings
from .db import engine


class GarminRunningTolerance(SQLModel, table=True):
    __tablename__ = "garmin_running_tolerance"
    key: str = Field(default="daily", primary_key=True)
    payload: str = "[]"
    status: str = "empty"
    attempted_at: datetime
    fetched_at: datetime | None = None


def _metres(value, positive=False):
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or not 0 <= value <= 2_000_000 or positive and value <= 0:
        return None
    return value / 1000


def normalize(raw, start, end):
    if not isinstance(raw, list) or len(raw) > 100:
        raise ValueError("Unexpected running-tolerance response.")
    by_day = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            day = date.fromisoformat(entry.get("calendarDate", ""))
        except (ValueError, TypeError):
            continue
        if not start <= day <= end:
            continue
        # Daily wire fields are metre-scaled; weekly totalImpactLoad is NOT acute load.
        tolerance = _metres(entry.get("acuteTolerance"), positive=True)
        if tolerance is None:
            continue
        by_day[day] = {"date": day.isoformat(), "tolerance_km": tolerance,
                       "acute_load_km": _metres(entry.get("acuteImpactLoad")),
                       "distance_km": _metres(entry.get("acuteDistance"))}
    return [by_day[day] for day in sorted(by_day)]


def sync_tolerance(api, *, full=False, force=False, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = now.replace(tzinfo=None)
    today = now.astimezone(ZoneInfo(settings.timezone)).date()
    start = max(settings.watch_source_switch_date or today - timedelta(days=89), today - timedelta(days=89))
    with Session(engine) as session:
        row = session.get(GarminRunningTolerance, "daily")
        if row and not full and not force and row.attempted_at > stamp - timedelta(hours=6):
            return {"status": "throttled", "requests": 0, "errors": 0}
        row = row or GarminRunningTolerance(attempted_at=stamp)
        row.attempted_at = stamp
        method = getattr(api, "get_running_tolerance", None)
        requests = 0
        if not callable(method):
            row.status = "unsupported"
        elif start > today:
            row.status = "empty"
        else:
            try:
                requests = 1
                raw = method(start.isoformat(), today.isoformat(), aggregation="daily")
                payload = normalize(raw, start, today)
                row.status = "available" if payload else "empty" if not raw else "unrecognized"
                if payload:
                    row.payload = json.dumps(payload, allow_nan=False)
                    row.fetched_at = stamp
            except Exception:
                row.status = "error"
        session.add(row)
        session.commit()
        return {"status": row.status, "requests": requests, "errors": int(row.status == "error")}


def tolerance_status(session, today):
    row = session.get(GarminRunningTolerance, "daily")
    payload = json.loads(row.payload) if row else []
    cutoff = settings.watch_source_switch_date or date.min
    eligible = [point for point in payload if cutoff <= date.fromisoformat(point["date"]) <= today]
    latest = eligible[-1] if eligible else {}
    status = row.status if row else "never"
    stale = bool(latest and (status != "available" or date.fromisoformat(latest["date"]) < today - timedelta(days=1)))
    reason = {"never": "Garmin-Lauftoleranz wird beim nächsten Import geprüft.",
              "empty": "Garmin liefert derzeit noch keine Lauftoleranz für dein Konto.",
              "unsupported": "Die Garmin-Verbindung stellt derzeit keine Lauftoleranz bereit.",
              "error": "Lauftoleranz konnte zuletzt nicht abgerufen werden; ein vorhandener Stand bleibt erhalten.",
              "unrecognized": "Garmins Lauftoleranz enthält noch keine sicher auswertbaren Tageswerte.",
              "available": "Lauftoleranz ist Garmins Schätzung aus deiner Laufhistorie."}[status]
    return {"source": "garmin_running_tolerance_daily", "available": bool(latest), "status": status,
            "stale": stale, "fetched_at": row.fetched_at.replace(tzinfo=timezone.utc).isoformat() if row and row.fetched_at else None,
            "date": latest.get("date"), "tolerance_km": latest.get("tolerance_km"),
            "acute_load_km": latest.get("acute_load_km"), "reason": reason}
