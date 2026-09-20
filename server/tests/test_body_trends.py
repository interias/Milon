import json

import pandas as pd

from app.metrics import body


def test_weight_gap_is_json_null_without_reusing_old_average(monkeypatch):
    series = pd.Series([80.0, 78.0], index=pd.to_datetime(["2026-01-01", "2026-01-20"])).asfreq("D")
    monkeypatch.setattr(body, "_weight_daily", lambda: series)

    result = body.weight_trend()
    json.dumps(result, allow_nan=False)
    assert result[6]["avg7"] == 80
    assert result[7]["avg7"] is None
    assert result[7]["weight"] is None
    assert result[-1]["avg7"] == 78


def test_body_fat_average_uses_calendar_days_and_exposes_gaps(monkeypatch):
    frame = pd.DataFrame({
        "measured_at": pd.to_datetime(["2026-01-01", "2026-01-03", "2026-01-20"]),
        "body_fat_pct": [24.0, 22.0, 20.0],
    })
    monkeypatch.setattr(body, "_read", lambda *args, **kwargs: frame)

    result = body.body_fat_trend()
    json.dumps(result, allow_nan=False)
    assert len(result) == 20
    assert result[1]["pct"] is None
    assert result[2]["avg7"] == 23
    assert result[9]["avg7"] is None
    assert result[-1]["avg7"] == 20


def test_weekly_weight_omits_empty_weeks_and_serializes(monkeypatch):
    series = pd.Series([80.0, 78.0], index=pd.to_datetime(["2026-01-01", "2026-01-25"])).asfreq("D")
    monkeypatch.setattr(body, "_weight_daily", lambda: series)

    result = body.weekly_weight()
    json.dumps(result, allow_nan=False)
    assert result == [{"week": "2026-01-04", "weight": 80.0}, {"week": "2026-01-25", "weight": 78.0}]


def test_composition_scenario_exposes_anchor_and_assumption(monkeypatch):
    monkeypatch.setattr(body, "weight_forecast", lambda *args: {
        "slope_per_day": -0.02, "current": 80.0, "projected": 79.4, "per_month": -0.6,
    })
    monkeypatch.setattr(body, "lean_mass_trend", lambda **kwargs: [
        {"date": f"2026-01-{day:02d}", "weight": 80.0, "ffm": 60.0, "fat": 20.0}
        for day in range(1, 5)
    ])

    result = body.composition_forecast()
    assert result["from_date"] == "2026-01-04"
    assert [item["key"] for item in result["scenarios"]] == ["preserved", "expected", "trend"]
    assert result["scenarios"][1]["p"] == 0.15
    assert "Annahme" in result["scenarios"][1]["label"]
    assert body.bodyfat_forecast()["from_date"] == "2026-01-04"


def test_adaptive_tdee_exposes_latest_estimate_date(monkeypatch):
    monkeypatch.setattr(body, "tdee_trend", lambda **kwargs: [
        {"date": "2026-01-10", "tdee_avg": 2400, "intake": 2200},
    ])
    monkeypatch.setattr(body, "_weight_daily", lambda: pd.Series(dtype=float))

    assert body.adaptive_tdee()["from_date"] == "2026-01-10"
