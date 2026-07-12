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


def pace_detail(alpha: float = 0.25) -> dict:
    """Pace je LAUF statt Wochen-Ø — ~3× feinere Auflösung — plus kausale EWMA-Glättung
    (α wie Stärke-Index/EF) für einen ruhigen Verlauf trotz Intensitäts-Rauschens.
    BEWUSST ohne Signifikanz-Urteil: rohe Pace mischt Intervall-/Locker-Läufe, ein
    Pace~Zeit-Trend wäre irreführend (mehr Locker-Läufe ⇒ „langsamer" trotz Fitness) —
    das belastbare Urteil liefert pace_at_hr(), das die Intensität herauskontrolliert."""
    df = _runs()
    if df.empty:
        return {}
    df = df.sort_values("started_at").copy()
    if len(df) < 2:
        return {}
    smooth = df["pace"].ewm(alpha=alpha).mean()
    series = [
        {"date": d.date().isoformat(), "pace": round(float(p), 2), "smooth": round(float(s), 2)}
        for d, p, s in zip(df["started_at"], df["pace"], smooth)
    ]
    return {
        "series": series,
        "runs": int(len(df)),
        "current": series[-1]["smooth"],
        "caveat": "Pace je Lauf (Intervall-/Locker-Läufe gemischt) + EWMA-Glättung nur zur "
                  "Anzeige. Belastbares Fitness-Urteil: Pace bei Referenzpuls.",
    }


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


def ef_trend(alpha: float = 0.25) -> dict:
    """Aerobe Effizienz je LAUF (Meter pro Herzschlag) statt Wochen-Ø — feiner aufgelöst,
    plus kausale EWMA-Glättung (α wie beim Stärke-Index) gegen Intensitäts-/Tagesform-
    Rauschen. Urteil (95%-CI) aus der Lauf-Level-Regression EF ~ Zeit (Läufe ~unabhängig,
    Ehrliche-Statistik-Regel); die geglättete Kurve ist reine Anzeige."""
    df = _runs()
    if df.empty:
        return {}
    df = df[df["ef"].notna()].sort_values("started_at").copy()
    if len(df) < 4:
        return {}
    smooth = df["ef"].ewm(alpha=alpha).mean()
    series = [
        {"date": d.date().isoformat(), "ef": round(float(e), 3), "smooth": round(float(s), 3)}
        for d, e, s in zip(df["started_at"], df["ef"], smooth)
    ]
    xs = ((df["started_at"] - df["started_at"].min()).dt.total_seconds() / 86_400).tolist()
    trend = stats.assess(stats.linear_trend(xs, df["ef"].tolist()), down_is_good=False)
    return {
        "series": series,
        "current": series[-1]["smooth"],
        "runs": int(len(df)),
        "trend": trend,
        "caveat": "EF = Speed/Ø-HF je Lauf; Temperatur/Terrain/Intensität nicht kontrolliert. "
                  "Urteil aus Einzel-Läufen, EWMA-Kurve nur zur Anzeige.",
    }


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


# Physiologische Lauf-Puls-Zonen als Anteil des Maximalpulses (%HFmax). 4 Zonen bei
# 70/80/90 %: (Kürzel, Name, untere Grenze, obere Grenze) — obere Grenze der Top-Zone offen.
_ZONE_DEFS = [
    ("Z1", "Locker", 0.00, 0.70),
    ("Z2", "Grundlage", 0.70, 0.80),
    ("Z3", "Tempo", 0.80, 0.90),
    ("Z4", "Hart", 0.90, 1.01),
]


def _resolved_hr_max(df: pd.DataFrame) -> tuple[float, str]:
    """Maximalpuls für die Zonen: Einstellung (robust) vor Datenableitung. 0/leer in der
    Einstellung ⇒ robustes 95.-Perzentil der max_hr (gegen Sensor-Spikes), Boden 180."""
    from ..config import settings
    configured = float(getattr(settings, "run_hr_max", 0) or 0)
    if configured > 0:
        return configured, "einstellung"
    if not df.empty and df["max_hr"].notna().any():
        return max(float(df["max_hr"].quantile(0.95)), 180.0), "daten"
    return 180.0, "standard"


