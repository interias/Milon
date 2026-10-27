"""Verbrauchsmodell: lernt einen bekannten Verbrauch aus synthetischer Waage + Essen + Bewegung."""
import json

import numpy as np
import pandas as pd

from app.metrics import body, expenditure as ex


def _world(days=240, base=2300.0, jump_at=None, jump=0.0, seed=1, weigh_every=1, skip_intake=()):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=days)
    active = pd.Series(rng.choice([150.0, 150.0, 900.0], size=days), index=dates)
    intake = pd.Series(rng.normal(2900, 400, size=days), index=dates)
    w, water, weights = 75.0, 0.0, []
    for i, d in enumerate(dates):
        water = ex.WATER_PHI * water + rng.normal(0, 0.35)
        weights.append(w + water + rng.normal(0, 0.1))
        b = base + (jump if jump_at is not None and i >= jump_at else 0.0)
        w += (intake.iloc[i] * (1 - ex.TEF) - b - active.iloc[i]) / ex.RHO
    weight = pd.Series(weights, index=dates)
    weight[np.arange(days) % weigh_every != 0] = np.nan
    for i in skip_intake:
        intake.iloc[i] = np.nan
    return weight, intake.dropna(), active


def test_learns_known_base_expenditure():
    weight, intake, active = _world()
    rows = ex.run(weight, intake, active)
    json.dumps(rows, allow_nan=False)
    last = rows[-1]
    assert abs(last["base"] - 2300) < 120
    assert last["expenditure"] == last["base"] + last["tef"] + last["active_avg"]
    assert last["expenditure_sd"] < 150


def test_tracks_a_change_within_weeks_and_survives_gaps():
    weight, intake, active = _world(days=300, jump_at=150, jump=400, weigh_every=2, skip_intake=range(200, 206))
    rows = {r["date"]: r for r in ex.run(weight, intake, active)}
    assert abs(rows["2025-05-30"]["base"] - 2300) < 150   # vor dem Sprung (Tag 149)
    assert abs(rows["2025-10-27"]["base"] - 2700) < 150   # 150 Tage nach dem Sprung
    assert rows["2025-07-20"]["intake"] is None            # Tag ohne Eintrag bleibt leer


def test_day_value_contains_todays_movement():
    weight, intake, active = _world(days=60)
    rows = ex.run(weight, intake, active)
    hard = next(r for r in reversed(rows) if r["active_day"] == 900)
    assert abs(hard["expenditure_day"] - hard["base"] - (hard["intake"] or 0) * ex.TEF - 900) <= 2  # gerundete Teile


def test_adaptive_tdee_uses_last_full_day_and_reports_parts(monkeypatch):
    weight, intake, _ = _world(days=120)
    monkeypatch.setattr(body, "_weight_daily", lambda: weight)
    monkeypatch.setattr(body, "_intake_daily", lambda: intake)
    monkeypatch.setattr(body, "_bodyfat_daily", lambda: pd.Series(15.0, index=weight.index))
    out = body.adaptive_tdee()
    json.dumps(out, allow_nan=False)
    assert out["from_date"] == "2025-04-30" and out["today"] == "2025-05-01"   # ein Tag nach den Daten, nicht bis heute
    assert out["deficit_per_day"] == out["tdee"] - out["avg_intake"]
    assert out["parts"]["resting"] == round(500 + 22 * out["weight_trend"] * 0.85)
    assert abs(out["parts"]["unmeasured"] - (out["parts"]["base"] - out["parts"]["resting"])) <= 1
    assert not out["provisional"]
    trend = body.tdee_trend(days=30)
    assert trend[-1]["date"] == "2025-04-30" and {"tdee", "tdee_avg", "tdee_sd", "intake_avg"} <= set(trend[-1])


def test_empty_inputs():
    assert ex.run(pd.Series(dtype=float), pd.Series(dtype=float), None) == []
