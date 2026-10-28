"""Körper-Metriken (ARCHITECTURE.md §5.1): EWMA-Gewicht, Körperfett-Trend, adaptives TDEE.
Reine Funktionen über die DB (kein Web/LLM). Speisen REST + Coach + MCP."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import text

from ..config import settings
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
    """Daily weight, EWMA (span 10), mean of the last seven calendar days, the target corridor
    of the weight phase (`band_low/band_high/phase`, only from a phase start) and the local rate
    tube (`fit/rate_pct/rate_ci/zone/sure/edge`, see weight_phase.rate_series)."""
    from . import weight_phase
    s = _weight_daily()
    if s.empty:
        return []
    ewma = s.interpolate().ewm(span=10).mean()
    avg7 = s.rolling(7, min_periods=1).mean()
    band = weight_phase.corridor(avg7)
    tube = weight_phase.rate_series(s)
    cutoff = s.index.max() - pd.Timedelta(days=days)
    out = []
    for d in s.index:
        if d < cutoff:
            continue
        low, high, phase = band.get(d, (None, None, None))
        out.append({
            "date": d.date().isoformat(),
            "weight": None if pd.isna(s[d]) else round(float(s[d]), 2),
            "ewma": round(float(ewma[d]), 2),
            "avg7": None if pd.isna(avg7[d]) else round(float(avg7[d]), 2),
            "band_low": low,
            "band_high": high,
            "phase": phase,
            **(tube.get(d) or {"fit": None, "rate_pct": None, "rate_ci": None, "zone": None, "sure": None, "edge": None}),
        })
    return out


def adaptive_tdee(window_days: int = 14, smooth_days: int = 14) -> dict:
    """Verbrauch aus dem lernenden Modell (`expenditure`): typischer Tag (Ø Essen und Bewegung der letzten
    14 Tage) mit Unsicherheit, Zerlegung und heute. `window_days`/`smooth_days` bleiben nur für alte Aufrufer."""
    from . import expenditure
    w, i = _weight_daily().dropna(), _intake_daily().dropna()
    if w.empty or i.empty:
        return {"tdee": None, "reason": "Gewicht oder Intake fehlt"}
    last_data = max(w.index.max(), i.index.max()).date()
    rows = expenditure.model(until=min(datetime.now(ZoneInfo(settings.timezone)).date(), last_data + timedelta(days=1)))
    if not rows:
        return {"tdee": None, "reason": "Gewicht oder Intake fehlt"}
    # Der heutige Tag ist beim Essen unvollständig: Stand und Mittel vom letzten vollen Tag, heute nur als Zusatz.
    last, now = (rows[-2], rows[-1]) if len(rows) > 1 else (rows[-1], rows[-1])
    wavg = _weight_daily().rolling(7, min_periods=3).mean().dropna()
    wc = None
    if not wavg.empty:
        ref = wavg[wavg.index <= wavg.index.max() - pd.Timedelta(days=smooth_days)]
        if not ref.empty:
            wc = round(float(wavg.iloc[-1] - ref.iloc[-1]), 2)
    born = settings.birth_date
    age = (date.fromisoformat(last["date"]) - born).days / 365.25 if born else None
    from . import composition
    resting, resting_method = expenditure.resting_kcal(last["weight_trend"], settings.body_height_cm, age,
                                                       composition.current_ffm())
    learned_days = sum(r["observed"] for r in rows)
    return {
        "tdee": last["expenditure"],
        "tdee_sd": last["expenditure_sd"],
        "from_date": last["date"],
        "avg_intake": last["intake_avg"],
        "deficit_per_day": last["expenditure"] - last["intake_avg"],
        "weight_change_kg": wc,
        "weight_trend": last["weight_trend"],
        "window_days": int(window_days),
        "smooth_days": int(smooth_days),
        "intake_days": int(sum(r["intake"] is not None for r in rows[-expenditure.AVG_DAYS - 1:-1] or rows)),
        "estimate_days": learned_days,
        "provisional": learned_days < 28,
        "parts": {"base": last["base"], "tef": last["tef"], "active": last["active_avg"],
                  "resting": round(resting) if resting else None,
                  "unmeasured": round(last["base"] - resting) if resting else None,
                  "resting_method": resting_method},
        "model": {"rho": expenditure.RHO, "tef": expenditure.TEF, "since": rows[0]["date"]},
        "today": now["date"],
        "active_kcal_today": now["active_day"],
        "tdee_base": last["base"] + last["tef"],
        "tdee_today": now["expenditure_day"],
        "intake_today": now["intake"],
        # Prognose für den ganzen Tag: Grundverbrauch + typische Verdauung + Bewegung (bisher, mindestens typisch)
        "tdee_forecast": last["base"] + last["tef"] + max(now["active_day"], last["active_avg"]),
        "active_avg": last["active_avg"],
        "intake_today_last": _last_meal_today(now["date"]),
    }


def _last_meal_today(day: str) -> str | None:
    """Uhrzeit (HH:MM) des letzten Esseintrags an `day` — zeigt, wie aktuell „gegessen“ ist."""
    df = _read(text("SELECT MAX(eaten_at) AS t FROM nutrition_entries WHERE date(eaten_at) = :d"), params={"d": day})
    t = None if df.empty else df["t"].iloc[0]
    return None if t is None or pd.isna(t) else str(t)[11:16]


def tdee_trend(window_days: int = 14, days: int = 180, smooth_days: int = 14,
               min_intake_days: int = 7) -> list[dict]:
    """Verbrauch je Tag aus dem Modell: `tdee` = dieser Tag, `tdee_avg` = typischer Tag (± `tdee_sd`).
    Nur Tage mit Esseintrag; Fenster-Parameter bleiben für alte Aufrufer."""
    from . import expenditure
    rows = [r for r in expenditure.model() if r["intake"] is not None]
    if not rows:
        return []
    cutoff = pd.Timestamp(rows[-1]["date"]) - pd.Timedelta(days=days)
    return [{"date": r["date"], "tdee": r["expenditure_day"], "tdee_avg": r["expenditure"], "tdee_sd": r["expenditure_sd"],
             "intake": r["intake"], "intake_avg": r["intake_avg"], "estimate_days": expenditure.AVG_DAYS}
            for r in rows if pd.Timestamp(r["date"]) >= cutoff]


def _window_tdee_trend(window_days: int = 14, days: int = 180, smooth_days: int = 14,
                       min_intake_days: int = 7) -> list[dict]:
    """Altes Verfahren (bis 2026-10-27), nur noch für `scripts/backtest_expenditure.py`.
    Rollendes adaptives TDEE je Tag (`tdee`) + geglättetes `tdee_avg` (rollendes
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


def summary() -> dict:
    s = _weight_daily()
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
        "tdee": adaptive_tdee().get("tdee"),
    }