def pace_by_hr_zone(min_runs: int = 3, min_weeks: int = 2, hr_max: float | None = None) -> dict:
    """Pace-Wochenkurven je physiologischer Puls-Zone (%HFmax): Läufe nach Ø-HF in 4 Zonen
    (Z1 Locker <70 %, Z2 Grundlage 70–80 %, Z3 Tempo 80–90 %, Z4 Hart ≥90 % des Maximalpulses)
    einsortiert, je Zone der Wochen-Ø der Pace. Beantwortet „bei Puls-Zone X — werde ich
    schneller?". BEWUSST ohne Signifikanz-Badge: pro Zone wenige Läufe + parallele Tests
    (Multiple-Comparisons); Δ/Monat nur als deskriptiver Punkt-Schätzer."""
    df = _runs()
    if df.empty:
        return {}
    df = df[df["avg_hr"].notna()].copy()
    if df.empty:
        return {}
    hrmax, hr_src = (float(hr_max), "einstellung") if hr_max and hr_max > 0 else _resolved_hr_max(df)
    edges_lo = np.array([lo * hrmax for _, _, lo, _ in _ZONE_DEFS])  # untere Grenzen in bpm
    # Zone-Index je Lauf: Anzahl unterer Grenzen ≤ Ø-HF, minus 1 (geklemmt auf 0..3)
    df["zone"] = df["avg_hr"].apply(
        lambda h: int(min(len(_ZONE_DEFS) - 1, max(0, int((edges_lo <= h).sum()) - 1)))
    )
    df["week"] = df["started_at"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())
    # durchgehende Wochenachse (inkl. Lücken) — Linien bleiben zeitlinear
    weeks_idx = [p.start_time.date() for p in
                 pd.period_range(df["started_at"].min(), df["started_at"].max(), freq="W-SUN")]

    zones: list[dict] = []
    hidden_runs = 0
    for z, grp in sorted(df.groupby("zone"), key=lambda kv: kv[0]):
        wk = grp.groupby("week")["pace"].mean()
        if len(grp) < min_runs or wk.size < min_weeks:
            hidden_runs += int(len(grp))
            continue
        # Δ s/km pro Monat als deskriptiver Punkt-Schätzer (Lauf-Level-OLS pace ~ Zeit)
        slope_month = None
        if len(grp) >= 3:
            xs = (grp["started_at"] - grp["started_at"].min()).dt.total_seconds().to_numpy() / 86_400
            if xs.max() > 0:
                slope, _ = np.polyfit(xs, grp["pace"].to_numpy(float), 1)
                slope_month = round(float(slope) * 30 * 60, 1)  # min/km je Tag -> s/km je Monat
        code, name, lo_f, hi_f = _ZONE_DEFS[z]
        top = z == len(_ZONE_DEFS) - 1
        raw_series = [round(float(wk[w]), 2) if w in wk.index else None for w in weeks_idx]
        # geglättete Trendlinie je Zone: kausale EWMA über die vorhandenen Wochenwerte
        # (Lücken bleiben Lücken) — macht die Richtung besser erkennbar (wie Pace-Trend/EF).
        obs = [(i, v) for i, v in enumerate(raw_series) if v is not None]
        smooth_series: list[float | None] = [None] * len(raw_series)
        if len(obs) >= 2:
            ewm = pd.Series([v for _, v in obs]).ewm(alpha=0.4).mean().tolist()
            for (i, _), sv in zip(obs, ewm):
                smooth_series[i] = round(float(sv), 2)
        zones.append({
            "zone": code,
            "name": name,
            "idx": z + 1,
            "lo": round(lo_f * hrmax),
            "hi": None if top else round(hi_f * hrmax),
            "pct": f"{int(lo_f * 100)}–{int(hi_f * 100)} %" if not top else f"≥{int(lo_f * 100)} %",
            "runs": int(len(grp)),
            "series": raw_series,
            "smooth": smooth_series,
            "sec_per_km_per_month": slope_month,
        })
    if not zones:
        return {}
    return {
        "hr_max": round(hrmax),
        "hr_max_source": hr_src,
        "weeks": [w.isoformat() for w in weeks_idx],
        "zones": zones,
        "hidden_runs": hidden_runs,
        "caveat": f"Zonen (in % von HFmax {round(hrmax)}) mit < {min_runs} Läufen oder < {min_weeks} "
                  f"Wochen ausgeblendet{f' ({hidden_runs} Läufe)' if hidden_runs else ''}; Δ/Monat ist "
                  "ein Punkt-Schätzer ohne Signifikanz. WICHTIG — Zonen-Wanderung: mit steigender "
                  "Fitness rutschen Läufe bei gleicher Pace in tiefere Zonen, die Zonen-Linien "
                  "unterschätzen den Fortschritt dadurch systematisch (Selektions-Bias); das "
                  "belastbare Urteil liefert Pace@Referenzpuls.",
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


_BEST_EFFORT_DISTANCES = (1000, 5000, 10000, 15000, 20000)


def _dist_label(m: int) -> str:
    return f"{m // 1000} km" if m % 1000 == 0 else f"{m} m"


def best_efforts(top: int = 3) -> dict:
    """Top-`top` Bestzeiten je Standard-Distanz — Best-Effort-Splits (schnellstes X-km-Fenster
    innerhalb eines Laufs, aus den HC-Distanz-Segmenten, à la Strava/Garmin). Distanzen ohne
    qualifizierten Lauf (nie so weit gelaufen) kommen mit leerer Liste zurück."""
    try:
        df = _read("SELECT distance_m, seconds, started_at FROM run_best_efforts",
                   parse_dates=["started_at"])
    except Exception:
        df = pd.DataFrame()
    out: list[dict] = []
    for d in _BEST_EFFORT_DISTANCES:
        entries: list[dict] = []
        if not df.empty:
            sub = df[df["distance_m"] == d].sort_values("seconds").head(top)
            entries = [
                {"seconds": round(float(r["seconds"]), 1),
                 "pace": round(float(r["seconds"]) / 60 / (d / 1000), 2),  # min/km
                 "date": r["started_at"].date().isoformat()}
                for _, r in sub.iterrows()
            ]
        out.append({"distance_m": d, "km": d / 1000, "label": _dist_label(d), "entries": entries})
    return {"distances": out, "top": top, "records": _run_records()}


def _run_records() -> dict:
    """Weitere Lauf-Rekorde (aus den Session-Daten): längster Lauf, größte Wochendistanz,
    beste aerobe Effizienz eines Einzellaufs."""
    df = _runs()
    if df.empty:
        return {}
    rec: dict = {}
    longest = df.loc[df["distance_km"].idxmax()]
    rec["longest_run"] = {"km": round(float(longest["distance_km"]), 1),
                          "date": longest["started_at"].date().isoformat()}
    ef_df = df[df["ef"].notna()]
    if not ef_df.empty:
        be = ef_df.loc[ef_df["ef"].idxmax()]
        rec["best_ef"] = {"ef": round(float(be["ef"]), 2),
                          "date": be["started_at"].date().isoformat()}
    vol = weekly_volume(weeks=999)
    if vol:
        bw = max(vol, key=lambda w: w["km"])
        rec["biggest_week"] = {"km": bw["km"], "week": bw["week"], "runs": bw["runs"]}
    return rec


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
