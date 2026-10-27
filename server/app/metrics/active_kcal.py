"""Aktive Kalorien je Tag (Übersicht), komplett aus Milons lokalen Daten — unabhängig von Garmins Schätzung.

Alles netto, also über dem Ruheumsatz (1 MET = 1 kcal je kg und Stunde), damit sich die Teile addieren lassen:
- Alltag: Tagesschritte der Uhr ohne die Schritte in Läufen (Kadenz) und auf dem Laufband (watch_steps),
  ACSM-Gehformel 0,1 ml O₂/kg/m × Schrittlänge (`walkpad_stride_m`).
- Laufen: ACSM-Laufformel 0,2 ml O₂/kg/m (≈ 1 kcal/kg/km).
- Rad indoor: gemessene Arbeit kJ / (24 % Wirkungsgrad × 4,184) minus Ruheanteil; ohne Watt MET 6,8.
- Rad draußen: MET nach Tempo (Compendium: < 16 km/h 4,0 · < 19 6,8 · < 22,5 8,0 · sonst 10,0).
- Laufband: ACSM mit Steigung (`walkpad.energy`), alle Walks.
- Gym (Hevy): MET 3,5 (Krafttraining, mehrere Übungen, 8–15 Wdh.).
Garmins activeKilocalories steht nur als Vergleich daneben. Nur Anzeige — nie zum adaptiven TDEE addieren."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import inspect

from .. import garmin_daily, walkpad
from ..config import settings
from ..db import engine

KCAL_PER_ML = 5 / 1000          # 5 kcal je Liter O₂
WALK_ML_PER_KG_M = 0.1
RUN_ML_PER_KG_M = 0.2
RUN_CADENCE = 165               # Schritte/min, um Laufschritte aus den Tagesschritten zu nehmen
BIKE_EFFICIENCY = 0.24
INDOOR_NO_POWER_MET = 6.8
GYM_MET = 3.5
PARTS = ("everyday", "run", "ride", "walkpad", "gym")


def _ride_met(speed_kmh: float) -> float:
    return 4.0 if speed_kmh < 16 else 6.8 if speed_kmh < 19 else 8.0 if speed_kmh < 22.5 else 10.0


def _kg(weights: pd.Series | None, day: date) -> float | None:
    from . import cycling
    if weights is None or weights.empty:
        return None
    return cycling._weight_at(weights, day) or float(weights.iloc[0])  # vor der ersten Messung: erste Messung


def _safe(read) -> pd.DataFrame:
    try:
        return read()
    except Exception:  # noqa: BLE001 -- eine fehlende Quelle kürzt nur ihren Anteil
        return pd.DataFrame()


def _add(out: dict, day: date, part: str, kcal: float) -> None:
    if kcal and kcal > 0:
        out.setdefault(day, dict.fromkeys(PARTS, 0.0))[part] += kcal


def compute(start: date, end: date) -> tuple[dict[date, dict], dict[date, int]]:
    """kcal je Tag und Teil sowie die Alltagsschritte, die in die Rechnung gingen."""
    from . import cycling, health, running

    weights = walkpad._weights()
    out: dict[date, dict] = {}
    excluded: dict[date, float] = {}   # Schritte, die in Lauf/Laufband schon stecken

    runs = _safe(running._runs)
    for r in runs.itertuples() if not runs.empty else []:
        day = r.started_at.date()
        if start <= day <= end and (kg := _kg(weights, day)):
            _add(out, day, "run", RUN_ML_PER_KG_M * r.distance_km * 1000 * kg * KCAL_PER_ML)
            excluded[day] = excluded.get(day, 0) + RUN_CADENCE * r.dur_min

    indoor = _safe(cycling.indoor_rides)
    for r in indoor.itertuples() if not indoor.empty else []:
        day, minutes = r.started_at.date(), (r.duration_seconds or 0) / 60
        if not (start <= day <= end and minutes > 0 and (kg := _kg(weights, day))):
            continue
        rest = kg * minutes / 60
        work = r.work_kj if pd.notna(r.work_kj) and r.work_kj > 0 else None
        _add(out, day, "ride", work / (BIKE_EFFICIENCY * 4.184) - rest if work else (INDOOR_NO_POWER_MET - 1) * rest)

    outdoor = _safe(health._rides)
    for r in outdoor.itertuples() if not outdoor.empty else []:
        day = r.started_at.date()
        if start <= day <= end and (kg := _kg(weights, day)):
            _add(out, day, "ride", (_ride_met(r.speed) - 1) * kg * r.dur_min / 60)

    with engine.connect() as con:
        walks = con.exec_driver_sql(
            "SELECT started_at, moving_s, distance_m, incline_pct, watch_steps FROM walkpad_sessions"
        ).fetchall() if inspect(con).has_table("walkpad_sessions") else []
        workouts = con.exec_driver_sql(
            "SELECT started_at, ended_at FROM workouts WHERE source='hevy' AND started_at IS NOT NULL AND ended_at IS NOT NULL"
        ).fetchall()
        steps = con.exec_driver_sql("SELECT day, steps FROM steps_daily WHERE day BETWEEN ? AND ?",
                                    (start.isoformat(), end.isoformat())).fetchall()

    for started, moving, dist, incline, watch in walks:
        day = datetime.fromisoformat(str(started)).date()
        if start <= day <= end:
            _add(out, day, "walkpad", walkpad.energy(dist, moving, incline or 0, _kg(weights, day))["kcal"] or 0)
            excluded[day] = excluded.get(day, 0) + (watch or 0)

    for started, ended in workouts:
        begin, finish = datetime.fromisoformat(str(started)), datetime.fromisoformat(str(ended))
        hours = (finish - begin).total_seconds() / 3600
        if start <= begin.date() <= end and 0 < hours <= 4 and (kg := _kg(weights, begin.date())):
            _add(out, begin.date(), "gym", (GYM_MET - 1) * kg * hours)

    everyday: dict[date, int] = {}
    stride = settings.walkpad_stride_m
    for day, count in steps:
        day = date.fromisoformat(str(day)[:10])
        rest = max(0, int(count or 0) - round(excluded.get(day, 0)))
        everyday[day] = rest
        if kg := _kg(weights, day):
            _add(out, day, "everyday", WALK_ML_PER_KG_M * rest * stride * kg * KCAL_PER_ML)
    return out, everyday


def daily(days: int = 14, *, now: datetime | None = None) -> dict:
    today = (now or datetime.now(ZoneInfo(settings.timezone))).astimezone(ZoneInfo(settings.timezone)).date()
    start = today - timedelta(days=days - 1)
    parts, steps = compute(start, today)
    try:
        garmin = {p["date"]: p["total"] for p in garmin_daily.active_calories(days, now=now)["series"]}
    except Exception:  # noqa: BLE001 -- Vergleichswert ist optional
        garmin = {}
    series = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        values = {k: round(v) for k, v in parts.get(day, dict.fromkeys(PARTS, 0.0)).items()}
        if day not in parts and day not in steps:
            continue
        series.append({"date": day.isoformat(), "total": sum(values.values()), **values,
                       "steps": steps.get(day), "garmin": garmin.get(day.isoformat()), "provisional": day == today})
    full = [p["total"] for p in series if not p["provisional"]][-7:]
    latest = series[-1] if series else None
    return {"today": latest if latest and latest["provisional"] else None, "latest": latest,
            "avg7": round(sum(full) / len(full)) if full else None, "avg7_days": len(full),
            "stride_m": settings.walkpad_stride_m, "gym_met": GYM_MET, "series": series}
