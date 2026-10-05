import json
from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

from app import run_reference as reference
from app.api import run_reference as api
from app.garmin_activity import GarminActivity
from app.garmin_routes import GarminRoute
from app.models import RunAnnotation, RunFitnessReference


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'reference.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[GarminActivity.__table__, GarminRoute.__table__,
        RunAnnotation.__table__, RunFitnessReference.__table__, reference.RunRouteReference.__table__])
    monkeypatch.setattr(reference, "engine", engine)
    monkeypatch.setattr(reference.settings, "watch_source_switch_date", date(2026, 9, 25))
    monkeypatch.setattr(reference.settings, "watch_source_package", reference.insights.GARMIN_PACKAGE)
    monkeypatch.setattr(reference.settings, "watch_source_legacy_session_ids", [])
    yield engine
    engine.dispose()


def save(db, activity_id="1", day=2, hr=140, *, reverse=False, complete=True, speed=3., seconds=2400, route=True):
    started = datetime(2026, 10, day, 10)
    points = [dict(elapsed_seconds=second, timer_seconds=second, distance_m=second * speed,
                   hr_bpm=hr, speed_m_s=speed, altitude_m=100, gap=False) for second in range(0, seconds + 1, 5)]
    summary = dict(title="Synthetic route", elapsed_seconds=seconds, duration_seconds=seconds,
                   distance_km=speed * seconds / 1000, activity_type="running")
    geometry = [{"lat": 51 + index * 7200 / 200 / 111195, "lon": 6.} for index in range(201)]
    with Session(db) as session:
        session.add(GarminActivity(activity_id=activity_id, started_at=started,
            canonical_external_id=f"run-{activity_id}", summary_json=json.dumps(summary),
            series_json=json.dumps(points), laps_json="[]", zones_json="[]",
            quality_json=json.dumps({"complete": complete, "canonical": complete}), fingerprint="test", fetched_at=started))
        if route:
            session.add(GarminRoute(activity_id=activity_id, title="Synthetic route", started_at=started,
                point_count=len(geometry), segments_json=json.dumps([list(reversed(geometry)) if reverse else geometry]), synced_at=started))
        session.commit()


def test_selection_is_explicit_reversible_and_no_automatic_baseline(db):
    save(db)
    save(db, "2", day=3)
    assert reference.overview(today=date(2026, 10, 5))["status"] == "unset"
    assert reference.selection("1")["selectable"] is True
    assert reference.choose("1")["reference"]["activity_id"] == "1"
    assert reference.choose("2")["reference"]["activity_id"] == "2"
    assert reference.clear()["reference"] is None
    assert reference.clear()["reference"] is None


def test_observations_are_against_fixed_anchor_and_keep_pair_evidence(db):
    save(db)
    save(db, "2", day=3, hr=135)
    save(db, "3", day=4, hr=142)
    reference.choose("1")
    result = reference.overview(today=date(2026, 10, 5))
    assert result["status"] == "ready"
    assert [item["hr_delta_bpm"] for item in result["observations"]] == [-5, 2]
    assert all(item["matched_pairs"] >= 6 for item in result["observations"])
    assert all(item["first_hr"] == 140 for item in result["observations"])
    assert all(item["pace_delta_seconds"] == 0 for item in result["observations"])
    assert "keine Signifikanz" in result["method"]
    assert "lat" not in json.dumps(result)


@pytest.mark.parametrize("change", ["reverse", "missing_route", "incomplete", "too_long", "different_pace", "sensor", "annotation", "legacy", "future"])
def test_incomparable_runs_do_not_create_observations(db, change, monkeypatch):
    save(db)
    save(db, "2", day=6 if change == "future" else 4, hr=130,
         reverse=change == "reverse", complete=change != "incomplete", route=change != "missing_route",
         seconds=3000 if change == "too_long" else 2400, speed=3.2 if change == "different_pace" else 3.)
    with Session(db) as session:
        if change == "sensor":
            session.add(RunFitnessReference(created_at=datetime(2026, 10, 3), payload=json.dumps({
                "sensor_changes": [{"date": "2026-10-03", "label": "New strap"}]})))
        if change == "annotation":
            session.add(RunAnnotation(external_id="run-2", exclude=True))
        session.commit()
    if change == "legacy":
        monkeypatch.setattr(reference.settings, "watch_source_legacy_session_ids", ["run-2"])
    reference.choose("1")
    assert reference.overview(today=date(2026, 10, 5))["observations"] == []


@pytest.mark.parametrize("change", ["missing", "incomplete", "missing_route", "short"])
def test_unusable_anchor_is_not_saved(db, change):
    if change != "missing":
        save(db, complete=change != "incomplete", route=change != "missing_route", seconds=900 if change == "short" else 2400)
    assert reference.selection("1")["selectable"] is False
    with pytest.raises(ValueError):
        reference.choose("1")
    assert reference.selection()["reference"] is None


def test_later_exclusion_preserves_selection_but_withholds_results(db):
    save(db)
    reference.choose("1")
    with Session(db) as session:
        session.add(RunAnnotation(external_id="run-1", exclude=True))
        session.commit()
    result = reference.overview(today=date(2026, 10, 5))
    assert result["status"] == "unavailable"
    assert result["reference"]["activity_id"] == "1"
    assert result["observations"] == []


def test_api_validation_and_selection_roundtrip(db):
    save(db)
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        assert client.get('/running/reference?days=0').status_code == 422
        assert client.get('/running/reference/selection?activity_id=abc').status_code == 422
        assert client.put('/running/reference', json={"activity_id": "abc"}).status_code == 422
        assert client.put('/running/reference', json={"activity_id": "999"}).status_code == 422
        assert client.put('/running/reference', json={"activity_id": "1", "extra": True}).status_code == 422
        assert client.put('/running/reference', json={"activity_id": "1"}).json()["reference"]["activity_id"] == "1"
        assert client.delete('/running/reference').json()["reference"] is None
