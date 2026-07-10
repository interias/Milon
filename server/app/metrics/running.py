"""Lauf-Metriken (ARCHITECTURE.md §5.2): Wochenvolumen, Pace-Trend, VO2max-Trend,
Herzfrequenz (Ø/Max je Lauf) + aerobe Effizienz (Meter pro Herzschlag) + HF-Drift,
Fitness-Trends (Pace@Referenzpuls, Locker-Korridor-HF, TRIMP-Trainingslast).
exercise_type 33 = Laufen. Höhenmeter sind NICHT verfügbar (HC liefert keine)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..db import engine
from . import stats

RUN = 33


def _read(sql: str, **kw) -> pd.DataFrame:
    with engine.connect() as con:
        return pd.read_sql(sql, con, **kw)


def _runs() -> pd.DataFrame:
    df = _read(
        "SELECT started_at, ended_at, distance_km, avg_hr, max_hr, hr_drift_pct "
        f"FROM exercise_sessions WHERE exercise_type = {RUN}",
        parse_dates=["started_at", "ended_at"],
    )
    if df.empty:
        return df
    df["dur_min"] = (df["ended_at"] - df["started_at"]).dt.total_seconds() / 60
    # Sanity-Filter: plausible Läufe (verrauschte HC-Distanzen aussortieren)
    df = df[(df["distance_km"].fillna(0) >= 1) & (df["distance_km"] <= 60)
            & (df["dur_min"] > 5) & (df["dur_min"] < 600)].copy()
    df["pace"] = df["dur_min"] / df["distance_km"]  # min/km
    df = df[(df["pace"] >= 3) & (df["pace"] <= 12)]  # plausible Pace
    # Aerobe Effizienz (Efficiency Factor): Meter pro Herzschlag = Speed (m/min) / HF (bpm).
    # Höher = fitter; aussagekräftiger als Pace allein, weil sie die "Kosten" mitmisst.
    speed_m_min = df["distance_km"] * 1000 / df["dur_min"]
    df["ef"] = (speed_m_min / df["avg_hr"]).where(df["avg_hr"] > 0)
    return df


def weekly_volume(weeks: int = 26) -> list[dict]:
    df = _runs()
    if df.empty:
        return []
    df["week"] = df["started_at"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())
    g = df.groupby("week").agg(km=("distance_km", "sum"), runs=("distance_km", "size")).reset_index()
    g = g.sort_values("week").tail(weeks)
    return [
        {"week": w.isoformat(), "km": round(float(km), 1), "runs": int(n)}
        for w, km, n in zip(g["week"], g["km"], g["runs"])
    ]


def volume_window(days: int = 7) -> dict:
    """Lauf-km der letzten `days` Tage vs. der `days` Tage davor (rollend, heute-relativ) —
    fairer als Kalenderwoche, die ja noch läuft."""
    df = _runs()
    if df.empty:
        return {"current_km": 0.0, "previous_km": 0.0, "current_runs": 0, "previous_runs": 0, "days": days}
    now = pd.Timestamp.now()
    cur_start = now - pd.Timedelta(days=days)
    prev_start = now - pd.Timedelta(days=2 * days)
    cur = df[df["started_at"] > cur_start]
    prev = df[(df["started_at"] > prev_start) & (df["started_at"] <= cur_start)]
    return {
        "current_km": round(float(cur["distance_km"].sum()), 1),
        "previous_km": round(float(prev["distance_km"].sum()), 1),
        "current_runs": int(len(cur)),
        "previous_runs": int(len(prev)),
        "days": days,
    }


def pace_trend(weeks: int = 26) -> list[dict]:
    df = _runs()
    if df.empty:
        return []
    df["week"] = df["started_at"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())
    g = df.groupby("week")["pace"].mean().reset_index().sort_values("week").tail(weeks)
    return [{"week": w.isoformat(), "pace": round(float(p), 2)} for w, p in zip(g["week"], g["pace"])]


def heart_rate_trend(weeks: int = 26) -> list[dict]:
    """Wochenwerte über Läufe MIT HF: Ø-HF, Max-HF, aerobe Effizienz (m/Herzschlag),
    Ø-Drift (Ø-HF 2. vs. 1. Hälfte, %). Wochen ohne HF-Läufe fehlen bewusst."""
    df = _runs()
    if df.empty:
        return []
    df = df[df["avg_hr"].notna()]
    if df.empty:
        return []
    df["week"] = df["started_at"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())
    g = df.groupby("week").agg(
        avg_hr=("avg_hr", "mean"), max_hr=("max_hr", "max"),
        ef=("ef", "mean"), drift=("hr_drift_pct", "mean"), runs=("avg_hr", "size"),
    ).reset_index().sort_values("week").tail(weeks)
    return [
        {
            "week": r["week"].isoformat(),
            "avg_hr": round(float(r["avg_hr"]), 1),
            "max_hr": round(float(r["max_hr"]), 0) if pd.notna(r["max_hr"]) else None,
            "ef": round(float(r["ef"]), 2) if pd.notna(r["ef"]) else None,
            "drift": round(float(r["drift"]), 1) if pd.notna(r["drift"]) else None,
            "runs": int(r["runs"]),
        }
        for _, r in g.iterrows()
    ]


def pace_at_hr(ref_hr: int | None = None, window_weeks: int = 8) -> dict:
    """„Welche Pace läufst du bei X bpm?" — Fitness-Kennzahl, die die Intensität herauskontrolliert.

    Anzeige-Serie: je Woche eine Regression Speed~HF über die Läufe der letzten `window_weeks`
    Wochen, ausgewertet am Referenzpuls (Fenster ohne genug Läufe/HF-Streuung → Lücke).
    Signifikanz-Urteil: NICHT aus der (autokorrelierten) Rolling-Serie, sondern aus dem
    Lauf-Level-Modell Speed = a + b·HF + c·Tage über ALLE HF-Läufe — c misst „schneller
    bei gleichem Puls", die Residuen einzelner Läufe sind ~unabhängig."""
    df = _runs()
    if df.empty:
        return {}
    df = df[df["avg_hr"].notna()].sort_values("started_at").copy()
    if len(df) < 6:
        return {}
    if ref_hr is None:
        ref_hr = int(round(float(df["avg_hr"].median()) / 5) * 5)
    df["speed"] = df["distance_km"] * 1000 / df["dur_min"]  # m/min
    t0 = df["started_at"].min()
    t_days = (df["started_at"] - t0).dt.total_seconds().to_numpy() / 86_400
    hr = df["avg_hr"].to_numpy(float)
    speed = df["speed"].to_numpy(float)

    # --- Urteil: Lauf-Level-Modell ---
    trend: dict = {"verdict": "wenig_daten", "label": "zu wenig Daten", "n": int(len(df))}
    fit = stats.ols(np.column_stack([np.ones(len(df)), hr, t_days]), speed)
    if fit is not None and hr.max() - hr.min() >= 8:
        beta, se, dof, r2 = fit
        b_hr, c_t = float(beta[1]), float(beta[2])
        ci_c = stats.t95(dof) * float(se[2])
        span = float(t_days.max() - t_days.min())
        # Pace-Änderung über den Zeitraum, am Referenzpuls ausgewertet (Sekunden/km)
        s_start = float(beta[0]) + b_hr * ref_hr + c_t * float(t_days.min())
        s_end = float(beta[0]) + b_hr * ref_hr + c_t * float(t_days.max())
        delta_sec = (1000 / s_end - 1000 / s_start) * 60 if s_start > 0 and s_end > 0 else None
        if b_hr <= 0:
            trend = {"verdict": "unklar", "label": "HF-Tempo-Zusammenhang zu schwach (Steigung ≤ 0)",
                     "n": int(len(df)), "r2": round(r2, 2)}
        else:
            significant = bool(len(df) >= 8 and abs(c_t) > ci_c)
            verdict = ("besser" if c_t > 0 else "schlechter") if significant else "unklar"
            trend = {
                "verdict": verdict,
                "label": "signifikanter Trend (95 %)" if significant else "kein belastbarer Trend",
                "significant": significant,
                "n": int(len(df)), "days": round(span), "r2": round(r2, 2),
                "delta_sec_per_km": round(delta_sec, 1) if delta_sec is not None else None,
                "sec_per_km_per_month": round(delta_sec / span * 30, 1) if delta_sec is not None and span > 0 else None,
            }

    # --- Anzeige-Serie: rollierende Fenster-Regression ---
    series: list[dict] = []
    win = pd.Timedelta(days=window_weeks * 7)
    for p in pd.period_range(df["started_at"].min(), df["started_at"].max(), freq="W-SUN"):
        w = df[(df["started_at"] > p.end_time - win) & (df["started_at"] <= p.end_time)]
        pace_ref = None
        if len(w) >= 6:
            whr = w["avg_hr"].to_numpy(float)
            if whr.max() - whr.min() >= 8 and whr.min() - 5 <= ref_hr <= whr.max() + 5:
                b, a = np.polyfit(whr, w["speed"].to_numpy(float), 1)
                if b > 0:
                    s_ref = a + b * ref_hr
                    if s_ref > 0 and 3 <= 1000 / s_ref <= 12:
                        pace_ref = round(1000 / s_ref, 2)
        series.append({"week": p.start_time.date().isoformat(), "pace": pace_ref})

    valid = [s["pace"] for s in series if s["pace"] is not None]
    return {
        "ref_hr": ref_hr,
        "window_weeks": window_weeks,
        "series": series,
        "points": len(valid),
        "current": valid[-1] if valid else None,
        "trend": trend,
        "caveat": "Ø-Werte pro Lauf; Temperatur/Terrain nicht kontrolliert. Urteil aus dem "
                  "Lauf-Level-Modell (Speed ~ HF + Zeit), Kurve nur zur Anzeige.",
    }


