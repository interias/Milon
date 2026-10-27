"""Rückblick-Test: Wie gut sagen altes TDEE, „Gewicht bleibt“ und Verbrauchsmodell das Gewicht voraus?

Ab jedem 3. Tag nach 90 Tagen Einlauf wird mit dem Stand an diesem Tag (nur Daten bis dahin) und dem
tatsächlich gegessenen/bewegten das Gewicht vorhergesagt. Ziel = Mittel der Waage ±3 Tage um den Zieltag
(mindestens 3 Wiegungen). Alle Verfahren auf denselben Startpunkten.
Aufruf (cwd server/): python -m scripts.backtest_expenditure [KONSTANTE=WERT …], z. B. RHO=6000 B_DRIFT_SD=8"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from app.metrics import body, expenditure as ex

HORIZONS = (7, 14, 28)


def _target(weight: pd.Series, day: pd.Timestamp) -> float | None:
    win = weight[(weight.index >= day - pd.Timedelta(days=3)) & (weight.index <= day + pd.Timedelta(days=3))].dropna()
    return float(win.mean()) if len(win) >= 3 else None


def main(overrides: dict[str, float]):
    for k, v in overrides.items():
        setattr(ex, k, v)
    weight, intake = body._weight_daily(), body._intake_daily()
    start = max(weight.dropna().index.min(), intake.dropna().index.min())
    end = weight.dropna().index.max()
    active = ex._active_series(start.date(), end.date())
    old = {pd.Timestamp(r["date"]): r for r in body._window_tdee_trend(days=2000)}
    rows = {pd.Timestamp(r["date"]): r for r in ex.run(weight, intake, active)}
    avg7 = weight.rolling(7, min_periods=3).mean()
    origins = [t for t in pd.date_range(start + pd.Timedelta(days=90), end - pd.Timedelta(days=max(HORIZONS)), freq="3D")
               if t in old and t in rows and pd.notna(avg7.get(t))]
    errs = {name: {h: [] for h in HORIZONS} for name in ("alt (14 T, 7.700)", "Gewicht bleibt", "Modell")}
    for t in origins:
        for h in HORIZONS:
            target = _target(weight, t + pd.Timedelta(days=h))
            if target is None:
                continue
            r, o = rows[t], old[t]
            eaten = [intake.get(d) for d in pd.date_range(t + pd.Timedelta(days=1), periods=h)]
            eaten = [o["intake_avg"] if e is None or pd.isna(e) else e for e in eaten]
            # avg7 hinkt ~3 Tage nach: das alte Verfahren rechnet ab der Fenstermitte
            old_pred = avg7[t] + (sum(eaten) + 3 * np.mean(eaten) - (h + 3) * o["tdee_avg"]) / body.KCAL_PER_KG
            errs["alt (14 T, 7.700)"][h].append(old_pred - target)
            errs["Gewicht bleibt"][h].append(r["weight_trend"] - target)
            nxt = dict(r, date=(t + pd.Timedelta(days=1)).date().isoformat())
            errs["Modell"][h].append(ex.predict_weight(nxt, intake, active, h) - target
                                     + (_today_step(r, intake, active, t)))
    print(f"{len(origins)} Startpunkte {origins[0].date()} … {origins[-1].date()}  {overrides or ''}")
    for name, by_h in errs.items():
        print(f"{name:<20} " + " · ".join(
            f"{h:>2} T: MAE {np.mean(np.abs(by_h[h])):.2f} kg, Bias {np.mean(by_h[h]):+.2f}" for h in HORIZONS))
    last = rows[max(rows)]
    print(f"heute: {last['expenditure']} ± {last['expenditure_sd']} kcal (B {last['base']})")


def _today_step(r: dict, intake: pd.Series, active: pd.Series, t: pd.Timestamp) -> float:
    """Bilanz des Starttages selbst (der Stand an t ist vor dem Essen dieses Tages)."""
    eaten = intake.get(t)
    eaten = r["intake_avg"] if eaten is None or pd.isna(eaten) else float(eaten)
    return (eaten * (1 - ex.TEF) - r["base"] - float(active.get(t, 0.0) or 0.0)) / ex.RHO


if __name__ == "__main__":
    main({k: float(v) for k, v in (a.split("=") for a in sys.argv[1:])})
