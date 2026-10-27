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


def test_weekly_weight_omits_empty_weeks_and_serializes(monkeypatch):
    series = pd.Series([80.0, 78.0], index=pd.to_datetime(["2026-01-01", "2026-01-25"])).asfreq("D")
    monkeypatch.setattr(body, "_weight_daily", lambda: series)

    result = body.weekly_weight()
    json.dumps(result, allow_nan=False)
    assert result == [{"week": "2026-01-04", "weight": 80.0}, {"week": "2026-01-25", "weight": 78.0}]
