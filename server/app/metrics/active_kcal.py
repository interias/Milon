"""Aktive Kalorien je Tag (Übersicht): Garmin als Basis plus Milons Schätzung für das, was Garmin fehlt.

Garmin: activeKilocalories = Alltag (wellnessActiveKilocalories, schrittbasiert) + aufgezeichnete
Aktivitäten (Läufe, Fahrten, hochgeladene Laufband-Walks). Dazu kommen:
- Laufband-Walks, die nicht zu Garmin hochgeladen sind: ACSM-Netto-kcal, aber nur der Anteil der
  Pad-Schritte, die die Uhr nicht gezählt hat (die gezählten stecken schon in Garmins Alltag).
- Hevy-Krafttrainings: Garmin kennt sie nicht (Annahme: Gym wird nicht auf der Uhr aufgezeichnet).
  Netto-kcal = (MET − 1) × kg × h mit MET 3,5 (Compendium, Krafttraining mehrere Übungen, 8–15 Wdh.).
Nur Anzeige — nie zum adaptiven TDEE addieren (das enthält die Bewegung schon)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import inspect

from .. import garmin_daily, walkpad
from ..config import settings
from ..db import engine

GYM_MET = 3.5
IN_GARMIN = ("uploaded", "duplicate")


def _walks(start: date, weights) -> dict[date, float]:
    from . import cycling
    out: dict[date, float] = {}
    with engine.connect() as con:
        if not inspect(con).has_table("walkpad_sessions"):
            return out
        rows = con.exec_driver_sql(
            "SELECT started_at, moving_s, distance_m, incline_pct, watch_steps, garmin_status FROM walkpad_sessions"
        ).fetchall()
    for started, moving, dist, incline, watch, status in rows:
        day = datetime.fromisoformat(str(started)).date()
        if day < start or status in IN_GARMIN:
            continue
        kg = cycling._weight_at(weights, day) if weights is not None else None
        kcal = walkpad.energy(dist, moving, incline or 0, kg)["kcal"]
        steps = walkpad.steps_of(dist)
        if kcal and steps:
            share = max(0, steps - (watch or 0)) / steps
            out[day] = out.get(day, 0.0) + kcal * share
    return out


def _gym(start: date, weights) -> dict[date, float]:
    from . import cycling
    out: dict[date, float] = {}
    with engine.connect() as con:
        rows = con.exec_driver_sql(
            "SELECT started_at, ended_at FROM workouts WHERE source='hevy' AND started_at IS NOT NULL AND ended_at IS NOT NULL"
        ).fetchall()
    for started, ended in rows:
        begin, end = datetime.fromisoformat(str(started)), datetime.fromisoformat(str(ended))
        hours = (end - begin).total_seconds() / 3600
        kg = cycling._weight_at(weights, begin.date()) if weights is not None else None
        if begin.date() >= start and kg and 0 < hours <= 4:
            out[begin.date()] = out.get(begin.date(), 0.0) + (GYM_MET - 1) * kg * hours
    return out


def daily(days: int = 14, *, now: datetime | None = None) -> dict:
    today = (now or datetime.now(ZoneInfo(settings.timezone))).astimezone(ZoneInfo(settings.timezone)).date()
    start = today - timedelta(days=days - 1)
    garmin = {p["date"]: p for p in garmin_daily.active_calories(days, now=now)["series"]}
    weights = walkpad._weights()
    walks, gym = _walks(start, weights), _gym(start, weights)
    series = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        g = garmin.get(day.isoformat())
        walk, strength = round(walks.get(day, 0)), round(gym.get(day, 0))
        if g is None and not walk and not strength:
            continue
        everyday = g["everyday"] if g else None
        training = g["training"] if g else None
        if g and everyday is None:  # no split available: count Garmin's total as everyday movement
            everyday, training = g["total"], 0
        series.append({"date": day.isoformat(), "total": (g["total"] if g else 0) + walk + strength,
                       "everyday": everyday, "training": training, "walkpad": walk, "gym": strength,
                       "garmin": g is not None, "provisional": day == today,
                       "synced_at": g["synced_at"] if g else None})
    full = [p["total"] for p in series if not p["provisional"] and p["garmin"]][-7:]
    latest = series[-1] if series else None
    return {"today": latest if latest and latest["provisional"] else None, "latest": latest,
            "avg7": round(sum(full) / len(full)) if full else None, "avg7_days": len(full),
            "gym_met": GYM_MET, "series": series}
