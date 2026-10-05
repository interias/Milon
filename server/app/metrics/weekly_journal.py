"""Seven completed local days of recorded training, sleep and optional self-reports."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlmodel import Session, select

from ..checkins import CheckIn
from ..config import settings
from ..db import engine
from ..garmin_activity import GarminActivity
from ..models import ExerciseSession, StepsDaily, Workout, WorkoutSet
from . import body, running, sleep


def journal(offset: int = 0, *, now: datetime | None = None) -> dict:
    zone = ZoneInfo(settings.timezone)
    local_now = now or datetime.now(zone)
    local_now = local_now.replace(tzinfo=zone) if local_now.tzinfo is None else local_now.astimezone(zone)
    # Calendar arithmetic, not fixed 168-hour windows, preserves DST boundaries.
    boundary = local_now.date() - timedelta(days=offset * 7)
    first, previous_first = boundary - timedelta(days=7), boundary - timedelta(days=14)
    last = boundary - timedelta(days=1)
    start_time, end_time = datetime.combine(first, datetime.min.time()), datetime.combine(boundary, datetime.min.time())
    previous_time = datetime.combine(previous_first, datetime.min.time())
    runs = running._runs()
    # Imports own source reconciliation. Never append Garmin's parallel raw activity store here.
    current_runs = runs[(runs["started_at"] >= pd.Timestamp(first)) & (runs["started_at"] < pd.Timestamp(boundary))]
    previous_runs = runs[(runs["started_at"] >= pd.Timestamp(previous_first)) & (runs["started_at"] < pd.Timestamp(first))]
    with Session(engine) as session:
        workouts = session.exec(select(Workout).where(Workout.source == "hevy", Workout.started_at >= previous_time,
                                                      Workout.started_at < end_time).order_by(Workout.started_at)).all()
        checkins = {entry.day: entry for entry in session.exec(select(CheckIn).where(CheckIn.day >= first, CheckIn.day < boundary)).all()}
        steps = {entry.day: entry.steps for entry in session.exec(select(StepsDaily).where(StepsDaily.day >= first, StepsDaily.day < boundary)).all()}
        run_links = {}
        linked = session.exec(select(ExerciseSession.started_at, ExerciseSession.ended_at, ExerciseSession.distance_km,
                                     GarminActivity.activity_id).join(GarminActivity,
                                     GarminActivity.canonical_external_id == ExerciseSession.external_id)
                              .where(ExerciseSession.exercise_type == running.RUN, ExerciseSession.started_at >= start_time,
                                     ExerciseSession.started_at < end_time)).all()
        for start, end, distance, activity_id in linked:
            run_links.setdefault((start, end, distance), set()).add(activity_id)
        exercises = {}
        workout_ids = [row.id for row in workouts if row.started_at >= start_time]
        if workout_ids:
            for workout_id, exercise in session.exec(select(WorkoutSet.workout_id, WorkoutSet.exercise)
                    .where(WorkoutSet.workout_id.in_(workout_ids)).distinct().order_by(WorkoutSet.exercise)).all():
                exercises.setdefault(workout_id, []).append(exercise)
    main_sleep = {item["date"]: item for item in sleep.overview(days=7, today=last)["series"] if item["main_sleep"]}
    days = []
    for index in range(7):
        day = first + timedelta(days=index)
        daily_runs = current_runs[current_runs["started_at"].dt.date == day] if not current_runs.empty else current_runs
        daily_strength = [row for row in workouts if row.started_at.date() == day]
        night, entry = main_sleep.get(day.isoformat()), checkins.get(day)
        def activity_id(row):
            matches = run_links.get((row.started_at.to_pydatetime(), row.ended_at.to_pydatetime(), row.distance_km), set())
            return next(iter(matches)) if len(matches) == 1 else None

        days.append({"date": day.isoformat(),
                     "runs": [{"started_at": row.started_at.isoformat(), "distance_km": round(float(row.distance_km), 2),
                               "minutes": round(float(row.dur_min), 1), "activity_id": activity_id(row)} for row in daily_runs.itertuples()],
                     "strength": [{"started_at": row.started_at.isoformat(), "title": row.title or "Krafttraining",
                                   "exercises": exercises.get(row.id, [])}
                                  for row in daily_strength],
                     "sleep": {"hours": night["asleep_hours"], "source": night["source_package"],
                               "label": sleep.LABELS.get(night["source_package"], "Uhr"),
                               "window_hours": night["window_hours"]} if night else None,
                     "checkin": {"energy": entry.energy, "training_effort": entry.training_effort} if entry else None,
                     "steps": steps.get(day)})
    weight = body._weight_daily()
    current_weight = weight[(weight.index >= pd.Timestamp(first)) & (weight.index < pd.Timestamp(boundary))].dropna() if not weight.empty else weight
    previous_weight = weight[(weight.index >= pd.Timestamp(previous_first)) & (weight.index < pd.Timestamp(first))].dropna() if not weight.empty else weight
    weight_delta = round(float(current_weight.mean() - previous_weight.mean()), 2) if min(len(current_weight), len(previous_weight)) >= 3 else None
    measured_sleep = [day["sleep"]["hours"] for day in days if day["sleep"] and day["sleep"]["hours"] is not None]
    current_workouts = [row for row in workouts if row.started_at >= start_time]
    previous_workouts = [row for row in workouts if row.started_at < start_time]
    current_km, previous_km = float(current_runs["distance_km"].sum()), float(previous_runs["distance_km"].sum())
    return {"timezone": settings.timezone, "offset": offset, "from_date": first.isoformat(), "to_date": last.isoformat(),
            "previous_from_date": previous_first.isoformat(), "previous_to_date": (first - timedelta(days=1)).isoformat(),
            "days": days,
            "summary": {"running_km": round(current_km, 1), "running_delta_km": round(current_km - previous_km, 1),
                        "running_sessions": len(current_runs), "strength_sessions": len(current_workouts),
                        "strength_delta_sessions": len(current_workouts) - len(previous_workouts),
                        "sleep_hours": round(sum(measured_sleep) / len(measured_sleep), 2) if measured_sleep else None,
                        "sleep_nights": len(measured_sleep), "weight_delta_kg": weight_delta,
                        "weight_days": len(current_weight), "previous_weight_days": len(previous_weight),
                        "steps_avg": round(sum(steps.values()) / len(steps)) if steps else None, "steps_days": len(steps),
                        "checkin_days": len(checkins)},
            "sources": sorted({day["sleep"]["label"] for day in days if day["sleep"]}),
            "note": "Erfasste Aktivitäten; — bedeutet nicht erfasst, keine bestätigte Pause. Schlaf nach Aufwachtag. Energie ist freiwillige Selbstauskunft (1–5)."}
