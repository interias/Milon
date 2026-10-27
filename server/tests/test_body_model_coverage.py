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


def test_mass_uses_paired_days_and_keeps_gaps(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=20)
    weight = pd.Series(80.0, index=dates)
    weight.iloc[3] = 120  # No BIA that day: must not affect the paired average.
    bf = pd.Series(25.0, index=dates)
    bf.iloc[3:18] = float("nan")
    monkeypatch.setattr(body, "_weight_daily", lambda: weight)
    monkeypatch.setattr(body, "_bodyfat_daily", lambda: bf)
    rows = body.lean_mass_trend()
    json.dumps(rows, allow_nan=False)
    assert rows[2]["ffm"] == 60
    assert rows[3]["ffm"] is None
    assert rows[-1]["ffm"] is None  # Only two new paired measurements.
    assert body.lean_mass_summary()["to_date"] == "2026-01-03"
    assert not body.composition_forecast()["available"]


def test_scenarios_do_not_reuse_old_bodyfat_anchor(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=30)
    monkeypatch.setattr(body, "_weight_daily", lambda: pd.Series(80.0, index=dates))
    monkeypatch.setattr(body, "_bodyfat_daily", lambda: pd.Series(25.0, index=dates[:-1]))
    assert body.weight_forecast()["available"]
    assert not body.composition_forecast()["available"]
    assert "projected" not in body.bodyfat_forecast()


def test_summary_counts_observed_pairs_not_only_smoothed_estimates(monkeypatch):
    dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03",
                            "2026-01-20", "2026-01-21", "2026-01-22"])
    monkeypatch.setattr(body, "_weight_daily", lambda: pd.Series(80.0, index=dates).asfreq("D"))
    monkeypatch.setattr(body, "_bodyfat_daily", lambda: pd.Series(25.0, index=dates).asfreq("D"))
    assert body.lean_mass_summary()["measurement_days"] == 4
