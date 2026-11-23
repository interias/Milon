"""Body scale over Web Bluetooth: the phone posts one stable reading (ScaleReading from qnScale.ts)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .. import scale

router = APIRouter(prefix="/scale", tags=["scale"])


class ReadingInput(BaseModel):
    """Field names as in the driver's ScaleReading interface."""
    weightKg: float
    r1: int | None = Field(default=None, ge=0, le=0xFFFF)
    r2: int | None = Field(default=None, ge=0, le=0xFFFF)
    source: Literal["live", "stored"]
    protocolType: int | None = Field(default=None, ge=-1, le=0xFF)
    timestamp: datetime
    rawHex: str | None = Field(default=None, max_length=200, pattern=r"^[0-9a-fA-F ]*$")


@router.post("/measurements")
def post_measurement(body: ReadingInput, response: Response) -> dict:
    """201 = new reading, 200 = duplicate (same time or same weight within 2 min), 422 = implausible."""
    try:
        row, created = scale.save(
            measured_at=body.timestamp, weight_kg=body.weightKg, r1=body.r1, r2=body.r2, source=body.source,
            protocol_type=None if body.protocolType is None or body.protocolType < 0 else body.protocolType,
            raw_hex=body.rawHex.lower() if body.rawHex else None)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    response.status_code = 201 if created else 200
    return {"measurement": row, "duplicate": not created}


@router.get("/measurements")
def get_measurements(days: int = Query(90, ge=1, le=3660)) -> dict:
    return {"measurements": scale.history(days)}


@router.delete("/measurements/{measurement_id}")
def delete_measurement(measurement_id: int) -> dict:
    if not scale.remove(measurement_id):
        raise HTTPException(status_code=404, detail="Messung nicht gefunden.")
    return {"deleted": measurement_id}
