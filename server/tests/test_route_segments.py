import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

from app.api.route_segments import router
from app.garmin_activity import GarminActivity
from app.garmin_routes import GarminRoute
from app.metrics import route_segments as segments
from app.models import RunAnnotation, RunFitnessReference


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'sections.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[GarminActivity.__table__, GarminRoute.__table__,
        RunAnnotation.__table__, RunFitnessReference.__table__])
    monkeypatch.setattr(segments, "engine", engine)
    monkeypatch.setattr(segments.run_cohort, "engine", engine)
    monkeypatch.setattr(segments.run_cohort.settings, "watch_source_switch_date", date(2026, 9, 25))
    monkeypatch.setattr(segments.run_cohort.settings, "watch_source_package", segments.run_cohort.insights.GARMIN_PACKAGE)
    monkeypatch.setattr(segments.run_cohort.settings, "watch_source_legacy_session_ids", [])
    yield engine
    engine.dispose()


def save(db, activity_id="1", *, pace=300, hr=140, canonical=None, reverse=False, offset=0):
    start = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
    raw = [{"lat": 51 + (index * 10 + offset) / 111195, "lon": 6.,
            "time": (start + timedelta(seconds=index * pace / 100)).isoformat()} for index in range(301)]
    if reverse:
        coordinates = [(point["lat"], point["lon"]) for point in raw][::-1]
        for point, (lat, lon) in zip(raw, coordinates):
            point.update(lat=lat, lon=lon)
    series = [{"elapsed_seconds": index * pace / 100, "timer_seconds": index * pace / 100,
               "distance_m": index * 10, "hr_bpm": hr, "gap": False} for index in range(301)]
    summary = {"title": "Synthetic", "started_at_utc": start.isoformat(), "distance_km": 3.,
               "duration_seconds": pace * 3, "elapsed_seconds": pace * 3,
               "avg_hr": hr, "activity_type": "running"}
    with Session(db) as session:
        session.add(GarminActivity(activity_id=activity_id, started_at=start.replace(tzinfo=None),
            canonical_external_id=canonical or f"run-{activity_id}", summary_json=json.dumps(summary),
            series_json=json.dumps(series), laps_json="[]", zones_json="[]", quality_json='{"complete":true,"canonical":true}',
            fingerprint="synthetic", fetched_at=start.replace(tzinfo=None)))
        session.add(GarminRoute(activity_id=activity_id, title="Synthetic", started_at=start.replace(tzinfo=None),
            started_at_utc=start.isoformat(), distance_km=3., point_count=301,
            segments_json=json.dumps([raw]), synced_at=start.replace(tzinfo=None)))
        session.commit()


def mutate(db, activity_id, model, field, change):
    with Session(db) as session:
        row = session.get(model, activity_id)
        value = json.loads(getattr(row, field))
        change(value)
        setattr(row, field, json.dumps(value))
        session.add(row)
        session.commit()


def test_metrics_are_paired_run_observations_with_selected_excluded(db):
    save(db)
    save(db, "2", pace=360, hr=150)
    save(db, "3", pace=330, hr=160)
    result = segments.comparison("1")
    assert result["status"] == "ready"
    assert len(result["sections"]) == 6
    first = result["sections"][0]
    assert first["n"] == 2 and first["omitted_runs"] == 0
    assert first["metrics"]["pace_seconds"]["selected"] == pytest.approx(300)
    assert first["metrics"]["pace_seconds"]["median"] == pytest.approx(345)
    assert first["metrics"]["avg_hr"]["median"] == pytest.approx(155)
    assert first["metrics"]["avg_hr"]["min"] == pytest.approx(150)
    assert first["metrics"]["avg_hr"]["max"] == pytest.approx(160)
    assert first["metrics"]["avg_hr"]["delta"] == pytest.approx(-15)
    assert first["metrics"]["avg_hr"]["q1"] is None


def test_shifted_start_is_not_blindly_aligned_by_distance(db):
    save(db)
    save(db, "2", offset=50)
    result = segments.comparison("1")
    assert result["cohort_runs"] == 1
    assert all(section["n"] == 0 for section in result["sections"])


def test_small_start_difference_uses_physical_endpoint_times(db):
    save(db)
    save(db, "2", offset=20)
    # Early first 20 m has a different HR. The matching 500–1000 m section
    # physically starts at candidate distance 480 m, not distance 500 m.
    def ramp(points):
        for point in points:
            point["hr_bpm"] = 100 + point["distance_m"] / 30
    mutate(db, "2", GarminActivity, "series_json", ramp)
    section = segments.comparison("1")["sections"][1]
    assert section["n"] == 1
    assert section["metrics"]["avg_hr"]["median"] == pytest.approx(100 + 730 / 30, abs=.01)


