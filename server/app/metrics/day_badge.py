"""Tages-Badge „Heute geschafft“ (Übersicht): alles Sportliche eines Tages in einer Antwort, zum Teilen als Bild.

Datenschutz (Entscheidung User 2026-11-08): das Bild wird geteilt, die Heimat darf sich daraus nicht ablesen
lassen. Deshalb liefert die API nie Koordinaten, Orts- oder Garmin-Titel (die können Ortsnamen tragen):
- GPS-Routen kommen nur als Linienform zurück: Start und Ende um `PRIVACY_TRIM_M` gekürzt (Privatzone wie
  bei Strava), dann in ein Einheitsquadrat skaliert — ohne Lage, Maßstab und Kartenhintergrund.
- Routen unter `MIN_SHAPE_M` haben nach dem Kürzen kaum Form übrig → keine Linie.
- Zwift-Spuren sind Positionen auf dem Kartenbild einer virtuellen Welt (kein echter Ort) und werden nur skaliert.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import inspect

from ..config import settings
from ..db import engine

PRIVACY_TRIM_M = 500
MIN_SHAPE_M = 1500
MAX_SHAPE_POINTS = 160
MATCH_S = 180          # Session ↔ GPS-Route: Startzeit ±3 min
STEP_GOAL = 10_000
WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def _today() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def _safe(read, default=None):
    try:
        return read()
    except Exception:  # noqa: BLE001 -- eine fehlende Quelle kürzt nur ihren Teil des Badges
        return pd.DataFrame() if default is None else default


def _on(df: pd.DataFrame, day: date) -> pd.DataFrame:
    if df is None or df.empty or "started_at" not in df:
        return pd.DataFrame()
    return df[pd.to_datetime(df["started_at"]).dt.date == day].sort_values("started_at")


def _num(value, digits: int = 1):
    return None if value is None or pd.isna(value) else round(float(value), digits)


# --- Linienform ------------------------------------------------------------------------------------------

def _fit(points: list[tuple[float, float]], *, flip_y: bool) -> list[list[float]] | None:
    """Ins Einheitsquadrat skalieren (längere Seite = 1, kürzere zentriert), höchstens MAX_SHAPE_POINTS."""
    if len(points) < 2:
        return None
    step = max(1, math.ceil(len(points) / MAX_SHAPE_POINTS))
    pts = points[::step] + ([points[-1]] if (len(points) - 1) % step else [])
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    if span <= 0:
        return None
    ox = (1 - (max(xs) - min(xs)) / span) / 2
    oy = (1 - (max(ys) - min(ys)) / span) / 2
    return [[round(ox + (x - min(xs)) / span, 3),
             round(oy + ((max(ys) - y) if flip_y else (y - min(ys))) / span, 3)] for x, y in pts]


def anonymize_shape(latlon: list[tuple[float, float]]) -> list[list[float]] | None:
    """GPS-Punkte → anonyme Linienform. Ohne Lage/Maßstab, Start und Ende um PRIVACY_TRIM_M gekürzt."""
    if len(latlon) < 2:
        return None
    lat0 = math.radians(latlon[0][0])
    metres = [((lon - latlon[0][1]) * 111_320 * math.cos(lat0), (lat - latlon[0][0]) * 110_540)
              for lat, lon in latlon]
    cum = [0.0]
    for (x1, y1), (x2, y2) in zip(metres, metres[1:]):
        cum.append(cum[-1] + math.hypot(x2 - x1, y2 - y1))
    total = cum[-1]
    if total < MIN_SHAPE_M:
        return None
    lo, hi = PRIVACY_TRIM_M, total - PRIVACY_TRIM_M

    def at(d: float) -> tuple[float, float]:
        i = next(k for k in range(1, len(cum)) if cum[k] >= d)
        seg = cum[i] - cum[i - 1]
        t = 0.0 if seg <= 0 else (d - cum[i - 1]) / seg
        (x1, y1), (x2, y2) = metres[i - 1], metres[i]
        return x1 + t * (x2 - x1), y1 + t * (y2 - y1)

    kept = [at(lo)] + [p for p, d in zip(metres, cum) if lo < d < hi] + [at(hi)]
    return _fit(kept, flip_y=True)


def _route_points(segments_json: str | None) -> list[tuple[float, float]]:
    try:
        segments = json.loads(segments_json or "[]")
    except ValueError:
        return []
    return [(p["lat"], p["lon"]) for seg in segments for p in seg
            if isinstance(p, dict) and p.get("lat") is not None and p.get("lon") is not None]


def _zwift_shape(track_json: str | None) -> list[list[float]] | None:
    try:
        segments = json.loads(track_json or "{}").get("segments") or []
    except (ValueError, AttributeError):
        return None
    return _fit([(p[0], p[1]) for seg in segments for p in seg if len(p) >= 2], flip_y=False)


# --- Quellen ---------------------------------------------------------------------------------------------

def _tracks(table: str, day: date) -> list[dict]:
    """GPS-Spuren des Tages aus garmin_routes (Läufe) bzw. garmin_rides (Rad)."""
    with engine.connect() as con:
        if not inspect(con).has_table(table):
            return []
        rows = con.exec_driver_sql(
            f"SELECT activity_id, started_at, distance_km, duration_seconds, segments_json FROM {table} "
            "WHERE started_at >= ? AND started_at < ?",
            (day.isoformat(), (day + timedelta(days=1)).isoformat())).fetchall()
    return [{"id": str(r[0]), "start": pd.Timestamp(r[1]), "km": r[2], "seconds": r[3], "segments": r[4]}
            for r in rows]


def _take_track(tracks: list[dict], start: pd.Timestamp) -> dict | None:
    best = min(tracks, key=lambda t: abs((t["start"] - start).total_seconds()), default=None)
    if best is None or abs((best["start"] - start).total_seconds()) > MATCH_S:
        return None
    tracks.remove(best)
    return best


def _clock(ts) -> str:
    return pd.Timestamp(ts).strftime("%H:%M")


def _runs(day: date) -> list[dict]:
    from . import running

    tracks = _tracks("garmin_routes", day)
    out = []
    for r in _on(_safe(running._runs), day).itertuples():
        track = _take_track(tracks, pd.Timestamp(r.started_at))
        out.append({"time": _clock(r.started_at), "km": _num(r.distance_km, 2), "minutes": _num(r.dur_min),
                    "pace_s": round(r.dur_min * 60 / r.distance_km) if r.distance_km else None,
                    "avg_hr": _num(getattr(r, "avg_hr", None), 0),
                    "shape": anonymize_shape(_route_points(track["segments"])) if track else None})
    for t in tracks:  # GPS-Lauf ohne (noch) importierte Session
        minutes = (t["seconds"] or 0) / 60
        if not t["km"] or minutes <= 0:
            continue
        out.append({"time": _clock(t["start"]), "km": _num(t["km"], 2), "minutes": _num(minutes),
                    "pace_s": round(minutes * 60 / t["km"]), "avg_hr": None,
                    "shape": anonymize_shape(_route_points(t["segments"]))})
    return sorted(out, key=lambda x: x["time"])


def _indoor_tracks(ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    with engine.connect() as con:
        if not inspect(con).has_table("garmin_indoor_rides"):
            return {}
        marks = ",".join("?" * len(ids))
        rows = con.exec_driver_sql(
            f"SELECT activity_id, track_json FROM garmin_indoor_rides WHERE activity_id IN ({marks})",
            tuple(ids)).fetchall()
    return {str(a): t for a, t in rows}


def _rides(day: date) -> list[dict]:
    from . import cycling, health

    out = []
    tracks = _tracks("garmin_rides", day)
    for r in _on(_safe(health._rides), day).itertuples():
        track = _take_track(tracks, pd.Timestamp(r.started_at))
        out.append({"kind": "outdoor", "time": _clock(r.started_at), "km": _num(r.distance_km),
                    "minutes": _num(r.dur_min), "world": None, "avg_power_w": None, "elevation_m": None,
                    "shape": anonymize_shape(_route_points(track["segments"])) if track else None})
    indoor = _on(_safe(cycling.indoor_rides), day)
    shapes = _indoor_tracks([str(i) for i in indoor["activity_id"]]) if not indoor.empty else {}
    for r in indoor.itertuples():
        out.append({"kind": "indoor", "time": _clock(r.started_at), "km": _num(r.distance_km),
                    "minutes": _num((r.duration_seconds or 0) / 60), "world": r.world or None,
                    "avg_power_w": _num(r.avg_power_w, 0), "elevation_m": _num(r.elevation_gain_m, 0),
                    "shape": _zwift_shape(shapes.get(str(r.activity_id)))})
    for r in _on(_safe(health._detected_rides), day).itertuples():
        out.append({"kind": "detected", "time": _clock(r.started_at), "km": None, "minutes": _num(r.dur_min),
                    "world": None, "avg_power_w": None, "elevation_m": None, "shape": None})
    return sorted(out, key=lambda x: x["time"])


def _strength(day: date) -> list[dict]:
    with engine.connect() as con:
        rows = con.exec_driver_sql(
            "SELECT w.started_at, w.ended_at, w.title, "
            "SUM(CASE WHEN COALESCE(s.set_type, 'normal') != 'warmup' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN COALESCE(s.set_type, 'normal') != 'warmup' THEN COALESCE(s.weight_kg, 0) * COALESCE(s.reps, 0) ELSE 0 END), "
            "COUNT(DISTINCT s.exercise) "
            "FROM workouts w LEFT JOIN workout_sets s ON s.workout_id = w.id "
            "WHERE w.source = 'hevy' AND w.started_at >= ? AND w.started_at < ? "
            "GROUP BY w.id ORDER BY w.started_at",
            (day.isoformat(), (day + timedelta(days=1)).isoformat())).fetchall()
    out = []
    for started, ended, title, sets, tonnage, exercises in rows:
        begin = pd.Timestamp(started)
        minutes = (pd.Timestamp(ended) - begin).total_seconds() / 60 if ended else None
        out.append({"time": _clock(begin), "title": title or "Krafttraining",
                    "minutes": _num(minutes) if minutes and 0 < minutes <= 240 else None,
                    "sets": int(sets or 0), "exercises": int(exercises or 0), "tonnage_kg": round(tonnage or 0)})
    return out


def _walks(day: date) -> list[dict]:
    from .. import walkpad

    with engine.connect() as con:
        if not inspect(con).has_table("walkpad_sessions"):
            return []
        rows = con.exec_driver_sql(
            "SELECT started_at, moving_s, distance_m, incline_pct FROM walkpad_sessions "
            "WHERE started_at >= ? AND started_at < ? ORDER BY started_at",
            (day.isoformat(), (day + timedelta(days=1)).isoformat())).fetchall()
    return [{"time": _clock(s), "minutes": _num((m or 0) / 60), "km": _num((d or 0) / 1000, 2),
             "incline_pct": _num(i or 0), "steps": walkpad.steps_of(d or 0)} for s, m, d, i in rows]


def _steps(day: date) -> int | None:
    from . import health

    df = _safe(health._steps)
    if df.empty:
        return None
    hit = df[pd.to_datetime(df["day"]).dt.date == day]
    return int(hit["steps"].sum()) if not hit.empty else None


def _active_kcal(day: date) -> int | None:
    from . import active_kcal

    parts = _safe(lambda: active_kcal.compute(day, day)[0], default={}).get(day)
    return round(sum(parts.values())) if parts else None


def badge(day: date | None = None) -> dict:
    today = _today()
    day = day or today
    runs, rides, strength, walks = _runs(day), _rides(day), _strength(day), _walks(day)
    steps = _steps(day)
    minutes = sum(x["minutes"] or 0 for group in (runs, rides, strength, walks) for x in group)
    km = {"run": round(sum(r["km"] or 0 for r in runs), 2),
          "ride": round(sum(r["km"] or 0 for r in rides if r["kind"] == "outdoor"), 1),
          "zwift": round(sum(r["km"] or 0 for r in rides if r["kind"] == "indoor"), 1),
          "walk": round(sum(w["km"] or 0 for w in walks), 2)}
    sessions = len(runs) + len(rides) + len(strength) + len(walks)
    return {"date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "is_today": day == today,
            "steps": steps, "step_goal": STEP_GOAL, "active_kcal": _active_kcal(day),
            "active_minutes": round(minutes), "sessions": sessions, "km": km,
            "runs": runs, "rides": rides, "strength": strength, "walks": walks,
            "empty": sessions == 0 and not steps,
            "privacy": {"trim_m": PRIVACY_TRIM_M, "min_shape_m": MIN_SHAPE_M}}
