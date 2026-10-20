"""Rad-Kennzahlen aus Indoor-Fahrten (Zwift/Rolle, Tabelle garmin_indoor_rides).

eFTP von Milon: 95 % der besten 20 min der letzten 90 Tage, ohne 20-min-Wert 95 % der Critical
Power aus einem Fit über die Leistungskurve (2–20 min); ohne brauchbare Fahrt Garmins FTP
(Startwert); BIKE_FTP > 0 übersteuert. Leistungszonen nach Coggan (55/75/90/105/120/150 % eFTP),
NP/IF/TSS je Fahrt selbst berechnet (Garmin liefert kein TSS/IF), W/kg mit dem 7-Tage-Gewicht.

EHRLICHE STATISTIK (wie Laufen, stats.py): Urteile „werde ich besser?“ nur auf Fahrt-Ebene
(Puls bei Referenzleistung, Effizienz NP/HF) — geglättete Serien sind reine Anzeige. Puls-
Kennzahlen nutzen nur Fahrten mit hr_valid. Watt-TSS wird NIE mit Lauflast verrechnet."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import inspect

from .. import garmin_indoor
from ..config import settings
from ..db import engine
from . import stats

EFTP_WINDOW_DAYS = 90
EFTP_FACTOR = 0.95
COGGAN = (0.55, 0.75, 0.90, 1.05, 1.20, 1.50)  # Obergrenzen Z1–Z6 als Anteil der eFTP; Z7 darüber
ZONE_NAMES = ("Aktive Erholung", "Grundlage", "Tempo", "Schwelle", "VO2max", "Anaerob", "Neuromuskulär")
STEADY_VI = 1.08          # Variabilitätsindex NP/Ø-Leistung, bis zu dem eine Fahrt als gleichmäßig gilt
DECOUPLING_MIN_S = 1200   # Mindestlänge nach dem Abschneiden von Ein-/Ausfahren
_COLUMNS = ("activity_id", "activity_type", "title", "world", "route", "started_at", "duration_seconds",
            "elapsed_duration_seconds", "distance_km", "elevation_gain_m", "avg_power_w", "norm_power_w",
            "max_power_w", "work_kj", "avg_cadence_rpm", "avg_hr", "max_hr", "hr_dropout", "hr_valid",
            "aerobic_te", "anaerobic_te", "training_load", "power_curve_json", "power_zones_json",
            "hr_zones_json")


def _clean(value):
    """Strictly JSON-safe: NaN/inf → None, numpy scalars → Python."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _r(value, digits: int = 1):
    if value is None or (isinstance(value, float) and not math.isfinite(value)) or pd.isna(value):
        return None
    return round(float(value), digits)


def _today(today: date | None) -> date:
    return today or datetime.now(ZoneInfo(settings.timezone)).date()


def indoor_rides(include_series: bool = False) -> pd.DataFrame:
    """Alle Indoor-Fahrten als DataFrame (Lese-API für Rad-Seite, TRIMP, Wochenbilanz):
    started_at (naiv lokal), duration/elapsed (s), distance_km, elevation_gain_m, avg/norm/max_power_w,
    work_kj, avg_cadence_rpm, avg/max_hr, hr_valid, Trainingseffekt/-last, world/route,
    power_curve {Sekunden: Watt}, power_zones/hr_zones (Garmin-Sekunden je Zone), optional series."""
    columns = list(_COLUMNS) + (["series_json"] if include_series else [])
    with engine.connect() as con:
        if not inspect(con).has_table("garmin_indoor_rides"):
            return pd.DataFrame(columns=[c.removesuffix("_json") for c in columns] + ["day"])
        df = pd.read_sql(f"SELECT {', '.join(columns)} FROM garmin_indoor_rides ORDER BY started_at",
                         con, parse_dates=["started_at"])
    df["power_curve"] = df.pop("power_curve_json").map(
        lambda s: {int(k): float(v) for k, v in json.loads(s or "{}").items()})
    df["power_zones"] = df.pop("power_zones_json").map(lambda s: json.loads(s or "[]"))
    df["hr_zones"] = df.pop("hr_zones_json").map(lambda s: json.loads(s or "[]"))
    if include_series:
        df["series"] = df.pop("series_json").map(lambda s: json.loads(s or "{}"))
    df["hr_valid"] = df["hr_valid"].astype(bool)
    df["day"] = df["started_at"].dt.date
    return df


