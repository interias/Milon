"""Rolling, run-weighted HR estimates; no watch VO2 values enter this model."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import run_standardization as shr

MODEL_VERSION = "run-fitness-v1"
WINDOW_DAYS = 56
REFERENCE_PACE = 360
REFERENCE_MINUTE = 20
CAVEAT = (
    "Experimentelle Schätzung aus gleichmäßigen Laufabschnitten. Acht Wochen überlappen; "
    "aufeinanderfolgende Punkte sind keine unabhängigen Bestätigungen. Das 95%-Intervall "
    "erfasst die Streuung der vorhandenen Läufe, nicht sämtliche Wetter-, Strecken-, "
    "Sensor- oder physiologischen Einflüsse. Einzelpunkte sind gemessene Abschnittsmediane "
    "nahe 6:00 min/km, die Kurve ist auf feste Pace und Laufminute geschätzt."
)


def _design(frame, pace, minute):
    return np.column_stack((np.ones(len(frame)),
                            (frame.speed.to_numpy() - 60000 / pace) / 20,
                            (frame.minute.to_numpy() - minute) / 10))


def _summaries(frame, pace, minute):
    matrices, vectors = [], []
    for _, part in frame.groupby("run", sort=True):
        x = _design(part, pace, minute)
        matrices.append(x.T @ x / len(part))
        vectors.append(x.T @ part.hr.to_numpy() / len(part))
    return np.asarray(matrices), np.asarray(vectors)


def _solve(matrices, vectors, weights=None):
    if not len(matrices):
        return None
    weights = np.ones(len(matrices)) if weights is None else weights
    matrix = np.einsum("i,ijk->jk", weights, matrices)
    vector = np.einsum("i,ij->j", weights, vectors)
    if np.linalg.matrix_rank(matrix) < 3 or np.linalg.cond(matrix) > 1e8:
        return None
    return np.linalg.solve(matrix, vector)


def _point(frame, day, pace, minute, iterations):
    count = int(frame.run.nunique())
    local = frame[(frame.speed - 60000 / pace).abs().le(1000 / 120)
                  & (frame.minute - minute).abs().le(5)]
    local_counts = local.groupby("run").size()
    local_runs = int(local_counts.ge(2).sum())
    point = dict(date=day.isoformat(), hr=None, ci_low=None, ci_high=None,
                 runs=count, local_runs=local_runs, status="insufficient", reasons=[])
    if count < 5:
        point["reasons"].append("Weniger als fünf geeignete Läufe in acht Wochen.")
    if local_runs < 3:
        point["reasons"].append("Weniger als drei Läufe nahe Referenzpace und Referenzminute.")
    if point["reasons"]:
        return point
    if not shr.inside(shr.hull(frame[["speed", "minute"]].to_numpy()), (60000 / pace, minute)):
        point["reasons"].append("Referenz liegt außerhalb der beobachteten Kombinationen aus Tempo und Zeit.")
        return point
    matrices, vectors = _summaries(frame, pace, minute)
    beta = _solve(matrices, vectors)
    if beta is None or beta[1] <= 0:
        point["reasons"].append("Tempo-Puls-Beziehung nicht ausreichend bestimmbar oder nicht positiv.")
        return point
    rng = np.random.default_rng(20260919 + day.toordinal() + pace + minute)
    estimates = []
    # Repeat counts retain bootstrap multiplicity; local support gates apply to the
    # observed sample, not to every resample of that same small sample.
    for weights in rng.multinomial(count, np.full(count, 1 / count), size=iterations):
        sampled = _solve(matrices, vectors, weights)
        if sampled is not None:
            estimates.append(float(sampled[0]))
    if len(estimates) < iterations * 0.9:
        point["reasons"].append("Zu viele numerisch unbestimmbare Bootstrap-Stichproben.")
        return point
    low, high = np.percentile(estimates, [2.5, 97.5])
    # Report sensitivity rather than treating five runs as a reliability guarantee.
    leave_out = [_solve(matrices, vectors, np.arange(count) != i) for i in range(count)]
    shifts = [abs(float(b[0] - beta[0])) for b in leave_out if b is not None]
    point.update(hr=round(float(beta[0]), 2), ci_low=round(float(low), 2),
                 ci_high=round(float(high), 2), status="ok",
                 leave_one_run_out_max_bpm=round(max(shifts), 2) if shifts else None)
    point["bootstrap_attempted"] = iterations
    point["bootstrap_valid"] = len(estimates)
    if len(estimates) != iterations:
        # Singular samples may contain the most extreme run combinations. Never
        # silently discard those tails and label the remainder a complete interval.
        point.update(ci_low=None, ci_high=None, status="sensitive")
        point["reasons"].append("Intervall fehlt: Nicht alle Bootstrap-Stichproben sind bestimmbar.")
    if len(shifts) < count or max(shifts, default=0) > 3:
        point["status"] = "sensitive"
        point["reasons"].append("Schätzung reagiert empfindlich auf einzelne Läufe.")
    return point


def analyze(windows: pd.DataFrame, sessions: pd.DataFrame, today: date | None = None,
            bootstrap_iterations: int = 1000) -> dict:
    """Estimate early HR at 6:00 and minute-30 curves on trailing 56-day windows."""
    if bootstrap_iterations < 1:
        raise ValueError("bootstrap_iterations must be positive")
    today = today or date.today()
    result = dict(model_version=MODEL_VERSION, reference_pace_seconds=REFERENCE_PACE,
                  window_days=WINDOW_DAYS, reference_minute=REFERENCE_MINUTE,
                  method="equal_run_weighted_linear_regression", points=[], observations=[],
                  pace_series=[], durability=[], empty_reason=None, caveat=CAVEAT)
    if windows.empty or sessions.empty:
        result["empty_reason"] = "Noch keine geeigneten Lauf-Minuten vorhanden."
        return result
    frame, metadata = shr._prepare(windows, sessions, today)
    dates = dict(zip(metadata.run, pd.to_datetime(metadata.started_at).dt.date))
    early = shr.select(frame, warmup=10, end=30)
    late = shr.select(frame, warmup=10, end=45)
    for part in (early, late):
        part["date"] = part.run.map(dates)
    matched = early[(early.minute - REFERENCE_MINUTE).abs().le(5)
                    & (early.speed - 60000 / REFERENCE_PACE).abs().le(1000 / 120)]
    for run, part in matched.groupby("run"):
        if len(part) >= 2:
            result["observations"].append(dict(date=dates[run].isoformat(), external_id=run,
                hr=round(float(part.hr.median()), 2), minutes=len(part),
                pace_seconds=round(float(60000 / part.speed.median()), 1)))
    result["observations"].sort(key=lambda p: (p["date"], p["external_id"]))
    for run, part in late.groupby("run"):
        near = part[(part.speed - 60000 / REFERENCE_PACE).abs().le(1000 / 120)]
        first = near[near.minute.between(15, 25)]
        last = near[near.minute.between(30, 40)]
        if len(first) >= 3 and len(last) >= 3 and abs(first.speed.mean() - last.speed.mean()) <= 3:
            early_hr, late_hr = float(first.hr.median()), float(last.hr.median())
            result["durability"].append(dict(date=dates[run].isoformat(), external_id=run,
                early_hr=round(early_hr, 2), late_hr=round(late_hr, 2),
                delta_bpm=round(late_hr - early_hr, 2)))
    result["durability"].sort(key=lambda p: (p["date"], p["external_id"]))
    endpoints = sorted(set(dates.values()) | {today})
    paces = [] if late.empty else range(int(np.ceil(60000 / late.speed.max() / 30)) * 30,
                                      int(np.floor(60000 / late.speed.min() / 30)) * 30 + 1, 30)
    series = {pace: [] for pace in paces}
    for day in endpoints:
        start = day - timedelta(days=WINDOW_DAYS - 1)
        subset = early[early.date.between(start, day)]
        result["points"].append(_point(subset, day, REFERENCE_PACE, REFERENCE_MINUTE, bootstrap_iterations))
        subset = late[late.date.between(start, day)]
        for pace in paces:
            series[pace].append(_point(subset, day, pace, 30, bootstrap_iterations))
    result["pace_series"] = [dict(pace_seconds=pace, reference_minute=30, points=points)
                             for pace, points in series.items() if any(p["hr"] is not None for p in points)]
    if not any(p["hr"] is not None for p in result["points"]):
        result["empty_reason"] = "Noch keine ausreichend unterstützte Schätzung für 6:00 min/km."
    return result
