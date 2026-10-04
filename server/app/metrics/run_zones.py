"""Observed pace distributions in explicit %HRmax zones, separated by watch."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ..config import settings, watch_source_for
from ..db import engine
from . import run_standardization as shr

WINDOW_DAYS = 56
ZONE_SOURCE = "https://www8.garmin.com/manuals/webhelp/GUID-28E0106C-B05A-44E9-BF7C-9CB36A596B82/EN-US/GUID-A8716C0B-B267-4C42-B45F-B9C7928BCA19.html"
ZONE_DEFS = [(1, "Sehr locker", 50, 60), (2, "Locker", 60, 70),
             (3, "Moderat", 70, 80), (4, "Intensiv", 80, 90), (5, "Sehr intensiv", 90, 100)]
CAVEAT = (
    "Beobachtetes Tempo gleichmäßiger Minuten 10–45, keine vorgeschriebene Trainingspace. "
    "Jeder Lauf erhält dasselbe Gesamtgewicht. Das Band enthält die mittleren 80 % der "
    "beobachteten Pace-Verteilung (P10–P90), kein Konfidenzintervall. Einzellauf-Werte sind "
    "besonders vorläufig; Wetter, Strecke, Ermüdung und Pulsverzögerung bleiben Einflüsse. "
    "Das Fünf-Zonen-Schema in %HFmax bildet keine gemessenen Laktatschwellen ab. "
    "Der gespeicherte HFmax-Referenzwert bestätigt die tatsächliche physiologische HFmax nicht."
)


def _sensor_label(package: str) -> str:
    if "garmin" in package:
        return "Garmin"
    if "shealth" in package:
        return "Samsung"
    return "Uhr"


def _weighted_quantiles(values: pd.Series, weights: pd.Series) -> tuple[float, float, float]:
    # Collapse equal values so repeated observations at the same pace do not alter
    # interpolation solely through their representation as multiple rows.
    mass = pd.DataFrame({"value": values.to_numpy(), "weight": weights.to_numpy()})
    mass = mass.groupby("value", sort=True).weight.sum()
    centers = (mass.cumsum() - mass / 2) / mass.sum()
    return tuple(float(value) for value in np.interp([0.1, 0.5, 0.9], centers, mass.index))


def _selected(windows: pd.DataFrame, sessions: pd.DataFrame, start: date, end: date,
              legacy: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    metadata = sessions.drop_duplicates("external_id").reset_index(drop=True).copy()
    started = pd.to_datetime(metadata.started_at)
    metadata = metadata[started.dt.date.between(start, end) & ~metadata.external_id.isin(legacy)].copy()
    if "category" not in metadata:
        metadata["category"] = "auto"
    if "exclude" not in metadata:
        metadata["exclude"] = False
    if metadata.empty or windows.empty:
        return pd.DataFrame(), metadata
    frame, metadata = shr._prepare(windows, metadata, end)
    frame = shr.select(frame, warmup=10, end=45)
    if not frame.empty:
        dates = dict(zip(metadata.run, pd.to_datetime(metadata.started_at).dt.date))
        frame["day"] = frame.run.map(dates)
    return frame, metadata


def _zone_values(frame: pd.DataFrame, low: float, high: float, top: bool = False) -> dict | None:
    if frame.empty:
        return None
    selected = frame[frame.hr.ge(low) & (frame.hr.le(high) if top else frame.hr.lt(high))].copy()
    counts = selected.groupby("run").size()
    selected = selected[selected.run.isin(counts[counts >= 3].index)].copy()
    if selected.empty:
        return None
    weights = 1 / selected.groupby("run").run.transform("size")
    pace = 60000 / selected.speed
    fast, median, slow = _weighted_quantiles(pace, weights)
    return {
        "pace_fast_seconds": round(fast, 1), "pace_median_seconds": round(median, 1),
        "pace_slow_seconds": round(slow, 1), "speed_low_kmh": round(3600 / slow, 1),
        "speed_median_kmh": round(3600 / median, 1), "speed_high_kmh": round(3600 / fast, 1),
        "pace_hr_low": round(float(selected.hr.min()), 1), "pace_hr_high": round(float(selected.hr.max()), 1),
        "supporting_runs": int(selected.run.nunique()), "supporting_days": int(selected.day.nunique()),
        "minutes": len(selected), "coverage": round(float((selected.coverage * weights).sum() / weights.sum()), 3),
        "from_date": min(selected.day).isoformat(), "to_date": max(selected.day).isoformat(),
        "status": "single_run" if selected.run.nunique() == 1 else "observed", "provisional": True,
    }


def analyze(sessions: pd.DataFrame, hr_max: float | None, today: date, config=None,
            windows: pd.DataFrame | None = None) -> dict:
    config = settings if config is None else config
    windows = pd.DataFrame() if windows is None else windows
    start = today - timedelta(days=WINDOW_DAYS - 1)
    switch = getattr(config, "watch_source_switch_date", None)
    sensor_start = switch if switch is not None and switch <= today else None
    if sensor_start is not None:
        start = max(start, sensor_start)
    package = watch_source_for(today, config)
    valid_max = isinstance(hr_max, (int, float)) and math.isfinite(hr_max) and 100 <= hr_max <= 250
    result = {
        "hr_max": float(hr_max) if valid_max else None,
        "hr_max_source": "configured_reference" if valid_max else "missing",
        "schema": "max_hr_five_zones", "schema_source": ZONE_SOURCE,
        "sensor": {"label": _sensor_label(package), "source_package": package,
                   "since": sensor_start.isoformat() if sensor_start else None},
        "from_date": start.isoformat(), "to_date": today.isoformat(), "window_days": WINDOW_DAYS,
        "runs": 0, "minutes": 0, "historical_runs": 0, "latest_run_date": None,
        "observed_hr_low": None, "observed_hr_high": None,
        "pace_status": "insufficient", "pace_reason": "Keine passenden gleichmäßigen Laufminuten vorhanden.",
        "zones": [], "caveat": CAVEAT, "method": "equal_run_weighted_observed_pace_quantiles",
    }
    current, historical = pd.DataFrame(), pd.DataFrame()
    legacy = set(getattr(config, "watch_source_legacy_session_ids", []))
    if not sessions.empty:
        current, metadata = _selected(windows, sessions, start, today, legacy)
        if not metadata.empty:
            result["latest_run_date"] = pd.to_datetime(metadata.started_at).max().date().isoformat()
        if not current.empty:
            result.update(runs=int(current.run.nunique()), minutes=len(current),
                          observed_hr_low=round(float(current.hr.min()), 1),
                          observed_hr_high=round(float(current.hr.max()), 1))
        if sensor_start is not None:
            historical_end = sensor_start - timedelta(days=1)
            historical, _ = _selected(windows, sessions, historical_end - timedelta(days=WINDOW_DAYS - 1),
                                      historical_end, legacy)
            if not historical.empty:
                result["historical_runs"] = int(historical.run.nunique())
    if not valid_max:
        result["pace_reason"] = "Bitte einen bekannten HFmax-Referenzwert eintragen; keine Ableitung aus Pulsspitzen."
        return result
    for number, label, low, high in ZONE_DEFS:
        values = _zone_values(current, hr_max * low / 100, hr_max * high / 100, top=number == 5)
        source, source_label = "current", _sensor_label(package)
        if values is None:
            values = _zone_values(historical, hr_max * low / 100, hr_max * high / 100, top=number == 5)
            source, source_label = "historical", f"{_sensor_label(config.steps_source_package)} · vor Wechsel"
        zone = {
            "zone": number, "label": label, "pct_low": low, "pct_high": high,
            "hr_low": math.ceil(hr_max * low / 100),
            "hr_high": math.floor(hr_max) if number == 5 else math.ceil(hr_max * high / 100) - 1,
            "pace_fast_seconds": None, "pace_median_seconds": None, "pace_slow_seconds": None,
            "speed_low_kmh": None, "speed_median_kmh": None, "speed_high_kmh": None,
            "pace_hr_low": None, "pace_hr_high": None, "supporting_runs": 0,
            "supporting_days": 0, "minutes": 0, "coverage": None, "source": None,
            "source_label": None, "status": "unavailable", "provisional": True,
            "from_date": None, "to_date": None, "reason": "Keine passenden Laufdaten in dieser Zone.",
        }
        if values is not None:
            zone.update(values, source=source, source_label=source_label, reason=None)
        result["zones"].append(zone)
    if any(zone["pace_median_seconds"] is not None for zone in result["zones"]):
        result.update(pace_status="observed", pace_reason="Beobachtete Pace-Korridore; historische Quellen sind je Zone gekennzeichnet.")
    return result


def zones(today: date | None = None) -> dict:
    today = today if today is not None else datetime.now(ZoneInfo(settings.timezone)).date()
    with engine.connect() as con:
        sessions = pd.read_sql(
            "SELECT e.external_id, e.started_at, e.ended_at, e.distance_km, "
            "COALESCE(a.category, 'auto') AS category, COALESCE(a.exclude, 0) AS exclude "
            "FROM exercise_sessions e LEFT JOIN run_annotations a ON a.external_id=e.external_id "
            "WHERE e.exercise_type=33 AND e.external_id IS NOT NULL ORDER BY e.started_at",
            con, parse_dates=["started_at", "ended_at"],
        )
        windows = pd.read_sql(
            "SELECT external_id,minute,speed_m_min,hr_bpm,coverage,steady FROM run_minutes "
            "WHERE model_version=? ORDER BY external_id,minute", con, params=(shr.MODEL_VERSION,),
        )
    return analyze(sessions, settings.run_hr_max, today, windows=windows)