def _usable(df: pd.DataFrame) -> pd.DataFrame:
    """Fahrten mit Leistungsmessung (Uhr-Fahrten ohne Watt zählen für keine Watt-Kennzahl)."""
    if df.empty:
        return df
    return df[(df["avg_power_w"].fillna(0) > 0) & df["power_curve"].map(bool)]


def _best_curve(df: pd.DataFrame) -> dict[int, float]:
    best: dict[int, float] = {}
    for curve in df["power_curve"]:
        for seconds, watts in curve.items():
            if watts > best.get(seconds, 0):
                best[seconds] = watts
    return best


def _cp_fit(curve: dict[int, float]) -> float | None:
    """Critical Power aus Arbeit = W' + CP·t über die Kurvenpunkte 2–20 min (ohne 20 min)."""
    points = [(t, p) for t, p in curve.items() if 120 <= t < 1200 and p > 0]
    if len(points) < 2:
        return None
    t = np.array([p[0] for p in points], float)
    work = np.array([p[0] * p[1] for p in points], float)
    slope = float(np.polyfit(t, work, 1)[0])
    return slope if slope > 0 else None


def _auto_eftp(power: pd.DataFrame, day: date, garmin_ftp: float | None) -> tuple[float | None, str | None]:
    window = power[(power["day"] > day - timedelta(days=EFTP_WINDOW_DAYS)) & (power["day"] <= day)] \
        if not power.empty else power
    if not window.empty:
        curve = _best_curve(window)
        if curve.get(1200):
            return EFTP_FACTOR * curve[1200], "20min"
        cp = _cp_fit(curve)
        if cp is not None:
            return EFTP_FACTOR * cp, "fit"
    if garmin_ftp:
        return garmin_ftp, "garmin"
    return None, None


def _eftp_at(power: pd.DataFrame, day: date, garmin_ftp: float | None) -> tuple[float | None, str | None]:
    if settings.bike_ftp and settings.bike_ftp > 0:
        return float(settings.bike_ftp), "setting"
    return _auto_eftp(power, day, garmin_ftp)


def _weights() -> pd.Series:
    from . import body  # lazy: Körperdaten nur für W/kg
    s = body._weight_daily()
    return s.rolling(7, min_periods=1).mean().dropna() if not s.empty else s


def _weight_at(weights: pd.Series, day: date) -> float | None:
    if weights.empty:
        return None
    upto = weights[weights.index <= pd.Timestamp(day)]
    return float(upto.iloc[-1]) if not upto.empty else None


def _with_load(df: pd.DataFrame) -> pd.DataFrame:
    """Je Fahrt: eFTP am Fahrttag (inkl. der Fahrt), IF = NP/eFTP, TSS = s·NP·IF/(eFTP·3600)·100."""
    df = df.copy()
    if df.empty:
        for col in ("eftp", "intensity", "tss"):
            df[col] = pd.Series(dtype=float)
        return df
    power, garmin_ftp = _usable(df), garmin_indoor.garmin_ftp()
    cache: dict[date, float | None] = {}
    for day in df["day"].unique():
        cache[day] = _eftp_at(power, day, garmin_ftp)[0]
    df["eftp"] = df["day"].map(cache).astype(float)
    norm = df["norm_power_w"].astype(float)
    df["intensity"] = norm / df["eftp"]
    df["tss"] = df["duration_seconds"].astype(float) * norm * df["intensity"] / (df["eftp"] * 3600) * 100
    return df


def _ride_row(r) -> dict:
    return {
        "activity_id": r["activity_id"], "type": r["activity_type"], "title": r["title"],
        "world": r["world"], "route": r["route"], "date": r["started_at"].isoformat(),
        "minutes": _r((r["duration_seconds"] or 0) / 60, 1), "km": _r(r["distance_km"], 1),
        "elevation_m": _r(r["elevation_gain_m"], 0), "avg_power": _r(r["avg_power_w"], 0),
        "np": _r(r["norm_power_w"], 0), "max_power": _r(r["max_power_w"], 0), "kj": _r(r["work_kj"], 0),
        "cadence": _r(r["avg_cadence_rpm"], 0), "avg_hr": _r(r["avg_hr"], 0), "max_hr": _r(r["max_hr"], 0),
        "hr_valid": bool(r["hr_valid"]), "eftp": _r(r.get("eftp"), 0), "if": _r(r.get("intensity"), 2),
        "tss": _r(r.get("tss"), 0), "aerobic_te": _r(r["aerobic_te"], 1),
        "anaerobic_te": _r(r["anaerobic_te"], 1), "training_load": _r(r["training_load"], 0),
    }


