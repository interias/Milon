"""The complete local Garmin route atlas; geometry never uses a map service."""
from fastapi import APIRouter
from sqlmodel import Session

from ..db import engine
from ..ingest.garmin import configured
from ..metrics.route_atlas import atlas
from ..models import SyncState

router = APIRouter(prefix="/metrics/running", tags=["running"])


@router.get("/route-atlas")
def route_atlas():
    result = atlas()
    with Session(engine) as session:
        sync = session.get(SyncState, "garmin")
        result.update(configured=configured(), sync={"last_sync": sync.last_sync, "status": sync.status}
                      if sync else None)
    return result
