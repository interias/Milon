"""Read-only pulse zone and recent pace orientation endpoint."""
from fastapi import APIRouter

from ..metrics import run_zones

router = APIRouter(prefix="/metrics/running", tags=["metrics"])


@router.get("/zones")
def running_zones() -> dict:
    return run_zones.zones()