def easy_hr_trend(band_pct: float = 5.0) -> dict:
    """Gegencheck zur Regression: nur Läufe im Pace-Korridor (Median ±band_pct %) —
    „gleiche Pace, welcher Puls?". Wochen-Ø fürs Chart, Urteil aus den Einzel-Läufen."""
    df = _runs()
    if df.empty:
        return {}
    df = df[df["avg_hr"].notna()].sort_values("started_at").copy()
    if len(df) < 4:
        return {}
    med = float(df["pace"].median())
    lo, hi = med * (1 - band_pct / 100), med * (1 + band_pct / 100)
    band = df[(df["pace"] >= lo) & (df["pace"] <= hi)].copy()
    if len(band) < 4:
        return {"pace_lo": round(lo, 2), "pace_hi": round(hi, 2), "runs": int(len(band)),
                "series": [], "trend": {"verdict": "wenig_daten", "label": "zu wenig Daten", "n": int(len(band))}}

    band["week"] = band["started_at"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())
    g = band.groupby("week").agg(avg_hr=("avg_hr", "mean"), runs=("avg_hr", "size")).reset_index().sort_values("week")
    series = [{"week": w.isoformat(), "avg_hr": round(float(h), 1), "runs": int(n)}
              for w, h, n in zip(g["week"], g["avg_hr"], g["runs"])]

    t0 = band["started_at"].min()
    xs = ((band["started_at"] - t0).dt.total_seconds() / 86_400).tolist()
    trend = stats.assess(stats.linear_trend(xs, band["avg_hr"].tolist()), down_is_good=True)
    return {
        "pace_lo": round(lo, 2), "pace_hi": round(hi, 2), "runs": int(len(band)),
        "series": series, "trend": trend,
        "caveat": f"Nur Läufe mit Pace {lo:.2f}–{hi:.2f} min/km (Median ±{band_pct:.0f} %); "
                  "Urteil aus Einzel-Läufen, Wochenkurve nur zur Anzeige.",
    }


