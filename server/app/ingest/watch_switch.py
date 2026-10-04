"""Repair a bounded watch-source interval without replacing unrelated history."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, delete, select

from ..config import DATA_DIR, INCOMING_DIR, settings, update_env_file
from ..db import engine, upsert
from ..models import (ExerciseSession, RestingHrDaily, RunAnalysisCache,
                      RunBestEffort, RunFitnessReference, RunMinute, StepsDaily)
from .health_connect import SOURCE, read_health_connect


def repair(since: date, until: date, package: str, *, sessions_since: date | None = None,
           legacy_session_ids: list[str] | None = None) -> dict:
    """Back up first; replace only source-derived rows inside the supplied interval.

    The caller must verify export coverage and choose the inclusive end date.
    An optional later session boundary preserves an unresolved transition-day run.
    """
    if until < since or not package.strip():
        raise ValueError("A source and a nonempty date interval are required.")
    sessions_since = sessions_since or since
    if not since <= sessions_since <= until:
        raise ValueError("Session boundary must lie inside the repair interval.")
    path = DATA_DIR / "tracker.db"
    if settings.resolved_database_url() != f"sqlite:///{path.as_posix()}":
        raise ValueError("This repair only supports the local data/tracker.db.")
    export = INCOMING_DIR / "health_connect_export.db"
    with sqlite3.connect(f"file:{export.as_posix()}?mode=ro", uri=True) as raw:
        if not raw.execute("SELECT 1 FROM application_info_table WHERE package_name=?", (package,)).fetchone():
            raise ValueError("The replacement source is absent from the export.")

    previous = settings.watch_source_switch_date, settings.watch_source_package, settings.watch_source_legacy_session_ids
    try:
        settings.watch_source_switch_date = since
        settings.watch_source_package = package
        settings.watch_source_legacy_session_ids = legacy_session_ids or []
        data = read_health_connect(export)
    finally:
        settings.watch_source_switch_date, settings.watch_source_package, settings.watch_source_legacy_session_ids = previous
    steps = [r for r in data["steps"] if since <= r["day"] <= until]
    if not steps or max(r["day"] for r in steps) < until:
        raise ValueError("Replacement steps do not cover the requested end date.")
    lower = datetime.combine(sessions_since, time.min)
    upper = datetime.combine(until + timedelta(days=1), time.min)
    sessions = [r for r in data["sessions"] if r["started_at"] and lower <= r["started_at"] < upper]
    ids = {r["external_id"] for r in sessions}
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / f"tracker-before-watch-switch-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    with sqlite3.connect(path) as original, sqlite3.connect(backup) as saved:
        original.backup(saved)

    with Session(engine) as session:
        old_ids = session.exec(select(ExerciseSession.external_id).where(
            ExerciseSession.source == SOURCE, ExerciseSession.started_at >= lower,
            ExerciseSession.started_at < upper)).all()
        vanished = set(old_ids) - ids
        replacements = {
            RunMinute: vanished | (set(data["run_windows"].get("session_ids", [])) & ids),
            RunBestEffort: vanished | (set(data.get("best_efforts_invalid_ids", [])) & ids)
                          | {r["external_id"] for r in data["best_efforts"] if r["external_id"] in ids},
        }
        for model, replacement_ids in replacements.items():
            replacement_ids = list(replacement_ids)
            for i in range(0, len(replacement_ids), 400):
                session.exec(delete(model).where(model.source == SOURCE,
                                                  model.external_id.in_(replacement_ids[i:i + 400])))
        session.exec(delete(ExerciseSession).where(ExerciseSession.source == SOURCE,
                                                   ExerciseSession.started_at >= lower,
                                                   ExerciseSession.started_at < upper))
        for model in (StepsDaily, RestingHrDaily):
            session.exec(delete(model).where(model.source == SOURCE, model.day >= since, model.day <= until))
        upsert(session, ExerciseSession, sessions, ["external_id"])
        upsert(session, StepsDaily, steps, ["day"], update_cols=["steps"])
        resting = [r for r in data["resting"] if since <= r["day"] <= until]
        upsert(session, RestingHrDaily, resting, ["day"], update_cols=["bpm"])
        efforts = [r for r in data["best_efforts"] if r["external_id"] in ids]
        minutes = [r for r in data["run_windows"]["rows"] if r["external_id"] in ids]
        upsert(session, RunBestEffort, efforts, ["external_id", "distance_m"])
        upsert(session, RunMinute, minutes, ["external_id", "minute"])
        reference = session.exec(select(RunFitnessReference).order_by(RunFitnessReference.id.desc())).first()
        if reference is None:
            raise ValueError("Initialize the running reference before recording the sensor change.")
        payload = json.loads(reference.payload)
        changes = {c["date"]: c for c in payload.get("sensor_changes", [])}
        change = {"date": since.isoformat(), "label": "Garmin Forerunner 970"}
        if changes.get(since.isoformat()) != change:
            changes[since.isoformat()] = change
            payload["sensor_changes"] = sorted(changes.values(), key=lambda c: c["date"])
            session.add(RunFitnessReference(created_at=datetime.now(), payload=json.dumps(payload, ensure_ascii=False)))
        session.exec(delete(RunAnalysisCache))
        # Write configuration before committing so a write failure rolls back DB changes.
        update_env_file({"WATCH_SOURCE_SWITCH_DATE": since.isoformat(), "WATCH_SOURCE_PACKAGE": package,
                         "WATCH_SOURCE_LEGACY_SESSION_IDS": json.dumps(legacy_session_ids or [])})
        session.commit()

    return {"backup": str(backup), "since": since.isoformat(), "until": until.isoformat(),
            "sessions_since": sessions_since.isoformat(), "steps_days": len(steps),
            "sessions_before": len(old_ids), "sessions_after": len(sessions),
            "sessions_with_hr": sum(r["avg_hr"] is not None for r in sessions),
            "resting_days": len(resting), "run_minutes": len(minutes)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=date.fromisoformat, required=True)
    parser.add_argument("--until", type=date.fromisoformat, required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--sessions-since", type=date.fromisoformat)
    parser.add_argument("--legacy-session", action="append", default=[])
    args = parser.parse_args()
    print(json.dumps(repair(args.since, args.until, args.package, sessions_since=args.sessions_since,
                            legacy_session_ids=args.legacy_session), indent=2))
