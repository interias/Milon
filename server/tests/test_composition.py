import json

import pandas as pd

from app.metrics import body, composition


def _setup(monkeypatch, waists, weight=73.5, height=178.0):
    monkeypatch.setattr(composition, "_waists", lambda: pd.Series(waists, dtype=float))
    dates = pd.date_range("2026-01-01", "2026-10-31")
    monkeypatch.setattr(body, "_weight_daily", lambda: pd.Series(weight, index=dates))
    monkeypatch.setattr(composition.settings, "body_height_cm", height)


def test_band_is_rfm_minus_photo_offset_with_lean_mass(monkeypatch):
    _setup(monkeypatch, {pd.Timestamp("2026-03-15"): 84.0, pd.Timestamp("2026-10-14"): 81.0})
    out = composition.estimate()
    json.dumps(out, allow_nan=False)
    c = out["current"]
    assert c["bf_high"] == round(64 - 20 * 178 / 81, 1) == 20.0
    assert c["bf_low"] == 15.0 and c["bf_mid"] == 17.5
    assert c["whtr"] == 0.455 and out["whtr_delta"] == round(81 / 178 - 84 / 178, 3)
    high = 64 - 20 * 178 / 81
    assert c["ffm_low"] == round(73.5 * (1 - high / 100), 1) and c["ffm_high"] == round(73.5 * (1 - (high - 5) / 100), 1)
    assert composition.current_ffm() == c["ffm_mid"]


def test_without_height_or_waist_nothing_is_invented(monkeypatch):
    _setup(monkeypatch, {pd.Timestamp("2026-10-14"): 81.0}, height=None)
    assert composition.estimate()["available"] is False
    _setup(monkeypatch, {})
    assert composition.estimate()["available"] is False
    assert composition.current_ffm() is None


def test_measurement_without_nearby_weighings_has_no_masses(monkeypatch):
    _setup(monkeypatch, {pd.Timestamp("2025-01-15"): 90.0})
    c = composition.estimate()["current"]
    assert c["weight"] is None and "ffm_low" not in c and c["bf_low"] is not None
