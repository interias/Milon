"""Synchronized Garmin sensor recordings for the running detail view."""
from fastapi import APIRouter

from .. import garmin_activity


router = APIRouter(prefix="/metrics/running/activities", tags=["running"])


@router.get("/{activity_id}")
def get_activity(activity_id: str) -> dict:
    return garmin_activity.activity_detail(activity_id)
