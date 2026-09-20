"""Guard the offline comparison against inventing coverage across gaps."""
import pandas as pd
import pytest

from scripts.compare_body_gaps import candidate, latest_segment, composition_observed


def test_candidate_uses_calendar_time_and_recovers_linear_trend():
    dates = pd.date_range("2026-01-01", periods=30)
    series = pd.Series([80 - n * 0.02 for n in range(30)], index=dates)
    series.iloc[[5, 8, 12, 19]] = float("nan")
    result = candidate(series)
    assert result["available"]
    assert result["observed_days"] == 26
    assert result["per_month"] == pytest.approx(-0.6)
    assert result["projected"] == pytest.approx(78.82)


def test_long_gap_cannot_supply_forecast_coverage():
    dates = pd.date_range("2026-01-01", periods=60)
    series = pd.Series(80.0, index=dates)
    series.iloc[20:45] = float("nan")
    assert len(latest_segment(series)) == 15
    assert not candidate(series)["available"]


def test_composition_requires_recent_paired_observations():
    dates = pd.date_range("2026-01-01", periods=20)
    weight = pd.Series(80.0, index=dates)
    bf = pd.Series(25.0, index=dates)
    bf.iloc[3:18] = float("nan")
    result = composition_observed(weight, bf)
    assert list(result.index) == [dates[2]]
    assert result.iloc[0].ffm == 60.0
