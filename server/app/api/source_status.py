from fastapi import APIRouter

from ..metrics.source_status import source_status

router = APIRouter(prefix="/metrics", tags=["sources"])


@router.get("/sources")
def get_source_status() -> dict:
    return source_status()
