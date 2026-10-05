import copy
import json
from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

from app.api import run_insights as api
from app.garmin_activity import GarminActivity
from app.garmin_routes import GarminRoute
from app.metrics import run_insights as insights
from app.models import RunAnnotation


def recording(seconds=2400, early_hr=140, late_hr=150, late_speed=3., grade=0):
    summary = {"elapsed_seconds": seconds, "duration_seconds": seconds, "distance_km": 7.2,
               "activity_type": "running", "title": "Synthetic run"}
    points, distance = [], 0
    for second in range(seconds + 1):
        speed = 3. if second < 1440 else late_speed
        if second:
            distance += speed
        points.append({"elapsed_seconds": second, "timer_seconds": second, "distance_m": distance,
                       "hr_bpm": early_hr if second < 1440 else late_hr, "speed_m_s": speed,
                       "altitude_m": 100 + distance * grade / 100, "gap": False,
                       "cadence_spm": 170, "power_w": 250})
    return summary, points


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'insights.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[GarminActivity.__table__, GarminRoute.__table__, RunAnnotation.__table__])
    monkeypatch.setattr(insights, "engine", engine)
    monkeypatch.setattr(insights.settings, "watch_source_switch_date", date(2026, 9, 25))
    monkeypatch.setattr(insights.settings, "watch_source_package", insights.GARMIN_PACKAGE)
    monkeypatch.setattr(insights.settings, "watch_source_legacy_session_ids", [])
    monkeypatch.setattr(insights.settings, "run_hr_max", 200.)
    yield engine
    engine.dispose()


def save(db, id="1", day=2, complete=True, **kwargs):
    summary, series = recording(**kwargs)
    row = GarminActivity(activity_id=id, started_at=datetime(2026, 10, day, 10),
        canonical_external_id=f"run-{id}", summary_json=json.dumps(summary), series_json=json.dumps(series),
        laps_json="[]", zones_json="[]", quality_json=json.dumps({"complete": complete, "canonical": complete}),
        fingerprint="test", fetched_at=datetime(2026, 10, day, 12))
    with Session(db) as session:
        session.add(row)
        session.commit()
    return row


def test_drift_matches_workload_and_reports_descriptive_difference():
    summary, series = recording()
    result = insights.drift(summary, series)
    assert result["status"] == "observed"
    assert result["matched_pairs"] >= 6
    assert result["hr_delta_bpm"] == pytest.approx(10, abs=.02)
    assert result["value_pct"] == pytest.approx(7.14, abs=.02)
    assert "Signifikanztest" in result["method"]


@pytest.mark.parametrize("change", ["missing_altitude", "faster_late", "steep", "sparse", "short", "excluded"])
def test_drift_withholds_incomparable_values(change):
    summary, series = recording(seconds=1200 if change == "short" else 2400,
                                late_speed=4 if change == "faster_late" else 3,
                                grade=4 if change == "steep" else 0)
    if change == "missing_altitude":
        for point in series:
            point["altitude_m"] = None
    if change == "sparse":
        series = series[::30]
    result = insights.drift(summary, series, change != "excluded")
    assert result["value_pct"] is None


def test_pauses_and_two_minutes_after_them_are_excluded():
    summary, series = recording()
    series[1200]["gap"] = True
    minutes = insights.steady_minutes(summary, series)
    assert all(not 20 <= point["minute"] < 22 for point in minutes)
    assert all(10 <= point["minute"] < 38 for point in minutes)


def test_opposite_hills_do_not_cancel_into_flat_minutes():
    summary, series = recording()
    for point in series:
        phase = point["elapsed_seconds"] % 60
        point["altitude_m"] = 100 + min(phase, 60 - phase) * .3
    assert insights.steady_minutes(summary, series) == []
    assert insights.drift(summary, series)["value_pct"] is None


def test_pair_matching_never_reuses_a_minute():
    first = [{"hr": 140, "speed": 3, "grade": 0}] * 10
    second = [{"hr": 145, "speed": 3, "grade": 0}] * 3
    assert len(insights._match(first, second)) == 3


