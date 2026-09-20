import json

import pandas as pd
import pytest

from app.metrics import body


@pytest.fixture
def summarize(monkeypatch):
    monkeypatch.setattr(body, "_read", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(body, "adaptive_tdee", lambda: {"tdee": 2400})

    def run(values, dates=None):
        series = pd.Series(values, index=pd.to_datetime(dates), dtype=float) if dates else pd.Series(dtype=float)
        if not series.empty:
            series = series.asfreq("D")
        monkeypatch.setattr(body, "_weight_daily", lambda: series)
        result = body.summary()
        json.dumps(result, allow_nan=False)
        return result

    return run


def test_sparse_measurements_use_calendar_windows(summarize):
    result = summarize([90, 88, 80, 78], ["2026-01-01", "2026-01-03", "2026-01-09", "2026-01-10"])
    assert result["weight_avg7"] == 79
    assert result["weight_delta7"] == -10
    assert result["weight_days7"] == 2
    assert result["previous_weight_days7"] == 2
    assert result["weight_date"] == "2026-01-10"
    assert result["weight_kg"] == 78


def test_comparison_does_not_reuse_old_window_across_gap(summarize):
    result = summarize([90, 80], ["2026-01-01", "2026-01-20"])
    assert result["weight_avg7"] == 80
    assert result["weight_delta7"] is None
    assert result["weight_days7"] == 1
    assert result["previous_weight_days7"] == 0


def test_latest_real_measurement_anchors_windows(summarize):
    result = summarize([82, 80, None], ["2026-01-01", "2026-01-08", "2026-01-12"])
    assert result["weight_date"] == "2026-01-08"
    assert result["weight_delta7"] == -2
    assert result["weight_days7"] == result["previous_weight_days7"] == 1


@pytest.mark.parametrize("values,dates", [([], None), ([None], ["2026-01-01"])])
def test_missing_measurements_are_null(summarize, values, dates):
    result = summarize(values, dates)
    assert result["weight_date"] is None
    assert result["weight_kg"] is None
    assert result["weight_avg7"] is None
    assert result["weight_delta7"] is None
    assert result["weight_days7"] == result["previous_weight_days7"] == 0
    assert result["tdee"] == 2400


def test_first_week_has_no_previous_comparison(summarize):
    result = summarize([80, 81], ["2026-01-01", "2026-01-02"])
    assert result["weight_avg7"] == 80.5
    assert result["weight_delta7"] is None
    assert result["weight_days7"] == 2
    assert result["previous_weight_days7"] == 0
