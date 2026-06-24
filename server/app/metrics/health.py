"""Allgemeine Gesundheits-/Aktivitätsmetriken: Schritte (Health Connect) + Radfahren.

exercise_type 4 = Radfahren (android.health.connect ExerciseSessionType BIKING; verifiziert
über App-Attribution Samsung Health + Distanz-/Speed-Profil). Reine Funktionen über die DB —
speisen wie alle Metriken REST + Coach + MCP."""
from __future__ import annotations

import pandas as pd

from ..db import engine

BIKE = 4


def _read(sql: str, **kw) -> pd.DataFrame:
    with engine.connect() as con:
        return pd.read_sql(sql, con, **kw)


# ---------------- Schritte ----------------
def _steps() -> pd.DataFrame:
    df = _read("SELECT day, steps FROM steps_daily ORDER BY day", parse_dates=["day"])
    return df.sort_values("day") if not df.empty else df


def steps_trend(days: int = 30) -> list[dict]:
    """Tagesschritte + 7-Tage-Mittel (kalenderbasiert, lückenfest) der letzten N Tage."""
    df = _steps()
    if df.empty:
        return []
    s = df.set_index("day")["steps"].sort_index()
    avg = s.rolling("7D").mean()  # gleitendes 7-Kalendertage-Fenster (überspringt fehlende Tage)
    cutoff = s.index.max() - pd.Timedelta(days=days)
    return [
        {"date": d.date().isoformat(), "steps": int(v), "avg7": int(round(a))}
        for d, v, a in zip(s.index, s.to_numpy(), avg.to_numpy()) if d >= cutoff
    ]


def steps_weekly(weeks: int = 12) -> list[dict]:
    """Wochensumme der Schritte (schneller Trendüberblick)."""
    df = _steps()
    if df.empty:
        return []
    s = df.set_index("day")["steps"].resample("W-SUN").sum()
    s = s[s > 0].tail(weeks)
    return [{"week": d.date().isoformat(), "steps": int(v)} for d, v in s.items()]


def steps_summary() -> dict:
    df = _steps()
    if df.empty:
        return {"last": None, "last_day": None, "avg7": None, "avg30": None, "best": None, "total_days": 0}
    s = df.set_index("day")["steps"].sort_index()
    last_day = s.index.max()
    w7 = s[s.index > last_day - pd.Timedelta(days=7)]    # letzte 7 Kalendertage (nicht 7 Zeilen)
    w30 = s[s.index > last_day - pd.Timedelta(days=30)]  # letzte 30 Kalendertage
    return {
        "last": int(s.iloc[-1]),
        "last_day": last_day.date().isoformat(),
        "avg7": int(round(w7.mean())),
        "avg30": int(round(w30.mean())),
        "best": int(s.max()),
        "total_days": int(len(s)),
    }


# ---------------- Radfahren ----------------
def _rides() -> pd.DataFrame:
    df = _read(
        "SELECT started_at, ended_at, distance_km FROM exercise_sessions "
        f"WHERE exercise_type = {BIKE}",
        parse_dates=["started_at", "ended_at"],
    )
    if df.empty:
        return df
    df = df.dropna(subset=["started_at"]).copy()
    df["dur_min"] = (df["ended_at"] - df["started_at"]).dt.total_seconds() / 60
    df["distance_km"] = df["distance_km"].fillna(0.0)
    # plausible Fahrten (GPS-Rauschen / Geister-Sessions aussortieren)
    df = df[(df["distance_km"] >= 0.2) & (df["distance_km"] <= 300)
            & (df["dur_min"] > 2) & (df["dur_min"] < 600)].copy()
    df["speed"] = df["distance_km"] / (df["dur_min"] / 60)  # km/h
    return df[(df["speed"] >= 4) & (df["speed"] <= 60)].copy()


def cycling_weekly(weeks: int = 12) -> list[dict]:
    """Wochen-Radvolumen (km) + Anzahl Fahrten der letzten N Wochen."""
    df = _rides()
    if df.empty:
        return []
    df["week"] = df["started_at"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())
    g = df.groupby("week").agg(km=("distance_km", "sum"), rides=("distance_km", "size")).reset_index()
    g = g.sort_values("week").tail(weeks)
    return [
        {"week": w.isoformat(), "km": round(float(km), 1), "rides": int(n)}
        for w, km, n in zip(g["week"], g["km"], g["rides"])
    ]


def cycling_recent(limit: int = 8) -> list[dict]:
    """Letzte Fahrten (Datum, km, Dauer, Ø-Speed)."""
    df = _rides()
    if df.empty:
        return []
    df = df.sort_values("started_at", ascending=False).head(limit)
    return [
        {"date": s.isoformat(), "km": round(float(k), 1), "dur_min": int(round(d)), "speed": round(float(v), 1)}
        for s, k, d, v in zip(df["started_at"], df["distance_km"], df["dur_min"], df["speed"])
    ]


def cycling_summary() -> dict:
    """Rad-Eckdaten. km_30d ist bewusst *heute*-relativ (rollendes Fenster), nicht ab letzter
    Fahrt — so zeigt es ehrlich an, wenn gerade eine Rad-Pause ist."""
    df = _rides()
    if df.empty:
        return {"total_km": 0.0, "rides": 0, "km_30d": 0.0, "avg_speed": None, "last_day": None}
    now = pd.Timestamp.now()
    total_min = float(df["dur_min"].sum())
    return {
        "total_km": round(float(df["distance_km"].sum()), 1),
        "rides": int(len(df)),
        "km_30d": round(float(df[df["started_at"] >= now - pd.Timedelta(days=30)]["distance_km"].sum()), 1),
        "avg_speed": round(float(df["distance_km"].sum() / (total_min / 60)), 1) if total_min else None,
        "last_day": df["started_at"].max().date().isoformat(),
    }


def overview() -> dict:
    """Allgemeine Gesundheitswerte gebündelt (Schritte + Radfahren)."""
    return {"steps": steps_summary(), "cycling": cycling_summary()}
