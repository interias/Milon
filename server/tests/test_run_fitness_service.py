from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import metrics
from app.metrics import run_fitness_service as service
from app.models import ExerciseSession, RunFitnessReference


@pytest.fixture
def fitness_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'fitness.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(service, "engine", engine)
    candidate = {"status": "candidate", "candidate_bpm": 185, "reason": "two_days"}
    monkeypatch.setattr(service, "reference_candidate", lambda _: dict(candidate))
    yield engine, candidate
    engine.dispose()


def test_reference_is_fixed_until_explicit_update_and_history_is_versioned(fitness_db):
    engine, candidate = fitness_db
    first = service.fitness()
    assert first["calibration"]["max_hr"] == 185
    assert first["calibration"]["rest_hr"] == 60
    assert first["calibration"]["provisional"]
    candidate["candidate_bpm"] = 190
    second = service.fitness()
    assert second["calibration"]["max_hr"] == 185
    assert second["calibration"]["candidate"]["candidate_bpm"] == 190
    updated = service.update_reference({"rest_hr": 53, "rest_source": "Three comparable awake measurements"})
    assert not updated["calibration"]["provisional"]
    assert updated["calibration"]["revision"] > first["calibration"]["revision"]
    updated = service.update_reference({"max_hr": 190})
    assert updated["calibration"]["max_hr"] == 190
    candidate["candidate_bpm"] = 180
    with pytest.raises(ValueError):
        service.update_reference({"max_hr": 180})
    with Session(engine) as session:
        assert len(session.exec(select(RunFitnessReference)).all()) == 3


def test_conversion_reverses_bounds_and_never_clips_invalid_tail():
    point = dict(hr=145, ci_low=140, ci_high=150, reasons=[])
    data = {"points": [point], "observations": []}
    service._convert(data, {"max_hr": 185, "rest_hr": 60, "provisional": True})
    assert point["vo2_low"] < point["vo2_eq"] < point["vo2_high"]
    point["ci_high"] = 200
    service._convert(data, {"max_hr": 185, "rest_hr": 60, "provisional": True})
    assert point["vo2_low"] is None and point["vo2_high"] is None
    assert service._equivalent(60, 185, 60) is None
    assert service._equivalent(190, 185, 60) is None
    point["hr"] = 180
    service._convert(data, {"max_hr": 185, "rest_hr": 60, "provisional": True})
    assert point["vo2_sensitivity_low"] is None


def test_sensor_change_separates_inputs_and_preserves_current_gap(monkeypatch):
    sessions = pd.DataFrame([{"external_id": "old", "started_at": datetime(2026, 1, 1)}])
    calls = []
    def analyze(windows, part, today):
        calls.append((list(part.external_id), today))
        points = [dict(date="2026-01-01", hr=140, ci_low=135, ci_high=145,
                       runs=5, local_runs=3, status="ok", reasons=[])] if not part.empty else []
        return dict(model_version="test", points=points, observations=[], durability=[],
                    pace_series=[{"pace_seconds": 360, "points": points}] if points else [])
    monkeypatch.setattr(service.run_fitness, "analyze", analyze)
    result = service._analyze_segments(pd.DataFrame(), sessions, [{"date": "2026-02-01", "label": "Chest strap"}], date(2026, 2, 5))
    assert calls == [(["old"], date(2026, 1, 31)), ([], date(2026, 2, 5))]
    assert result["points"][-1]["hr"] is None
    assert result["points"][-1]["segment_id"] == 1
    assert result["pace_series"][0]["points"][-1]["hr"] is None


def test_reference_api_rejects_incomplete_or_unverified_values(fitness_db):
    app = FastAPI()
    app.include_router(metrics.router)
    with TestClient(app) as client:
        url = "/metrics/running/fitness-reference"
        for patch in ({}, {"rest_hr": None}, {"rest_hr": 50}, {"rest_hr": 50, "rest_source": " "},
                      {"max_hr": 210}, {"sensor_change": {"date": "wrong", "label": "Watch"}},
                      {"sensor_change": {"date": "2999-01-01", "label": "Watch"}}):
            assert client.put(url, json=patch).status_code == 422
        result = client.put(url, json={"rest_hr": 52, "rest_source": "Comparable awake measurements"})
        assert result.status_code == 200
        assert result.json()["calibration"]["rest_hr"] == 52
        assert client.get("/metrics/running/fitness").status_code == 200


def test_cache_invalidates_when_inputs_change(fitness_db, monkeypatch):
    engine, _ = fitness_db
    calls = []
    original = service.run_fitness.analyze
    def analyze(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(service.run_fitness, "analyze", analyze)
    first = service.fitness()
    assert service.fitness() == first
    assert len(calls) == 1
    with Session(engine) as session:
        start = datetime(2026, 1, 1)
        session.add(ExerciseSession(external_id="new", exercise_type=33, started_at=start,
                                    ended_at=start + timedelta(minutes=40), distance_km=6))
        session.commit()
    service.fitness()
    assert len(calls) == 2
