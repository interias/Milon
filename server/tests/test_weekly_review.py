from datetime import date, datetime, timezone

import pandas as pd

from app import checkins
from app.metrics import activity, body, sleep


def test_review_uses_completed_local_days_and_matching_calendar_windows(monkeypatch):
    monkeypatch.setattr(activity.settings, "timezone", "Europe/Berlin")
    seen = {}

    def overview(now):
        seen["activity_now"] = now
        return {"from_date": "2026-03-24", "to_date": "2026-03-30"}

    def sleep_overview(days, today):
        seen["sleep"] = (days, today)
        return {"series": [
            {"date": "2026-03-24", "main_sleep": True, "asleep_hours": 6},
            {"date": "2026-03-25", "main_sleep": True, "asleep_hours": None},
            {"date": "2026-03-25", "main_sleep": False, "asleep_hours": 0.5},
            {"date": "2026-03-30", "main_sleep": True, "asleep_hours": 8},
        ]}

    def checkin_summary(days, today):
        seen["checkins"] = (days, today)
        return {"count": 0}

    monkeypatch.setattr(activity, "overview", overview)
    monkeypatch.setattr(sleep, "overview", sleep_overview)
    monkeypatch.setattr(checkins, "summary", checkin_summary)
    weights = pd.Series([80, 80, 80, 79, 79, 79, 99], index=pd.to_datetime([
        "2026-03-17", "2026-03-19", "2026-03-23", "2026-03-24", "2026-03-27", "2026-03-30", "2026-03-31"]))
    monkeypatch.setattr(body, "_weight_daily", lambda: weights)
    # In Berlin, March 31 has begun although UTC still says March 30.
    review = activity.weekly_review(datetime(2026, 3, 30, 22, 15, tzinfo=timezone.utc))
    assert seen["activity_now"].date() == date(2026, 3, 30)
    assert seen["sleep"] == seen["checkins"] == (7, date(2026, 3, 30))
    assert review["weight"] == {"delta_kg": -1.0, "current_days": 3, "previous_days": 3}
    assert review["sleep"] == {"avg_hours": 7.0, "measured_nights": 2, "recorded_nights": 3}


def test_review_does_not_estimate_a_sparse_weight_comparison(monkeypatch):
    monkeypatch.setattr(activity, "overview", lambda now: {"from_date": "2026-09-27", "to_date": "2026-10-03"})
    monkeypatch.setattr(body, "_weight_daily", lambda: pd.Series([70, 69], index=pd.to_datetime(["2026-09-25", "2026-10-03"])))
    monkeypatch.setattr(sleep, "overview", lambda **kwargs: {"series": []})
    monkeypatch.setattr(checkins, "summary", lambda **kwargs: {"count": 0})
    review = activity.weekly_review(datetime(2026, 10, 4, 12, tzinfo=timezone.utc))
    assert review["weight"]["delta_kg"] is None
    assert review["sleep"]["avg_hours"] is None