# ---------------- eFTP ----------------
def eftp(weeks: int = 26, today: date | None = None) -> dict:
    """Aktuelle eFTP (+ Quelle, W/kg) und Wochenverlauf der automatischen eFTP (Wochenende, 90-T-Fenster)."""
    today = _today(today)
    df = indoor_rides()
    power, garmin_ftp = _usable(df), garmin_indoor.garmin_ftp()
    value, source = _eftp_at(power, today, garmin_ftp)
    weight = _weight_at(_weights(), today)
    series = []
    if not df.empty:
        first = max(df["day"].min(), today - timedelta(weeks=weeks))
        for period in pd.period_range(first, today, freq="W-SUN"):
            end = min(period.end_time.date(), today)
            auto, auto_source = _auto_eftp(power, end, garmin_ftp)
            series.append({"week": period.start_time.date().isoformat(), "eftp": _r(auto, 0),
                           "source": auto_source})
    return _clean({
        "value": _r(value, 0), "source": source,
        "wkg": _r(value / weight, 2) if value and weight else None, "weight_kg": _r(weight, 1),
        "garmin_ftp": _r(garmin_ftp, 0), "setting": _r(settings.bike_ftp, 0),
        "window_days": EFTP_WINDOW_DAYS, "factor": EFTP_FACTOR,
        "zones": _zone_bounds(value), "series": series,
        "caveat": "eFTP = 95 % der besten 20 min (90 T), sonst 95 % der Critical Power aus der "
                  "Leistungskurve, sonst Garmin-FTP. BIKE_FTP > 0 übersteuert.",
    })


def _zone_bounds(ftp: float | None) -> list[dict]:
    if not ftp:
        return []
    edges = (0.0, *COGGAN, None)
    return [{"zone": i + 1, "name": ZONE_NAMES[i], "lo_pct": round(edges[i] * 100),
             "hi_pct": round(edges[i + 1] * 100) if edges[i + 1] is not None else None,
             "lo_w": round(edges[i] * ftp), "hi_w": round(edges[i + 1] * ftp) if edges[i + 1] is not None else None}
            for i in range(7)]


# ---------------- Übersicht / Fahrten ----------------
def summary(today: date | None = None) -> dict:
    today = _today(today)
    df = _with_load(indoor_rides())
    current = eftp(today=today)
    if df.empty:
        return _clean({"rides": 0, "rides_with_power": 0, "hours": 0.0, "km": 0.0, "elevation_m": 0,
                       "kj": 0.0, "rides_30d": 0, "hours_30d": 0.0, "tss_7d": 0.0, "tss_28d": 0.0,
                       "hr_valid_rides": 0, "eftp": current["value"], "eftp_source": current["source"],
                       "wkg": current["wkg"], "last_ride": None})
    df = df[df["day"] <= today]
    recent = df[df["day"] > today - timedelta(days=30)]
    last = df.iloc[-1] if not df.empty else None
    return _clean({
        "rides": int(len(df)), "rides_with_power": int(len(_usable(df))),
        "hours": _r(df["duration_seconds"].fillna(0).sum() / 3600, 1),
        "km": _r(df["distance_km"].fillna(0).sum(), 1),
        "elevation_m": _r(df["elevation_gain_m"].fillna(0).sum(), 0),
        "kj": _r(df["work_kj"].fillna(0).sum(), 0),
        "rides_30d": int(len(recent)), "hours_30d": _r(recent["duration_seconds"].fillna(0).sum() / 3600, 1),
        "tss_7d": _r(df[df["day"] > today - timedelta(days=7)]["tss"].fillna(0).sum(), 0),
        "tss_28d": _r(df[df["day"] > today - timedelta(days=28)]["tss"].fillna(0).sum(), 0),
        "hr_valid_rides": int(df["hr_valid"].sum()),
        "eftp": current["value"], "eftp_source": current["source"], "wkg": current["wkg"],
        "last_ride": _ride_row(last) if last is not None else None,
    })


