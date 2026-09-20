"""Persisted inputs and content-addressed cache for the experimental sHR analysis."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from threading import Lock
from zoneinfo import ZoneInfo

import pandas as pd
from sqlmodel import Session, select

from ..config import settings
from ..db import engine
from ..models import ExerciseSession, RunAnalysisCache, RunAnnotation
from . import run_standardization

_analysis_lock = Lock()
_SESSION_SQL = """
    SELECT e.external_id, e.started_at, e.ended_at, e.distance_km,
           COALESCE(a.category, 'auto') AS category, COALESCE(a.exclude, 0) AS exclude
    FROM exercise_sessions e LEFT JOIN run_annotations a ON a.external_id=e.external_id
    WHERE e.exercise_type=33 ORDER BY e.started_at, e.external_id
"""


def standardized_hr() -> dict:
    """Recompute only after data, annotations, model version or calendar month changes."""
    with _analysis_lock:
        now = datetime.now(ZoneInfo(settings.timezone))
        version = run_standardization.MODEL_VERSION
        with engine.connect() as con:
            sessions = pd.read_sql(_SESSION_SQL, con, parse_dates=["started_at", "ended_at"])
            windows = pd.read_sql(
                "SELECT external_id, minute, speed_m_min, hr_bpm, coverage, steady, model_version "
                "FROM run_minutes WHERE model_version = ? ORDER BY external_id, minute", con, params=(version,),
            )
        fingerprint = hashlib.sha256(
            (version + now.strftime("%Y-%m") + sessions.to_json(date_format="iso") + windows.to_json()).encode()
        ).hexdigest()
        with Session(engine) as session:
            cached = session.get(RunAnalysisCache, "standardized_hr")
            if cached and cached.fingerprint == fingerprint:
                return json.loads(cached.payload)
        result = run_standardization.analyze(windows, sessions, today=now.date())
        result["updated_at"] = now.isoformat()
        payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
        with Session(engine) as session:
            session.merge(RunAnalysisCache(key="standardized_hr", fingerprint=fingerprint, payload=payload))
            session.commit()
        return result


def _session_result(row: ExerciseSession, annotation: RunAnnotation | None) -> dict:
    duration = ((row.ended_at - row.started_at).total_seconds() / 60) if row.ended_at else None
    return {"external_id": row.external_id, "date": row.started_at.isoformat(),
            "distance_km": row.distance_km, "duration_min": round(duration, 1) if duration is not None else None,
            "category": annotation.category if annotation else "auto",
            "exclude": annotation.exclude if annotation else False}


def analysis_sessions() -> list[dict]:
    with Session(engine) as session:
        annotations = {a.external_id: a for a in session.exec(select(RunAnnotation)).all()}
        runs = session.exec(select(ExerciseSession).where(
            ExerciseSession.exercise_type == 33, ExerciseSession.external_id.is_not(None),
        ).order_by(ExerciseSession.started_at.desc())).all()
        return [_session_result(row, annotations.get(row.external_id)) for row in runs]


def annotate_session(external_id: str, category: str, exclude: bool) -> dict | None:
    with Session(engine) as session:
        row = session.exec(select(ExerciseSession).where(
            ExerciseSession.external_id == external_id, ExerciseSession.exercise_type == 33,
        )).first()
        if row is None:
            return None
        annotation = RunAnnotation(external_id=external_id, category=category, exclude=exclude)
        session.merge(annotation)
        session.commit()
        return _session_result(row, annotation)
