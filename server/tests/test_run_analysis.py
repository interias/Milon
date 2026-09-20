from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import metrics
from app.ingest import health_connect
from app.metrics import run_analysis
from app.models import ExerciseSession, RunAnnotation, RunMinute


@pytest.fixture
def analysis_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'analysis.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(run_analysis, "engine", engine)
    monkeypatch.setattr(health_connect, "engine", engine)
    started = datetime(2026, 5, 1, 8)
    with Session(engine) as session:
        session.add(ExerciseSession(external_id="run-1", exercise_type=33, started_at=started,
                                    ended_at=started + timedelta(minutes=40), distance_km=6))
        session.add(RunMinute(external_id="run-1", minute=20.5, speed_m_min=166.7,
                              hr_bpm=140, coverage=1, steady=True))
        session.commit()
    yield engine
    engine.dispose()


def test_cache_tracks_inputs_and_user_annotations(analysis_db, monkeypatch):
    calls = []

    def analyze(windows, sessions, today):
        calls.append((windows.copy(), sessions.copy(), today))
        return {"pace_series": [], "caveat": "experimental"}

    monkeypatch.setattr(run_analysis.run_standardization, "analyze", analyze)
    first = run_analysis.standardized_hr()
    assert run_analysis.standardized_hr() == first
    assert len(calls) == 1
    assert run_analysis.annotate_session("run-1", "beast", True)["category"] == "beast"
    run_analysis.standardized_hr()
    assert len(calls) == 2
    assert calls[-1][1].iloc[0]["category"] == "beast"
    assert calls[-1][1].iloc[0]["exclude"] == 1
    with Session(analysis_db) as session:
        minute = session.exec(select(RunMinute)).one()
        minute.hr_bpm = 130
        session.add(minute)
        session.commit()
    run_analysis.standardized_hr()
    assert len(calls) == 3
    assert calls[-1][0].iloc[0]["hr_bpm"] == 130


def test_annotation_api_validates_and_preserves_training_history(analysis_db):
    app = FastAPI()
    app.include_router(metrics.router)
    with TestClient(app) as client:
        url = "/metrics/running/analysis-sessions/run-1"
        assert client.put(url, json={"category": "unknown", "exclude": False}).status_code == 422
        assert client.put(url + "-missing", json={"category": "normal", "exclude": False}).status_code == 404
        result = client.put(url, json={"category": "trail", "exclude": False})
        assert result.status_code == 200
        assert result.json()["category"] == "trail"
        listed = client.get("/metrics/running/analysis-sessions").json()
        assert listed[0]["category"] == "trail"
        assert listed[0]["duration_min"] == 40
    with Session(analysis_db) as session:
        assert session.exec(select(ExerciseSession)).one().distance_km == 6


def test_reimport_replaces_windows_but_full_import_keeps_annotations(analysis_db, monkeypatch):
    with Session(analysis_db) as session:
        row = session.exec(select(ExerciseSession)).one()
        source_row = row.model_dump(exclude={"id"})
    run_analysis.annotate_session("run-1", "beast", True)
    minute = {"external_id": "run-1", "minute": 22.5, "speed_m_min": 165,
              "hr_bpm": 142, "coverage": 1, "steady": True}
    data = {"body": {}, "sessions": [source_row], "best_efforts": [], "vo2": [], "steps": [],
            "resting": [], "skipped_body": 0,
            "run_windows": {"available": True, "session_ids": ["run-1"], "rows": [minute]}}
    monkeypatch.setattr(health_connect, "read_health_connect", lambda _: data)
    for full in (False, False, True):
        health_connect.import_health_connect("unused", full=full)
        with Session(analysis_db) as session:
            windows = session.exec(select(RunMinute)).all()
            assert len(windows) == 1 and windows[0].minute == 22.5
            assert session.get(RunAnnotation, "run-1").category == "beast"
            assert session.exec(select(ExerciseSession)).one().distance_km == 6
    data["run_windows"] = {"available": False, "session_ids": [], "rows": []}
    health_connect.import_health_connect("unused", full=True)
    with Session(analysis_db) as session:
        assert session.exec(select(RunMinute)).one().minute == 22.5
        assert session.get(RunAnnotation, "run-1").exclude


def test_full_import_preserves_partial_series_but_removes_orphans(analysis_db, monkeypatch):
    with Session(analysis_db) as session:
        original = session.exec(select(ExerciseSession)).one().model_dump(exclude={"id"})
        second = {**original, "external_id": "run-2"}
        session.add(ExerciseSession(**second))
        for name in ("run-2", "removed-run"):
            session.add(RunMinute(external_id=name, minute=20.5, speed_m_min=166,
                                  hr_bpm=145, coverage=1, steady=True))
        session.commit()
    data = {"body": {}, "sessions": [original, second], "best_efforts": [], "vo2": [], "steps": [],
            "resting": [], "skipped_body": 0, "run_windows": {
                "available": True, "session_ids": ["run-1"], "rows": [
                    {"external_id": "run-1", "minute": 21.5, "speed_m_min": 167,
                     "hr_bpm": 141, "coverage": 1, "steady": True}]}}
    monkeypatch.setattr(health_connect, "read_health_connect", lambda _: data)
    health_connect.import_health_connect("unused", full=True)
    with Session(analysis_db) as session:
        rows = {r.external_id: r.minute for r in session.exec(select(RunMinute)).all()}
        assert rows == {"run-1": 21.5, "run-2": 20.5}
