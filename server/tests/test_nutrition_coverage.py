import json

import pandas as pd

from app.metrics import nutrition


def source(monkeypatch, rows):
    frame = pd.DataFrame(rows, columns=["eaten_at", "kcal", "protein_g", "carb_g", "fat_g"])
    frame["eaten_at"] = pd.to_datetime(frame["eaten_at"], format="mixed")
    for column in ("kcal", "protein_g", "carb_g", "fat_g"):
        frame[column] = pd.to_numeric(frame[column])
    monkeypatch.setattr(nutrition, "_read", lambda *args, **kwargs: frame)
    monkeypatch.setattr(nutrition, "protein_target", lambda: 100)
    monkeypatch.setattr(nutrition.body, "adaptive_tdee", lambda: {"tdee": 2400})


def test_summary_counts_metric_days_in_same_calendar_window(monkeypatch):
    source(monkeypatch, [
        ("2026-01-01", 9000, 900, 200, 50),  # Outside the latest seven days.
        ("2026-01-02", 2000, 110, 200, 50),
        ("2026-01-02 12:00", 100, 10, 0, 0),
        ("2026-01-04", None, 80, None, None),
        ("2026-01-08", 1900, None, None, None),
    ])

    result = nutrition.summary()
    json.dumps(result, allow_nan=False)
    assert result["window_start"] == "2026-01-02"
    assert result["last_day"] == "2026-01-08"
    assert result["recorded_days_7"] == 3
    assert result["protein_days_7"] == 2
    assert result["kcal_days_7"] == 2
    assert result["protein_avg7"] == 100
    assert result["kcal_avg7"] == 2000
    assert result["on_target_days_7"] == 1
    assert result["protein_today"] is None


def test_calendar_trends_keep_missing_values_and_expire_rolling_average(monkeypatch):
    source(monkeypatch, [
        ("2026-01-01", 2000, 100, None, None),
        ("2026-01-03", 0, None, None, None),
        ("2026-01-12", 2200, 120, None, None),
    ])

    protein = nutrition.protein_trend()
    kcal = nutrition.kcal_trend()
    json.dumps([protein, kcal], allow_nan=False)
    assert len(protein) == len(kcal) == 12
    assert protein[1] == {"date": "2026-01-02", "protein": None, "avg7": 100, "days7": 1}
    assert protein[6]["avg7"] == 100
    assert protein[7]["avg7"] is None
    assert protein[7]["days7"] == 0
    assert kcal[2]["kcal"] == 0  # Recorded zero is distinct from missing.
    assert kcal[2]["avg7"] == 1000
    assert kcal[2]["days7"] == 2
    assert kcal[9]["avg7"] is None
    assert protein[-1]["avg7"] == 120
    assert protein[-1]["days7"] == 1


def test_partial_macros_remain_unknown_instead_of_zero(monkeypatch):
    source(monkeypatch, [
        ("2026-01-01", 2000, None, 200, None),
        ("2026-01-01 12:00", None, None, None, None),
    ])

    result = nutrition.summary()
    daily = nutrition.daily()
    json.dumps([result, daily], allow_nan=False)
    assert result["protein_days_7"] == 0
    assert result["on_target_days_7"] is None
    assert result["protein_avg7"] is None
    assert result["macro_g"] == {"protein": None, "carb": 200, "fat": None}
    assert result["macro_split"] is None
    assert daily == [{"date": "2026-01-01", "kcal": 2000, "protein": None, "carb": 200, "fat": None}]


def test_empty_summary_exposes_zero_coverage(monkeypatch):
    source(monkeypatch, [])

    result = nutrition.summary()
    json.dumps(result, allow_nan=False)
    assert result["window_start"] is None
    assert result["recorded_days_7"] == result["protein_days_7"] == result["kcal_days_7"] == 0
    assert result["on_target_days_7"] is None
    assert nutrition.protein_trend() == nutrition.kcal_trend() == nutrition.daily() == []