def trimp_weekly(weeks: int = 26) -> dict:
    """Trainingslast je Woche (Banister-TRIMP): Dauer × HF-Intensität — ein harter kurzer
    Lauf zählt mehr als ein lockerer langer. Reine Last-Metrik, kein „besser/schlechter"."""
    df = _runs()
    if df.empty:
        return {}
    df = df[df["avg_hr"].notna()].copy()
    if df.empty:
        return {}
    # Referenzen: Ruhepuls aus resting_hr_daily (Median 90 T), sonst 60; HFmax = beobachtetes
    # Maximum (mind. 180 als Boden). Absolutwerte sind grob — es zählt der Wochenvergleich.
    rest_df = _read("SELECT bpm FROM resting_hr_daily ORDER BY day DESC LIMIT 90")
    hr_rest = float(rest_df["bpm"].median()) if not rest_df.empty else 60.0
    observed_max = float(df["max_hr"].max()) if df["max_hr"].notna().any() else float(df["avg_hr"].max())
    hr_max = max(observed_max, 180.0)
    denom = max(hr_max - hr_rest, 1.0)
    hrr = ((df["avg_hr"] - hr_rest) / denom).clip(0, 1)
    df["trimp"] = df["dur_min"] * hrr * 0.64 * np.exp(1.92 * hrr)

    df["week"] = df["started_at"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())
    g = df.groupby("week").agg(trimp=("trimp", "sum"), runs=("trimp", "size")).reset_index()
    g = g.sort_values("week").tail(weeks)
    series = [{"week": w.isoformat(), "trimp": round(float(t), 0), "runs": int(n)}
              for w, t, n in zip(g["week"], g["trimp"], g["runs"])]
    last4 = [s["trimp"] for s in series[-4:]]
    return {
        "hr_rest": round(hr_rest, 0), "hr_max": round(hr_max, 0),
        "series": series,
        "avg4": round(sum(last4) / len(last4), 0) if last4 else None,
        "caveat": "Banister-TRIMP aus Ø-HF je Lauf; HFmax/Ruhepuls geschätzt — Vergleich "
                  "über Wochen zählt, nicht der Absolutwert.",
    }


