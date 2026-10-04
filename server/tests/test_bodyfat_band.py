import json

import pandas as pd

from app.metrics import body


def test_bia_band_uses_calendar_window_and_daily_means_not_measurement_count(monkeypatch):
    frame = pd.DataFrame({
        "measured_at": pd.to_datetime(["2026-09-01", "2026-09-01 12:00"] + [f"2026-09-{day:02}" for day in range(2, 9)] + ["2026-10-01"], format="mixed"),
        "body_fat_pct": [18, 22, 20, 21, 22, 23, 24, 25, 26, 30],
    })
    monkeypatch.setattr(body, "_read", lambda *args, **kwargs: frame)
    result = body.body_fat_band(60)
    json.dumps(result, allow_nan=False)
    series = {p["date"]: p for p in result["series"]}
    assert series["2026-09-06"]["median"] is None  # Only six distinct measured days.
    assert series["2026-09-07"]["median"] == 22
    assert series["2026-09-07"]["days"] == 7
    assert series["2026-09-09"]["median"] is None  # Missing measurements stay visible.
    assert series["2026-10-01"]["days"] == 6  # Values outside 28 calendar days expire.
    assert series["2026-10-01"]["median"] is None
    assert "kein Korridor" in result["note"]


def test_empty_bia_band_has_no_fabricated_range(monkeypatch):
    monkeypatch.setattr(body, "_read", lambda *args, **kwargs: pd.DataFrame())
    assert body.body_fat_band()["series"] == []
