"""Measured sleep and exploratory, device-separated prior-night performance pairs."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import text
from sqlmodel import Session, select

from ..config import settings, watch_source_for
from ..db import engine
from ..models import SleepSession

LABELS = {"com.garmin.android.apps.connectmobile": "Garmin", "com.sec.android.app.shealth": "Samsung"}
SLEEP_METHOD = ("Datum = lokales Aufwachen. Hauptschlaf = längstes erfasstes Fenster ab 2 Stunden je Tag; "
                "kürzere Fenster werden separat als Nickerchen gezeigt. Schlafdauer zählt nur Schlafphasen "
                "bei mindestens 98 % bekannter Phasenabdeckung, ohne widersprüchliche Phasen.")
CAVEAT = ("Explorativer Zusammenhang, keine Ursache und keine Trainingsfreigabe. Trainingsart, Tageszeit, "
          "Wetter, Strecke, Erkrankungen und langfristige Trends können das Ergebnis beeinflussen. "
          "Geräte werden getrennt ausgewertet; fehlende Nächte werden nicht geschätzt.")


def _today() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def _sleep_rows(days: int, today: date) -> list[SleepSession]:
    with Session(engine) as session:
        rows = session.exec(select(SleepSession).where(
            SleepSession.day >= today - timedelta(days=days - 1), SleepSession.day <= today)
            .order_by(SleepSession.ended_at)).all()
    return [row for row in rows if row.source_package == watch_source_for(row.day, settings)]


def _main_by_day(rows: list[SleepSession]) -> dict[date, SleepSession]:
    main = {}
    for row in rows:
        if row.main_sleep and (row.day not in main or
                               row.duration_window_minutes > main[row.day].duration_window_minutes):
            main[row.day] = row
    return main


def overview(days: int = 90, today: date | None = None) -> dict:
    today = today or _today()
    rows = _sleep_rows(days, today)
    main = _main_by_day(rows)
    current_package = watch_source_for(today, settings)
    recent = [row for day, row in main.items() if day >= today - timedelta(days=6)
              and row.source_package == current_package]
    known = [row.asleep_minutes for row in recent if row.asleep_minutes is not None]
    latest = max(main.values(), key=lambda row: row.ended_at, default=None)
    summary = {"latest_date": latest.day.isoformat() if latest else None,
               "latest_asleep_hours": round(latest.asleep_minutes / 60, 2)
               if latest and latest.asleep_minutes is not None else None,
               "latest_window_hours": round(latest.duration_window_minutes / 60, 2) if latest else None,
               "latest_source_package": latest.source_package if latest else None,
               "avg_asleep_hours_7d": round(float(np.mean(known)) / 60, 2) if known else None,
               "nights_7d": len(recent), "known_asleep_nights_7d": len(known),
               "naps_7d": sum(not row.main_sleep and row.day >= today - timedelta(days=6) for row in rows)}
    series = [{"external_id": row.external_id, "date": row.day.isoformat(),
               "started_at": row.started_at.isoformat(), "ended_at": row.ended_at.isoformat(),
               "asleep_hours": round(row.asleep_minutes / 60, 2) if row.asleep_minutes is not None else None,
               "window_hours": round(row.duration_window_minutes / 60, 2), "awake_minutes": row.awake_minutes,
               "nap": not row.main_sleep, "main_sleep": main.get(row.day) is row,
               "source_package": row.source_package, "stage_coverage": row.stage_coverage} for row in rows]
    sources = [{"package": package, "label": LABELS.get(package, package),
                "nights": sum(row.source_package == package for row in main.values()),
                "known_asleep_nights": sum(row.source_package == package and row.asleep_minutes is not None
                                           for row in main.values())}
               for package in sorted({row.source_package for row in rows})]
    cutoff = settings.watch_source_switch_date
    return {"summary": summary, "series": series, "sources": sources,
            "switch_date": cutoff.isoformat() if cutoff else None, "method": SLEEP_METHOD,
            "notes": ["Schlaffenster ohne bekannte Phasen ist keine gemessene Schlafdauer.",
                      "Die 7-Tage-Zahl verwendet ausschließlich die aktuelle Uhr; fehlende Tage sind keine Nullnächte."]}


def _run_outcomes() -> list[dict]:
    with engine.connect() as con:
        rows = con.execute(text(
            "SELECT e.external_id, e.started_at, e.ended_at, e.distance_km, e.avg_hr, "
            "COALESCE(a.exclude,0) AS excluded FROM exercise_sessions e "
            "LEFT JOIN run_annotations a ON a.external_id=e.external_id "
            "WHERE e.exercise_type=33 ORDER BY e.started_at")).mappings().all()
    result = []
    legacy_ids = set(settings.watch_source_legacy_session_ids)
    for row in rows:
        start = datetime.fromisoformat(row["started_at"])
        end = datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None
        minutes = (end - start).total_seconds() / 60 if end else 0
        distance, hr = row["distance_km"], row["avg_hr"]
        valid = (distance is not None and 1 <= distance <= 60 and 5 < minutes < 600
                 and 3 <= minutes / distance <= 12 and hr is not None and 25 <= hr <= 250)
        result.append({"session_id": row["external_id"], "started_at": start, "title": "Lauf",
                       "value": distance * 1000 / minutes / hr if valid else None,
                       "excluded": bool(row["excluded"]) or row["external_id"] in legacy_ids})
    return result


def _strength_outcomes() -> list[dict]:
    with engine.connect() as con:
        workouts = con.execute(text(
            "SELECT id, external_id, title, started_at FROM workouts WHERE started_at IS NOT NULL "
            "ORDER BY started_at,id")).mappings().all()
        sets = con.execute(text(
            "SELECT workout_id, exercise, weight_kg, reps FROM workout_sets WHERE set_type='normal' "
            "AND weight_kg>0 AND reps>0")).mappings().all()
    tops = defaultdict(dict)
    for row in sets:
        e1rm = row["weight_kg"] * (1 + min(row["reps"], 12) / 30)
        if np.isfinite(e1rm):
            values = tops[row["workout_id"]]
            values[row["exercise"]] = max(values.get(row["exercise"], 0), e1rm)
    previous = {}
    result = []
    for workout in workouts:
        start = datetime.fromisoformat(workout["started_at"])
        changes = []
        for exercise, value in tops[workout["id"]].items():
            baseline = previous.get(exercise)
            if baseline and timedelta(hours=12) <= start - baseline[0] <= timedelta(days=60):
                changes.append(float(np.log(value / baseline[1])))
            previous[exercise] = (start, value)
        # Exercise changes have equal weight; new exercises do not invent a baseline.
        result.append({"session_id": workout["external_id"] or f"workout-{workout['id']}",
                       "started_at": start, "title": workout["title"] or "Krafttraining",
                       "value": float(np.expm1(np.mean(changes)) * 100) if changes else None,
                       "exercises": len(changes), "excluded": False})
    return result


def _correlation(points: list[dict]) -> dict:
    n = len(points)
    if n < 10:
        return {"correlation": None, "ci95": None, "status": "collecting",
                "status_label": f"{n} Paare – wir sammeln weiter (ab 10 beschreibendes r)"}
    x = np.array([point["sleep_hours"] for point in points], float)
    y = np.array([point["value"] for point in points], float)
    if np.std(x) < 1e-8 or np.std(y) < 1e-8:
        return {"correlation": None, "ci95": None, "status": "no_variation",
                "status_label": "Zu wenig Streuung für eine Korrelation"}
    r = float(np.corrcoef(x, y)[0, 1])
    # Fisher interval is approximate; nights, not duplicated training sessions, are the unit.
    ci = None
    if n >= 20:
        z = np.arctanh(np.clip(r, -0.999999, 0.999999))
        delta = 1.96 / np.sqrt(n - 3)
        ci = [round(float(np.tanh(z - delta)), 3), round(float(np.tanh(z + delta)), 3)]
    return {"correlation": round(r, 3), "ci95": ci, "status": "exploratory",
            "status_label": "Beschreibendes r; Näherungsintervall setzt unabhängige Nächte voraus"
            if ci else "Beschreibendes r; für ein Näherungsintervall sammeln wir mindestens 20 Paare"}


def performance(kind: str = "run", source: str = "current", days: int = 180,
                today: date | None = None) -> dict:
    today = today or _today()
    sleeps = _main_by_day(_sleep_rows(days, today))
    outcomes = _run_outcomes() if kind == "run" else _strength_outcomes()
    selected_packages = {watch_source_for(today, settings)} if source == "current" else {settings.steps_source_package}
    if source == "all":
        selected_packages |= {watch_source_for(today, settings)} | {row.source_package for row in sleeps.values()}
    buckets = {package: {"by_day": defaultdict(list),
                         "missing": {"no_sleep": 0, "unknown_sleep": 0, "no_outcome": 0, "excluded": 0}}
               for package in sorted(selected_packages)}
    for outcome in outcomes:
        day = outcome["started_at"].date()
        if not today - timedelta(days=days - 1) <= day <= today:
            continue
        package = watch_source_for(day, settings)
        if package not in buckets:
            continue
        bucket, sleep = buckets[package], sleeps.get(day)
        if outcome["excluded"]:
            bucket["missing"]["excluded"] += 1
        elif outcome["value"] is None:
            bucket["missing"]["no_outcome"] += 1
        elif sleep is None or sleep.ended_at > outcome["started_at"]:
            bucket["missing"]["no_sleep"] += 1
        elif sleep.asleep_minutes is None:
            bucket["missing"]["unknown_sleep"] += 1
        else:
            bucket["by_day"][day].append((sleep, outcome))
    groups = []
    for package, bucket in buckets.items():
        points = []
        for day, paired in sorted(bucket["by_day"].items()):
            sleep = paired[0][0]
            points.append({"date": day.isoformat(), "sleep_hours": sleep.asleep_minutes / 60,
                           "value": float(np.median([outcome["value"] for _, outcome in paired])),
                           "title": " · ".join(outcome["title"] for _, outcome in paired),
                           "session_id": paired[0][1]["session_id"], "session_count": len(paired)})
        groups.append({"package": package, "label": LABELS.get(package, package), "n": len(points),
                       "points": points, "missing": bucket["missing"], **_correlation(points)})
    outcome_label = "Aerobe Effizienz des folgenden Laufs" if kind == "run" else "e1RM-Veränderung zu vorherigen Übungseinheiten"
    outcome_unit = "m/Herzschlag" if kind == "run" else "%"
    method = ("Hauptschlaf der vorherigen Nacht mit Training nach dem Aufwachen am selben lokalen Tag; "
              "Nickerchen werden ausgeschlossen. Mehrere Einheiten am selben Tag: Median, ein Punkt je Nacht. "
              "r basiert auf ungerundeten Rohpaaren, getrennt nach Uhr.")
    method += (" Laufwert = Geschwindigkeit / mittlere HF; dadurch nicht vollständig intensitätsbereinigt."
               if kind == "run" else " Kraftwert = gleich gewichtete logarithmische Veränderungen der besten "
               "e1RM-Arbeitssätze je gleicher Übung gegenüber der letzten Einheit (12 Stunden bis 60 Tage zurück), "
               "Epley mit höchstens 12 Wiederholungen; kein Volumenvergleich.")
    return {"kind": kind, "source": source, "outcome_label": outcome_label, "outcome_unit": outcome_unit,
            "groups": groups, "method": method, "caveat": CAVEAT}
