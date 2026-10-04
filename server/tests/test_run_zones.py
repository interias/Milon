from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.api import run_zones as zones_api
from app.metrics import run_zones
from app.models import ExerciseSession, RunAnnotation, RunMinute


def config():
    return SimpleNamespace(steps_source_package="com.sec.android.app.shealth",
        watch_source_package="com.garmin.android.apps.connectmobile",
        watch_source_switch_date=date(2026, 9, 25), watch_source_legacy_session_ids=[])


def sample(specs):
    sessions, windows = [], []
    for external_id, day, heart_rate, speed, minutes in specs:
        start = datetime.fromisoformat(day)
        sessions.append(dict(external_id=external_id, started_at=start,
            ended_at=start + timedelta(minutes=60), distance_km=speed * 60 / 1000,
            category="normal", exclude=False))
        for minute in range(minutes):
            windows.append(dict(external_id=external_id, minute=minute + 8.5,
                speed_m_min=speed, hr_bpm=heart_rate, coverage=1.0, steady=True))
    return pd.DataFrame(sessions), pd.DataFrame(windows)


def calculate(specs, hr_max=185):
    sessions, windows = sample(specs)
    return run_zones.analyze(sessions, hr_max, date(2026, 10, 4), config(), windows)


def test_five_zones_partition_integer_bpm_without_shared_boundaries():
    result = run_zones.analyze(pd.DataFrame(), 185, date(2026, 10, 4), config())
    assert [(z["hr_low"], z["hr_high"]) for z in result["zones"]] == [(93, 110), (111, 129), (130, 147), (148, 166), (167, 185)]
    assert result["hr_max_source"] == "configured_reference"
    assert result["sensor"] == {"label": "Garmin", "source_package": "com.garmin.android.apps.connectmobile", "since": "2026-09-25"}
    assert all(z["pace_median_seconds"] is None for z in result["zones"])


@pytest.mark.parametrize("value", [0, -1, None, 99, 251, float("nan"), float("inf")])
def test_missing_reference_never_uses_observed_peak(value):
    result = calculate([("new", "2026-10-01", 180, 180, 40)], value)
    assert result["hr_max"] is None and result["zones"] == []


def test_one_real_run_is_displayed_as_provisional_without_extrapolating_other_zones():
    result = calculate([("new", "2026-10-01", 140, 150, 40)])
    assert result["runs"] == 1 and result["pace_status"] == "observed"
    populated = [zone for zone in result["zones"] if zone["pace_median_seconds"] is not None]
    assert len(populated) == 1
    zone = populated[0]
    assert zone["zone"] == 3 and zone["source"] == "current" and zone["source_label"] == "Garmin"
    assert zone["status"] == "single_run" and zone["provisional"]
    assert zone["supporting_runs"] == 1 and zone["supporting_days"] == 1
    assert zone["pace_median_seconds"] == 400 and zone["speed_median_kmh"] == 9
    assert not any("ci" in key for key in zone)


def test_current_watch_always_wins_even_when_history_has_more_runs():
    result = calculate([("old1", "2026-09-10", 140, 220, 40),
        ("old2", "2026-09-20", 140, 220, 40), ("new", "2026-09-27", 140, 150, 40)])
    zone = result["zones"][2]
    assert zone["source"] == "current" and zone["supporting_runs"] == 1
    assert zone["pace_median_seconds"] == 400


def test_history_only_fills_zones_without_current_support_and_is_explicitly_labelled():
    result = calculate([("old", "2026-09-20", 155, 200, 40), ("new", "2026-09-27", 140, 150, 40)])
    assert result["zones"][2]["source"] == "current"
    zone = result["zones"][3]
    assert zone["source"] == "historical" and zone["source_label"] == "Samsung · vor Wechsel"
    assert zone["from_date"] == zone["to_date"] == "2026-09-20"
    assert zone["pace_median_seconds"] == 300
    assert result["zones"][0]["pace_median_seconds"] is None
    assert result["zones"][4]["pace_median_seconds"] is None


def test_historical_window_has_exact_boundaries_and_stops_before_watch_switch():
    result = calculate([("outside", "2026-07-30", 155, 220, 40),
        ("first", "2026-07-31", 155, 200, 40), ("last", "2026-09-24", 155, 200, 40)])
    zone = result["zones"][3]
    assert result["historical_runs"] == 2
    assert zone["from_date"] == "2026-07-31" and zone["to_date"] == "2026-09-24"
    assert zone["source"] == "historical" and zone["pace_median_seconds"] == 300


def test_runs_have_equal_weight_independent_of_minute_count():
    first = calculate([("long", "2026-09-27", 140, 150, 40), ("short", "2026-10-01", 140, 200, 15)])
    second = calculate([("long", "2026-09-27", 140, 150, 22), ("short", "2026-10-01", 140, 200, 15)])
    for key in ("pace_fast_seconds", "pace_median_seconds", "pace_slow_seconds"):
        assert first["zones"][2][key] == second["zones"][2][key]
    assert first["zones"][2]["pace_median_seconds"] == 350
    assert first["zones"][2]["supporting_runs"] == 2


