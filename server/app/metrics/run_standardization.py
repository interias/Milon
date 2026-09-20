"""Experimental monthly HR standardization; runs are the independent sampling units.

Quality thresholds are conservative product rules, not validated physiological cutoffs.
This module is deliberately independent of persistence and Health Connect extraction.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

MODEL_VERSION = "shr-v1"
REFERENCE_MINUTE = 30
PACE_STEP_SECONDS = 30
SEED = 20260919
CAVEAT = (
    "Experimentelle Standardisierung auf Minute 30. Die Prüfgrenzen sind vorläufig. "
    "Das 95%-Intervall beschreibt die Unsicherheit der vorhandenen Läufe im Modell; "
    "Wetter, Strecke, Sensorfehler und physiologische Modellunsicherheit sind nicht vollständig enthalten. "
    "Niedrigerer standardisierter Puls ist kein isolierter Nachweis besserer Fitness."
)


def select(windows, warmup=10, end=45, transition=True):
    frame = windows.sort_values(["run", "minute"]).copy()
    accepted = (frame.steady.fillna(False).astype(bool) & frame.eligible_session
                & frame.coverage.ge(0.9) & frame.speed.between(120, 480)
                & frame.hr.between(25, 250) & np.isfinite(frame.speed)
                & np.isfinite(frame.hr))
    # Incomplete bins remain in the sequence: missing minutes must never be bridged.
    if transition:
        for lag in (1, 2):
            prev = frame.groupby("run").shift(lag)
            accepted &= prev.steady.fillna(False).astype(bool)
            accepted &= prev.coverage.ge(0.9) & prev.hr.between(25, 250)
            accepted &= prev.speed.between(120, 480)
            accepted &= (frame.minute - prev.minute - lag).abs() < 1e-6
            accepted &= (frame.speed - prev.speed).abs() <= 18
        previous = frame.groupby("run").speed.shift(1)
        earlier = frame.groupby("run").speed.shift(2)
        accepted &= (previous - earlier).abs() <= 18
    frame = frame[accepted & frame.minute.between(warmup, end)].copy()
    counts = frame.groupby("run").size()
    return frame[frame.run.isin(counts[counts >= 8].index)].copy()


def hull(points):
    pts = sorted(set(map(tuple, points)))
    if len(pts) < 3:
        return []
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def inside(polygon, point):
    if len(polygon) < 3:
        return False
    x, y = point
    return all((b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]) >= -1e-8
               for a, b in zip(polygon, polygon[1:] + polygon[:1]))


def support(frame, pace, minute):
    speed = 1000 / pace
    local = frame[(frame.speed - speed).abs() <= 0.5 * 1000 / 60]
    local = local[(local.minute - minute).abs() <= 10]
    counts = local.groupby("run").size()
    local_ids = counts[counts >= 2].index.to_numpy()
    return {"runs": int(frame.run.nunique()), "local_runs": int(len(local_ids)),
            "inside_hull": bool(inside(hull(frame[["speed", "minute"]].to_numpy()), (speed, minute)))}, local_ids


def design(frame, variant="main"):
    speed = (frame.speed.to_numpy() - 1000 / 6) / 20
    minute = (frame.minute.to_numpy() - 30) / 10
    columns = [np.ones(len(frame)), speed, minute]
    if variant == "interaction":
        columns.append(speed * minute)
    return np.column_stack(columns)


def fit(frame, variant="main", counts=None):
    X, y = design(frame, variant), frame.hr.to_numpy()
    ids, ix = np.unique(frame.run.to_numpy(), return_inverse=True)
    multiplicity = np.ones(len(ids)) if counts is None else np.array([counts.get(i, 0) for i in ids])
    n = np.bincount(ix)
    base = multiplicity[ix] / n[ix]
    if (multiplicity > 0).sum() < 3:
        return None
    weights = base.copy()
    old = None
    for _ in range(80):
        root = np.sqrt(weights)
        beta, _, rank, _ = np.linalg.lstsq(X * root[:, None], y * root, rcond=None)
        if rank != X.shape[1]:
            return None
        if variant == "ols" or (old is not None and np.max(np.abs(beta - old)) < 1e-5):
            return beta
        residual = y - X @ beta
        order = np.argsort(np.abs(residual))
        cum = np.cumsum(base[order])
        scale = max(float(np.abs(residual)[order][np.searchsorted(cum, cum[-1] / 2)]) * 1.4826, 1)
        robust = np.minimum(1, 1.345 * scale / np.maximum(np.abs(residual), 1e-9))
        # Preserve total weight per run, including its bootstrap multiplicity.
        norm = np.bincount(ix, weights=robust)
        weights = multiplicity[ix] * robust / norm[ix]
        old = beta
    return None


def predict(beta, pace, minute, variant="main"):
    x = (1000 / pace - 1000 / 6) / 20
    t = (minute - 30) / 10
    row = [1, x, t] + ([x * t] if variant == "interaction" else [])
    return float(np.dot(beta, row))



def _bootstrap(frame, iterations):
    ids = np.sort(frame.run.unique())
    rng = np.random.default_rng(SEED + int(frame.month.iloc[0].replace("-", "")))
    betas, draws = [], []
    for _ in range(iterations):
        unique, count = np.unique(rng.choice(ids, len(ids), replace=True), return_counts=True)
        beta = fit(frame, counts=dict(zip(unique, count)))
        betas.append(beta if beta is not None else np.full(3, np.nan))
        draws.append(tuple(unique))
    return np.array(betas), draws


def _prepare(windows, sessions, today):
    metadata = sessions.copy().rename(columns={"external_id": "run"})
    # Datetimes are stored as local session wall time by the importer.
    started = pd.to_datetime(metadata.started_at)
    ended = pd.to_datetime(metadata.ended_at)
    metadata = metadata[started.dt.date <= today].copy()
    started, ended = started.loc[metadata.index], ended.loc[metadata.index]
    metadata["month"] = started.dt.strftime("%Y-%m")
    duration = (ended - started).dt.total_seconds() / 60
    metadata["eligible_session"] = (
        metadata.distance_km.ge(0.5) & duration.between(3, 120)
        & metadata.category.isin(["auto", "normal"]) & ~metadata.exclude.fillna(False).astype(bool)
    )
    frame = windows.rename(columns={"external_id": "run", "speed_m_min": "speed", "hr_bpm": "hr"}).copy()
    for column in ("minute", "speed", "hr", "coverage"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    frame = frame.merge(metadata[["run", "month", "eligible_session"]], on="run", how="inner", validate="many_to_one")
    # Each source minute is one observation, even if a caller repeated an import.
    frame = frame.drop_duplicates(["run", "minute"])
    return frame, metadata


def _point(month, runs=0, local_runs=0):
    return {"month": month, "hr": None, "ci_low": None, "ci_high": None,
            "runs": runs, "local_runs": local_runs, "status": "insufficient",
            "reasons": [], "exploratory_hr": None}


def analyze(windows: pd.DataFrame, sessions: pd.DataFrame, today: date | None = None,
            bootstrap_iterations: int = 2000) -> dict:
    """Return independently gated 30-second pace references and monthly gaps.

    Bootstrap draws resample whole runs and retain duplicate-run multiplicity.
    Every fit has equal total weight per sampled run, regardless of its duration.
    All pace references share a month's fits; no estimates outside joint support.
    """
    if bootstrap_iterations < 1:
        raise ValueError("bootstrap_iterations must be positive")
    today = today or date.today()
    result = {"reference_minute": REFERENCE_MINUTE, "pace_step_seconds": PACE_STEP_SECONDS,
              "model_version": MODEL_VERSION, "pace_series": [], "empty_reason": None, "caveat": CAVEAT}
    if sessions.empty or windows.empty:
        result["empty_reason"] = "Noch keine geeigneten Minutenwerte aus Outdoor-Läufen vorhanden."
        return result
    windows, metadata = _prepare(windows, sessions, today)
    main = select(windows)
    if main.empty:
        result["empty_reason"] = "Keine Läufe mit mindestens acht geeigneten, gleichmäßigen Minuten vorhanden."
        return result
    months = pd.period_range(metadata.month.min(), today.strftime("%Y-%m"), freq="M").astype(str)
    # Discover all fixed half-minute references from observed speeds, including faster future paces.
    fastest = int(np.ceil(60000 / main.speed.max() / PACE_STEP_SECONDS)) * PACE_STEP_SECONDS
    slowest = int(np.floor(60000 / main.speed.min() / PACE_STEP_SECONDS)) * PACE_STEP_SECONDS
    paces = list(range(fastest, slowest + 1, PACE_STEP_SECONDS))
    points = {pace: [] for pace in paces}
    distributions = {}
    alternatives = {"warmup5": select(windows, warmup=5), "end60": select(windows, end=60),
                    "no_transition": select(windows, transition=False)}
    for month in months:
        sub = main[main.month == month]
        run_count = int(sub.run.nunique())
        beta = fit(sub) if run_count >= 3 else None
        support_by_pace = {pace: support(sub, pace / 60, REFERENCE_MINUTE) for pace in paces}
        # Only months with basic support need costly resampling or influence diagnostics.
        testable = beta is not None and beta[1] > 0 and run_count >= 10 and any(
            sup["local_runs"] >= 5 and sup["inside_hull"] for sup, _ in support_by_pace.values())
        variants, left_out, betas, draws, polygons = {}, [], None, [], {}
        if testable:
            variants = {key: (fit(sub, key), sub) for key in ("ols", "interaction")}
            for key, alt in alternatives.items():
                part = alt[alt.month == month]
                variants[key] = (fit(part) if part.run.nunique() >= 3 else None, part)
            left_out = [fit(sub[sub.run != run]) for run in sub.run.unique()]
            betas, draws = _bootstrap(sub, bootstrap_iterations)
            # Hull of a union is unchanged if its constituent runs are reduced to their hulls.
            run_hulls = {run: hull(part[["speed", "minute"]].to_numpy())
                         for run, part in sub.groupby("run")}
            for draw in set(draws):
                vertices = []
                for run in draw:
                    vertices.extend(run_hulls[run] or sub[sub.run == run][["speed", "minute"]].to_numpy().tolist())
                polygons[draw] = hull(vertices)
        for pace in paces:
            sup, local_ids = support_by_pace[pace]
            point = _point(month, run_count, sup["local_runs"])
            reasons = point["reasons"]
            if run_count < 10:
                reasons.append("Weniger als zehn geeignete Läufe im Monat.")
            if sup["local_runs"] < 5:
                reasons.append("Weniger als fünf Läufe nahe Referenzpace und Minute 30.")
            if not sup["inside_hull"]:
                reasons.append("Referenz liegt außerhalb der gemeinsam beobachteten Tempi und Laufminuten.")
            if beta is None:
                reasons.append("Monatsmodell ist nicht ausreichend bestimmbar.")
            elif beta[1] <= 0:
                reasons.append("Keine positive Tempo-Puls-Beziehung im Monatsmodell.")
            value = predict(beta, pace / 60, REFERENCE_MINUTE) if beta is not None else None
            if beta is not None and beta[1] > 0 and run_count >= 6 and sup["local_runs"] >= 3 and sup["inside_hull"]:
                point["exploratory_hr"] = round(value, 2)
            if not reasons and testable:
                boot = betas[:, 0] + betas[:, 1] * ((60000 / pace - 1000 / 6) / 20)
                local_set = set(local_ids)
                invalid = np.array([
                    len(set(draw) & local_set) < 3 or not inside(polygons[draw], (60000 / pace, REFERENCE_MINUTE))
                    for draw in draws
                ]) | ~np.isfinite(boot)
                if invalid.mean() > 0.05:
                    reasons.append("Zu viele Bootstrap-Ziehungen verlieren ausreichende Datenabdeckung.")
                if any(b is None for b in left_out):
                    reasons.append("Das Modell ist beim Weglassen einzelner Läufe nicht stabil bestimmbar.")
                elif max(abs(predict(b, pace / 60, REFERENCE_MINUTE) - value) for b in left_out) > 3:
                    reasons.append("Ein einzelner Lauf verändert die Schätzung um mehr als 3 bpm.")
                if any(b is None for b, _ in variants.values()):
                    reasons.append("Mindestens eine Modellvariante ist nicht bestimmbar.")
                shifts = []
                for name, (b, part) in variants.items():
                    if b is None:
                        continue
                    alt_sup, _ = support(part, pace / 60, REFERENCE_MINUTE)
                    if alt_sup["inside_hull"] and alt_sup["local_runs"] >= 3:
                        shifts.append(abs(predict(b, pace / 60, REFERENCE_MINUTE,
                                                  "interaction" if name == "interaction" else "main") - value))
                if max(shifts, default=0) > 3:
                    reasons.append("Alternative Modellannahmen verändern die Schätzung um mehr als 3 bpm.")
                if not reasons:
                    # Support failures count against the gate; intervals use every finite fit,
                    # as in the feasibility study (rather than hiding unstable tails).
                    finite = np.isfinite(boot)
                    lo, hi = np.quantile(boot[finite], [0.025, 0.975])
                    point.update(hr=round(value, 2), ci_low=round(float(lo), 2), ci_high=round(float(hi), 2),
                                 status="provisional" if month == today.strftime("%Y-%m") else "ok")
                    distributions[(month, pace)] = boot
                else:
                    point["status"] = "unstable"
            elif (beta is None and run_count >= 10) or (beta is not None and beta[1] <= 0):
                point["status"] = "unstable"
            if month == today.strftime("%Y-%m"):
                reasons.append("Laufender Monat: Daten und Schätzung sind vorläufig.")
            points[pace].append(point)
    for pace in paces:
        if not any(p["hr"] is not None for p in points[pace]):
            continue
        complete = [p for p in points[pace] if p["status"] == "ok"]
        comparison = None
        if len(complete) >= 2:
            first, last = complete[0], complete[-1]
            delta = distributions[(last["month"], pace)] - distributions[(first["month"], pace)]
            delta = delta[np.isfinite(delta)]
            lo, hi = np.quantile(delta, [0.025, 0.975])
            comparison = {"from_month": first["month"], "to_month": last["month"],
                          "delta": round(last["hr"] - first["hr"], 2),
                          "ci_low": round(float(lo), 2), "ci_high": round(float(hi), 2),
                          "verdict": "lower" if hi < 0 else "higher" if lo > 0 else "unclear"}
        result["pace_series"].append({"pace_seconds": pace, "points": points[pace], "comparison": comparison})
    if not result["pace_series"]:
        result["empty_reason"] = "Noch keine Pace in 30-Sekunden-Schritten mit ausreichend belegtem, stabilem Monatswert."
    return result
