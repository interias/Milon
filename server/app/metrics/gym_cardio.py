"""Cardio-Sätze aus Hevy (Laufband, Spinning, Treppe) — aktive kcal statt Krafttraining-Pauschale.

Hevy liefert je Satz Strecke und Dauer, aber keine Steigung. Steigung des Laufbands, in dieser Reihenfolge:
eigene Änderung (Tabelle `gym_cardio_incline`) › Zahl mit % in der Übungsnotiz (`12%`) › Einstellung
`gym_treadmill_incline_pct` (Standard 12 %).

Alles netto (über Ruhe, wie `active_kcal`):
- Laufband: ACSM Gehen 0,1·v + 1,8·v·Steigung bzw. ab 8 km/h Laufen 0,2·v + 0,9·v·Steigung (ml O₂/kg/min).
- Spinning/Rad: MET 6,8 (wie Indoor-Rad ohne Watt). Treppe: MET 9,0 (Compendium, Stepper).
Tippfehler: ergibt die Dauer mehr als 25 km/h (ohne Strecke: unter 60 s), war sie in Minuten gemeint
(1 km in „14 s“ = 14 min)."""
from __future__ import annotations

import re
from datetime import date, datetime

from sqlmodel import Field, Session, SQLModel, select

from ..config import settings
from ..db import engine

KCAL_PER_ML = 5 / 1000
RUN_FROM_KMH = 8.0
MAX_KMH = 25.0
BIKE_MET = 6.8
STAIRS_MET = 9.0
INCLINE_MAX = 20.0

TREADMILL_IDS = {"243710DE"}
BIKE_IDS = {"213AB238"}
STAIRS_IDS = {"4377A52B"}
_NOTE_INCLINE = re.compile(r"(\d{1,2}(?:[.,]\d)?)\s*%")


class GymCardioIncline(SQLModel, table=True):
    __tablename__ = "gym_cardio_incline"

    key: str = Field(primary_key=True)        # <Hevy-Workout-ID>:<Vorlage>:<Satz>
    incline_pct: float
    updated_at: datetime = Field(default_factory=datetime.now)


def kind_of(template: str | None, name: str | None) -> str | None:
    n = (name or "").lower()
    if template in TREADMILL_IDS or "laufband" in n or "treadmill" in n:
        return "treadmill"
    if template in BIKE_IDS or any(w in n for w in ("spinning", "radfahren", "bike", "cycling", "ergometer")):
        return "bike"
    if template in STAIRS_IDS or "treppe" in n or "stair" in n:
        return "stairs"
    return None


def note_incline(notes: str | None) -> float | None:
    m = _NOTE_INCLINE.search(notes or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return value if 0 <= value <= INCLINE_MAX else None


def treadmill_kcal(distance_m: float, minutes: float, incline_pct: float, kg: float) -> tuple[float, float]:
    """(netto kcal, davon eben) nach ACSM."""
    v = distance_m / minutes
    run = v * 0.06 >= RUN_FROM_KMH
    flat, climb = (0.2, 0.9) if run else (0.1, 1.8)
    per_ml = kg * minutes * KCAL_PER_ML
    return (flat * v + climb * v * incline_pct / 100) * per_ml, flat * v * per_ml


def overrides() -> dict[str, float]:
    with Session(engine) as s:
        return {r.key: r.incline_pct for r in s.exec(select(GymCardioIncline)).all()}


def set_incline(key: str, incline_pct: float | None) -> bool:
    """Steigung eines Satzes setzen (None = zurück auf Notiz/Standard). False = unbekannter Satz."""
    if key not in {e["key"] for e in entries()}:
        return False
    with Session(engine) as s:
        row = s.get(GymCardioIncline, key)
        if incline_pct is None:
            if row:
                s.delete(row)
        else:
            row = row or GymCardioIncline(key=key, incline_pct=incline_pct)
            row.incline_pct, row.updated_at = float(incline_pct), datetime.now()
            s.add(row)
        s.commit()
    return True


def _rows(start: date | None, end: date | None) -> list[tuple]:
    sql = ("SELECT w.external_id, w.title, w.started_at, s.exercise, s.exercise_template_id, s.set_index, "
           "s.distance_m, s.duration_s, s.notes FROM workout_sets s JOIN workouts w ON w.id = s.workout_id "
           "WHERE w.source='hevy' AND w.started_at IS NOT NULL AND s.reps IS NULL AND s.weight_kg IS NULL")
    with engine.connect() as con:
        rows = con.exec_driver_sql(sql).fetchall()
    out = []
    for r in rows:
        day = datetime.fromisoformat(str(r[2])).date()
        if (start is None or day >= start) and (end is None or day <= end):
            out.append(r)
    return out


def entries(start: date | None = None, end: date | None = None, weights=None) -> list[dict]:
    """Ein Eintrag je Cardio-Satz, neueste zuerst. `kcal` None = zu wenig Daten (bleibt Krafttraining)."""
    from . import active_kcal

    custom = overrides()
    default = settings.gym_treadmill_incline_pct
    stride = settings.walkpad_stride_m
    out = []
    for wid, title, started, name, template, idx, dist, dur, notes in _rows(start, end):
        kind = kind_of(template, name)
        if not kind:
            continue
        key = f"{wid}:{template or name}:{idx or 0}"
        day = datetime.fromisoformat(str(started)).date()
        kg = active_kcal._kg(weights, day) if weights is not None else None
        dist = float(dist) if dist and dist > 0 else None
        seconds = float(dur) if dur and dur > 0 else None
        fixed = bool(seconds and (dist / seconds * 3.6 > MAX_KMH if dist else seconds < 60))
        if fixed:
            seconds *= 60
        speed = dist / seconds * 3.6 if dist and seconds else None
        e = {"key": key, "workout_id": wid, "title": title, "date": day.isoformat(), "started_at": str(started),
             "exercise": name, "kind": kind, "distance_m": dist, "duration_s": seconds, "duration_fixed": fixed,
             "speed_kmh": round(speed, 2) if speed else None, "incline_pct": None, "incline_source": None,
             "mode": None, "kcal": None, "kcal_flat": None, "steps": 0, "part": None}
        minutes = seconds / 60 if seconds else None
        if kind == "treadmill":
            if key in custom:
                e["incline_pct"], e["incline_source"] = custom[key], "custom"
            elif (n := note_incline(notes)) is not None:
                e["incline_pct"], e["incline_source"] = n, "note"
            else:
                e["incline_pct"], e["incline_source"] = default, "default"
            if speed and 0.5 <= speed <= MAX_KMH:
                e["mode"] = "run" if speed >= RUN_FROM_KMH else "walk"
                e["part"] = "walkpad"
                e["steps"] = round(active_kcal.RUN_CADENCE * minutes) if e["mode"] == "run" else round(dist / stride)
                if kg:
                    total, flat = treadmill_kcal(dist, minutes, e["incline_pct"], kg)
                    e["kcal"], e["kcal_flat"] = round(total), round(flat)
        elif minutes and minutes <= 240:
            met = BIKE_MET if kind == "bike" else STAIRS_MET
            e["part"] = "ride" if kind == "bike" else "gym"
            if kg:
                e["kcal"] = round((met - 1) * kg * minutes / 60)
        out.append(e)
    out.sort(key=lambda e: e["started_at"], reverse=True)
    return out


def listing(days: int = 120) -> dict:
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    from .. import walkpad

    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return {"default_incline_pct": settings.gym_treadmill_incline_pct, "incline_max": INCLINE_MAX,
            "entries": entries(today - timedelta(days=days - 1), today, walkpad._weights())}