def rides(limit: int = 20) -> list[dict]:
    df = _with_load(indoor_rides())
    if df.empty:
        return []
    df = df.sort_values("started_at", ascending=False)
    if limit > 0:
        df = df.head(limit)
    return _clean([_ride_row(r) for _, r in df.iterrows()])


def _zone_seconds(series: dict, ftp: float | None) -> list[float] | None:
    if not ftp or not series.get("power_w"):
        return None
    power = garmin_indoor.grid(series, "power_w")
    power = power[~np.isnan(power)]
    if not power.size:
        return None
    edges = [0.0] + [f * ftp for f in COGGAN] + [float("inf")]
    counts, _ = np.histogram(power, bins=edges)
    return [float(c) for c in counts]


def _display(series: dict, limit: int = 600) -> list[dict]:
    t = series.get("t") or []
    if not t:
        return []
    picks = sorted({round(i * (len(t) - 1) / max(1, limit - 1)) for i in range(min(limit, len(t)))})
    keys = [k for k in garmin_indoor.SERIES_KEYS if series.get(k)]
    return [{"t": t[i], **{k: series[k][i] for k in keys}} for i in picks]


def ride_detail(activity_id: str) -> dict | None:
    df = _with_load(indoor_rides(include_series=True))
    hit = df[df["activity_id"] == activity_id] if not df.empty else df
    if hit.empty:
        return None
    r = hit.iloc[0]
    seconds = _zone_seconds(r["series"], r["eftp"] if pd.notna(r["eftp"]) else None)
    return _clean({
        **_ride_row(r),
        "power_curve": [{"seconds": s, "watts": _r(w, 0)} for s, w in sorted(r["power_curve"].items())],
        "zones": [{**z, "seconds": seconds[i] if seconds else None}
                  for i, z in enumerate(_zone_bounds(r["eftp"] if pd.notna(r["eftp"]) else None))],
        "garmin_power_zones": r["power_zones"], "garmin_hr_zones": r["hr_zones"],
        "hr_dropout": _r(r["hr_dropout"], 3),
        "series": _display(r["series"]),
    })


