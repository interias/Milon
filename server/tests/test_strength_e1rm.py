import math

import pandas as pd
import pytest

from app.metrics import strength as st


def test_e1rm_counts_reps_in_reserve_up_to_three_and_caps_at_12():
    assert st.e1rm(100, 10, 10) == pytest.approx(100 * (1 + 10 / 30))
    assert st.e1rm(100, 9, 8) == pytest.approx(100 * (1 + 11 / 30))    # 2 RIR → 11 bis zum Versagen
    assert st.e1rm(100, 8, 5) == st.e1rm(100, 8, None)                  # RIR 5 zu unsicher → ignoriert
    assert st.e1rm(100, 20, 10) == pytest.approx(100 * (1 + 12 / 30))   # Kappung 12
    assert st.e1rm(100, 10, 7) == pytest.approx(100 * 1.4)              # 10 + 3 → gekappt


def test_example_from_user_three_sets_rir_2_1_0():
    sets = [(60, 10, 8), (60, 10, 9), (60, 9, 10)]
    best = max(st.e1rm(*s) for s in sets)
    assert best == pytest.approx(60 * (1 + 12 / 30))


def _df(rows):
    df = pd.DataFrame(rows, columns=["exercise", "weight_kg", "reps", "rpe", "started_at"])
    df["started_at"] = pd.to_datetime(df["started_at"])
    st.add_e1rm(df)
    df["day"] = df["started_at"].dt.floor("D")
    df["month"] = df["started_at"].dt.to_period("M")
    df["mg"] = df["exercise"].map(lambda e: e[0])  # drei Gruppen A/B/C
    return df


def test_no_fake_jump_when_rpe_logging_starts():
    """Gleiche Leistung, nur ab Oktober mit RPE 8 erfasst: mit RIR auf einer Seite gäbe es +5 %."""
    rows = []
    for ex in ("A1", "B1", "C1"):
        rows += [(ex, 100, 10, None, "2025-09-10"), (ex, 100, 10, 8.0, "2025-10-10"), (ex, 102, 10, 8.0, "2025-11-10")]
    raw, basket, months, _ = st._monthly_backbone(_df(rows))
    sep, oct_, nov = months
    assert raw[oct_] == pytest.approx(raw[sep])                       # ohne RIR auf beiden Seiten
    assert raw[nov] / raw[oct_] == pytest.approx(math.exp(math.log(102 / 100)))  # beide mit RIR
    assert basket[oct_]["A1"][3] is True and basket[sep]["A1"][3] is False


def test_submax_session_no_longer_looks_weaker():
    rows = []
    for ex in ("A1", "B1", "C1"):
        rows += [(ex, 100, 12, 10.0, "2026-01-10"), (ex, 100, 10, 8.0, "2026-02-10")]
    raw, _, months, _ = st._monthly_backbone(_df(rows))
    assert raw[months[1]] == pytest.approx(raw[months[0]])


def test_detail_has_trend_line(monkeypatch):
    rows = [("Bank", 60, r, 10.0, f"2026-0{m}-10") for m, r in ((1, 8), (2, 12), (3, 8), (4, 9))]
    df = pd.DataFrame(rows, columns=["exercise", "weight_kg", "reps", "rpe", "started_at"])
    df["started_at"] = pd.to_datetime(df["started_at"])
    st.add_e1rm(df)
    df["tonnage"] = df["weight_kg"] * df["reps"]
    df["week"] = df["started_at"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())
    df["day"] = df["started_at"].dt.floor("D")
    monkeypatch.setattr(st, "_sets", lambda: df)
    monkeypatch.setattr(st, "exercise_status", lambda e: None)
    series = st.exercise_detail("Bank", "all")["series"]
    trend = [p["e1rm_trend"] for p in series]
    assert trend[0] == series[0]["e1rm"]
    assert series[1]["e1rm"] > trend[1] > trend[0]                    # Spitze wird gedämpft
    assert trend[2] > series[2]["e1rm"]                                # Einbruch auch


def test_index_period_all_measures_from_first_month(monkeypatch):
    rows = []
    for ex in ("A1", "B1", "C1"):
        for m, w in ((1, 100), (2, 105), (3, 110), (4, 115), (5, 120)):
            rows.append((ex, w, 10, None, f"2026-0{m}-10"))
            rows.append((ex, w, 10, None, f"2026-0{m}-17"))
    df = pd.DataFrame(rows, columns=["exercise", "weight_kg", "reps", "rpe", "started_at"])
    df["started_at"] = pd.to_datetime(df["started_at"])
    st.add_e1rm(df)
    df["day"] = df["started_at"].dt.floor("D")
    df["week"] = df["started_at"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())
    monkeypatch.setattr(st, "_sets", lambda: df)
    monkeypatch.setattr(st, "_muscle_group", lambda e: e[0])
    fn = getattr(st.strength_index, "__wrapped__", st.strength_index)
    full, short = fn("all"), fn("1m")
    assert full["period"] == "all"
    assert full["window_delta_pct"] > short["window_delta_pct"] > 0
    assert full["series"][0]["week"] == full["base_week"]
