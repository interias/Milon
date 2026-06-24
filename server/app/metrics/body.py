"""Körper-Metriken (ARCHITECTURE.md §5.1): EWMA-Gewicht, Körperfett-Trend, adaptives TDEE.
Reine Funktionen über die DB (kein Web/LLM). Speisen REST + Coach + MCP."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..db import engine

KCAL_PER_KG = 7700  # Energiegehalt 1 kg Körpermasse (Faustwert)


def _read(sql: str, **kw) -> pd.DataFrame:
    with engine.connect() as con:
        return pd.read_sql(sql, con, **kw)


def _weight_daily() -> pd.Series:
    df = _read(
        "SELECT measured_at, weight_kg FROM body_measurements WHERE weight_kg IS NOT NULL",
        parse_dates=["measured_at"],
    )
    if df.empty:
        return pd.Series(dtype=float)
    s = df.groupby(df["measured_at"].dt.floor("D"))["weight_kg"].mean().sort_index()
    return s.asfreq("D")  # Lücken als NaN


def _intake_daily() -> pd.Series:
    df = _read(
        "SELECT eaten_at, kcal FROM nutrition_entries WHERE kcal IS NOT NULL",
        parse_dates=["eaten_at"],
    )
    if df.empty:
        return pd.Series(dtype=float)
    return df.groupby(df["eaten_at"].dt.floor("D"))["kcal"].sum().sort_index()


def weight_trend(days: int = 180) -> list[dict]:
    """Tagesgewicht (roh), 7-Tage-EWMA und 7-Tage-Mittel. Tageswerte nie roh interpretieren."""
    s = _weight_daily()
    if s.empty:
        return []
    ewma = s.interpolate().ewm(span=10).mean()
    avg7 = s.rolling(7, min_periods=1).mean()
    cutoff = s.index.max() - pd.Timedelta(days=days)
    out = []
    for d in s.index:
        if d < cutoff:
            continue
        out.append({
            "date": d.date().isoformat(),
            "weight": None if pd.isna(s[d]) else round(float(s[d]), 2),
            "ewma": round(float(ewma[d]), 2),
            "avg7": round(float(avg7[d]), 2),
        })
    return out


def body_fat_trend(days: int = 180) -> list[dict]:
    df = _read(
        "SELECT measured_at, body_fat_pct FROM body_measurements WHERE body_fat_pct IS NOT NULL",
        parse_dates=["measured_at"],
    )
    if df.empty:
        return []
    s = df.groupby(df["measured_at"].dt.floor("D"))["body_fat_pct"].mean().sort_index()
    avg7 = s.rolling(7, min_periods=1).mean()
    cutoff = s.index.max() - pd.Timedelta(days=days)
    return [
        {"date": d.date().isoformat(), "pct": round(float(s[d]), 1), "avg7": round(float(avg7[d]), 1)}
        for d in s.index if d >= cutoff
    ]


def adaptive_tdee(window_days: int = 14, smooth_days: int = 14) -> dict:
    """Aktuelles TDEE = Mittel der täglichen rollenden TDEE-Schätzungen über die letzten
    smooth_days Tage. Die EINZEL-Tagesschätzung schwankt stark (Wasser/Glykogen im
    Gewichtsverlauf) — das 14-Tage-Mittel ist der stabile Wert. Defizit = TDEE − Ø-Intake
    der letzten 7 Tage (aktuelles Essverhalten)."""
    trend = tdee_trend(window_days=window_days, days=400, smooth_days=smooth_days)
    if not trend:
        return {"tdee": None, "reason": "Gewicht oder Intake fehlt"}
    tdee = trend[-1]["tdee_avg"]
    # Ø-Intake aus demselben Glättungsfenster -> TDEE = Ø-Intake + Defizit gilt sauber.
    recent = trend[-smooth_days:] if len(trend) >= smooth_days else trend
    avg_intake = round(sum(p["intake"] for p in recent) / len(recent))
    # Gewichtsänderung (7-Tage-Mittel) über das Glättungsfenster — nur Kontext.
    wavg = _weight_daily().rolling(7, min_periods=3).mean().dropna()
    wc = None
    if not wavg.empty:
        ref = wavg[wavg.index <= wavg.index.max() - pd.Timedelta(days=smooth_days)]
        if not ref.empty:
            wc = round(float(wavg.iloc[-1] - ref.iloc[-1]), 2)
    return {
        "tdee": tdee,
        "avg_intake": avg_intake,
        "deficit_per_day": tdee - avg_intake,
        "weight_change_kg": wc,
        "window_days": int(window_days),
        "smooth_days": int(smooth_days),
        "intake_days": int(len(recent)),
    }


def tdee_trend(window_days: int = 14, days: int = 180, smooth_days: int = 14,
               min_intake_days: int = 7) -> list[dict]:
    """Rollendes adaptives TDEE je Tag (`tdee`) + geglättetes `tdee_avg` (rollendes
    smooth_days-Mittel der Tagesschätzungen). TDEE(t) = Ø-Intake[t−window..t] −
    Δ(7-Tage-Gewicht über das Fenster) × 7700 / window. Die Einzelschätzung schwankt durch
    Wasser/Glykogen stark → `tdee_avg` ist der stabile Wert."""
    w = _weight_daily()
    intake = _intake_daily()
    if w.empty or intake.empty:
        return []
    avg7 = w.rolling(7, min_periods=3).mean()  # 7-Tage-geglättetes Gewicht
    out: list[dict] = []
    for t in avg7.index:
        t0 = t - pd.Timedelta(days=window_days)
        wt, w0 = avg7.get(t), avg7.get(t0)
        if wt is None or w0 is None or pd.isna(wt) or pd.isna(w0):
            continue
        win = intake[(intake.index > t0) & (intake.index <= t)]
        if len(win) < min_intake_days:
            continue
        delta = float(wt - w0)
        avg_intake = float(win.mean())
        out.append({
            "date": t.date().isoformat(),
            "tdee": round(avg_intake - delta * KCAL_PER_KG / window_days),
            "intake": round(avg_intake),
        })
    if not out:
        return []
    # Tagesschätzung glätten: rollendes smooth_days-Mittel (Kalender) -> stabile Linie/Aktuell-Wert
    ser = pd.Series([o["tdee"] for o in out], index=pd.to_datetime([o["date"] for o in out]))
    avg = ser.rolling(f"{smooth_days}D").mean()
    for o, a in zip(out, avg.to_numpy()):
        o["tdee_avg"] = round(float(a))
    cutoff = pd.Timestamp(out[-1]["date"]) - pd.Timedelta(days=days)
    return [r for r in out if pd.Timestamp(r["date"]) >= cutoff]


def steps_recent(days: int = 14) -> dict:
    """Letzte Tagesschritte + 7-Tage-Schnitt (Health Connect)."""
    df = _read("SELECT day, steps FROM steps_daily ORDER BY day", parse_dates=["day"])
    if df.empty:
        return {"last": None, "last_day": None, "avg7": None, "series": []}
    df = df.sort_values("day")
    last = int(df["steps"].iloc[-1])
    avg7 = int(round(df["steps"].tail(7).mean()))
    cutoff = df["day"].max() - pd.Timedelta(days=days)
    series = [
        {"date": d.date().isoformat(), "steps": int(v)}
        for d, v in zip(df["day"], df["steps"]) if d >= cutoff
    ]
    return {"last": last, "last_day": df["day"].iloc[-1].date().isoformat(), "avg7": avg7, "series": series}


def weekly_weight(weeks: int = 12) -> list[dict]:
    """Wochenmittel des Gewichts (zum schnellen Trend-Überblick)."""
    s = _weight_daily().dropna()
    if s.empty:
        return []
    w = s.resample("W-SUN").mean().dropna().tail(weeks)
    return [{"week": d.date().isoformat(), "weight": round(float(v), 2)} for d, v in w.items()]


def _bodyfat_daily() -> pd.Series:
    df = _read(
        "SELECT measured_at, body_fat_pct FROM body_measurements WHERE body_fat_pct IS NOT NULL",
        parse_dates=["measured_at"],
    )
    if df.empty:
        return pd.Series(dtype=float)
    s = df.groupby(df["measured_at"].dt.floor("D"))["body_fat_pct"].mean().sort_index()
    return s.asfreq("D")


def lean_mass_trend(days: int = 180) -> list[dict]:
    """Recomp-Sicht: Magermasse (FFM) & Fettmasse aus geglättetem Gewicht × (1 − KFA%).
    Beantwortet 'behalte ich im Defizit meine Muskeln?' (FFM stabil/↑ = ja)."""
    w = _weight_daily()
    bf = _bodyfat_daily()
    if w.empty or bf.empty:
        return []
    w = w.interpolate().ewm(span=10).mean()
    bf = bf.interpolate().rolling(7, min_periods=1).mean()
    idx = w.index.intersection(bf.index)
    if len(idx) < 2:
        return []
    w, bf = w.loc[idx], bf.loc[idx]
    ffm = w * (1 - bf / 100.0)
    fat = w - ffm
    cutoff = idx.max() - pd.Timedelta(days=days)
    return [
        {"date": d.date().isoformat(), "weight": round(float(w[d]), 2),
         "ffm": round(float(ffm[d]), 2), "fat": round(float(fat[d]), 2)}
        for d in idx if d >= cutoff
    ]


def lean_mass_summary(days: int = 90) -> dict:
    """Aktuelle FFM/Fettmasse + Veränderung über das Fenster (erste → letzte)."""
    t = lean_mass_trend(days=days)
    if len(t) < 2:
        return {"ffm": None, "fat": None, "weight": None, "ffm_delta": None, "fat_delta": None, "days": 0}
    a, b = t[0], t[-1]
    return {
        "ffm": b["ffm"], "fat": b["fat"], "weight": b["weight"],
        "ffm_delta": round(b["ffm"] - a["ffm"], 2),
        "fat_delta": round(b["fat"] - a["fat"], 2),
        "days": len(t),
    }


def _forecast(s: pd.Series, horizon: int, fit_days: int, ndigits: int) -> dict:
    """Linearer Trend (kleinste Quadrate) über die letzten fit_days der geglätteten Serie,
    horizon Tage in die Zukunft extrapoliert. Die Prognoselinie ist am letzten Ist-Wert
    verankert und verlängert sich mit der Trendsteigung. Liefert zusätzlich die jüngste
    History (für ein lückenloses Chart) und den projizierten Endwert (Horizontallinie)."""
    s = s.dropna()
    if len(s) < 4:
        return {}
    last_date = s.index.max()
    window = s[s.index > last_date - pd.Timedelta(days=fit_days)]
    if len(window) < 3:
        window = s.tail(max(3, min(len(s), fit_days)))
    x = (window.index - window.index.min()).days.to_numpy(dtype=float)
    y = window.to_numpy(dtype=float)
    slope, _ = np.polyfit(x, y, 1)  # y = slope*x + b
    slope = float(slope)
    current = float(s.iloc[-1])
    projected = current + slope * horizon
    hist = s.tail(90)
    return {
        "current": round(current, ndigits),
        "projected": round(projected, ndigits),
        "slope_per_day": round(slope, 4),
        "per_week": round(slope * 7, ndigits),
        "per_month": round(slope * 30, ndigits),
        "horizon_days": int(horizon),
        "fit_days": int(fit_days),
        "from_date": last_date.date().isoformat(),
        "history": [
            {"date": d.date().isoformat(), "value": round(float(v), ndigits)} for d, v in hist.items()
        ],
        "points": [
            {"date": (last_date + pd.Timedelta(days=k)).date().isoformat(),
             "value": round(current + slope * k, ndigits)}
            for k in range(0, horizon + 1)
        ],
    }


def weight_forecast(horizon: int = 30, fit_days: int = 30) -> dict:
    """30-Tage-Gewichtsprognose auf Basis des EWMA-Trends (Wasser-Rauschen geglättet)."""
    s = _weight_daily()
    if s.empty:
        return {}
    return _forecast(s.interpolate().ewm(span=10).mean(), horizon, fit_days, 2)


def composition_forecast(horizon: int = 30, fit_days: int = 30) -> dict:
    """Körperkomposition-Prognose, verankert am VERLÄSSLICHEN Gewichtstrend. Die geschätzte
    Gewichtsänderung wird über einen Magerverlust-Anteil p (Anteil der Abnahme, der FFM ist)
    in Fett & FFM aufgeteilt; KFA/FFM/Fett folgen arithmetisch — `weight = fat + ffm` und
    `BF = fat/weight` gelten per Konstruktion. KEIN eigener Trend-Fit aufs verrauschte
    Bioimpedanz-KFA. Drei Szenarien:
      p=0    Magermasse erhalten (optimistisch; alles Verlust = Fett)
      p=0.15 erwartet (Literatur: High-Protein-Cut) — Headline
      p=p_obs Waagentrend (pessimistisch; = aktueller BIA-Trend, überschätzt Muskelverlust).
    """
    wf = weight_forecast(horizon, fit_days)
    lm = lean_mass_trend(days=max(fit_days * 3, 120))
    if not wf or len(lm) < 4 or wf.get("slope_per_day") is None:
        return {}
    sW = wf["slope_per_day"]
    a = lm[-1]
    W0, FFM0, FAT0 = float(a["weight"]), float(a["ffm"]), float(a["fat"])
    if W0 <= 0:
        return {}
    BF0 = round(FAT0 / W0 * 100, 1)

    # p_obs = beobachteter Magerverlust-Anteil aus der geglätteten FFM-Reihe — NUR für den
    # pessimistischen Rand (explizit als BIA-limitiert gelabelt), nie als zentrale Schätzung.
    s = pd.Series([p["ffm"] for p in lm], index=pd.to_datetime([p["date"] for p in lm])).dropna()
    s = s[s.index > s.index.max() - pd.Timedelta(days=fit_days)]
    if len(s) >= 4 and sW:
        sFFM = float(np.polyfit((s.index - s.index.min()).days.to_numpy(float), s.to_numpy(float), 1)[0])
        p_obs = sFFM / sW
    else:
        p_obs = 0.0
    p_hi = min(0.46, max(0.0, p_obs))

    def scn(p: float, key: str, label: str, note: str | None = None) -> dict:
        ffm = FFM0 + p * sW * horizon
        fat = FAT0 + (1 - p) * sW * horizon
        w = ffm + fat
        return {
            "key": key, "label": label, "p": round(p, 2),
            "weight": round(w, 1), "ffm": round(ffm, 1), "fat": round(fat, 1),
            "bf_pct": round(100 * fat / w, 1) if w > 0 else None,
            "ffm_delta": round(ffm - FFM0, 1), "fat_delta": round(fat - FAT0, 1),
            "note": note,
        }

    return {
        "horizon_days": int(horizon),
        "weight": {"current": wf["current"], "projected": wf["projected"], "per_month": wf["per_month"]},
        "anchor": {"weight": round(W0, 1), "bf_pct": BF0, "fat": round(FAT0, 1), "ffm": round(FFM0, 1)},
        "scenarios": [
            scn(0.0, "preserved", "Magermasse erhalten"),
            scn(0.15, "expected", "Erwartet"),
            scn(p_hi, "trend", "Waagentrend", "Waage roh – überschätzt Muskelverlust"),
        ],
        "p_obs": round(p_obs, 2),
        "note": "Gewicht verlässlich; Fett-/Muskel-Anteil der Abnahme per Bioimpedanz nicht sicher messbar.",
    }


def bodyfat_forecast(horizon: int = 30, fit_days: int = 30) -> dict:
    """Körperfett-Prognose (für Coach/Snapshot/MCP) = 'Erwartet'-Szenario (p=0.15) aus
    composition_forecast — am Gewichtstrend verankert statt eigenständiger BIA-Extrapolation."""
    cf = composition_forecast(horizon, fit_days)
    if not cf:
        return {}
    cur = cf["anchor"]["bf_pct"]
    exp = next((s for s in cf["scenarios"] if s["key"] == "expected"), None)
    if cur is None or exp is None or exp["bf_pct"] is None:
        return {}
    proj = exp["bf_pct"]
    return {
        "current": cur, "projected": proj,
        "per_week": round((proj - cur) * 7.0 / horizon, 1),
        "per_month": round((proj - cur) * 30.0 / horizon, 1),
        "horizon_days": int(horizon),
        "scenarios": cf["scenarios"],
    }


def summary() -> dict:
    s = _weight_daily().dropna()
    bf = _read(
        "SELECT measured_at, body_fat_pct FROM body_measurements WHERE body_fat_pct IS NOT NULL "
        "ORDER BY measured_at DESC LIMIT 1", parse_dates=["measured_at"],
    )
    avg7 = s.rolling(7, min_periods=1).mean() if not s.empty else pd.Series(dtype=float)
    latest_avg7 = float(avg7.iloc[-1]) if not avg7.empty else None
    prev_avg7 = float(avg7.iloc[-8]) if len(avg7) >= 8 else None
    return {
        "weight_kg": round(float(s.iloc[-1]), 1) if not s.empty else None,
        "weight_avg7": round(latest_avg7, 1) if latest_avg7 is not None else None,
        "weight_delta7": round(latest_avg7 - prev_avg7, 2) if (latest_avg7 and prev_avg7) else None,
        "body_fat_pct": round(float(bf["body_fat_pct"].iloc[0]), 1) if not bf.empty else None,
        "tdee": adaptive_tdee().get("tdee"),
    }
