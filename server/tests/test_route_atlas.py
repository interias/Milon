import json
from datetime import date, datetime, timedelta

import pytest
from sqlmodel import SQLModel, Session, create_engine
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.garmin_activity import GarminActivity
from app.garmin_routes import GarminRoute
from app.metrics import route_atlas as atlas
from app.models import RunAnnotation, RunFitnessReference, SyncState


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'atlas.db'}")
    SQLModel.metadata.create_all(engine, tables=[GarminActivity.__table__, GarminRoute.__table__,
                                                RunAnnotation.__table__, RunFitnessReference.__table__, SyncState.__table__])
    monkeypatch.setattr(atlas, "engine", engine)
    monkeypatch.setattr(atlas.run_insights.settings, "watch_source_switch_date", date(2026, 9, 25))
    monkeypatch.setattr(atlas.run_insights.settings, "watch_source_package", atlas.run_insights.GARMIN_PACKAGE)
    monkeypatch.setattr(atlas.run_insights.settings, "watch_source_legacy_session_ids", [])
    atlas._geometry_cache.clear()
    atlas._group_cache.clear()
    yield engine
    engine.dispose()


def save(db, activity_id, *, day=1, shift=0, reverse=False, alias=None, complete=True, pace=360, hr=140):
    started = datetime(2026, 10, day, 10)
    points = [{"lat": 51 + i * 30 / 111195, "lon": 6 + shift / 70000} for i in range(101)]
    with Session(db) as session:
        session.add(GarminRoute(activity_id=activity_id, title="Synthetic route", started_at=started,
            distance_km=3, duration_seconds=pace * 3, point_count=101,
            segments_json=json.dumps([points[::-1] if reverse else points]), synced_at=started))
        session.add(GarminActivity(activity_id=activity_id, started_at=started,
            canonical_external_id=alias or f"run-{activity_id}", summary_json=json.dumps({"title": "Synthetic run",
                "distance_km": 3, "duration_seconds": pace * 3, "avg_hr": hr, "activity_type": "running"}),
            quality_json=json.dumps({"complete": complete, "canonical": complete}),
            series_json="[]", laps_json="[]", zones_json="[]", fingerprint="test", fetched_at=started))
        session.commit()


def test_empty_atlas_is_valid(db):
    assert atlas.atlas()["groups"] == []
    assert atlas.atlas()["total_runs"] == 0


def test_fixed_anchor_prevents_transitive_chaining_and_is_input_order_independent(db):
    save(db, "3", day=3, shift=50)
    save(db, "1", day=1)
    save(db, "2", day=2, shift=25)
    result = atlas.atlas()
    assert result["total_runs"] == 3
    assert [(group["anchor_id"], group["count"]) for group in result["groups"]] == [("3", 1), ("1", 2)]
    assert '"lat":' not in json.dumps(result) and '"lon":' not in json.dumps(result)
    for group in result["groups"]:
        assert all(9 <= value <= 191 for segment in group["contour"] for point in segment for value in point)


def test_reversed_route_stays_separate(db):
    save(db, "1")
    save(db, "2", day=2, reverse=True)
    assert len(atlas.atlas()["groups"]) == 2


def test_canonical_alias_counts_once_and_keeps_newest_recording(db):
    save(db, "1", alias="same")
    save(db, "2", day=2, alias="same")
    result = atlas.atlas()
    assert result["total_runs"] == 1
    assert result["groups"][0]["members"][0]["activity_id"] == "2"


def test_progress_is_descriptive_excludes_annotations_and_sensor_changes(db):
    save(db, "1", pace=360, hr=140)
    save(db, "2", day=2, pace=350, hr=138)
    save(db, "3", day=3, pace=330, hr=150)
    result = atlas.atlas()["groups"][0]
    assert result["changes"]["pace_seconds"]["delta"] == -30
    with Session(db) as session:
        session.add(RunAnnotation(external_id="run-3", exclude=True))
        session.commit()
    result = atlas.atlas()["groups"][0]
    assert result["count"] == 3
    assert result["changes"]["pace_seconds"]["delta"] == -10
    with Session(db) as session:
        session.add(RunFitnessReference(created_at=datetime(2026, 10, 3), payload=json.dumps({
            "sensor_changes": [{"date": "2026-10-03", "label": "New strap"}]})))
        session.commit()
    assert atlas.atlas()["groups"][0]["changes"]["avg_hr"] is None


def test_cache_reuses_grouping_but_invalidates_route_revision(db, monkeypatch):
    save(db, "1")
    save(db, "2", day=2)
    atlas.atlas()
    original = atlas.overlap
    calls = []
    monkeypatch.setattr(atlas, "overlap", lambda a, b: calls.append(True) or original(a, b))
    atlas.atlas()
    assert calls == []
    with Session(db) as session:
        row = session.get(GarminRoute, "2")
        row.synced_at += timedelta(seconds=1)
        session.add(row)
        session.commit()
    atlas.atlas()
    assert calls == [True]


def test_atlas_is_not_limited_to_first_hundred_runs(db):
    with Session(db) as session:
        for index in range(105):
            session.add(GarminRoute(activity_id=str(index), title="Incomplete GPS", started_at=datetime(2026, 10, 1),
                point_count=0, segments_json="[]", synced_at=datetime(2026, 10, 1)))
        session.commit()
    result = atlas.atlas()
    assert result["total_runs"] == 105
    assert len(result["groups"]) == 105


def test_api_serializes_sync_and_complete_atlas(db, monkeypatch):
    from app.api import route_atlas as api
    monkeypatch.setattr(api, "engine", db)
    monkeypatch.setattr(api, "configured", lambda: True)
    save(db, "1")
    with Session(db) as session:
        session.add(SyncState(source="garmin", last_sync=datetime(2026, 10, 5), status="ok"))
        session.commit()
    app = FastAPI()
    app.include_router(api.router)
    response = TestClient(app).get("/metrics/running/route-atlas")
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["sync"] == {"last_sync": "2026-10-05T00:00:00", "status": "ok"}
    assert response.json()["total_runs"] == 1