# ---------------- Leistungskurve ----------------
def _label(seconds: int) -> str:
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min" if seconds < 3600 else f"{seconds // 3600} h"


def power_curve(today: date | None = None) -> dict:
    """Beste Leistung je Dauer: letzte 90 T vs. die 90 T davor, plus Allzeit-Bestwert mit Datum."""
    today = _today(today)
    power = _usable(indoor_rides())
    if power.empty:
        return {"window_days": EFTP_WINDOW_DAYS, "durations": []}
    recent = power[power["day"] > today - timedelta(days=EFTP_WINDOW_DAYS)]
    previous = power[(power["day"] <= today - timedelta(days=EFTP_WINDOW_DAYS))
                     & (power["day"] > today - timedelta(days=2 * EFTP_WINDOW_DAYS))]
    rc, pc = _best_curve(recent) if not recent.empty else {}, _best_curve(previous) if not previous.empty else {}
    durations = sorted({s for curve in power["power_curve"] for s in curve})
    rows = []
    for seconds in durations:
        best, best_day = None, None
        for curve, day in zip(power["power_curve"], power["day"]):
            if seconds in curve and (best is None or curve[seconds] > best):
                best, best_day = curve[seconds], day
        rows.append({"seconds": seconds, "label": _label(seconds), "recent": _r(rc.get(seconds), 0),
                     "previous": _r(pc.get(seconds), 0), "best": _r(best, 0),
                     "best_date": best_day.isoformat() if best_day else None})
    return _clean({"window_days": EFTP_WINDOW_DAYS, "durations": rows})


# ---------------- „Werde ich besser?“ ----------------
def _hr_rides() -> pd.DataFrame:
    df = indoor_rides()
    if df.empty:
        return df
    df = df[df["hr_valid"] & df["avg_hr"].notna()].copy()
    df["p"] = df["norm_power_w"].fillna(df["avg_power_w"])
    return df[df["p"].fillna(0) > 0].sort_values("started_at")


def hr_at_power(ref_power: int | None = None, alpha: float = 0.25) -> dict:
    """„Welcher Puls bei X Watt?“ — Fahrt-Level-Modell HF = a + b·P + c·Tage (P = NP, sonst Ø-Leistung)
    über alle Fahrten mit gültigem Puls. c < 0 signifikant (95 %-CI, n ≥ 8) und b > 0 ⇒ „besser“.
    Anzeige: je Fahrt auf die Referenzleistung korrigierter Puls + EWMA (nur Anzeige)."""
    df = _hr_rides()
    if df.empty or len(df) < 6:
        return {"trend": {"verdict": "wenig_daten", "label": "zu wenig Daten", "n": int(len(df))}, "series": []}
    if ref_power is None:
        ref_power = int(round(float(df["p"].median()) / 5) * 5)
    t_days = (df["started_at"] - df["started_at"].min()).dt.total_seconds().to_numpy() / 86_400
    p, hr = df["p"].to_numpy(float), df["avg_hr"].to_numpy(float)
    trend: dict = {"verdict": "wenig_daten", "label": "zu wenig Daten", "n": int(len(df))}
    fit = stats.ols(np.column_stack([np.ones(len(df)), p, t_days]), hr)
    series: list[dict] = []
    if fit is not None and p.max() - p.min() >= 15:
        beta, se, dof, r2 = fit
        b_p, c_t = float(beta[1]), float(beta[2])
        span = float(t_days.max() - t_days.min())
        if b_p <= 0:
            trend = {"verdict": "unklar", "label": "Puls-Leistungs-Zusammenhang zu schwach (Steigung ≤ 0)",
                     "n": int(len(df)), "r2": round(r2, 2)}
        else:
            significant = bool(len(df) >= 8 and abs(c_t) > stats.t95(dof) * float(se[2]))
            trend = {
                "verdict": ("besser" if c_t < 0 else "schlechter") if significant else "unklar",
                "label": "signifikanter Trend (95 %)" if significant else "kein belastbarer Trend",
                "significant": significant, "n": int(len(df)), "days": round(span), "r2": round(r2, 2),
                "delta_bpm": round(c_t * span, 1), "bpm_per_month": round(c_t * 30, 2),
                "bpm_per_watt": round(b_p, 3),
            }
            adjusted = pd.Series(hr - b_p * (p - ref_power), index=df.index)
            smooth = adjusted.ewm(alpha=alpha).mean()
            series = [{"date": d.date().isoformat(), "activity_id": a, "hr": round(float(h), 1),
                       "smooth": round(float(s), 1)}
                      for d, a, h, s in zip(df["started_at"], df["activity_id"], adjusted, smooth)]
    return _clean({
        "ref_power": ref_power, "series": series, "trend": trend,
        "current": series[-1]["smooth"] if series else None,
        "caveat": "Ø-Werte je Fahrt; Temperatur/Tagesform nicht kontrolliert. Urteil aus dem "
                  "Fahrt-Level-Modell (HF ~ Leistung + Zeit), Kurve nur zur Anzeige.",
    })


def _decoupling(series: dict) -> tuple[float, float, float] | None:
    """Pw:HR-Entkopplung einer gleichmäßigen Fahrt: Ein-/Ausfahren (je max(5 min, 10 %)) abgeschnitten,
    Rest ≥ 20 min, VI ≤ 1,08. Liefert (Entkopplung %, VI, Minuten) oder None."""
    if not series.get("power_w") or not series.get("hr_bpm"):
        return None
    power, hr = garmin_indoor.grid(series, "power_w"), garmin_indoor.grid(series, "hr_bpm")
    trim = max(300, int(0.1 * power.size))
    power, hr = power[trim:power.size - trim], hr[trim:hr.size - trim]
    if power.size < DECOUPLING_MIN_S:
        return None
    both = ~np.isnan(power) & ~np.isnan(hr) & (power > 0)
    if both.mean() < 0.8:
        return None
    avg = float(np.nanmean(power))
    norm = garmin_indoor.normalized_power(power)
    if not avg or norm is None or norm / avg > STEADY_VI:
        return None
    half = power.size // 2
    first, second = both[:half], both[half:]
    ef1 = power[:half][first].mean() / hr[:half][first].mean()
    ef2 = power[half:][second].mean() / hr[half:][second].mean()
    return (ef1 / ef2 - 1) * 100, norm / avg, power.size / 60


def efficiency(alpha: float = 0.25) -> dict:
    """Effizienz NP/HF (Watt je Herzschlag/min) je Fahrt + EWMA (α 0,25, nur Anzeige); Urteil aus der
    Fahrt-Level-Regression EF ~ Zeit. Dazu Pw:HR-Entkopplung gleichmäßiger Fahrten ≥ 20 min."""
    df = _hr_rides()
    result: dict = {"series": [], "current": None, "rides": 0,
                    "trend": {"verdict": "wenig_daten", "label": "zu wenig Daten", "n": 0}, "decoupling": []}
    if df.empty:
        return result
    df = df[df["norm_power_w"].notna()].copy()
    if len(df) >= 4:
        df["ef"] = df["norm_power_w"] / df["avg_hr"]
        smooth = df["ef"].ewm(alpha=alpha).mean()
        xs = ((df["started_at"] - df["started_at"].min()).dt.total_seconds() / 86_400).tolist()
        result.update({
            "series": [{"date": d.date().isoformat(), "activity_id": a, "ef": round(float(e), 3),
                        "smooth": round(float(s), 3)}
                       for d, a, e, s in zip(df["started_at"], df["activity_id"], df["ef"], smooth)],
            "current": round(float(smooth.iloc[-1]), 3), "rides": int(len(df)),
            "trend": stats.assess(stats.linear_trend(xs, df["ef"].tolist()), down_is_good=False),
        })
    with_series = indoor_rides(include_series=True)
    with_series = with_series[with_series["hr_valid"]] if not with_series.empty else with_series
    for _, r in with_series.iterrows():
        dec = _decoupling(r["series"])
        if dec is not None:
            result["decoupling"].append({"date": r["started_at"].date().isoformat(), "activity_id": r["activity_id"],
                                         "title": r["title"], "decoupling_pct": round(dec[0], 1),
                                         "vi": round(dec[1], 3), "minutes": round(dec[2])})
    result["caveat"] = ("EF = NP/Ø-HF je Fahrt (nur Fahrten mit gültigem Puls); Urteil aus Einzel-Fahrten, "
                        "EWMA-Kurve nur zur Anzeige. Entkopplung < 5 % = stabile aerobe Basis.")
    return _clean(result)


# ---------------- Zonen / Welten ----------------
def zones(weeks: int = 12, today: date | None = None) -> dict:
    """Zeit in Coggan-Zonen je Woche (aus der Sekunden-Serie, eFTP am Fahrttag)."""
    today = _today(today)
    df = _with_load(indoor_rides(include_series=True))
    current = eftp(today=today)
    out = {"eftp": current["value"], "source": current["source"], "zones": current["zones"],
           "weeks": [], "unzoned_rides": 0}
    if df.empty:
        return _clean(out)
    df = df[df["day"] > today - timedelta(weeks=weeks)]
    buckets: dict[date, dict] = {}
    for _, r in df.iterrows():
        seconds = _zone_seconds(r["series"], r["eftp"] if pd.notna(r["eftp"]) else None)
        if seconds is None:
            out["unzoned_rides"] += 1
            continue
        week = pd.Period(r["started_at"], freq="W-SUN").start_time.date()
        bucket = buckets.setdefault(week, {"seconds": [0.0] * 7, "rides": 0})
        bucket["seconds"] = [a + b for a, b in zip(bucket["seconds"], seconds)]
        bucket["rides"] += 1
    out["weeks"] = [{"week": w.isoformat(), "seconds": b["seconds"], "total": sum(b["seconds"]), "rides": b["rides"]}
                    for w, b in sorted(buckets.items())]
    return _clean(out)


def worlds() -> dict:
    """Zwift-Welten und -Routen: Fahrten, km, Höhenmeter, Stunden, zuletzt."""
    df = indoor_rides()
    if df.empty:
        return {"worlds": [], "other_rides": 0}
    named = df[df["world"].notna()]

    def agg(frame: pd.DataFrame) -> dict:
        return {"rides": int(len(frame)), "km": _r(frame["distance_km"].fillna(0).sum(), 1),
                "elevation_m": _r(frame["elevation_gain_m"].fillna(0).sum(), 0),
                "hours": _r(frame["duration_seconds"].fillna(0).sum() / 3600, 1),
                "last": frame["started_at"].max().date().isoformat()}

    result = []
    for world, frame in named.groupby("world"):
        routes = [{"route": route, **agg(part)} for route, part in frame.groupby(frame["route"].fillna("–"))]
        result.append({"world": world, **agg(frame),
                       "routes": sorted(routes, key=lambda x: (-x["rides"], x["route"]))})
    result.sort(key=lambda x: (-x["rides"], x["world"]))
    return _clean({"worlds": result, "other_rides": int(len(df) - len(named))})
