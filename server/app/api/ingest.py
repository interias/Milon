"""Ingest-Endpunkte: Quellen ziehen/aktualisieren.
- Hevy & FDDB: live über API/Cookie (Secrets aus server/.env).
- Health Connect: re-importiert die zuletzt in data/incoming/ abgelegte Export-DB.
(Automatische Zeitpläne = Phase 2.)"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from ..config import INCOMING_DIR
from ..ingest import fddb, health_connect, hevy
from ..sync import scheduler

router = APIRouter(prefix="/ingest", tags=["ingest"])
HC_DB = INCOMING_DIR / "health_connect_export.db"


@router.get("/status")
def status() -> dict:
    """Scheduler-Status + letzter Sync-Stand je Quelle."""
    return scheduler.status()


def _run(source: str, fn, cursor: str | None = None) -> dict:
    """Import ausfuehren und Ergebnis/Fehler in sync_state protokollieren."""
    try:
        res = fn()
    except Exception as e:  # noqa: BLE001
        scheduler.record_sync(source, "error", str(e))
        raise HTTPException(status_code=502, detail=f"{source}-Import fehlgeschlagen: {e}")
    detail = json.dumps({k: v for k, v in res.items() if k != "columns"}) if isinstance(res, dict) else ""
    scheduler.record_sync(source, "ok", detail, cursor=cursor)
    return res


@router.post("/hevy")
def ingest_hevy(full: bool = False) -> dict:
    return _run("hevy", lambda: hevy.import_hevy(full=full))


@router.post("/fddb")
def ingest_fddb(full: bool = False) -> dict:
    return _run("fddb", lambda: fddb.import_fddb(full=full))


@router.post("/health-connect")
def ingest_health_connect(full: bool = False) -> dict:
    if not HC_DB.exists():
        raise HTTPException(status_code=404, detail="Keine health_connect_export.db in data/incoming/")
    return _run("health_connect", lambda: health_connect.import_health_connect(HC_DB, full=full),
                cursor=str(int(HC_DB.stat().st_mtime)))


@router.post("/refresh")
def refresh_all(full: bool = False) -> dict:
    """Alle Quellen aktualisieren (inkrementell; full=true erzwingt Voll-Reconciliation)."""
    res: dict = {}
    for src, fn in (("hevy", lambda: hevy.import_hevy(full=full)), ("fddb", lambda: fddb.import_fddb(full=full))):
        try:
            res[src] = _run(src, fn)
        except HTTPException as e:
            res[src] = {"error": e.detail}
    if HC_DB.exists():
        try:
            res["health_connect"] = _run(
                "health_connect",
                lambda: health_connect.import_health_connect(HC_DB, full=full),
                cursor=str(int(HC_DB.stat().st_mtime)),
            )
        except HTTPException as e:
            res["health_connect"] = {"error": e.detail}
    else:
        res["health_connect"] = {"skipped": "keine DB in data/incoming/"}
    return res
