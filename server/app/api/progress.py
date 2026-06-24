"""Fortschritts-/Optik-Fotos: Timeline-Einträge mit bis zu 5 Ansichten.
Bilder werden serverseitig vereinheitlicht (RGB, max. Kante 1080 px, JPEG q85) und im
statischen Dateisystem (data/progress/) abgelegt. Ausgeliefert über /media/progress/<datei>."""
from __future__ import annotations

import uuid
from datetime import date as date_cls
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlmodel import Session

from ..config import PROGRESS_DIR
from ..db import engine
from ..models import ProgressEntry

router = APIRouter(prefix="/progress", tags=["progress"])

VIEWS = ["front", "side", "back", "pose1", "pose2"]
MAX_SIDE = 1080
JPEG_Q = 85


def _save_image(file: UploadFile) -> str:
    raw = file.file.read()
    if not raw:
        raise ValueError("leere Datei")
    img = Image.open(BytesIO(raw))
    img = ImageOps.exif_transpose(img)  # Orientierung aus EXIF anwenden
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_SIDE:
        scale = MAX_SIDE / max(w, h)
        img = img.resize((round(w * scale), round(h * scale)))
    name = uuid.uuid4().hex + ".jpg"
    img.save(PROGRESS_DIR / name, "JPEG", quality=JPEG_Q, optimize=True)
    return name


def _to_dict(e: ProgressEntry) -> dict:
    return {
        "id": e.id,
        "taken_on": e.taken_on.isoformat(),
        "note": e.note,
        "photos": {v: getattr(e, v) for v in VIEWS},
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _unlink(filename: str | None) -> None:
    if filename:
        try:
            (PROGRESS_DIR / filename).unlink(missing_ok=True)
        except OSError:
            pass


@router.get("")
def list_entries() -> list[dict]:
    with Session(engine) as s:
        rows = s.execute(
            select(ProgressEntry).order_by(ProgressEntry.taken_on.desc(), ProgressEntry.id.desc())
        ).scalars().all()
        return [_to_dict(e) for e in rows]


@router.post("")
def create_entry(
    taken_on: str = Form(...),
    note: str = Form(""),
    front: UploadFile | None = File(None),
    side: UploadFile | None = File(None),
    back: UploadFile | None = File(None),
    pose1: UploadFile | None = File(None),
    pose2: UploadFile | None = File(None),
) -> dict:
    try:
        d = date_cls.fromisoformat(taken_on)
    except ValueError:
        raise HTTPException(status_code=422, detail="Ungültiges Datum (YYYY-MM-DD).")

    files = {"front": front, "side": side, "back": back, "pose1": pose1, "pose2": pose2}
    saved: dict[str, str] = {}
    for view, f in files.items():
        if f is not None and (f.filename or "").strip():
            try:
                saved[view] = _save_image(f)
            except Exception as e:  # noqa: BLE001
                raise HTTPException(status_code=400, detail=f"Bild '{view}' nicht verarbeitbar: {e}")

    with Session(engine) as s:
        entry = ProgressEntry(taken_on=d, note=(note.strip() or None), created_at=datetime.now(), **saved)
        s.add(entry)
        s.commit()
        s.refresh(entry)
        return _to_dict(entry)


@router.put("/{entry_id}")
def update_entry(
    entry_id: int,
    taken_on: str = Form(...),
    note: str = Form(""),
    cleared: str = Form(""),  # kommagetrennte Ansichten, deren Foto entfernt werden soll
    front: UploadFile | None = File(None),
    side: UploadFile | None = File(None),
    back: UploadFile | None = File(None),
    pose1: UploadFile | None = File(None),
    pose2: UploadFile | None = File(None),
) -> dict:
    """Aktualisiert einen Eintrag: Datum/Notiz immer; je Ansicht — neues Bild = ersetzen
    (altes löschen), Name in `cleared` = entfernen, sonst behalten."""
    try:
        d = date_cls.fromisoformat(taken_on)
    except ValueError:
        raise HTTPException(status_code=422, detail="Ungültiges Datum (YYYY-MM-DD).")

    files = {"front": front, "side": side, "back": back, "pose1": pose1, "pose2": pose2}
    clear_set = {v.strip() for v in cleared.split(",") if v.strip()}
    with Session(engine) as s:
        entry = s.get(ProgressEntry, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
        entry.taken_on = d
        entry.note = note.strip() or None
        for view, f in files.items():
            old = getattr(entry, view)
            if f is not None and (f.filename or "").strip():
                try:
                    new = _save_image(f)
                except Exception as e:  # noqa: BLE001
                    raise HTTPException(status_code=400, detail=f"Bild '{view}' nicht verarbeitbar: {e}")
                _unlink(old)
                setattr(entry, view, new)
            elif view in clear_set:
                _unlink(old)
                setattr(entry, view, None)
        s.add(entry)
        s.commit()
        s.refresh(entry)
        return _to_dict(entry)


@router.delete("/{entry_id}")
def delete_entry(entry_id: int) -> dict:
    with Session(engine) as s:
        entry = s.get(ProgressEntry, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
        for view in VIEWS:
            _unlink(getattr(entry, view))
        s.delete(entry)
        s.commit()
    return {"deleted": entry_id}
