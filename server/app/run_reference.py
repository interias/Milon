"""A user-selected route anchor with descriptive, sensor-separated observations."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import defer
from sqlmodel import Field, Session, SQLModel, select

from .config import settings
from .db import engine
from .garmin_activity import GarminActivity
from .garmin_routes import GarminRoute
from .metrics import run_insights as insights
from .models import RunFitnessReference


class RunRouteReference(SQLModel, table=True):
    __tablename__ = "run_route_reference"

    id: int = Field(default=1, primary_key=True)
    activity_id: str
    selected_at: datetime


METHOD = (
    "Feste Referenzaufzeichnung, gleiche Laufrichtung und ähnlicher GPS-Verlauf: "
    "90 % der Streckenpositionen höchstens 120 m auseinander, Start und Ziel höchstens 150 m. "
    "Distanz höchstens ±10 %, aktive und verstrichene Dauer höchstens ±20 % zur Referenz. "
    "Nur vollständige Garmin-Aufzeichnungen derselben eingetragenen Sensorperiode. "
    "Verglichen werden gleichmäßige Minuten ab Minute 10 bis zwei Minuten vor dem Ende, "
    "höchstens bis zum entsprechenden Ende der Referenz. Tempo höchstens 0,1 m/s und "
    "Steigung höchstens 0,5 Prozentpunkte auseinander, mindestens sechs einmalig gepaarte Minuten. "
    "Die ausgewählten Minuten können je Lauf variieren; dies ist kein standardisierter Test. "
    "Einzelne Beobachtungen, keine Signifikanz oder nachgewiesene Fitnessveränderung. "
    "Wetter, Tagesform und nicht eingetragene Sensorwechsel bleiben mögliche Einflüsse."
)


def _brief(row):
    summary = json.loads(row.summary_json)
    return {"activity_id": row.activity_id, "title": summary.get("title") or "Lauf",
            "started_at": row.started_at.isoformat(), "distance_km": summary.get("distance_km")}


def _boundaries(session):
    boundaries = {}
    if settings.watch_source_switch_date:
        boundaries[settings.watch_source_switch_date] = "Garmin"
    row = session.exec(select(RunFitnessReference).order_by(RunFitnessReference.id.desc())).first()
    if row:
        for change in json.loads(row.payload).get("sensor_changes", []):
            boundaries[date.fromisoformat(change["date"])] = change["label"]
    return sorted(boundaries.items())


def _period(day, boundaries):
    return next(((start, label) for start, label in reversed(boundaries) if start <= day), (date.min, "Garmin"))


def _reason(row, route, annotations):
    if row is None:
        return "Laufaufzeichnung nicht gefunden."
    summary, series, quality = insights._load(row)
    if not insights._eligible(row, summary, quality, annotations):
        return "Nur vollständige, freigegebene Garmin-Läufe können als Referenz dienen."
    if insights._route_signature(route) is None:
        return "Für die Referenz fehlt eine durchgehende GPS-Strecke von mindestens 1 km."
    if len(insights.steady_minutes(summary, series)) < 6:
        return "Für die Referenz fehlen sechs gleichmäßige Minuten mit Puls, Tempo und Höhe."
    return None


def selection(activity_id=None):
    with Session(engine) as session:
        saved = session.get(RunRouteReference, 1)
        anchor = session.get(GarminActivity, saved.activity_id) if saved else None
        result = {"reference": _brief(anchor) if anchor else None, "selectable": None, "reason": None}
        if activity_id:
            row = session.get(GarminActivity, activity_id)
            reason = _reason(row, session.get(GarminRoute, activity_id), insights._annotations(session))
            result.update(selectable=reason is None, reason=reason)
        return result


def choose(activity_id):
    with Session(engine) as session:
        row = session.get(GarminActivity, activity_id)
        reason = _reason(row, session.get(GarminRoute, activity_id), insights._annotations(session))
        if reason:
            raise ValueError(reason)
        saved = session.get(RunRouteReference, 1) or RunRouteReference(activity_id=activity_id, selected_at=datetime.now())
        saved.activity_id = activity_id
        saved.selected_at = datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None)
        session.add(saved)
        session.commit()
    return selection(activity_id)


def clear():
    with Session(engine) as session:
        saved = session.get(RunRouteReference, 1)
        if saved:
            session.delete(saved)
            session.commit()
    return selection()


def overview(days=365, today=None):
    today = today or datetime.now(ZoneInfo(settings.timezone)).date()
    start = today - timedelta(days=days - 1)
    result = {"status": "unset", "reference": None, "observations": [], "days": days,
              "period_start": start.isoformat(), "period_end": today.isoformat(),
              "sensor_since": None, "sensor_label": None, "reason": None, "method": METHOD}
    with Session(engine) as session:
        saved = session.get(RunRouteReference, 1)
        if saved is None:
            return result
        anchor = session.get(GarminActivity, saved.activity_id)
        route = session.get(GarminRoute, saved.activity_id)
        annotations = insights._annotations(session)
        reason = _reason(anchor, route, annotations)
        result.update(status="unavailable" if reason else "ready", reason=reason,
                      reference=_brief(anchor) if anchor else None)
        if reason:
            return result
        summary, series, _ = insights._load(anchor)
        minutes = insights.steady_minutes(summary, series)
        boundaries = _boundaries(session)
        period = _period(anchor.started_at.date(), boundaries)
        result.update(sensor_since=period[0].isoformat() if period[0] != date.min else None, sensor_label=period[1])
        rows = session.exec(select(GarminActivity).options(
            defer(GarminActivity.series_json), defer(GarminActivity.laps_json), defer(GarminActivity.zones_json)).where(
            GarminActivity.started_at >= datetime.combine(start, datetime.min.time()),
            GarminActivity.started_at < datetime.combine(today + timedelta(days=1), datetime.min.time()),
            GarminActivity.activity_id != anchor.activity_id).order_by(GarminActivity.started_at)).all()
        for row in rows:
            other, quality = json.loads(row.summary_json), json.loads(row.quality_json)
            if not insights._eligible(row, other, quality, annotations) or _period(row.started_at.date(), boundaries) != period:
                continue
            if any(not insights._number(summary.get(key)) or summary[key] <= 0
                   or not insights._number(other.get(key)) or abs(other[key] / summary[key] - 1) > tolerance
                   for key, tolerance in (("distance_km", .1), ("duration_seconds", .2), ("elapsed_seconds", .2))):
                continue
            if not insights.similar_route(route, session.get(GarminRoute, row.activity_id)):
                continue
            points = json.loads(row.series_json)
            other_minutes = [point for point in insights.steady_minutes(other, points)
                             if point["minute"] * 60 < summary["elapsed_seconds"] - 120]
            comparison = insights._comparison(insights._match(minutes, other_minutes))
            if comparison["status"] != "observed":
                continue
            result["observations"].append({**_brief(row), **{key: comparison[key] for key in
                ("matched_pairs", "hr_delta_bpm", "pace_delta_seconds", "first_hr", "second_hr")}})
    return result
