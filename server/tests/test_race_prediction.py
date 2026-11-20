from datetime import date, timedelta

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import metrics
from app.metrics import race_prediction, running

TODAY = date(2026, 11, 20)


def _runs(n=30, km=10.0, noise=0.0, seed=1, today=TODAY):
    """Synthetic runs with speed (m/min) = 40 + 1.0 * HR, so pace at HR is known exactly."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        hr = 130 + (i % 6) * 5
        v = 40 + hr + rng.normal(0, noise)
        dur = km * 1000 / v
        start = pd.Timestamp(today - timedelta(days=100 - 3 * i)) + pd.Timedelta(hours=8)
        rows.append({"started_at": start, "ended_at": start + pd.Timedelta(minutes=dur),
                     "distance_km": km, "avg_hr": float(hr), "max_hr": 175.0,
                     "dur_min": dur, "pace": dur / km})
    return pd.DataFrame(rows)


def _setup(monkeypatch, runs, best=None):
    monkeypatch.setattr(running, "_runs", lambda: runs)
    monkeypatch.setattr(running.settings, "run_hr_max", 180)
    frame = pd.DataFrame(best or [], columns=["distance_m", "seconds", "started_at", "avg_hr"])
    frame["started_at"] = pd.to_datetime(frame["started_at"])
    monkeypatch.setattr(race_prediction, "_best_efforts", lambda since: frame[frame["started_at"] >= since])


def test_hr_model_hits_known_speed_with_calibration(monkeypatch):
    _setup(monkeypatch, _runs())
    out = race_prediction.predict(TODAY)
    ten = next(d for d in out["distances"] if d["label"] == "10 km")
    cell = ten["cells"][0]  # HFmax 180 -> 10 km at 92 % = 165.6 bpm
    assert cell["race_hr"] == 166 and cell["hr_max"] == 180
    expected = 10000 / (40 + 0.92 * 180) * 60  # no best effort -> pure HR model
    assert abs(cell["seconds"] - expected) <= 1
    assert cell["beyond_bpm"] == 11  # highest training HR is 155
    assert out["scenarios"] == [180, 170]
    # cautious column: lower race HR -> slower
    assert ten["cells"][1]["seconds"] > cell["seconds"]


def test_floor_from_best_effort_caps_slow_side(monkeypatch):
    runs = _runs(noise=8)
    best = [(5000, 1500.0, pd.Timestamp(TODAY - timedelta(days=20)), None)]
    _setup(monkeypatch, runs, best)
    out = race_prediction.predict(TODAY)
    five = next(d for d in out["distances"] if d["label"] == "5 km")
    assert five["floor"] == {"seconds": 1500, "from": "5 km", "measured": True}
    for c in five["cells"]:
        assert c["slow"] <= 1500 and c["seconds"] <= 1500 and c["fast"] < c["seconds"]
    ten = next(d for d in out["distances"] if d["label"] == "10 km")
    assert ten["floor"]["seconds"] == round(1500 * 2 ** race_prediction.RIEGEL_K)


def test_anchor_averages_best_effort_shifted_to_race_hr(monkeypatch):
    # best 10 km at 150 bpm, 20 m/min faster than the model says for 150 bpm
    v_best = 40 + 150 + 20
    best = [(10000, 10000 / v_best * 60, pd.Timestamp(TODAY - timedelta(days=10)), 150.0)]
    _setup(monkeypatch, _runs(), best)
    ten = next(d for d in race_prediction.predict(TODAY)["distances"] if d["label"] == "10 km")
    hr = 0.92 * 180
    model_v, anchor_v = 40 + hr, v_best + (hr - 150)  # slope 1 m/min per bpm
    assert abs(ten["cells"][0]["seconds"] - 10000 / ((model_v + anchor_v) / 2) * 60) <= 1


def test_short_distances_scale_the_5k_prediction_without_hr(monkeypatch):
    _setup(monkeypatch, _runs())
    rows = race_prediction.predict(TODAY)["distances"]
    assert [d["label"] for d in rows][:3] == ["400 m", "1 km", "5 km"]
    five, one = rows[2]["cells"][0], rows[1]["cells"][0]
    assert one["race_hr"] is None and rows[1]["sprint"] is True
    assert abs(one["seconds"] - five["seconds"] * 0.2 ** race_prediction.RIEGEL_K) <= 1


def test_marathon_without_long_runs_is_not_reliable(monkeypatch):
    _setup(monkeypatch, _runs(km=15.0))
    out = race_prediction.predict(TODAY)
    by = {d["label"]: d for d in out["distances"]}
    assert by["Halbmarathon"]["reliable"] is True  # 21.1 km <= 1.5 x 15 km
    assert by["Marathon"]["reliable"] is False and by["Marathon"]["note"]


def test_too_few_runs_and_no_best_gives_empty(monkeypatch):
    _setup(monkeypatch, _runs(n=5))
    assert race_prediction.predict(TODAY) == {}


def test_endpoint_is_json(monkeypatch):
    _setup(monkeypatch, _runs(today=date.today()))
    app = FastAPI()
    app.include_router(metrics.router)
    r = TestClient(app).get("/metrics/running/race-prediction")
    assert r.status_code == 200 and len(r.json()["distances"]) == 6
