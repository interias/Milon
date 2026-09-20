"""Synthetic checks for support gating, clustered uncertainty and fixed references."""
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from app.metrics import run_standardization as shr


def fixture(months=(1,), offsets=None, runs=14):
    windows, sessions = [], []
    for month in months:
        for run in range(runs):
            external_id = f"{month}-{run}"
            start = datetime(2026, month, run + 1, 12)
            sessions.append(dict(external_id=external_id, started_at=start,
                                 ended_at=start + timedelta(minutes=60), distance_km=12,
                                 category="auto", exclude=False))
            offset = 0 if offsets is None else offsets[run]
            for minute in np.arange(0.5, 60, 1):
                # Each run supports 4:30 and 5:00 at minute 30, with tempo and time
                # independently varied and no transition larger than 0.3 m/s.
                speed = 211 + 20 * np.sin(minute / 4 + run * 0.07)
                hr = 145 + 0.15 * (speed - 200) + 0.12 * (minute - 30) + offset - month
                windows.append(dict(external_id=external_id, minute=minute, speed_m_min=speed,
                                    hr_bpm=hr, coverage=1, steady=True))
    return pd.DataFrame(windows), pd.DataFrame(sessions)


def test_dynamic_half_minute_paces_month_gaps_and_provisional():
    windows, sessions = fixture(months=(1, 3, 4))
    result = shr.analyze(windows, sessions, date(2026, 4, 30), bootstrap_iterations=80)
    assert [s["pace_seconds"] for s in result["pace_series"]] == [270, 300]
    for series in result["pace_series"]:
        points = series["points"]
        assert [p["month"] for p in points] == ["2026-01", "2026-02", "2026-03", "2026-04"]
        assert [p["status"] for p in points] == ["ok", "insufficient", "ok", "provisional"]
        assert points[1]["hr"] is None and points[1]["ci_low"] is None
        assert series["comparison"]["from_month"] == "2026-01"
        assert series["comparison"]["to_month"] == "2026-03"
        assert series["comparison"]["delta"] == -2
        assert series["comparison"]["verdict"] == "lower"


def test_bootstrap_multiplicity_matches_explicit_run_copies():
    windows, sessions = fixture(runs=6, offsets=[-3, -2, 0, 1, 2, 4])
    frame, _ = shr._prepare(windows, sessions, date(2026, 2, 1))
    frame = shr.select(frame)
    counts = {"1-0": 3, "1-2": 1, "1-5": 2}
    weighted = shr.fit(frame, counts=counts)
    explicit = []
    for run, count in counts.items():
        for copy in range(count):
            part = frame[frame.run == run].copy()
            part["run"] = f"{run}-copy-{copy}"
            explicit.append(part)
    copied = shr.fit(pd.concat(explicit, ignore_index=True))
    np.testing.assert_allclose(weighted, copied, atol=1e-7)
    # Replicating minutes of a single run must not increase that run's weight.
    duplicated = pd.concat([frame, frame[frame.run == "1-0"]] * 2, ignore_index=True)
    np.testing.assert_allclose(shr.fit(frame), shr.fit(duplicated), atol=1e-7)


def test_run_level_interval_preserves_between_run_variation():
    windows, sessions = fixture(offsets=np.linspace(-4, 4, 14))
    result = shr.analyze(windows, sessions, date(2026, 2, 1), bootstrap_iterations=300)
    point = result["pace_series"][0]["points"][0]
    assert point["status"] == "ok"
    assert point["ci_high"] - point["ci_low"] > 2
    # Repeating every minute cannot manufacture precision from identical samples.
    duplicate = shr.analyze(pd.concat([windows] * 3), sessions, date(2026, 2, 1), bootstrap_iterations=300)
    assert duplicate == result


def test_no_pace_admitted_from_exploratory_support_or_singular_model():
    windows, sessions = fixture(runs=6)
    result = shr.analyze(windows, sessions, date(2026, 2, 1), bootstrap_iterations=30)
    assert not result["pace_series"] and result["empty_reason"]
    windows, sessions = fixture()
    windows["speed_m_min"] = 200
    result = shr.analyze(windows, sessions, date(2026, 2, 1), bootstrap_iterations=30)
    assert not result["pace_series"]
    assert shr.analyze(pd.DataFrame(), pd.DataFrame())["empty_reason"]


def test_manual_exclusion_and_future_sessions_do_not_enter_model():
    windows, sessions = fixture(months=(1, 3))
    sessions.loc[sessions.external_id.str.startswith("1-"), "category"] = "beast"
    result = shr.analyze(windows, sessions, date(2026, 2, 1), bootstrap_iterations=30)
    assert not result["pace_series"]
    sessions["category"] = "auto"
    sessions["exclude"] = True
    assert not shr.analyze(windows, sessions, date(2026, 4, 1), bootstrap_iterations=30)["pace_series"]


def test_missing_minutes_and_invalid_hr_break_transition_support():
    windows, sessions = fixture()
    frame, _ = shr._prepare(windows, sessions, date(2026, 2, 1))
    frame = frame[~frame.minute.eq(24.5)]
    selected = shr.select(frame)
    assert not selected.minute.isin([25.5, 26.5]).any()
    windows["hr_bpm"] = None
    assert not shr.analyze(windows, sessions, date(2026, 2, 1), bootstrap_iterations=30)["pace_series"]

def test_failed_quality_gates_hide_main_values_but_keep_safe_exploration():
    from unittest.mock import patch

    windows, sessions = fixture(months=(1, 2))
    real_bootstrap = shr._bootstrap

    def unstable_bootstrap(frame, iterations):
        betas, draws = real_bootstrap(frame, iterations)
        if frame.month.iloc[0] == "2026-02":
            betas[:iterations // 5] = np.nan
        return betas, draws

    with patch.object(shr, "_bootstrap", unstable_bootstrap):
        result = shr.analyze(windows, sessions, date(2026, 3, 1), bootstrap_iterations=80)
    for series in result["pace_series"]:
        january, february, _ = series["points"]
        assert january["status"] == "ok"
        assert february["status"] == "unstable"
        assert february["hr"] is None and february["ci_low"] is None and february["ci_high"] is None
        assert february["exploratory_hr"] is not None
        assert any("Bootstrap" in reason for reason in february["reasons"])
        assert series["comparison"] is None
