"""Aligned observations of waist size, weight and comparable lifting performance."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from statistics import fmean, median

from sqlmodel import Session, select

from ..circumferences import CircumferenceEntry, DEFINITION_VERSION, DEFINITIONS, local_today
from ..db import engine
from ..models import BodyMeasurement, Workout, WorkoutSet
from .strength import _idx_weights, _muscle_group


def _valid(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _observation(points: list[tuple[date, float]], start: date, end: date, minimum: int = 1,
                 use_median: bool = False) -> dict:
    points = sorted((day, value) for day, value in points if start <= day <= end)
    return {
        "value": round((median if use_median else fmean)(value for _, value in points), 2)
        if len(points) >= minimum else None,
        "count": len(points),
        "first_date": points[0][0].isoformat() if points else None,
        "last_date": points[-1][0].isoformat() if points else None,
    }


def _change(first: dict, last: dict) -> float | None:
    return round(last["value"] - first["value"], 2) if first["value"] is not None and last["value"] is not None else None


def progress(weeks: int = 8, measure: str = "abdomen_navel", today: date | None = None) -> dict:
    """Compare fixed, non-overlapping endpoint windows; never extend stale data to today."""
    if weeks not in (4, 8, 12) or measure not in ("abdomen_navel", "waist_narrowest"):
        raise ValueError("Unsupported body progress window or measure")
    end = today or local_today()
    start = end - timedelta(days=weeks * 7 - 1)
    baseline_end, current_start = start + timedelta(days=13), end - timedelta(days=13)
    with Session(engine) as session:
        tape = session.exec(select(CircumferenceEntry).where(
            CircumferenceEntry.measured_on >= start, CircumferenceEntry.measured_on <= end)).all()
        weights = session.exec(select(BodyMeasurement).where(
            BodyMeasurement.measured_at >= datetime.combine(start, time.min),
            BodyMeasurement.measured_at < datetime.combine(end + timedelta(days=1), time.min))).all()
        sets = session.exec(select(Workout.started_at, WorkoutSet.exercise, WorkoutSet.weight_kg, WorkoutSet.reps)
            .join(WorkoutSet, WorkoutSet.workout_id == Workout.id).where(
                Workout.started_at >= datetime.combine(start, time.min),
                Workout.started_at < datetime.combine(end + timedelta(days=1), time.min),
                WorkoutSet.set_type == "normal")).all()

    definition = next(item for item in DEFINITIONS if item["key"] == measure)
    tape_points, ignored = [], 0
    for entry in tape:
        value = json.loads(entry.values_json).get(measure)
        if not _valid(value):
            continue
        if entry.protocol != "standard" or entry.definition_version != DEFINITION_VERSION:
            ignored += 1
            continue
        tape_points.append((entry.measured_on, value))
    tape_first = _observation(tape_points, start, baseline_end, use_median=True)
    tape_last = _observation(tape_points, current_start, end, use_median=True)

    daily_weights = defaultdict(list)
    for row in weights:
        if _valid(row.weight_kg):
            daily_weights[row.measured_at.date()].append(row.weight_kg)
    weight_points = [(day, fmean(values)) for day, values in daily_weights.items()]
    weight_first = _observation(weight_points, start, baseline_end, minimum=3)
    weight_last = _observation(weight_points, current_start, end, minimum=3)

    # Match the existing strength index's capped Epley estimate and muscle-group weights.
    daily_lifts: dict[str, dict[date, float]] = defaultdict(dict)
    for started_at, exercise, weight, reps in sets:
        if not (_valid(weight) and _valid(reps)):
            continue
        day = started_at.date()
        estimate = weight * (1 + min(reps, 12) / 30)
        daily_lifts[exercise][day] = max(daily_lifts[exercise].get(day, 0), estimate)
    first_exercises, last_exercises, comparisons = set(), set(), []
    for exercise, values in sorted(daily_lifts.items()):
        first = _observation(list(values.items()), start, baseline_end, minimum=2, use_median=True)
        last = _observation(list(values.items()), current_start, end, minimum=2, use_median=True)
        if first["count"]:
            first_exercises.add(exercise)
        if last["count"]:
            last_exercises.add(exercise)
        if first["value"] is not None and last["value"] is not None:
            comparisons.append({"exercise": exercise, "group": _muscle_group(exercise),
                                "baseline": first, "current": last,
                                "delta_pct": round(100 * (last["value"] / first["value"] - 1), 1)})
    cohort = [row["exercise"] for row in comparisons]
    groups = {row["group"] for row in comparisons}
    sufficient = len(cohort) >= 3 and len(groups) >= 2
    strength_delta = None
    if sufficient:
        weights_by_exercise = _idx_weights(cohort, {row["exercise"]: row["group"] for row in comparisons})
        strength_delta = round(100 * (math.exp(sum(
            weights_by_exercise[row["exercise"]] * math.log(row["current"]["value"] / row["baseline"]["value"])
            for row in comparisons)) - 1), 1)
    union = first_exercises | last_exercises
    return {
        "weeks": weeks, "start": start.isoformat(), "end": end.isoformat(),
        "baseline": {"start": start.isoformat(), "end": baseline_end.isoformat()},
        "current": {"start": current_start.isoformat(), "end": end.isoformat()},
        "circumference": {"key": measure, "name": definition["name"], "site": definition["site"],
                          "baseline": tape_first, "current": tape_last, "delta": _change(tape_first, tape_last),
                          "ignored_measurements": ignored},
        "weight": {"baseline": weight_first, "current": weight_last, "delta": _change(weight_first, weight_last)},
        "strength": {"delta_pct": strength_delta, "exercises": comparisons, "groups": len(groups),
                     "baseline_exercises": len(first_exercises), "current_exercises": len(last_exercises),
                     "unmatched_exercises": len(union - set(cohort)),
                     "changed_exercises": len(first_exercises ^ last_exercises)},
    }
