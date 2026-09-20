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
    """Daily weight, EWMA (span 10) and mean of the last seven calendar days."""
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
            "avg7": None if pd.isna(avg7[d]) else round(float(avg7[d]), 2),
        })
    return out


def body_fat_trend(days: int = 180) -> list[dict]:
    """Daily BIA estimates and seven-calendar-day mean, with missing days as null."""
    df = _read(
        "SELECT measured_at, body_fat_pct FROM body_measurements WHERE body_fat_pct IS NOT NULL",
        parse_dates=["measured_at"],
    )
    if df.empty:
        return []
    s = df.groupby(df["measured_at"].dt.floor("D"))["body_fat_pct"].mean().sort_index().asfreq("D")
    avg7 = s.rolling("7D", min_periods=1).mean()
    cutoff = s.index.max() - pd.Timedelta(days=days)
    return [
        {"date": d.date().isoformat(),
         "pct": None if pd.isna(s[d]) else round(float(s[d]), 1),
         "avg7": None if pd.isna(avg7[d]) else round(float(avg7[d]), 1)}
        for d in s.index if d >= cutoff
    ]


def adaptive_tdee(window_days: int = 14, smooth_days: int = 14) -> dict:
    """TDEE and intake averaged over identical calendar-dated estimates."""
    trend = tdee_trend(window_days=window_days, days=400, smooth_days=smooth_days)
    if not trend:
        return {"tdee": None, "reason": "Gewicht oder Intake fehlt"}
    tdee = trend[-1]["tdee_avg"]
    cutoff = pd.Timestamp(trend[-1]["date"]) - pd.Timedelta(days=smooth_days)
    recent = [p for p in trend if pd.Timestamp(p["date"]) > cutoff]
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
        "from_date": trend[-1]["date"],
        "avg_intake": avg_intake,
        "deficit_per_day": tdee - avg_intake,
        "weight_change_kg": wc,
        "window_days": int(window_days),
        "smooth_days": int(smooth_days),
        "intake_days": int(len(recent)),
        "estimate_days": len(recent),
        # Coverage marker, not a physiological validity threshold.
        "provisional": len(recent) < max(1, (smooth_days + 1) // 2),
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
    intake_avg = pd.Series([o["intake"] for o in out], index=ser.index).rolling(f"{smooth_days}D").mean()
    counts = ser.rolling(f"{smooth_days}D").count()
    for o, a, i, count in zip(out, avg.to_numpy(), intake_avg.to_numpy(), counts.to_numpy()):
        o["tdee_avg"] = round(float(a))
        o["intake_avg"] = round(float(i))
        o["estimate_days"] = int(count)
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


def _paired_mass() -> pd.DataFrame:
    """Composition on observed paired days, with identical trailing windows."""
    pairs = pd.concat({"weight": _weight_daily(), "bf": _bodyfat_daily()}, axis=1).dropna()
    if pairs.empty:
        return pd.DataFrame(columns=["weight", "bf", "ffm", "fat", "paired_days"])
    means = pairs.rolling("7D", min_periods=3).mean()
    means["ffm"] = means.weight * (1 - means.bf / 100)
    means["fat"] = means.weight - means.ffm
    means["paired_days"] = pairs.weight.rolling("7D").count()
    return means


def lean_mass_trend(days: int = 180) -> list[dict]:
    """Fat-free mass and fat mass derived from smoothed weight and BIA estimates.
    Fat-free mass includes water and other tissues; it does not measure muscle mass."""
    mass = _paired_mass()
    if mass.empty:
        return []
    mass = mass.asfreq("D")
    cutoff = mass.index.max() - pd.Timedelta(days=days)
    return [
        {"date": d.date().isoformat(),
         **{key: None if pd.isna(row[key]) else round(float(row[key]), 2)
            for key in ("weight", "ffm", "fat")},
         "paired_days": int(row.paired_days) if pd.notna(row.paired_days) else 0}
        for d, row in mass.iterrows() if d >= cutoff
    ]


def lean_mass_summary(days: int = 90) -> dict:
    """Aktuelle FFM/Fettmasse + Veränderung über das Fenster (erste → letzte)."""
    rows = lean_mass_trend(days=days)
    t = [p for p in rows if p["ffm"] is not None]
    if not t:
        return {"ffm": None, "fat": None, "weight": None, "ffm_delta": None, "fat_delta": None, "days": 0, "measurement_days": 0}
    a, b = t[0], t[-1]
    return {
        "ffm": b["ffm"], "fat": b["fat"], "weight": b["weight"],
        "ffm_delta": round(b["ffm"] - a["ffm"], 2),
        "fat_delta": round(b["fat"] - a["fat"], 2),
        "days": (pd.Timestamp(b["date"]) - pd.Timestamp(a["date"])).days + 1,
        "from_date": a["date"], "to_date": b["date"],
        "measurement_days": sum(p["paired_days"] > 0 for p in rows if a["date"] <= p["date"] <= b["date"]),
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
    """Observed-day EWMA projection, restarted after >7 missing calendar days."""
    return _guarded_forecast(_weight_daily(), horizon, fit_days)


def _guarded_forecast(s: pd.Series, horizon: int, fit_days: int) -> dict:
    observed = s.dropna()
    metadata = {"available": False, "observed_days": 0, "span_days": 0,
                "min_observed_days": 14, "min_span_days": 21, "fit_days": min(fit_days, 30)}
    if observed.empty:
        return {**metadata, "reason": "Keine Gewichtsmessungen verfügbar."}
    groups = observed.index.to_series().diff().dt.days.gt(8).cumsum()
    segment = observed.loc[groups == groups.iloc[-1]]
    end = segment.index[-1]
    window = segment[segment.index > end - pd.Timedelta(days=metadata["fit_days"])]
    span = (window.index[-1] - window.index[0]).days if len(window) else 0
    metadata.update(from_date=end.date().isoformat(), observed_days=len(window), span_days=span)
    if len(window) < 14 or span < 21:
        return {**metadata, "reason": "Fortschreibung pausiert: mindestens 14 Messtage über 21 verstrichene Tage im letzten 30-Tage-Fenster erforderlich; Neustart nach mehr als 7 fehlenden Tagen."}
    return {**metadata, **_forecast(segment.ewm(span=10).mean(), horizon, metadata["fit_days"], 2),
            "available": True}


def composition_forecast(horizon: int = 30, fit_days: int = 30) -> dict:
    """Composition scenarios anchored to extrapolated weight and BIA-derived mass.
    The assumed fraction p allocates weight change to fat-free mass; the remainder
    goes to fat. The 0.15 scenario is an assumption, not a personalized expectation.
    The BIA-derived fraction is clipped to [0, 0.46], not an uncertainty bound.
    These scenarios do not measure or predict muscle change independently.
    """
    # Both scenarios and standalone weight projection share weight and anchor date.
    mass = _paired_mass()
    if mass.empty:
        return {"available": False, "reason": "Keine gemeinsamen Gewicht- und Körperfettmessungen verfügbar."}
    weight = _weight_daily()
    if mass.index[-1] != weight.last_valid_index() or pd.isna(mass.ffm.iloc[-1]):
        return {"available": False, "reason": "Szenarien pausiert: keine ausreichend belegte Körperzusammensetzung am letzten Gewichtsdatum."}
    paired_weight = weight.reindex(mass.index)
    coverage = _guarded_forecast(paired_weight, horizon, fit_days)
    wf = weight_forecast(horizon, fit_days)
    if not coverage.get("available") or not wf.get("available"):
        unavailable = coverage if not coverage.get("available") else wf
        return {**unavailable, "reason": "Szenarien pausiert: gemeinsame Messbasis reicht noch nicht für die Gewichtsfortschreibung."}
    end = pd.Timestamp(wf["from_date"])
    groups = paired_weight.index.to_series().diff().dt.days.gt(8).cumsum()
    segment_dates = paired_weight.loc[groups == groups.iloc[-1]].index
    lm = mass.loc[mass.index.intersection(segment_dates)].dropna()
    sW = wf["slope_per_day"]
    a = lm.iloc[-1]
    # Anchor mass partitions to the same EWMA weight used by this forecast.
    W0 = float(wf["current"])
    FAT0 = W0 * float(a["bf"]) / 100
    FFM0 = W0 - FAT0
    if W0 <= 0:
        return {}
    BF0 = round(FAT0 / W0 * 100, 1)

    # Observed fraction from smoothed BIA-derived fat-free mass, used only as a scenario.
    s = lm.ffm[lm.index > end - pd.Timedelta(days=wf["fit_days"])]
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
        "available": True,
        "from_date": wf["from_date"],
        "weight": {"current": wf["current"], "projected": wf["projected"], "per_month": wf["per_month"]},
        "anchor": {"weight": round(W0, 1), "bf_pct": BF0, "fat": round(FAT0, 1), "ffm": round(FFM0, 1)},
        "scenarios": [
            scn(0.0, "preserved", "Fettfreie Masse konstant"),
            scn(0.15, "expected", "Annahme: 15 % fettfreie Masse"),
            scn(p_hi, "trend", "BIA-Trendszenario", "Aus geglätteten BIA-Werten; Anteil auf 0–46 % begrenzt"),
        ],
        "p_obs": round(p_obs, 2),
        "note": "Modellszenarien, keine gesicherte Prognose. Fettfreie Masse ist nicht Muskelmasse; BIA wird unter anderem durch den Wasserhaushalt beeinflusst.",
    }


def bodyfat_forecast(horizon: int = 30, fit_days: int = 30) -> dict:
    """Body-fat scenario for Coach/Snapshot/MCP, assuming p=0.15.
    This is a weight-anchored assumption, not a personalized expected outcome."""
    cf = composition_forecast(horizon, fit_days)
    if not cf.get("available"):
        return cf
    cur = cf["anchor"]["bf_pct"]
    exp = next((s for s in cf["scenarios"] if s["key"] == "expected"), None)
    if cur is None or exp is None or exp["bf_pct"] is None:
        return {}
    proj = exp["bf_pct"]
    return {
        "available": True,
        "current": cur, "projected": proj,
        "per_week": round((proj - cur) * 7.0 / horizon, 1),
        "per_month": round((proj - cur) * 30.0 / horizon, 1),
        "horizon_days": int(horizon),
        "from_date": cf["from_date"],
        "note": cf["note"],
        "scenarios": cf["scenarios"],
    }


def summary() -> dict:
    s = _weight_daily()
    bf = _read(
        "SELECT measured_at, body_fat_pct FROM body_measurements WHERE body_fat_pct IS NOT NULL "
        "ORDER BY measured_at DESC LIMIT 1", parse_dates=["measured_at"],
    )
    avg7 = s.rolling(7, min_periods=1).mean() if not s.empty else pd.Series(dtype=float)
    latest_date = s.last_valid_index()
    previous_date = latest_date - pd.Timedelta(days=7) if latest_date is not None else None
    latest_avg7 = avg7.get(latest_date)
    prev_avg7 = avg7.get(previous_date)
    latest_avg7 = float(latest_avg7) if latest_avg7 is not None and np.isfinite(latest_avg7) else None
    prev_avg7 = float(prev_avg7) if prev_avg7 is not None and np.isfinite(prev_avg7) else None
    counts = s.rolling(7, min_periods=1).count()
    return {
        "weight_kg": round(float(s.loc[latest_date]), 1) if latest_date is not None else None,
        "weight_date": latest_date.date().isoformat() if latest_date is not None else None,
        "weight_days7": int(counts.get(latest_date, 0)),
        "previous_weight_days7": int(counts.get(previous_date, 0)),
        "weight_avg7": round(latest_avg7, 1) if latest_avg7 is not None else None,
        "weight_delta7": round(latest_avg7 - prev_avg7, 2) if latest_avg7 is not None and prev_avg7 is not None else None,
        "body_fat_pct": round(float(bf["body_fat_pct"].iloc[0]), 1) if not bf.empty else None,
        "tdee": adaptive_tdee().get("tdee"),
    }