def test_zones_use_time_not_sample_count_and_allocate_crossings():
    points = [dict(elapsed_seconds=t, timer_seconds=t, hr_bpm=hr, gap=False)
              for t, hr in [(0, 110), (10, 130), (11, 130)]]
    result = insights.zone_summary({"duration_seconds": 11}, points, 200)
    assert result["zones"][0]["seconds"] == 5
    assert result["zones"][1]["seconds"] == 6
    assert result["known_seconds"] == 11


def test_zones_retain_unknown_outside_and_paused_time_separately():
    points = [dict(elapsed_seconds=t, timer_seconds=timer, hr_bpm=hr, gap=gap)
              for t, timer, hr, gap in [(0, 0, 80, False), (10, 10, 80, False),
                 (20, 20, None, False), (30, 30, 140, False), (50, 30, 140, True), (60, 40, 140, False)]]
    result = insights.zone_summary({"duration_seconds": 40}, points, 200)
    assert result["outside_seconds"] == 10
    assert result["unknown_seconds"] == 20
    assert result["zones"][2]["seconds"] == 10


def test_invalid_max_does_not_invent_zones():
    summary, series = recording()
    result = insights.zone_summary(summary, series, float("nan"))
    assert result["hr_max"] is None
    assert result["zones"] == []
    assert result["unknown_seconds"] == 2400


def test_comparison_exclusions_and_delta_direction(db):
    save(db, "1", early_hr=140, late_hr=140)
    save(db, "2", day=3, early_hr=145, late_hr=145)
    result = insights.compare("1", "2")
    assert result["comparison"]["hr_delta_bpm"] == 5
    assert result["comparison"]["pace_delta_seconds"] == 0
    with Session(db) as session:
        session.add(RunAnnotation(external_id="run-2", exclude=True))
        session.commit()
    assert insights.compare("1", "2")["comparison"]["status"] == "excluded"
    assert insights.activity_insights("1")["candidates"] == []


def test_same_run_and_incomplete_record_are_not_comparisons(db):
    save(db)
    save(db, "2", complete=False)
    assert insights.compare("1", "1")["comparison"]["status"] == "excluded"
    assert insights.compare("1", "2")["comparison"]["status"] == "excluded"


def test_weekly_totals_follow_local_monday_and_exclude_bad_data(db):
    save(db, "1", day=4)
    save(db, "2", day=5)
    save(db, "3", day=5, complete=False)
    result = insights.weekly_zones(2, today=date(2026, 10, 5))
    assert [week["week"] for week in result["weeks"]] == ["2026-09-28", "2026-10-05"]
    assert [week["runs"] for week in result["weeks"]] == [1, 1]
    assert result["weeks"][1]["excluded_runs"] == 1
    assert result["weeks"][0]["known_seconds"] == 2400


def test_no_runs_means_empty_coverage_not_fabricated_training(db):
    result = insights.weekly_zones(2, today=date(2026, 10, 5))
    assert all(week["runs"] == 0 for week in result["weeks"])
    assert "keine Aussage" in result["note"]


def test_route_similarity_is_directional_and_requires_continuous_geometry():
    points = [{"lat": 51 + n / 10000, "lon": 6., "time": None} for n in range(200)]
    first = GarminRoute(activity_id="1", title="A", started_at=datetime(2026, 10, 1),
                        point_count=200, segments_json=json.dumps([points]), synced_at=datetime(2026, 10, 1))
    second = copy.deepcopy(first)
    assert insights.similar_route(first, second)
    second.segments_json = json.dumps([list(reversed(points))])
    assert not insights.similar_route(first, second)
    second.segments_json = json.dumps([points[:100], points[100:]])
    assert not insights.similar_route(first, second)


def test_api_routes_validation_and_missing_record(db):
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        assert client.get('/metrics/running/insights/compare?first=1&second=2').status_code == 404
        assert client.get('/metrics/running/insights/compare?first=abc&second=2').status_code == 422
        assert client.get('/metrics/running/insights/zones?weeks=0').status_code == 422
        assert client.get('/metrics/running/insights/123').json()['available'] is False
