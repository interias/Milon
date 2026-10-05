"""Within-run mechanics and source-owned impact totals, without injury predictions."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
import json
from zoneinfo import ZoneInfo

import numpy as np
from sqlmodel import Session, select

from ..config import settings, watch_source_for
from ..db import engine
from ..garmin_activity import GarminActivity, OUTDOOR_RUN_TYPES
from ..ingest.run_windows import GARMIN_PACKAGE
from ..models import RunAnnotation, Workout, WorkoutSet
from .run_insights import _eligible, _intervals, _match, _number, steady_minutes, MATCH_METHOD
from .strength import _muscle_group

METRICS = {
    "step_speed_loss_pct": ("Schrittbremsung", "%", "Anteil der Laufgeschwindigkeit, der beim Bodenkontakt verloren geht (SSL%)."),
    "ground_contact_ms": ("Bodenkontakt", "ms", "Zeit des Fußes am Boden pro Schritt."),
    "cadence_spm": ("Schrittfrequenz", "spm", "Gesamte Schritte beider Füße pro Minute."),
    "stride_length_cm": ("Schrittlänge", "cm", "Zurückgelegte Strecke pro Schritt laut Garmin."),
    "vertical_ratio_pct": ("Vertikales Verhältnis", "%", "Vertikale Bewegung im Verhältnis zur Schrittlänge."),
    "ground_contact_balance_left_pct": ("Kontaktbalance links", "%", "Linker Anteil der Bodenkontaktzeit; kein Symmetrie- oder Verletzungsurteil."),
}
METHOD = ("Früh und spät innerhalb derselben Aufzeichnung, keine Mischung unterschiedlicher Sensorperioden. "
          "Jeder Kanal benötigt zusätzlich mindestens 54 erfasste Sekunden pro Minute. "
          "Je Kennzahl mindestens sechs verschiedene Minutenpaare, jedes Paar gleich gewichtet. "
          "Die Spanne zeigt Minimum bis Maximum der gepaarten Unterschiede; kein Konfidenzintervall. "
          "Änderungen beschreiben den Laufstil; sie beweisen weder Ermüdung noch bessere Technik. " + MATCH_METHOD)


def mechanics_minutes(summary, series):
    minutes = steady_minutes(summary, series)
    wanted = {int(point["minute"]): point for point in minutes}
    buckets = defaultdict(lambda: defaultdict(lambda: [0., 0.]))
    for left, right, duration in _intervals(series):
        begin, end = left["elapsed_seconds"], right["elapsed_seconds"]
        for minute in range(int(begin // 60), int(end // 60) + 1):
            if minute not in wanted:
                continue
            lo, hi = max(begin, minute * 60), min(end, (minute + 1) * 60)
            if hi <= lo:
                continue
            fraction = ((lo + hi) / 2 - begin) / duration
            for key in METRICS:
                a, b = left.get(key), right.get(key)
                if not _number(a) or not _number(b):
                    continue
                if key in {"ground_contact_ms", "cadence_spm", "stride_length_cm"} and min(a, b) <= 0:
                    continue
                bucket = buckets[minute][key]
                bucket[0] += hi - lo
                bucket[1] += (a + fraction * (b - a)) * (hi - lo)
    return [{**point, **{key: buckets[int(point["minute"])][key][1] / buckets[int(point["minute"])][key][0]
                        if buckets[int(point["minute"])][key][0] >= 54 else None for key in METRICS}}
            for point in minutes]


def compare_mechanics(summary, series, allowed=True):
    minutes = mechanics_minutes(summary, series) if allowed else []
    midpoint = (600 + max(600, (summary.get("elapsed_seconds") or 0) - 120)) / 120
    result = []
    for key, (label, unit, definition) in METRICS.items():
        known = [point for point in minutes if point[key] is not None]
        early = [point for point in known if point["minute"] < midpoint]
        late = [point for point in known if point["minute"] >= midpoint]
        pairs = _match(early, late)
        enough = len(pairs) >= 6
        changes = [b[key] - a[key] for a, b in pairs]
        mean = lambda values: round(float(np.mean(values)), 3) if enough else None
        result.append({"key": key, "label": label, "unit": unit, "definition": definition,
                       "status": "observed" if enough else "collecting" if allowed else "excluded",
                       "pairs": len(pairs), "known_minutes": len(known),
                       "early": mean([a[key] for a, _ in pairs]), "late": mean([b[key] for _, b in pairs]),
                       "delta": mean(changes),
                       "delta_min": round(min(changes), 3) if enough else None,
                       "delta_max": round(max(changes), 3) if enough else None,
                       "pace_delta_seconds": mean([1000 / b["speed"] - 1000 / a["speed"] for a, b in pairs]),
                       "series": [{"minute": point["minute"], "value": round(point[key], 3)} for point in known]})
    return {"status": "observed" if any(metric["status"] == "observed" for metric in result)
            else "collecting" if allowed else "excluded", "metrics": result, "method": METHOD,
            "midpoint_minute": midpoint, "eligible_minutes": len(minutes),
            "reason": "Frühe und späte Abschnitte bei ähnlichem Tempo und ähnlicher Steigung."
            if allowed else "Diese Aufzeichnung ist unvollständig oder für gleichmäßige Vergleiche ausgeschlossen."}


def activity(activity_id):
    with Session(engine) as session:
        row = session.get(GarminActivity, activity_id)
        if row is None:
            return None
        summary, series, quality = json.loads(row.summary_json), json.loads(row.series_json), json.loads(row.quality_json)
        annotations = {a.external_id: a for a in session.exec(select(RunAnnotation)).all()}
    return {"activity_id": activity_id, "source": "garmin_recording", "parser_version": row.parser_version,
            "impact_load_km": summary.get("impact_load_km"),
            **compare_mechanics(summary, series, bool(_eligible(row, summary, quality, annotations)))}


def load(weeks=12, today=None):
    from ..garmin_load import tolerance_status

    today = today or datetime.now(ZoneInfo(settings.timezone)).date()
    first_week = today - timedelta(days=today.weekday(), weeks=weeks - 1)
    buckets = {first_week + timedelta(weeks=index): {"runs": [], "leg_days": set(), "excluded_runs": 0}
               for index in range(weeks)}
    with Session(engine) as session:
        rows = session.exec(select(GarminActivity).where(GarminActivity.started_at >= datetime.combine(first_week, time.min),
                                                      GarminActivity.started_at < datetime.combine(today + timedelta(days=1), time.min))).all()
        annotations = {a.external_id: a for a in session.exec(select(RunAnnotation)).all()}
        seen = set()
        for row in sorted(rows, key=lambda item: item.fetched_at, reverse=True):
            summary, quality = json.loads(row.summary_json), json.loads(row.quality_json)
            day = row.started_at.date()
            bucket = buckets[day - timedelta(days=day.weekday())]
            annotation = annotations.get(row.canonical_external_id)
            eligible = (quality.get("complete") and quality.get("canonical") and row.canonical_external_id
                        and summary.get("activity_type") in OUTDOOR_RUN_TYPES
                        and watch_source_for(day, settings) == GARMIN_PACKAGE
                        and row.canonical_external_id not in settings.watch_source_legacy_session_ids
                        and not (annotation and annotation.exclude))
            if not eligible:
                bucket["excluded_runs"] += 1
                continue
            if row.canonical_external_id in seen:
                continue
            seen.add(row.canonical_external_id)
            distance, impact = summary.get("distance_km"), summary.get("impact_load_km")
            bucket["runs"].append({"activity_id": row.activity_id, "date": day.isoformat(),
                                   "distance_km": distance if _number(distance) and distance > 0 else None,
                                   "impact_load_km": impact if quality.get("impact_unit_verified") and _number(impact) and impact >= 0 else None})
        sets = session.exec(select(Workout, WorkoutSet).join(WorkoutSet, Workout.id == WorkoutSet.workout_id).where(
            Workout.source == "hevy", Workout.started_at >= datetime.combine(first_week, time.min),
            Workout.started_at < datetime.combine(today + timedelta(days=1), time.min))).all()
        for workout, entry in sets:
            if entry.set_type == "warmup" or not entry.reps or entry.reps <= 0 or _muscle_group(entry.exercise) != "Beine":
                continue
            day = workout.started_at.date()
            buckets[day - timedelta(days=day.weekday())]["leg_days"].add(day.isoformat())
        tolerance = tolerance_status(session, today)
    result = []
    for week, bucket in buckets.items():
        runs = bucket["runs"]
        paired = [run for run in runs if run["distance_km"] is not None and run["impact_load_km"] is not None]
        result.append({"week": week.isoformat(), "runs": len(runs), "paired_runs": len(paired),
                       "distance_km": round(sum(run["distance_km"] or 0 for run in paired), 2) if paired else None,
                       "impact_load_km": round(sum(run["impact_load_km"] for run in paired), 2) if paired else None,
                       "all_distance_km": round(sum(run["distance_km"] or 0 for run in runs), 2) if runs else None,
                       "leg_days": sorted(bucket["leg_days"]), "excluded_runs": bucket["excluded_runs"],
                       "activities": sorted(runs, key=lambda run: run["date"]), "provisional": week <= today < week + timedelta(days=7)})
    return {"weeks": result, "tolerance": tolerance, "source": "garmin_direct",
            "method": "ISO-Wochen ab Montag. Distanz und Garmin-Impact-Load stammen aus denselben vollständigen Läufen mit bestätigter Einheit; fehlende Impact-Werte sind keine Null. Jede kanonische Einheit zählt einmal. Impact Load ist Garmins geschätzte mechanische Belastung in äquivalenten Kilometern, keine tatsächlich gelaufene Strecke. Toleranz ist eine separate Garmin-Schätzung und keine Sicherheitsgrenze. Hevy-Beintage markieren protokollierte Arbeitssätze (Muskelgruppe nach Übungsnamen); sie werden nicht in Laufkilometer umgerechnet."}
