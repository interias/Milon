"""Lauf-Metriken (ARCHITECTURE.md §5.2): Wochenvolumen, Pace-Trend, VO2max-Trend.
exercise_type 33 = Laufen. Höhenmeter sind NICHT verfügbar (HC liefert keine)."""
from __future__ import annotations

import pandas as pd

from ..db import engine

RUN = 33


def _read(sql: str, **kw) -> pd.DataFrame:
    with engine.connect() as con:
        return pd.read_sql(sql, con, **kw)


def _runs() -> pd.DataFrame:
    df = _read(
        "SELECT started_at, ended_at, distance_km FROM exercise_sessions "
        f"WHERE exercise_type = {RUN}",
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
    return {
        "week_km": vol[-1]["km"] if vol else None,
        "week_runs": vol[-1]["runs"] if vol else None,
        "pace": pace[-1]["pace"] if pace else None,
        "vo2max": vo2[-1]["vo2"] if vo2 else None,
        "elevation": None,  # bewusst: Höhenmeter nicht verfügbar
    }
