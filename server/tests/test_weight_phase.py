import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.metrics import body, weight_phase

TODAY = date(2026, 6, 30)


def _series(kg_per_week: float, days: int = 56, noise: float = 0.0, seed: int = 1, start=75.0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(end=pd.Timestamp(TODAY), periods=days, freq="D")
    values = start + kg_per_week / 7 * np.arange(days) + rng.normal(0, noise, days)
    return pd.Series(values, index=idx).asfreq("D")


@pytest.fixture
def weights(monkeypatch):
    def use(series):
        monkeypatch.setattr(body, "_weight_daily", lambda: series)
    return use


def test_cut_in_corridor(weights):
    weights(_series(-0.28))  # ≈ −0,37 %/Woche bei ~74,5 kg
    weight_phase.set_phase(date(2026, 5, 1), "cut_gentle")
    st = weight_phase.status(TODAY)
    json.dumps(st, allow_nan=False)
    assert st["phase"]["name"] == "Cut schonend"
    assert st["verdict"] == "im" and st["certain"] and st["label"] == "im Korridor"
    assert st["rate"]["kg_per_week"] == pytest.approx(-0.28, abs=0.01)
    assert "kcal_per_day" not in st


def test_in_corridor_but_wide_spread_says_unsure(weights):
    weights(_series(0.0, noise=0.4, seed=2))
    weight_phase.set_phase(date(2026, 5, 1), "maintain")  # ±0,06 %/Woche: enger als jede 4-Wochen-Spanne
    st = weight_phase.status(TODAY)
    if st["verdict"] == "im":
        assert not st["certain"] and st["label"] == "im Korridor (noch unsicher)"


def test_cut_too_fast_gives_kcal_hint(weights):
    weights(_series(-0.9))  # ≈ −1,2 %/Woche
    weight_phase.set_phase(date(2026, 5, 1), "cut_gentle")
    st = weight_phase.status(TODAY)
    assert st["verdict"] == "below" and st["certain"] and st["label"] == "zu schnell"
    assert st["kcal_per_day"] > 0  # mehr essen


def test_bulk_too_fast(weights):
    weights(_series(0.5))
    weight_phase.set_phase(date(2026, 5, 1), "bulk_intermediate")
    st = weight_phase.status(TODAY)
    assert st["verdict"] == "above" and st["label"] == "zu schnell" and st["kcal_per_day"] < 0


def test_noise_is_not_a_verdict(weights):
    # Kleine Abweichung bei viel Rauschen: Punkt außerhalb, Spanne reicht hinein → unsicher
    weights(_series(-0.32, noise=0.5, seed=3))  # knapp über −0,5 %/Woche
    weight_phase.set_phase(date(2026, 5, 1), "cut_standard")
    st = weight_phase.status(TODAY)
    assert st["verdict"] == "above" and not st["certain"]
    assert st["label"].startswith("eher zu langsam")


def test_young_phase_and_no_phase(weights):
    weights(_series(-0.3))
    assert weight_phase.status(TODAY)["verdict"] == "keine_phase"
    weight_phase.set_phase(date(2026, 6, 25), "cut_gentle")  # erst 6 Tage alt
    assert weight_phase.status(TODAY)["verdict"] == "wenig_daten"


def test_corridor_per_phase_in_weight_trend(weights):
    weights(_series(0.0, start=74.0))
    weight_phase.set_phase(date(2026, 5, 15), "cut_standard")
    weight_phase.set_phase(date(2026, 6, 15), "maintain")
    rows = {r["date"]: r for r in body.weight_trend()}
    assert rows["2026-05-14"]["band_low"] is None
    start, week2 = rows["2026-05-15"], rows["2026-05-29"]
    assert start["band_low"] == start["band_high"] == pytest.approx(74.0, abs=0.01)
    assert week2["band_low"] == pytest.approx(74 * (1 - 0.02), abs=0.01)   # −1 %/Woche × 2
    assert week2["band_high"] == pytest.approx(74 * (1 - 0.01), abs=0.01)
    assert rows["2026-06-14"]["phase"] == "Cut Standard" and rows["2026-06-15"]["phase"] == "Erhalt"
    assert [p["end"] for p in weight_phase.phases()] == ["2026-06-14", None]


def test_api_roundtrip(weights):
    from app.main import app
    weights(_series(-0.3))
    with TestClient(app) as c:
        assert c.post("/metrics/body/weight-phases", json={"start": "2026-05-01", "preset": "nope"}).status_code == 422
        r = c.post("/metrics/body/weight-phases", json={"start": "2026-05-01", "preset": "cut_gentle"})
        assert r.status_code == 200
        pid = r.json()["id"]
        r = c.post("/metrics/body/weight-phases", json={"start": "2026-05-01", "preset": "maintain"})
        assert r.json()["id"] == pid and r.json()["name"] == "Erhalt"
        assert c.get("/metrics/body/weight-rate").status_code == 200
        assert c.delete(f"/metrics/body/weight-phases/{pid}").status_code == 200
        assert c.delete(f"/metrics/body/weight-phases/{pid}").status_code == 404
