import json

import pandas as pd

from app.metrics import body


def test_forecast_resumes_only_when_both_coverage_rules_pass(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=70)
    weight = pd.Series(80.0, index=dates)
    weight.iloc[20:48] = float("nan")
    monkeypatch.setattr(body, "_weight_daily", lambda: weight.iloc[:-1])
    paused = body.weight_forecast()
    assert not paused["available"]
    assert paused["observed_days"] == 21
    assert paused["span_days"] == 20
    assert "projected" not in paused
    monkeypatch.setattr(body, "_weight_daily", lambda: weight)
    assert body.weight_forecast()["available"]
    sparse = weight.copy()
    sparse.iloc[49:68] = float("nan")
    monkeypatch.setattr(body, "_weight_daily", lambda: sparse)
    assert not body.weight_forecast()["available"]


def test_weekly_weight_skips_empty_weeks(monkeypatch):
    dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03",
                            "2026-01-20", "2026-01-21", "2026-01-22"])
    monkeypatch.setattr(body, "_weight_daily", lambda: pd.Series(80.0, index=dates).asfreq("D"))
