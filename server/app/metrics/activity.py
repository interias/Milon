"""Bereichsübergreifende Aktivitäten (für die Übersicht): letzte Läufe + Kraft-Workouts,
Trainings-Konsistenz (Heatmap + Streak)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from ..config import settings
from ..db import engine
from . import running, strength

RUN = 33


def overview(now: datetime | None = None) -> dict:
    """Two calendar-day windows; steps averages only include observed days."""
    local_now = (now or datetime.now(ZoneInfo(settings.timezone))).astimezone(ZoneInfo(settings.timezone))
    today = local_now.date()
    current_start = today - timedelta(days=6)
    previous_start = current_start - timedelta(days=7)
    cutoff = pd.Timestamp(local_now.replace(tzinfo=None))
    runs = running._runs()
    with engine.connect() as con:
        workouts = pd.read_sql(
            "SELECT started_at FROM workouts WHERE source='hevy' AND started_at IS NOT NULL",
            con, parse_dates=["started_at"],
        )
        steps = pd.read_sql("SELECT day, steps FROM steps_daily", con, parse_dates=["day"])

    # Both HC and Hevy imports store naive local wall times.
    def selected(frame: pd.DataFrame, column: str, start: date, end: pd.Timestamp) -> pd.DataFrame:
        return frame[(frame[column] >= pd.Timestamp(start)) & (frame[column] < end)]

    boundary = pd.Timestamp(current_start)
    current_runs = selected(runs, "started_at", current_start, cutoff)
    previous_runs = selected(runs, "started_at", previous_start, boundary)
    current_workouts = selected(workouts, "started_at", current_start, cutoff)
    previous_workouts = selected(workouts, "started_at", previous_start, boundary)
    current_steps = selected(steps, "day", current_start, pd.Timestamp(today + timedelta(days=1)))
    previous_steps = selected(steps, "day", previous_start, boundary)

    def average(frame: pd.DataFrame) -> float | None:
        return round(float(frame["steps"].mean()), 1) if not frame.empty else None

    return {
        "from_date": current_start.isoformat(), "to_date": today.isoformat(),
        "previous_from_date": previous_start.isoformat(),
        "previous_to_date": (current_start - timedelta(days=1)).isoformat(),
        "running": {"current_km": round(float(current_runs["distance_km"].sum()), 1),
                    "previous_km": round(float(previous_runs["distance_km"].sum()), 1)},
        "strength": {"current_sessions": len(current_workouts), "previous_sessions": len(previous_workouts)},
        "steps": {"current_avg": average(current_steps), "previous_avg": average(previous_steps),
                  "current_days": len(current_steps), "previous_days": len(previous_steps)},
    }


def compare(days: int = 7) -> dict:
    """Rollender Vergleich „letzte N Tage" vs. „die N Tage davor" für Laufvolumen + Tonnage
    (fairer als Kalenderwoche). Schritte/Gewicht macht die Übersicht bereits rollend."""
    return {"days": days, "running": running.volume_window(days), "strength": strength.tonnage_window(days)}


def consistency(days: int = 140, step_goal: int = 10000) -> dict:
    """Tages-Heatmap der Trainingskonsistenz + aktuelle Streak. Level je Tag:
    3 = Kraft/Lauf, 2 = Schrittziel erreicht, 1 = halbes Schrittziel, 0 = nichts."""
    with engine.connect() as con:
        wo = pd.read_sql("SELECT started_at FROM workouts WHERE started_at IS NOT NULL", con, parse_dates=["started_at"])
        runs = pd.read_sql(f"SELECT started_at FROM exercise_sessions WHERE exercise_type={RUN}", con, parse_dates=["started_at"])
        steps = pd.read_sql("SELECT day, steps FROM steps_daily", con, parse_dates=["day"])

    trained: set[date] = set()
    for df in (wo, runs):
        if not df.empty:
            trained |= {t.date() for t in df["started_at"].dropna()}
    step_map: dict[date, int] = {}
    if not steps.empty:
        step_map = {d.date(): int(s) for d, s in zip(steps["day"], steps["steps"])}

    end = datetime.now(ZoneInfo(settings.timezone)).date()
    start = end - timedelta(days=days - 1)
    out: list[dict] = []
    for i in range(days):
        d = start + timedelta(days=i)
        is_train = d in trained
        st = step_map.get(d, 0)
        level = 3 if is_train else (2 if st >= step_goal else 1 if st >= step_goal / 2 else 0)
        out.append({"date": d.isoformat(), "level": level, "steps": st, "trained": is_train})

    rev = list(reversed(out))
    skip = 1 if (rev and rev[0]["level"] == 0) else 0  # heute evtl. noch nicht erfasst
    streak = 0
    for day in rev[skip:]:
        if day["level"] >= 1:
            streak += 1
        else:
            break
    return {
        "days": out,
        "streak": streak,
        "active_days": sum(1 for x in out if x["level"] >= 1),
        "trained_days": sum(1 for x in out if x["trained"]),
        "total": days,
        "step_goal": step_goal,
    }


def recent(limit: int = 8) -> list[dict]:
    with engine.connect() as con:
        runs = pd.read_sql(
            f"SELECT started_at, distance_km FROM exercise_sessions WHERE exercise_type={RUN} "
            "ORDER BY started_at DESC LIMIT 25",
            con, parse_dates=["started_at"],
        )
        wos = pd.read_sql(
            "SELECT started_at, title FROM workouts WHERE source='hevy' ORDER BY started_at DESC LIMIT 25",
            con, parse_dates=["started_at"],
        )
    items: list[dict] = []
    for _, r in runs.iterrows():
        if pd.isna(r["started_at"]):
            continue
        km = r["distance_km"]
        items.append({
            "kind": "run", "date": r["started_at"].isoformat(), "title": "Lauf",
            "detail": f"{km:.1f} km" if pd.notna(km) else "—",
        })
    for _, r in wos.iterrows():
        if pd.isna(r["started_at"]):
            continue
        items.append({
            "kind": "workout", "date": r["started_at"].isoformat(),
            "title": r["title"] or "Workout", "detail": "Kraft",
        })
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:limit]
