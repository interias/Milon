"""Schreibt den Trainingsplan (metrics.strength_plan) als Hevy-Routinen „Milon OK“/„Milon UK“
in den Routinen-Ordner „Milon“. Nur diese beiden Routinen werden angelegt bzw. überschrieben
(PUT ersetzt die Übungsliste komplett); andere Routinen bleiben unberührt. Ist der Inhalt seit
dem letzten Schreiben gleich (Hash in sync_state 'hevy_routines'.cursor), geht kein Request raus.
Die Hevy-API kennt kein RPE in Routinen → Ziel-RIR und Begründung stehen in der Übungsnotiz."""
from __future__ import annotations

import hashlib
import json

import httpx
from sqlmodel import Session

from ..config import settings
from ..db import engine
from ..metrics import strength_plan
from ..models import SyncState
from .hevy import BASE

FOLDER = "Milon"
STATE = "hevy_routines"
ROUTINE_NOTES = ("Automatisch von Milon nach jedem Hevy-Sync gesetzt – Änderungen hier werden überschrieben. "
                 "Gewicht & Wdh. = Ziel; Begründung in der Übungsnotiz.")


def routine_body(plan: dict) -> dict:
    exercises = []
    for ex in plan["exercises"]:
        exercises.append({
            "exercise_template_id": ex["template_id"],
            "superset_id": ex["superset"],
            "rest_seconds": ex["rest_seconds"],
            "notes": f"{ex['rir_note']}. {ex['reason']}",
            "sets": [{"type": s["type"], "weight_kg": s["weight_kg"], "reps": s["reps"]} for s in ex["sets"]],
        })
    return {"title": plan["title"], "notes": ROUTINE_NOTES, "exercises": exercises}


def _list_all(c: httpx.Client, path: str, key: str) -> list[dict]:
    out, page = [], 1
    while True:
        r = c.get(f"{BASE}{path}", params={"page": page, "pageSize": 10})
        if r.status_code == 404:  # Hevy antwortet bei leerer Liste mit 404
            break
        r.raise_for_status()
        d = r.json()
        out.extend(d.get(key, []))
        if page >= int(d.get("page_count", 1)):
            break
        page += 1
    return out


def write_routines(force: bool = False) -> dict:
    if not settings.hevy_api_key:
        raise RuntimeError("HEVY_API_KEY fehlt in server/.env")
    plans = strength_plan.next_training()["plans"]
    bodies = [routine_body(p) for p in plans]
    digest = hashlib.sha256(json.dumps(bodies, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with Session(engine) as s:
        st = s.get(SyncState, STATE)
        if not force and st and st.cursor == digest:
            return {"mode": "unchanged"}

    headers = {"api-key": settings.hevy_api_key, "Accept": "application/json"}
    created, updated = [], []
    with httpx.Client(timeout=30, headers=headers) as c:
        folder = next((f for f in _list_all(c, "/routine_folders", "routine_folders") if f.get("title") == FOLDER), None)
        if folder is None:
            r = c.post(f"{BASE}/routine_folders", json={"routine_folder": {"title": FOLDER}})
            r.raise_for_status()
            d = r.json()
            folder = d.get("routine_folder", d)
        existing = {r["title"]: r for r in _list_all(c, "/routines", "routines")
                    if r.get("folder_id") == folder["id"]}
        for body in bodies:
            payload = {"routine": {**body, "folder_id": folder["id"]}}
            old = existing.get(body["title"])
            if old:
                r = c.put(f"{BASE}/routines/{old['id']}", json=payload)
                updated.append(body["title"])
            else:
                r = c.post(f"{BASE}/routines", json=payload)
                created.append(body["title"])
            if r.status_code >= 400:
                raise RuntimeError(f"Hevy {r.status_code} für {body['title']}: {r.text[:300]}")

    with Session(engine) as s:
        st = s.get(SyncState, STATE) or SyncState(source=STATE)
        st.cursor = digest
        s.merge(st)
        s.commit()
    return {"mode": "written", "folder_id": folder["id"], "created": created, "updated": updated}