def test_repeated_minutes_do_not_change_counts_or_quantiles():
    sessions, windows = sample([("new", "2026-10-01", 140, 150, 40)])
    original = run_zones.analyze(sessions, 185, date(2026, 10, 4), config(), windows)
    repeated = run_zones.analyze(pd.concat([sessions] * 3), 185, date(2026, 10, 4), config(), pd.concat([windows] * 3))
    assert repeated == original


def test_insufficient_local_minutes_sparse_coverage_and_annotations_are_not_evidence():
    sessions, windows = sample([("new", "2026-10-01", 140, 150, 40)])
    windows.loc[windows.minute.between(20, 21), "hr_bpm"] = 175
    result = run_zones.analyze(sessions, 185, date(2026, 10, 4), config(), windows)
    assert result["zones"][4]["pace_median_seconds"] is None
    windows["coverage"] = 0.05
    result = run_zones.analyze(sessions, 185, date(2026, 10, 4), config(), windows)
    assert all(zone["pace_median_seconds"] is None for zone in result["zones"])
    windows["coverage"] = 1
    sessions.loc[0, "exclude"] = True
    result = run_zones.analyze(sessions, 185, date(2026, 10, 4), config(), windows)
    assert result["runs"] == 0
    sessions.loc[0, "exclude"] = False
    sessions.loc[0, "category"] = "trail"
    result = run_zones.analyze(sessions, 185, date(2026, 10, 4), config(), windows)
    assert result["runs"] == 0


def test_future_old_outside_window_and_legacy_transition_never_enter():
    sessions, windows = sample([("ancient", "2026-06-01", 140, 220, 40),
        ("future", "2026-10-06", 140, 220, 40), ("legacy", "2026-09-25", 140, 220, 40),
        ("new", "2026-09-27", 140, 150, 40)])
    settings = config()
    settings.watch_source_legacy_session_ids = ["legacy"]
    result = run_zones.analyze(sessions, 185, date(2026, 10, 4), settings, windows)
    assert result["runs"] == 1 and result["historical_runs"] == 0
    assert result["zones"][2]["pace_median_seconds"] == 400


def test_quantile_band_is_observed_distribution_not_confidence_interval():
    sessions, windows = sample([("new", "2026-10-01", 140, 150, 40)])
    windows["speed_m_min"] += windows.minute % 6
    result = run_zones.analyze(sessions, 185, date(2026, 10, 4), config(), windows)
    zone = result["zones"][2]
    assert zone["pace_fast_seconds"] <= zone["pace_median_seconds"] <= zone["pace_slow_seconds"]
    assert zone["speed_low_kmh"] <= zone["speed_median_kmh"] <= zone["speed_high_kmh"]
    assert zone["pace_fast_seconds"] >= 60000 / windows.speed_m_min.max() - 0.1
    assert zone["pace_slow_seconds"] <= 60000 / windows.speed_m_min.min() + 0.1


def test_endpoint_recomputes_after_new_persisted_training(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'zones.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(run_zones, "engine", engine)
    monkeypatch.setattr(run_zones.settings, "run_hr_max", 185)
    monkeypatch.setattr(run_zones.settings, "watch_source_switch_date", date(2026, 9, 25))
    monkeypatch.setattr(run_zones.settings, "watch_source_package", "com.garmin.android.apps.connectmobile")
    original = run_zones.zones
    monkeypatch.setattr(run_zones, "zones", lambda: original(date(2026, 10, 4)))
    app = FastAPI()
    app.include_router(zones_api.router)

    def add_training(external_id, day, speed):
        sessions, windows = sample([(external_id, day, 140, speed, 40)])
        row = sessions.iloc[0]
        with Session(engine) as session:
            session.add(ExerciseSession(external_id=external_id, started_at=row.started_at.to_pydatetime(),
                ended_at=row.ended_at.to_pydatetime(), exercise_type=33, distance_km=row.distance_km))
            session.add_all([RunMinute(**minute) for minute in windows.to_dict("records")])
            session.commit()

    add_training("first", "2026-09-27", 150)
    with TestClient(app) as client:
        first = client.get("/metrics/running/zones")
        assert first.status_code == 200 and first.json()["zones"][2]["pace_median_seconds"] == 400
        add_training("second", "2026-10-01", 200)
        updated = client.get("/metrics/running/zones").json()
        assert updated["runs"] == 2 and updated["zones"][2]["pace_median_seconds"] == 350
        with Session(engine) as session:
            session.add(RunAnnotation(external_id="second", exclude=True))
            session.commit()
        assert client.get("/metrics/running/zones").json()["zones"][2]["pace_median_seconds"] == 400
        monkeypatch.setattr(run_zones.settings, "run_hr_max", 200)
        changed_reference = client.get("/metrics/running/zones").json()
        assert changed_reference["hr_max"] == 200
        assert changed_reference["zones"][2]["hr_low"] == 140
        assert changed_reference["zones"][2]["pace_median_seconds"] == 400
    engine.dispose()
