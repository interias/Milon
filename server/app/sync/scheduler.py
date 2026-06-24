"""Phase-2-Automatik: geplante Quell-Syncs via APScheduler.
- Hevy: API-Polling (alle 6 h)
- FDDB: taeglich (Auto-Login -> CSV-Export)
- Health Connect: taeglicher Drive-Pull (05:00, wenn GOOGLE_API_KEY + HC_DRIVE_FOLDER_ID gesetzt)
  PLUS Ordner-Scan auf data/incoming/ (alle 10 min) -> importiert auch manuell abgelegte Dateien.
Jeder Lauf schreibt Status/Detail nach sync_state.
"""
from __future__ import annotations

import json
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, select

from ..config import INCOMING_DIR, settings
from ..db import engine
from ..ingest import fddb, health_connect, hevy
from ..models import SyncState

_scheduler: BackgroundScheduler | None = None
HC_DB = INCOMING_DIR / "health_connect_export.db"


def _tz():
    try:
        import pytz
        return pytz.timezone(settings.timezone)
    except Exception:
        return None


def record_sync(source: str, status: str, detail: str | None = None, cursor: str | None = None) -> None:
    with Session(engine) as s:
        row = s.get(SyncState, source) or SyncState(source=source)
        row.last_sync = datetime.now()
        row.status = status
        row.detail = (detail or "")[:500]
        if cursor is not None:
            row.cursor = cursor
        s.merge(row)
        s.commit()


def sync_hevy() -> None:
    try:
        record_sync("hevy", "ok", json.dumps(hevy.import_hevy()))
    except Exception as e:  # noqa: BLE001
        record_sync("hevy", "error", str(e))


def sync_fddb() -> None:
    try:
        res = fddb.import_fddb()
        record_sync("fddb", "ok", json.dumps({k: v for k, v in res.items() if k != "columns"}))
    except Exception as e:  # noqa: BLE001
        record_sync("fddb", "error", str(e))


def sync_hc_if_new() -> None:
    """Importiert die HC-DB nur, wenn sich die Datei seit dem letzten Import geaendert hat."""
    if not HC_DB.exists():
        return
    mtime = str(int(HC_DB.stat().st_mtime))
    with Session(engine) as s:
        row = s.get(SyncState, "health_connect")
    if row and row.cursor == mtime and row.status == "ok":
        return
    try:
        record_sync("health_connect", "ok", json.dumps(health_connect.import_health_connect(HC_DB)), cursor=mtime)
    except Exception as e:  # noqa: BLE001
        record_sync("health_connect", "error", str(e))


def sync_hc_drive() -> None:
    """Täglicher Pull der HC-Export-Zip aus Drive (wenn HC_DRIVE_FILE_ID gesetzt)."""
    if not settings.hc_drive_file_id:
        return
    from ..ingest import drive
    try:
        res = drive.pull()
        cur = str(int(HC_DB.stat().st_mtime)) if HC_DB.exists() else None
        record_sync("health_connect", "ok",
                    json.dumps({k: v for k, v in res.items() if k != "columns"}), cursor=cur)
    except Exception as e:  # noqa: BLE001
        record_sync("health_connect", "error", str(e))


def start_scheduler() -> None:
    global _scheduler
    if not settings.scheduler_enabled or _scheduler is not None:
        return
    tz = _tz()
    sch = BackgroundScheduler(timezone=tz) if tz else BackgroundScheduler()
    sch.add_job(sync_hevy, "interval", hours=6, id="hevy", replace_existing=True)
    sch.add_job(sync_fddb, "cron", hour=4, minute=30, id="fddb", replace_existing=True)
    sch.add_job(sync_hc_if_new, "interval", minutes=10, id="hc_scan",
                replace_existing=True, next_run_time=datetime.now())
    sch.add_job(sync_hc_drive, "cron", hour=5, minute=0, id="hc_drive", replace_existing=True)
    sch.start()
    _scheduler = sch


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def status() -> dict:
    jobs = []
    if _scheduler is not None:
        for j in _scheduler.get_jobs():
            jobs.append({"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None})
    with Session(engine) as s:
        rows = s.exec(select(SyncState)).all()
        state = [
            {"source": r.source,
             "last_sync": r.last_sync.isoformat() if r.last_sync else None,
             "status": r.status, "detail": r.detail, "cursor": r.cursor}
            for r in rows
        ]
    return {"enabled": settings.scheduler_enabled, "running": _scheduler is not None, "jobs": jobs, "state": state}
