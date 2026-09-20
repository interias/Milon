import pandas as pd

from app.metrics import body, strength


def test_energy_balance_uses_matching_smoothing_windows(monkeypatch):
    weeks = pd.date_range("2026-01-05", periods=8, freq="W-MON")
    monkeypatch.setattr(strength, "strength_index", lambda period: {
        "series": [{"week": str(day.date()), "smoothed": 110 - i} for i, day in enumerate(weeks)]
    })
    monkeypatch.setattr(body, "tdee_trend", lambda **kw: [
        {"date": str(day.date()), "tdee_avg": 2500, "intake": 1800, "intake_avg": 2300}
        for day in weeks
    ])
    result = strength.strength_energy()
    assert result["deficit_avg"] == 200
    assert all(point["deficit"] == 200 for point in result["series"])
    assert result["corr_change_deficit"] is None
    assert result["phase_label"] == "Index fällt bei geschätztem Defizit"