@pytest.mark.parametrize("kind", ["gap", "pause", "distance_reset", "distance_unit", "missing_hr"])
def test_bad_intervals_are_not_interpolated_or_counted_as_zero(db, kind):
    save(db)
    save(db, "2")
    def change(points):
        if kind == "gap":
            points[20]["gap"] = True
        elif kind == "pause":
            points[20]["timer_seconds"] = points[19]["timer_seconds"]
        elif kind == "distance_reset":
            points[20]["distance_m"] = 0
        elif kind == "distance_unit":
            for point in points:
                point["distance_m"] /= 1000
        else:
            for point in points[:40]:
                point["hr_bpm"] = None
    mutate(db, "2", GarminActivity, "series_json", change)
    result = segments.comparison("1")
    assert result["sections"][0]["n"] == 0
    assert result["sections"][0]["metrics"]["avg_hr"]["median"] is None
    if kind != "distance_unit":
        assert result["sections"][2]["n"] == 1


def test_utc_offsets_are_equivalent_and_naive_times_rejected(db):
    save(db)
    save(db, "2")
    def offset_time(raw):
        for point in raw[0]:
            point["time"] = datetime.fromisoformat(point["time"]).astimezone(timezone(timedelta(hours=2))).isoformat()
    mutate(db, "2", GarminRoute, "segments_json", offset_time)
    assert segments.comparison("1")["sections"][0]["n"] == 1
    def naive(raw):
        raw[0][20]["time"] = raw[0][20]["time"][:19]
    mutate(db, "2", GarminRoute, "segments_json", naive)
    assert segments.comparison("1")["sections"][0]["n"] == 0


def test_reverse_and_canonical_aliases_do_not_enter_distribution(db):
    save(db)
    save(db, "2", reverse=True)
    save(db, "3", canonical="run-1")
    save(db, "4")
    save(db, "5", canonical="run-4")
    result = segments.comparison("1")
    assert result["cohort_runs"] == 1
    assert result["sections"][0]["n"] == 1


def test_annotation_exclusions_are_inherited(db):
    save(db)
    save(db, "2")
    with Session(db) as session:
        session.add(RunAnnotation(external_id="run-2", exclude=True))
        session.commit()
    assert segments.comparison("1")["cohort_runs"] == 0


def test_sensor_periods_are_not_mixed(db):
    save(db)
    save(db, "2")
    with Session(db) as session:
        other = session.get(GarminActivity, "2")
        other.started_at = datetime(2026, 10, 3, 10)
        session.add(other)
        session.add(RunFitnessReference(created_at=datetime(2026, 10, 2), payload=json.dumps({
            "sensor_changes": [{"date": "2026-10-02", "label": "New strap"}]})))
        session.commit()
    assert segments.comparison("1", today=date(2026, 10, 5))["cohort_runs"] == 0


def test_gps_time_gap_excludes_only_affected_sections(db):
    save(db)
    save(db, "2")
    def gap(raw):
        # The cohort tolerates a small spatial gap, but the section must not
        # interpolate elapsed time through a missing 18-second GPS interval.
        del raw[0][15:20]
    mutate(db, "2", GarminRoute, "segments_json", gap)
    result = segments.comparison("1")
    assert result["cohort_runs"] == 1
    assert result["sections"][0]["n"] == 0
    assert result["sections"][1]["n"] == 1


def test_time_weighted_hr_and_partial_boundaries():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    row = GarminActivity(activity_id="1", started_at=start,
        summary_json=json.dumps({"started_at_utc": start.isoformat()}),
        series_json=json.dumps([
            {"elapsed_seconds": time, "timer_seconds": time, "distance_m": time * 3,
             "hr_bpm": hr, "gap": False} for time, hr in [(0, 100), (1, 110), (11, 150), (20, 160)]]))
    result = segments._window(row, start.timestamp() + 1, start.timestamp() + 11, 30)
    assert result["avg_hr"] == pytest.approx(130)
    assert result["pace_seconds"] == pytest.approx(1000 / 3)


def test_repeated_parallel_pass_is_ambiguous():
    # Same line traversed twice in the same direction within the progression
    # tolerance must not silently pick one pass.
    reference = segments.Track(np.array([[6., 51.], [6., 51.03]]), np.array([0., 3335.85]), np.array([0., 1000.]), 51.)
    points = np.array([[6., 51.], [6., 51.001], [6., 51.], [6., 51.03]])
    xy = reference.xy(points)
    distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    other = segments.Track(points, distance, np.arange(4) * 10., 51.)
    assert segments._alignment(reference, other, 0., 500.) is None


def test_api_returns_only_projected_contours_and_handles_missing(db):
    save(db)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/metrics/running/segments/1")
    assert response.status_code == 200
    assert '"lat"' not in response.text and '"lon"' not in response.text
    assert all(0 <= coordinate <= 200 for point in response.json()["contour"] for coordinate in point)
    assert client.get("/metrics/running/segments/999").status_code == 404
    assert client.get("/metrics/running/segments/invalid").status_code == 422
