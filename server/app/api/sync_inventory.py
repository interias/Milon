"""Stable local identities for honest before/after feedback on manual imports."""
from datetime import datetime, timedelta
import math
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from sqlalchemy import func
from sqlmodel import Session, select

from ..config import settings, watch_source_for
from ..db import engine
from ..garmin_activity import GarminActivity
from ..ingest.run_windows import GARMIN_PACKAGE
from ..models import BodyMeasurement, ExerciseSession, NutritionEntry, SleepSession, Workout

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _item(identifier, day, href):
    return {"id": str(identifier), "date": str(day), "href": href}


@router.get("/inventory")
def inventory():
    """No row IDs, raw measurements, coordinates or credentials leave this endpoint."""
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    end = datetime.combine(today + timedelta(days=1), datetime.min.time())
    with Session(engine) as session:
        activities = session.exec(select(GarminActivity.canonical_external_id, GarminActivity.activity_id)
                                  .order_by(GarminActivity.fetched_at)).all()
        activity_ids = {external: activity for external, activity in activities if external}
        runs = []
        for row in session.exec(select(ExerciseSession).where(
                ExerciseSession.exercise_type == 33, ExerciseSession.started_at < end)).all():
            distance = row.distance_km
            minutes = (row.ended_at - row.started_at).total_seconds() / 60 if row.ended_at else 0
            if (distance is None or not math.isfinite(distance) or not 1 <= distance <= 60
                    or not 5 < minutes < 600 or not 3 <= minutes / distance <= 12):
                continue
            identifier = row.external_id or row.started_at.isoformat()
            activity = activity_ids.get(row.external_id)
            runs.append(_item(identifier, row.started_at.date(), f"/laufen/{activity}" if activity else "/laufen"))
        nights = {}
        for row in session.exec(select(SleepSession.day, SleepSession.source_package).where(
                SleepSession.main_sleep.is_(True), SleepSession.day <= today)).all():
            day, package = row
            if package == watch_source_for(day, settings):
                nights[str(day)] = _item(day, day, f"/gesundheit?night={day}" if package == GARMIN_PACKAGE else "/gesundheit")
        workouts = [_item(row.external_id or row.started_at.isoformat(), row.started_at.date(), "/kraft")
                    for row in session.exec(select(Workout).where(
                        Workout.source == "hevy", Workout.started_at < end)).all() if row.started_at]

        def days(column, href, *conditions):
            values = session.exec(select(func.date(column)).where(column < end, *conditions).distinct()).all()
            return [_item(day, day, href) for day in values if day]

        weights = days(BodyMeasurement.measured_at, "/koerper", BodyMeasurement.weight_kg > 0)
        nutrition = days(NutritionEntry.eaten_at, "/ernaehrung")
    return {"runs": runs, "nights": list(nights.values()), "workouts": workouts,
            "weights": weights, "nutrition": nutrition}
