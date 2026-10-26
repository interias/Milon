"""Rad-Trainingsplan: Import, Übersicht, Plan-FTP, Messpunkte, .zwo-Export."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from .. import bike_plan

router = APIRouter(prefix="/bike-plan", tags=["bike-plan"])


class FtpInput(BaseModel):
    watts: float = Field(ge=50, le=600)
    day: date | None = None


class CheckpointInput(BaseModel):
    checkpoint: str = Field(min_length=1, max_length=10)
    key: str = Field(min_length=1, max_length=20)
    value: float | None = None
    estimated: bool = False


def _active():
    plan = bike_plan.active_plan()
    if plan is None:
        raise HTTPException(404, "Kein Plan importiert")
    return plan


@router.get("")
def overview() -> dict:
    return bike_plan.overview()


@router.post("")
def import_plan(file: UploadFile = File(...)) -> dict:
    """Plan hochladen: JSON oder HTML-Datei mit eingebettetem #agent-context."""
    content = file.file.read(bike_plan.MAX_IMPORT_BYTES + 1)
    try:
        return bike_plan.import_plan(content)
    except bike_plan.Duplicate as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/{plan_id}")
def delete_plan(plan_id: str) -> dict:
    if not bike_plan.delete_plan(plan_id):
        raise HTTPException(404, "Plan unbekannt")
    return {"deleted": plan_id}


@router.post("/ftp")
def set_ftp(body: FtpInput) -> dict:
    bike_plan.set_manual_ftp(_active().id, body.watts, body.day)
    return bike_plan.overview()["ftp"]


@router.delete("/ftp/{entry_id}")
def delete_ftp(entry_id: int) -> dict:
    if not bike_plan.delete_manual_ftp(entry_id):
        raise HTTPException(404, "FTP-Eintrag unbekannt")
    return bike_plan.overview()["ftp"]


@router.get("/checkpoints")
def checkpoints() -> dict:
    return bike_plan.checkpoints()


@router.put("/checkpoints")
def set_checkpoint(body: CheckpointInput) -> dict:
    bike_plan.set_checkpoint(_active().id, body.checkpoint, body.key, body.value, body.estimated)
    return bike_plan.checkpoints()


@router.get("/session/{session_id}.zwo")
def session_zwo(session_id: int) -> Response:
    result = bike_plan.zwo(session_id)
    if result is None:
        raise HTTPException(404, "Kein Zwift-Workout für diese Einheit")
    xml, filename = result
    return Response(xml, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
