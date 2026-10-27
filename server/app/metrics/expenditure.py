"""Lernendes Verbrauchsmodell: Kalman-Filter über Essen, Waage und gemessene Bewegung.

Ein Schritt je Kalendertag, Zustand x = [W, Wasser, B]:
- W: Körpermasse ohne Wasserschwankung (kg). Bilanz: W' = W + (Essen·(1 − TEF) − B − Aktiv) / RHO.
- Wasser: Tagesschwankung der Waage (Salz, Glykogen, Darminhalt), AR(1) mit WATER_PHI.
- B: Grundverbrauch (kcal/Tag) = Ruheumsatz + alles, was Milon nicht misst (Stehen, Hausarbeit, Nachbrenneffekt);
  wandert langsam (Random Walk) und ist das, was das Modell lernt.
Waage = W + Wasser + Messrauschen. Tage ohne Waage: kein Update. Tage ohne Essen: Ø der letzten 14 Tage mit
großer Unsicherheit. Verbrauch eines Tages = B + TEF·Essen + Milons aktive kcal (`active_kcal.compute`).

Festgelegt per Rückblick-Test (`scripts/backtest_expenditure.py`, echte Daten 2025-07 … 2026-09, 110 Startpunkte):
Gewicht 28 T voraus mittlerer Fehler 0,46 kg (altes 14-Tage-Verfahren 0,82, „Gewicht bleibt“ 0,69).
- RHO 7.700: sagte besser voraus als Hall/Forbes (~5.950 bei 12 kg Fett: 0,53 kg).
- Bewegung mit Faktor 1: ein gelernter Faktor (≈ 0,6) war nicht genauer — die Daten trennen ihn nicht von
  Wasser nach harten Tagen, also gelten die Formeln von `active_kcal`.
Grenze: ein systematischer Fehler beim Erfassen des Essens ist vom Verbrauch nicht trennbar; das Modell
lernt den Verbrauch, der zu den Einträgen passt."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

TEF = 0.10                    # Verdauung: Anteil der Zufuhr
RHO = 7700.0                  # kcal je kg Gewichtsänderung
WATER_PHI = 0.4               # Autokorrelation der Waagenschwankung (echte Daten: 0,35 an Tag 1)
WATER_SD = 0.40               # stationäre Streuung der Wasserschwankung (kg)
SCALE_SD = 0.15               # reines Messrauschen der Waage (kg)
INTAKE_SD = 0.10              # Erfassungsfehler je Tag als Anteil der Zufuhr
MISSING_INTAKE_SD = 3000.0    # kcal: ein Tag ohne Eintrag ist praktisch unbekannt (Urlaubslücke soll B nicht verbiegen)
B_DRIFT_SD = 15.0             # kcal/Tag: so schnell darf der Grundverbrauch wandern
B_PRIOR_SD = 400.0
AVG_DAYS = 14                 # „typischer Tag“: Mittel über Essen und Bewegung der letzten 14 Tage


def run(weight: pd.Series, intake: pd.Series, active: pd.Series | None, until: date | None = None) -> list[dict]:
    """Filtert Tag für Tag (kausal: der Stand an Tag t kennt nur Daten bis t)."""
    weight, intake = weight.dropna(), intake.dropna()
    if weight.empty or intake.empty:
        return []
    start = max(weight.index.min(), intake.index.min()).normalize()
    end = pd.Timestamp(until) if until else max(weight.index.max(), intake.index.max()).normalize()
    if end <= start:
        return []
    days = pd.date_range(start, end, freq="D")
    intake = intake.reindex(days)
    active = (active.reindex(days).fillna(0.0) if active is not None and not active.empty
              else pd.Series(0.0, index=days))

    first = intake.dropna().head(AVG_DAYS)
    x = np.array([float(weight.iloc[0]), 0.0, float(first.mean()) * (1 - TEF) - float(active.iloc[:AVG_DAYS].mean())])
    P = np.diag([1.0, WATER_SD ** 2, B_PRIOR_SD ** 2])
    H = np.array([1.0, 1.0, 0.0])
    F = np.array([[1.0, 0.0, -1 / RHO], [0.0, WATER_PHI, 0.0], [0.0, 0.0, 1.0]])
    q_water = WATER_SD ** 2 * (1 - WATER_PHI ** 2)

    out: list[dict] = []
    for i, day in enumerate(days):
        z = weight.get(day)
        observed = z is not None and pd.notna(z)
        if observed:  # Update mit der Waage dieses Tages
            S = float(H @ P @ H) + SCALE_SD ** 2
            K = P @ H / S
            x = x + K * (float(z) - float(H @ x))
            P = P - np.outer(K, H @ P)
        eaten, a = intake.iloc[i], float(active.iloc[i])
        recent = intake.iloc[max(0, i - AVG_DAYS + 1):i + 1].dropna()
        mean_i = float(recent.mean()) if not recent.empty else float(first.mean())
        mean_a = float(active.iloc[max(0, i - AVG_DAYS + 1):i + 1].mean())
        b, b_sd = float(x[2]), float(np.sqrt(P[2, 2]))
        out.append({
            "date": day.date().isoformat(), "weight_trend": round(float(x[0]), 2),
            "expenditure": round(b + TEF * mean_i + mean_a), "expenditure_sd": round(b_sd),
            "expenditure_day": round(b + TEF * (float(eaten) if pd.notna(eaten) else mean_i) + a),
            "base": round(b), "tef": round(TEF * mean_i), "active_avg": round(mean_a), "active_day": round(a),
            "intake": None if pd.isna(eaten) else round(float(eaten)), "intake_avg": round(mean_i),
            "observed": bool(observed),
        })
        # Vorhersage auf morgen
        net, i_sd = ((float(eaten) * (1 - TEF), INTAKE_SD * float(eaten)) if pd.notna(eaten)
                     else (mean_i * (1 - TEF), MISSING_INTAKE_SD))
        x = F @ x + np.array([(net - a) / RHO, 0.0, 0.0])
        P = F @ P @ F.T + np.diag([(i_sd / RHO) ** 2, q_water, B_DRIFT_SD ** 2])
    return out


def predict_weight(row: dict, intake: pd.Series, active: pd.Series, days: int) -> float:
    """Trendgewicht `days` Tage nach `row` (exklusive dieses Tages), mit dem tatsächlichen Essen und der Bewegung."""
    w = row["weight_trend"]
    for d in pd.date_range(pd.Timestamp(row["date"]), periods=days, freq="D"):
        eaten = intake.get(d)
        eaten = row["intake_avg"] if eaten is None or pd.isna(eaten) else float(eaten)
        w += (eaten * (1 - TEF) - row["base"] - float(active.get(d, 0.0) or 0.0)) / RHO
    return w


def resting_kcal(weight: float, height_cm: float | None, age: float | None,
                 ffm: float | None = None) -> tuple[float | None, str | None]:
    """Ruheumsatz nur zur Einordnung von B: mit fettfreier Masse (aus dem Taillenumfang) Cunningham
    (500 + 22 · FFM, für Trainierte genauer), sonst Mifflin-St Jeor (Mann: 10·kg + 6,25·cm − 5·Jahre + 5).
    Bewusst nie mit dem Körperfett der Waage: eine Formel aus dem Gewicht (R² 0,998), keine Messung."""
    if ffm is not None:
        return 500 + 22 * ffm, "cunningham"
    if height_cm is None or age is None:
        return None, None
    return 10 * weight + 6.25 * height_cm - 5 * age + 5, "mifflin"


# ---------------- Anbindung an Milons Daten ----------------
def _active_series(start: date, end: date) -> pd.Series:
    from . import active_kcal
    try:
        parts, _ = active_kcal.compute(start, end)
    except Exception:  # noqa: BLE001 -- ohne Bewegungsdaten lernt das Modell alles in B
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(d): sum(v.values()) for d, v in parts.items()}, dtype=float).sort_index()


def model(until: date | None = None) -> list[dict]:
    from . import body
    weight, intake = body._weight_daily().dropna(), body._intake_daily().dropna()
    if weight.empty or intake.empty:
        return []
    start = max(weight.index.min(), intake.index.min()).date()
    end = until or max(weight.index.max(), intake.index.max()).date()
    return run(weight, intake, _active_series(start, end), until=end)