def vo2_trend(days: int = 365) -> list[dict]:
    df = _read("SELECT measured_at, vo2 FROM vo2max ORDER BY measured_at", parse_dates=["measured_at"])
    if df.empty:
        return []
    cutoff = df["measured_at"].max() - pd.Timedelta(days=days)
    df = df[df["measured_at"] >= cutoff]
    return [
        {"date": d.date().isoformat(), "vo2": round(float(v), 1)}
        for d, v in zip(df["measured_at"], df["vo2"])
    ]


def summary() -> dict:
    vol = weekly_volume(weeks=4)
    pace = pace_trend(weeks=4)
    vo2 = vo2_trend(days=365)
    # WICHTIG: hr[-1] ist die letzte Woche MIT HF-Läufen — die kann älter sein als die
    # letzte Lauf-Woche (watch-lose Läufe). hr_week macht das für Snapshot/UI sichtbar,
    # damit alte HF-Werte nicht als "letzte Woche" gelesen werden.
    hr = heart_rate_trend(weeks=4)
    return {
        "week_km": vol[-1]["km"] if vol else None,
        "week_runs": vol[-1]["runs"] if vol else None,
        "pace": pace[-1]["pace"] if pace else None,
        "vo2max": vo2[-1]["vo2"] if vo2 else None,
        "avg_hr": hr[-1]["avg_hr"] if hr else None,  # Ø-HF der letzten Woche mit HF-Läufen
        "max_hr": hr[-1]["max_hr"] if hr else None,
        "ef": hr[-1]["ef"] if hr else None,  # Meter pro Herzschlag (höher = fitter)
        "hr_drift": hr[-1]["drift"] if hr else None,
        "hr_week": hr[-1]["week"] if hr else None,  # Woche, aus der die HF-Werte stammen
        "elevation": None,  # bewusst: Höhenmeter nicht verfügbar
    }
