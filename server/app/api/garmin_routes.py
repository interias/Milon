"""Read-only access to independently stored Garmin running routes."""
from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session

from .. import garmin_routes
from ..ingest import garmin
from ..models import SyncState


router = APIRouter(prefix="/metrics/running/routes", tags=["running"])


@router.get("")
def get_routes(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)) -> dict:
    with Session(garmin_routes.engine) as session:
        state = session.get(SyncState, "garmin")
        sync = {"last_sync": state.last_sync.isoformat() if state.last_sync else None,
                "status": state.status, "detail": state.detail} if state else None
    return {**garmin_routes.list_routes(limit, offset), "configured": garmin.configured(), "sync": sync}


@router.get("/{activity_id}")
def get_route(activity_id: str) -> dict:
    route = garmin_routes.route_detail(activity_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Die Laufroute wurde nicht gefunden.")
    return route
