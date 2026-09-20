import json
from datetime import datetime, timezone

import pandas as pd

from app.metrics import health


def steps_source(monkeypatch, rows):
    frame = pd.DataFrame(rows, columns=["day", "steps"])
    frame["day"] = pd.to_datetime(frame["day"])
    monkeypatch.setattr(health, "_steps", lambda: frame)


def test_step_calendar_preserves_zero_and_expires_missing_average(monkeypatch):
    steps_source(monkeypatch, [("2026-01-01", 1000), ("2026-01-03", 0), ("2026-01-20", 3000)])
    trend = health.steps_trend()
    json.dumps(trend, allow_nan=False)
    assert len(trend) == 20
    assert trend[1] == {"date": "2026-01-02", "steps": None, "avg7": 1000, "days7": 1}
    assert trend[2] == {"date": "2026-01-03", "steps": 0, "avg7": 500, "days7": 2}
    assert trend[9]["avg7"] is None
    assert trend[9]["days7"] == 0
    last_week = health.steps_trend(days=7)
    assert len(last_week) == 7
    assert last_week[0]["date"] == "2026-01-14"


def test_weekly_steps_keep_empty_and_recorded_zero_weeks(monkeypatch):
    steps_source(monkeypatch, [("2026-01-01", 0), ("2026-01-03", 0), ("2026-01-20", 3000)])
    weekly = health.steps_weekly()
    json.dumps(weekly, allow_nan=False)
    assert weekly == [
        {"week": "2026-01-04", "steps": 0, "days": 2},
        {"week": "2026-01-11", "steps": None, "days": 0},
        {"week": "2026-01-18", "steps": None, "days": 0},
        {"week": "2026-01-25", "steps": 3000, "days": 1},
    ]


def test_step_summary_counts_actual_days_and_labels_config_not_provenance(monkeypatch):
    steps_source(monkeypatch, [("2025-12-01", 9000), ("2026-01-01", 1000), ("2026-01-02", 0), ("2026-01-08", 2000)])
    monkeypatch.setattr(health.settings, "steps_source_package", "com.sec.android.app.shealth")
    result = health.steps_summary()
    assert result["window_start"] == "2026-01-02"
    assert result["days7"] == 2
    assert result["days30"] == 3
    assert result["avg7"] == 1000
    assert result["total_days"] == 4
    assert "Import-Auswahl: Samsung Health" in result["source_label"]
    assert "Fallback" in result["source_label"]


def rides_source(monkeypatch, rows):
    frame = pd.DataFrame(rows, columns=["started_at", "distance_km", "dur_min", "speed"])
    frame["started_at"] = pd.to_datetime(frame["started_at"], format="mixed")
    monkeypatch.setattr(health, "_rides", lambda: frame.copy())


def test_cycling_summary_uses_local_calendar_boundary_and_excludes_future(monkeypatch):
    monkeypatch.setattr(health.settings, "timezone", "Europe/Berlin")
    rides_source(monkeypatch, [
        ("2026-02-28 23:59", 10, 60, 10),
        ("2026-03-01 00:00", 11, 60, 11),
        ("2026-03-29 23:30", 12, 60, 12),
        ("2026-03-30 00:15", 13, 60, 13),
        ("2026-03-30 01:00", 14, 60, 14),
        ("2026-03-31 12:00", 15, 60, 15),
    ])
    # The UTC date is still March 29; Berlin is March 30, after DST started.
    result = health.cycling_summary(datetime(2026, 3, 29, 22, 30, tzinfo=timezone.utc))
    json.dumps(result, allow_nan=False)
    assert result["window_start"] == "2026-03-01"
    assert result["to_date"] == "2026-03-30"
    assert result["km_30d"] == 36
    assert result["total_km"] == 46
    assert result["rides"] == 4
    assert result["last_day"] == "2026-03-30"
    assert result["last_ride"] == {"date": "2026-03-30T00:15:00", "km": 13, "dur_min": 60, "speed": 13}


def test_cycling_recent_zero_limit_returns_complete_history(monkeypatch):
    rides_source(monkeypatch, [(f"2026-01-{day:02}", day, 60, day) for day in range(1, 16)])
    assert len(health.cycling_recent()) == 8
    all_rides = health.cycling_recent(limit=0)
    assert len(all_rides) == 15
    assert all_rides[0]["date"] == "2026-01-15T00:00:00"


def test_empty_health_schemas_include_coverage_and_window(monkeypatch):
    steps_source(monkeypatch, [])
    monkeypatch.setattr(health.settings, "steps_source_package", "")
    steps = health.steps_summary()
    assert steps["days7"] == steps["days30"] == 0
    assert steps["window_start"] is None
    assert steps["source_label"] == "Health Connect · Import-Auswahl: Tagesmaximum je App"
    assert health.steps_trend() == health.steps_weekly() == []
    rides_source(monkeypatch, [])
    rides = health.cycling_summary(datetime(2026, 3, 30, 12, tzinfo=timezone.utc))
    assert rides["last_ride"] is None
    assert rides["km_30d"] == 0
    assert rides["window_start"] == "2026-03-01"
    json.dumps([steps, rides], allow_nan=False)
