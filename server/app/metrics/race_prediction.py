"""Wettkampf-Prognose: Zeiten für 5 km bis Marathon aus Training statt aus Rennen.

Bausteine (Rückblick-Test auf einer DB-Kopie, 2026-11-20: harte Läufe der nächsten 45 Tage
aus den 120 Tagen davor vorhergesagt, n = 31):
- **Untergrenze** = Riegel (t2 = t1 · (d2/d1)^1,06) aus den Bestzeiten der letzten 90 Tage.
  Das ist auf Trainingsniveau schon gelaufen.
- **Puls-Modell** = Tempo = a + b·Ø-HF + c·Tage über die Läufe der letzten 120 Tage (wie
  `running.pace_at_hr`), beim Renn-Puls ausgewertet. Allein im Schnitt 2,7 % zu langsam.
- **Anker** = beste 5-/10-km-Zeit, per Riegel auf die Strecke, plus b × (Renn-Puls − Ø-Puls
  jenes Laufs). Allein 3,7 % zu schnell (der beste Tag ist ein guter Tag).
- **Prognose** = Mittel der beiden Tempi: Bias −0,6 %, mittlerer Fehler 3,7 % (besser als jedes
  allein). Geprüft nur bis 16 bpm über dem bisher höchsten Ø-Puls; darüber ungeprüft.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import running

DISTANCES = (("5 km", 5000.0), ("10 km", 10000.0), ("Halbmarathon", 21097.5), ("Marathon", 42195.0))
# Typischer Ø-Puls im Rennen in % HFmax (Hobbyläufer, Mitte der Literaturspannen).
RACE_HR_PCT = {"5 km": 0.95, "10 km": 0.92, "Halbmarathon": 0.88, "Marathon": 0.83}
RIEGEL_K = 1.06
FIT_DAYS = 120
BEST_DAYS = 90
MIN_RUNS = 8
SCENARIOS = (180.0, 170.0)  # zwei HFmax-Annahmen als Spalten (User-Entscheid 2026-11-20)
RELIABLE_FACTOR = 1.5   # Strecke höchstens 1,5 × längster Lauf (90 T)


def _best_efforts(since: pd.Timestamp) -> pd.DataFrame:
    try:
        df = running._read(
            "SELECT b.distance_m, b.seconds, b.started_at, s.avg_hr FROM run_best_efforts b "
            "LEFT JOIN exercise_sessions s ON s.external_id = b.external_id",
            parse_dates=["started_at"])
    except Exception:
        return pd.DataFrame(columns=["distance_m", "seconds", "started_at", "avg_hr"])
    df = df[df["started_at"] >= since]
    pace = df["seconds"] / 60 / (df["distance_m"] / 1000)
    return df[pace.between(3, 9)]  # Gehstrecken als „Lauf" fallen raus


def _fit(df: pd.DataFrame, today: pd.Timestamp):
    """OLS Tempo (m/min) ~ Ø-HF + Tage. Liefert (predict(hr) -> (v, se), slope) oder None."""
    x0 = df["started_at"].min()
    X = np.column_stack([np.ones(len(df)), df["avg_hr"].to_numpy(float),
                         (df["started_at"] - x0).dt.days.to_numpy(float)])
    y = (df["distance_km"] * 1000 / df["dur_min"]).to_numpy(float)
    try:
        inv = np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:
        return None
    beta = inv @ X.T @ y
    resid = y - X @ beta
    s2 = float(resid @ resid) / (len(y) - 3)
    if beta[1] <= 0:
        return None
    day = float((today - x0).days)

    def predict(hr: float) -> tuple[float, float]:
        x = np.array([1.0, hr, day])
        return float(x @ beta), math.sqrt(float(x @ (inv * s2) @ x) + s2)  # inkl. Tagesform
    return predict, float(beta[1])


def predict(today: date | None = None, scenarios: tuple[float, ...] = SCENARIOS) -> dict:
    today_ts = pd.Timestamp(today or date.today()) + timedelta(days=1)
    runs = running._runs()
    if runs.empty:
        return {}
    hrmax, hr_src = running._resolved_hr_max(runs)
    recent = runs[(runs["started_at"] >= today_ts - timedelta(days=FIT_DAYS))
                  & (runs["started_at"] < today_ts)]
    longest = float(recent[recent["started_at"] >= today_ts - timedelta(days=BEST_DAYS)]["distance_km"].max()
                    if not recent.empty else 0) or 0.0
    fit_df = recent[recent["avg_hr"].between(100, 200) & (recent["distance_km"] >= 3)
                    & recent["pace"].between(4, 9)]
    model = _fit(fit_df, today_ts) if len(fit_df) >= MIN_RUNS else None

    best = _best_efforts(today_ts - timedelta(days=BEST_DAYS))
    best = best[best["distance_m"].isin([5000, 10000])]
    anchors = {int(d): float(g["seconds"].min()) for d, g in best.groupby("distance_m")}
    with_hr = best[best["avg_hr"].between(100, 200)]

    hr_seen = float(fit_df["avg_hr"].max()) if model else None
    rows = []
    for label, dist in DISTANCES:
        floor = None
        if anchors:
            src_d, src_t = min(((d, t * (dist / d) ** RIEGEL_K) for d, t in anchors.items()), key=lambda p: p[1])
            floor = {"seconds": round(src_t), "from": f"{int(src_d // 1000)} km",
                     "measured": src_d == dist}
        cells = []
        if model:
            fn, slope = model
            for hm in scenarios:
                race_hr = RACE_HR_PCT[label] * hm
                v, se = fn(race_hr)
                if not with_hr.empty:  # Anker: beste Zeit, auf Renn-Puls verschoben
                    anchor = max(dist / (t * (dist / d) ** RIEGEL_K) * 60 + slope * (race_hr - h)
                                 for d, t, h in zip(with_hr["distance_m"], with_hr["seconds"], with_hr["avg_hr"]))
                    v = (v + anchor) / 2
                if v <= 0:
                    cells.append(None)
                    continue
                mid = dist / v * 60
                fast = dist / (v + se) * 60
                slow = dist / max(v - se, v * 0.5) * 60
                pm = (slow - fast) / 2  # vor dem Kappen: ehrliche Streuung
                at_floor = bool(floor and mid >= floor["seconds"])
                if floor:  # langsamer als schon gelaufen wird es nicht
                    slow = min(slow, floor["seconds"])
                    mid = min(mid, floor["seconds"])
                cells.append({"hr_max": round(hm), "race_hr": round(race_hr),
                              "pct": round(RACE_HR_PCT[label] * 100),
                              "seconds": round(mid), "fast": round(fast), "slow": round(slow),
                              "pm": round(pm), "at_floor": at_floor,
                              "beyond_bpm": max(0, round(race_hr - hr_seen))})
        reliable = longest > 0 and dist / 1000 <= RELIABLE_FACTOR * longest
        rows.append({"label": label, "distance_m": dist, "floor": floor, "cells": cells,
                     "reliable": reliable,
                     "note": None if reliable else f"Dein längster Lauf (90 T) war {longest:.0f} km — "
                                                   "für diese Strecke fehlt die Grundlage."})
    if not model and not anchors:
        return {}
    return {
        "hr_max_setting": round(hrmax), "hr_max_source": hr_src,
        "scenarios": [round(s) for s in scenarios] if model else [],
        "model": ({"runs": int(len(fit_df)), "hr_lo": round(float(fit_df["avg_hr"].min())),
                   "hr_hi": round(hr_seen), "kmh_per_bpm": round(model[1] * 60 / 1000, 3)}
                  if model else None),
        "longest_km": round(longest, 1),
        "distances": rows,
        "caveat": "Mitte = Mittel aus Puls-Modell und deiner besten Zeit, beide auf den typischen "
                  "Renn-Puls hochgerechnet (5 km 95 %, 10 km 92 %, HM 88 %, Marathon 83 % HFmax); ± = eine "
                  "Standardabweichung inkl. Tagesform. Untergrenze = Riegel aus deinen Bestzeiten "
                  "(90 T). Über deinen bisher höchsten Ø-Puls hinaus ist die Hochrechnung ungeprüft.",
    }
