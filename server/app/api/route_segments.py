"""Read-only section comparisons for locally recorded routes."""
from fastapi import APIRouter, HTTPException, Path

from ..metrics import route_segments

router = APIRouter(prefix="/metrics/running/segments", tags=["running"])


@router.get("/{activity_id}")
def comparison(activity_id: str = Path(pattern=r"^[0-9]{1,30}$")):
    result = route_segments.comparison(activity_id)
    if result is None:
        raise HTTPException(404, "Laufaufzeichnung nicht gefunden.")
    return result
