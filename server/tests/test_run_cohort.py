import json
from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

from app.api.run_insights import router
from app.garmin_activity import GarminActivity
from app.garmin_routes import GarminRoute
from app.metrics import run_cohort as cohort
from app.models import RunAnnotation, RunFitnessReference


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'cohort.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[GarminActivity.__table__, GarminRoute.__table__,
        RunAnnotation.__table__, RunFitnessReference.__table__])
    monkeypatch.setattr(cohort, "engine", engine)
    monkeypatch.setattr(cohort.settings, "watch_source_switch_date", date(2026, 9, 25))
    monkeypatch.setattr(cohort.settings, "watch_source_package", cohort.insights.GARMIN_PACKAGE)
    monkeypatch.setattr(cohort.settings, "watch_source_legacy_session_ids", [])
    yield engine
    engine.dispose()


def save(db, activity_id="1", *, day=2, pace=360, hr=140, complete=True,
         distance=3, route=True, reverse=False, shift=0):
    started = datetime(2026, 10, day, 10)
    summary = dict(title="Synthetic run", duration_seconds=pace * distance,
                   distance_km=distance, avg_hr=hr, activity_type="running")
    geometry = [{"lat": 51 + i * 30 / 111195, "lon": 6. + shift} for i in range(101)]
    with Session(db) as session:
        session.add(GarminActivity(activity_id=activity_id, started_at=started,
            canonical_external_id=f"run-{activity_id}", summary_json=json.dumps(summary),
            series_json="[]", laps_json="[]", zones_json="[]",
            quality_json=json.dumps({"complete": complete, "canonical": complete}),
            fingerprint="synthetic", fetched_at=started))
        if route:
            session.add(GarminRoute(activity_id=activity_id, title="Synthetic route", started_at=started,
                distance_km=3, point_count=len(geometry),
                segments_json=json.dumps([list(reversed(geometry)) if reverse else geometry]), synced_at=started))
        session.commit()


def test_all_other_runs_form_cohort_without_selected_or_temporal_leakage_claim(db):
    save(db, day=2, pace=360, hr=140)
    save(db, "2", day=1, pace=380, hr=135)
    save(db, "3", day=4, pace=340, hr=150)
    result = cohort.comparison("1", today=date(2026, 10, 5))
    assert result["status"] == "ready"
    assert [row["activity_id"] for row in result["cohort"]] == ["2", "3"]
    assert result["period_start"].startswith("2026-10-01")
    assert result["period_end"].startswith("2026-10-04")
    assert result["metrics"]["avg_hr"] == dict(n=2, selected=140, median=142.5,
        min=135, max=150, q1=None, q3=None, delta=-2.5)
    assert result["metrics"]["pace_seconds"]["delta"] == 0
    assert all(item["overlap_pct"] == 100 for item in result["cohort"])
    assert "auch spätere Läufe" in result["method"]
    assert "lat" not in result and "segments" not in result


@pytest.mark.parametrize("change", ["route", "reverse", "length", "incomplete", "sensor", "excluded",
                                     "special", "legacy", "future", "different"])
def test_incompatible_runs_are_excluded(db, change, monkeypatch):
    save(db)
    save(db, "2", day=6 if change == "future" else 4, route=change != "route",
         reverse=change == "reverse", distance=6 if change == "length" else 3,
         complete=change != "incomplete", shift=.02 if change == "different" else 0)
    with Session(db) as session:
        if change == "sensor":
            session.add(RunFitnessReference(created_at=datetime(2026, 10, 3), payload=json.dumps({
                "sensor_changes": [{"date": "2026-10-03", "label": "New strap"}]})))
        if change in {"excluded", "special"}:
            session.add(RunAnnotation(external_id="run-2", exclude=change == "excluded",
                                      category="intervals" if change == "special" else "auto"))
        session.commit()
    if change == "legacy":
        monkeypatch.setattr(cohort.settings, "watch_source_legacy_session_ids", ["run-2"])
    result = cohort.comparison("1", today=date(2026, 10, 5))
    assert result["status"] == "empty"
    assert result["cohort"] == []
    assert result["metrics"]["pace_seconds"]["median"] is None


@pytest.mark.parametrize("change", ["incomplete", "route", "excluded"])
def test_unusable_selected_run_has_explicit_reason(db, change):
    save(db, complete=change != "incomplete", route=change != "route")
    save(db, "2", day=1)
    if change == "excluded":
        with Session(db) as session:
            session.add(RunAnnotation(external_id="run-1", exclude=True))
            session.commit()
    result = cohort.comparison("1")
    assert result["status"] == "unavailable"
    assert result["reason"]
    assert result["cohort"] == []


def test_missing_heart_rate_keeps_pace_and_does_not_become_zero(db):
    save(db, hr=None)
    save(db, "2", hr=145)
    save(db, "3", hr=None)
    result = cohort.comparison("1")
    assert len(result["cohort"]) == 2
    assert result["metrics"]["avg_hr"]["n"] == 1
    assert result["metrics"]["avg_hr"]["delta"] is None
    assert result["metrics"]["avg_hr"]["median"] == 145
    assert result["metrics"]["pace_seconds"]["n"] == 2


def test_no_100_run_limit_and_no_selected_weight_in_distribution(db):
    save(db, pace=300, hr=170)
    for index in range(2, 104):
        save(db, str(index), pace=360, hr=140)
    result = cohort.comparison("1")
    assert len(result["cohort"]) == 102
    assert result["metrics"]["avg_hr"]["median"] == 140
    assert result["metrics"]["avg_hr"]["delta"] == 30
    assert result["metrics"]["pace_seconds"]["median"] == 360


def test_distribution_small_samples_outlier_and_missing_values():
    empty = cohort.distribution(None, [])
    assert empty == dict(n=0, selected=None, median=None, min=None, max=None, q1=None, q3=None, delta=None)
    single = cohort.distribution(10, [8, None, float("nan"), True, float("inf")])
    assert single == dict(n=1, selected=10, median=8, min=8, max=8, q1=None, q3=None, delta=2)
    four = cohort.distribution(6, [1, 2, 3, 100])
    assert four["median"] == 2.5 and four["q1"] is None
    five = cohort.distribution(6, [1, 2, 3, 4, 100])
    assert five == dict(n=5, selected=6, median=3, min=1, max=100, q1=2, q3=4, delta=3)


def test_canonical_aliases_never_count_selected_or_other_runs_twice(db):
    save(db, pace=300)
    save(db, "2", pace=310)
    save(db, "3", pace=380)
    save(db, "4", pace=370)
    with Session(db) as session:
        alias = session.get(GarminActivity, "2")
        alias.canonical_external_id = "run-1"
        duplicate = session.get(GarminActivity, "4")
        duplicate.canonical_external_id = "run-3"
        duplicate.fetched_at = datetime(2026, 10, 1)
        session.add_all([alias, duplicate])
        session.commit()
    result = cohort.comparison("1")
    assert [item["activity_id"] for item in result["cohort"]] == ["3"]
    assert result["metrics"]["pace_seconds"]["median"] == 380
    assert result["metrics"]["pace_seconds"]["n"] == 1


def test_api_returns_cohort_or_not_found_without_coordinates(db):
    save(db)
    save(db, "2", day=1)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/metrics/running/insights/cohort/1")
    assert response.status_code == 200
    assert response.json()["cohort"][0]["activity_id"] == "2"
    assert "segments_json" not in response.text and '"lon"' not in response.text
    assert client.get("/metrics/running/insights/cohort/404").status_code == 404
