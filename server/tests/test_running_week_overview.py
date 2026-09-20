from datetime import date, datetime

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import metrics
from app.metrics import running


def runs(monkeypatch, rows):
    frame = pd.DataFrame(rows, columns=["started_at", "distance_km", "dur_min"])
    frame["started_at"] = pd.to_datetime(frame["started_at"])
    monkeypatch.setattr(running, "_runs", lambda: frame)


def test_empty_current_week_does_not_fall_back_to_last_active_week(monkeypatch):
    runs(monkeypatch, [("2026-09-13 10:00", 10, 61.2)])
    result = running.week_overview(date(2026, 9, 16))
    assert result == {
        "week_start": "2026-09-14", "previous_week_start": "2026-09-07",
        "current": {"km": 0.0, "runs": 0, "minutes": 0.0},
        "previous": {"km": 10.0, "runs": 1, "minutes": 61.2},
    }


def test_year_boundary_and_injected_today_include_only_today_and_prior_dates(monkeypatch):
    runs(monkeypatch, [
        ("2025-12-21 12:00", 50, 300),
        ("2025-12-28 23:59", 5, 30),
        ("2025-12-29 00:00", 6, 36),
        ("2026-01-01 23:59", 7, 43),
        ("2026-01-02 00:00", 8, 48),
    ])
    result = running.week_overview(date(2026, 1, 1))
    assert result["week_start"] == "2025-12-29"
    assert result["previous_week_start"] == "2025-12-22"
    assert result["current"] == {"km": 13.0, "runs": 2, "minutes": 79.0}
    assert result["previous"] == {"km": 5.0, "runs": 1, "minutes": 30.0}


def test_live_clock_uses_configured_timezone_and_excludes_future_times(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert str(tz) == "Pacific/Auckland"
            return cls(2026, 1, 5, 0, 30, tzinfo=tz)

    monkeypatch.setattr(running, "datetime", Clock)
    monkeypatch.setattr(running.settings, "timezone", "Pacific/Auckland")
    runs(monkeypatch, [
        ("2026-01-04 23:59", 5, 30),
        ("2026-01-05 00:01", 6, 36),
        ("2026-01-05 01:00", 7, 42),
    ])
    result = running.week_overview()
    assert result["week_start"] == "2026-01-05"
    assert result["current"]["km"] == 6
    assert result["previous"]["km"] == 5


def test_empty_data_and_http_schema(monkeypatch):
    runs(monkeypatch, [])
    app = FastAPI()
    app.include_router(metrics.router)
    response = TestClient(app).get("/metrics/running/week-overview")
    assert response.status_code == 200
    data = response.json()
    assert data["current"] == data["previous"] == {"km": 0.0, "runs": 0, "minutes": 0.0}
    assert date.fromisoformat(data["week_start"]).weekday() == 0
