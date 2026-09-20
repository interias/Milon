"""Rolling estimates preserve sampling units and explicit unsupported periods."""
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from app.metrics import run_fitness as fitness


def data(runs=6):
    windows, sessions = [], []
    for run in range(runs):
        start = datetime(2026, 1, 1) + timedelta(days=run * 4)
        sessions.append(dict(external_id=str(run), started_at=start,
            ended_at=start + timedelta(minutes=50), distance_km=8, category="auto", exclude=False))
        for minute in np.arange(.5, 50):
            speed = 166.67 + 6 * np.sin(minute / 3 + run)
            windows.append(dict(external_id=str(run), minute=minute, speed_m_min=speed,
                hr_bpm=145 + .3 * (speed - 60000 / 360) + .1 * (minute - 20),
                coverage=1, steady=True))
    return pd.DataFrame(windows), pd.DataFrame(sessions)


def test_five_runs_support_fixed_reference_and_stale_gap():
    windows, sessions = data(5)
    result = fitness.analyze(windows, sessions, date(2026, 4, 1), 40)
    point = result["points"][-2]
    assert point["runs"] == 5 and point["local_runs"] == 5
    assert point["hr"] == 145 and point["status"] == "ok"
    assert result["points"][-1]["hr"] is None
    assert result["points"][-1]["runs"] == 0
    assert result["observations"] and result["durability"]
    assert all(p["reference_minute"] == 30 for p in result["pace_series"])


def test_duplicate_minutes_do_not_manufacture_precision():
    windows, sessions = data()
    windows["hr_bpm"] += windows.external_id.astype(int) - 2
    first = fitness.analyze(windows, sessions, date(2026, 1, 22), 80)
    repeated = fitness.analyze(pd.concat([windows, windows, windows]), sessions, date(2026, 1, 22), 80)
    assert first == repeated
    assert first["points"][-1]["ci_high"] - first["points"][-1]["ci_low"] > 1


def test_insufficient_local_support_and_annotations_exclude():
    windows, sessions = data()
    windows.loc[windows.external_id.isin(["2", "3", "4", "5"]), "speed_m_min"] += 35
    result = fitness.analyze(windows, sessions, date(2026, 1, 22), 20)
    assert result["points"][-1]["hr"] is None
    assert result["points"][-1]["local_runs"] == 2
    windows, sessions = data()
    sessions.loc[:2, "exclude"] = True
    result = fitness.analyze(windows, sessions, date(2026, 1, 22), 20)
    assert result["points"][-1]["runs"] == 3
    assert result["points"][-1]["hr"] is None


def test_run_weights_do_not_depend_on_number_of_minutes():
    windows, sessions = data()
    frame, _ = fitness.shr._prepare(windows, sessions, date(2026, 1, 22))
    frame = fitness.shr.select(frame)
    beta = fitness._solve(*fitness._summaries(frame, 360, 20))
    copied = pd.concat([frame, frame[frame.run == "0"]] * 2)
    np.testing.assert_allclose(beta, fitness._solve(*fitness._summaries(copied, 360, 20)))


def test_future_sessions_do_not_leak_and_empty_inputs_are_supported():
    windows, sessions = data()
    result = fitness.analyze(windows, sessions, date(2026, 1, 10), 20)
    assert all(p["date"] <= "2026-01-10" for p in result["points"])
    assert max(p["runs"] for p in result["points"]) == 3
    assert fitness.analyze(pd.DataFrame(), pd.DataFrame())["empty_reason"]
