"""Local month-end snapshots from bounded observations and exportable month recaps."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.orm import defer
from sqlmodel import Session, select

from ..config import settings
from ..db import engine
from ..garmin_activity import GarminActivity
from ..garmin_routes import GarminRoute
from ..models import RunFitnessReference
from . import run_fitness, run_standardization, strength
from .route_atlas import _contour
from .run_analysis import _SESSION_SQL


def _now(now):
    zone = ZoneInfo(settings.timezone)
    value = now or datetime.now(zone)
    return value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)


def _inputs(cutoff):
    with engine.connect() as connection:
        weights = pd.read_sql("SELECT measured_at, weight_kg FROM body_measurements WHERE weight_kg > 0 AND measured_at <= ?",
                              connection, params=(cutoff.isoformat(sep=" "),), parse_dates=["measured_at"])
        sessions = pd.read_sql(_SESSION_SQL, connection, parse_dates=["started_at", "ended_at"])
        windows = pd.read_sql("SELECT external_id, minute, speed_m_min, hr_bpm, coverage, steady, source FROM run_minutes WHERE model_version='shr-v1'", connection)
        sets = pd.read_sql("SELECT ws.exercise, ws.weight_kg, ws.reps, w.started_at FROM workout_sets ws "
                           "JOIN workouts w ON w.id=ws.workout_id WHERE w.source='hevy' AND ws.set_type='normal' "
                           "AND ws.weight_kg > 0 AND ws.reps > 0 AND w.started_at <= ?", connection,
                           params=(cutoff.isoformat(sep=" "),), parse_dates=["started_at"])
        workouts = pd.read_sql("SELECT started_at FROM workouts WHERE source='hevy' AND started_at <= ?", connection,
                               params=(cutoff.isoformat(sep=" "),), parse_dates=["started_at"])
    sessions = sessions[(sessions.started_at <= cutoff) & (sessions.ended_at <= cutoff)].copy()
    if not sets.empty:
        sets["day"] = sets.started_at.dt.floor("D")
        sets["month"] = sets.started_at.dt.to_period("M")
        sets["mg"] = sets.exercise.map(strength._muscle_group)
        sets["e1rm_c"] = sets.weight_kg * (1 + sets.reps.clip(upper=12) / 30)
    with Session(engine) as session:
        reference = session.exec(select(RunFitnessReference).order_by(RunFitnessReference.id.desc())).first()
    changes = json.loads(reference.payload).get("sensor_changes", []) if reference else []
    boundaries = sorted({date.fromisoformat(change["date"]) for change in changes}
                        | ({settings.watch_source_switch_date} if settings.watch_source_switch_date else set()))
    return weights, sessions, windows, sets, workouts, boundaries


def _weight(weights, day):
    selected = weights[(weights.measured_at.dt.date >= day - timedelta(days=6)) & (weights.measured_at.dt.date <= day)]
    daily = selected.groupby(selected.measured_at.dt.date).weight_kg.mean()
    return {"value": round(float(daily.mean()), 1) if len(daily) else None, "days": len(daily),
            "date": max(daily.index).isoformat() if len(daily) else None}


def _strength(sets, day):
    selected = sets[sets.started_at.dt.date <= day].copy()
    if selected.empty:
        return {"value": None, "exercises": 0, "date": None, "basis": []}
    counts = selected.groupby("exercise").day.nunique()
    selected = selected[selected.exercise.isin(counts[counts >= 3].index)]
    if selected.empty:
        return {"value": None, "exercises": 0, "date": None, "basis": []}
    raw, baskets, months, _ = strength._monthly_backbone(selected)
    last = selected.started_at.max().date()
    # The backbone carries forward thin links. That fallback is not a measured
    # historical index and must not become a numeric snapshot.
    overlap = len(set(baskets[months[-1]]) & set(baskets[months[-2]])) if len(months) >= 2 else 0
    note = None
    if last.strftime("%Y-%m") != day.strftime("%Y-%m"):
        note = "Keine geeigneten Arbeitssätze in diesem Monat."
    elif overlap < 3:
        note = "Weniger als drei gemeinsame Übungen im letzten Monatsvergleich."
    value = round((raw[months[-1]] + raw[months[-2]]) / 2) if note is None else None
    return {"value": value, "exercises": len(baskets[months[-1]]), "date": last.isoformat(),
            "basis": sorted(selected.exercise.unique().tolist()), "note": note, "comparable_exercises": overlap}


def _run(sessions, windows, boundaries, day):
    lower = max((value for value in boundaries if value <= day), default=date.min)
    start = max(lower, day - timedelta(days=55))
    selected = sessions[(sessions.started_at.dt.date >= start) & (sessions.started_at.dt.date <= day)
                        & (sessions.ended_at.dt.date <= day)]
    legacy = set(getattr(settings, "watch_source_legacy_session_ids", []))
    selected = selected[~selected.external_id.isin(legacy)]
    result = {"value": None, "runs": 0, "sensor_from": lower.isoformat(), "status": "insufficient"}
    if selected.empty or windows.empty:
        return result
    bounded_windows = windows[windows.external_id.isin(selected.external_id)]
    frame, _ = run_standardization._prepare(bounded_windows, selected, day)
    frame = run_standardization.select(frame, warmup=10, end=45)
    point = run_fitness._point(frame, day, 360, 30, 1000)
    return {**result, "value": point["hr"], "runs": point["runs"], "status": point["status"]}


def history(*, now: datetime | None = None):
    local = _now(now)
    inputs = _inputs(local.replace(tzinfo=None))
    weights, sessions, windows, sets, workouts, boundaries = inputs
    dates = [frame[column].min() for frame, column in ((weights, "measured_at"), (sessions, "started_at"),
             (sets, "started_at"), (workouts, "started_at")) if not frame.empty]
    first = min(dates).date().replace(day=1) if dates else local.date().replace(day=1)
    months = pd.period_range(first, local.date(), freq="M")
    points = []
    for month in months:
        day = min(month.end_time.date(), local.date())
        points.append({"month": str(month), "as_of": day.isoformat(), "partial": str(month) == local.strftime("%Y-%m"),
                       "body": _weight(weights, day), "running": _run(sessions, windows, boundaries, day),
                       "strength": _strength(sets, day)})
    current = points[-1]
    for point in points:
        for key in ("body", "running", "strength"):
            before, after = point[key]["value"], current[key]["value"]
            comparable = key != "running" or point[key]["sensor_from"] == current[key]["sensor_from"]
            note = "Sensorwechsel seit diesem Monat." if not comparable else None
            if key == "strength" and point[key]["basis"] != current[key]["basis"]:
                comparable = False
                note = "Die für den Index verfügbaren Übungen haben sich verändert."
            point[key]["change_to_now"] = round(after - before, 2) if comparable and before is not None and after is not None else None
            point[key]["comparison_note"] = note
    for point in points:
        point["strength"].pop("basis")
    return {"points": points, "timezone": settings.timezone,
            "note": "Bis zum Stichtag gemessene Daten, mit heutiger Quellenklärung neu berechnet. Gewicht: letzte 7 Kalendertage. Puls: 6:00/km bei Minute 30, letzte 56 Tage; kein Vergleich über Sensorwechsel. Kraft: damaliger Übungskorb im Monatsindex; Unterschiede nur bei unveränderter Übungsbasis. Fehlende Monate werden nicht fortgeschrieben."}


def monthly(month: str, *, now: datetime | None = None):
    local = _now(now)
    period = pd.Period(month, freq="M")
    if period > pd.Period(local.date(), freq="M"):
        raise ValueError("Zukünftige Monate sind nicht verfügbar.")
    start = period.start_time.to_pydatetime()
    end = min((period + 1).start_time.to_pydatetime(), local.replace(tzinfo=None))
    # Recaps assign completed activities to their local start day, including
    # runs finishing after midnight on the first day of the next month.
    weights, sessions, _, _, workouts, _ = _inputs(local.replace(tzinfo=None))
    runs = sessions[(sessions.started_at >= start) & (sessions.started_at < end)].copy()
    minutes = (runs.ended_at - runs.started_at).dt.total_seconds() / 60
    distance = runs.distance_km
    valid = distance.between(1, 60) & minutes.between(5, 600, inclusive="neither") & (minutes / distance).between(3, 12)
    runs = runs[valid]
    gym = workouts[(workouts.started_at >= start) & (workouts.started_at < end)]
    with Session(engine) as session:
        routes = session.exec(select(GarminRoute).where(GarminRoute.started_at >= start, GarminRoute.started_at < end)
                              .order_by(GarminRoute.started_at)).all()
        activities = session.exec(select(GarminActivity).options(defer(GarminActivity.series_json), defer(GarminActivity.laps_json),
                                  defer(GarminActivity.zones_json)).order_by(GarminActivity.fetched_at.desc())).all()
    by_id = {row.activity_id: row for row in activities}
    available = {route.activity_id for route in routes}
    aliases, chosen = set(), set()
    for row in activities:
        key = row.canonical_external_id or f"garmin:{row.activity_id}"
        if row.activity_id in available and key not in aliases:
            chosen.add(row.activity_id)
            aliases.add(key)
    contours = [{"activity_id": route.activity_id, "contour": _contour(route)} for route in routes
                if route.activity_id not in by_id or route.activity_id in chosen]
    first_weight = _weight(weights, start.date() + timedelta(days=6))
    last_weight = _weight(weights, (end - timedelta(microseconds=1)).date())
    separate = (end.date() - start.date()).days >= 14
    weight_delta = round(last_weight["value"] - first_weight["value"], 1) if separate and min(first_weight["days"], last_weight["days"]) >= 3 else None
    return {"month": str(period), "from_date": start.date().isoformat(), "to_date": min(period.end_time.date(), local.date()).isoformat(),
            "partial": period == pd.Period(local.date(), freq="M"), "running_km": round(float(runs.distance_km.sum()), 1),
            "runs": len(runs), "strength_sessions": len(gym), "training_days": len(set(runs.started_at.dt.date) | set(gym.started_at.dt.date)),
            "weight_delta_kg": weight_delta, "weight_first_days": first_weight["days"], "weight_last_days": last_weight["days"],
            "routes": contours, "route_count": len(contours),
            "note": "Erfasste Einheiten; Laufkilometer aus der bereinigten Aktivitätstabelle. Konturen zeigen verfügbare Garmin-GPS-Aufzeichnungen. Gewicht: letzte gegen erste sieben Kalendertage, mindestens drei Messtage je Fenster."}
