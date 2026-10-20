"""Garmin indoor/virtual rides (Zwift, trainer, watch indoor cycling) — power and heart-rate records.

Kept apart from GarminRoute/GarminRide on purpose: the world map, dungeons and mounts read those GPS
tables, and Zwift's coordinates are fictional. Virtual lat/lon are never read, stored or returned —
neither from the detail series nor from a polyline (details are requested with maxpoly=0)."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy.dialects.sqlite import insert
from sqlmodel import Field, Session, SQLModel, select

from .config import settings
from .db import engine

MAX_POINTS = 100_000
MAX_GAP_S = 5            # a sample older than this does not carry over into the 1 Hz grid
HR_MIN_AVG = 60          # Ø-HF below this is a strap/optical dropout, not a ride
HR_MAX_DROPOUT = 0.20    # more than 20 % seconds without HR → no heart-rate metric uses the ride
CURVE_SECONDS = (1, 5, 10, 30, 60, 120, 300, 600, 1200, 1800, 3600)
SERIES_KEYS = ("power_w", "cadence_rpm", "hr_bpm", "speed_m_s", "altitude_m")
_CHANNELS = {  # descriptor key → (series key, low, high); lat/lon descriptors are ignored on purpose
    "directPower": ("power_w", 0, 2500),
    "directBikeCadence": ("cadence_rpm", 0, 250),
    "directHeartRate": ("hr_bpm", 25, 250),
    "directSpeed": ("speed_m_s", 0, 40),
    "directElevation": ("altitude_m", -1000, 10000),
}
_ZWIFT_TITLE = re.compile(r"^\s*zwift\s*[-–—:]\s*(?P<rest>.+?)\s*$", re.IGNORECASE)


class GarminIndoorRide(SQLModel, table=True):
    """One indoor ride; no coordinate column exists by design."""
    __tablename__ = "garmin_indoor_rides"

    activity_id: str = Field(primary_key=True)
    activity_type: str | None = None
    title: str
    world: str | None = None
    route: str | None = None
    started_at: datetime = Field(index=True)  # naive local wall time like every other session table
    started_at_utc: str | None = None
    duration_seconds: float | None = None
    elapsed_duration_seconds: float | None = None
    distance_km: float | None = None  # virtual distance
    elevation_gain_m: float | None = None
    avg_power_w: float | None = None
    norm_power_w: float | None = None
    max_power_w: float | None = None
    work_kj: float | None = None
    avg_cadence_rpm: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    hr_dropout: float | None = None
    hr_valid: bool = False
    aerobic_te: float | None = None
    anaerobic_te: float | None = None
    training_load: float | None = None
    power_curve_json: str = "{}"       # {"seconds": watts}
    power_zones_json: str = "[]"       # Garmin powerTimeInZone_1..7 (seconds, Garmin's own FTP)
    hr_zones_json: str = "[]"          # Garmin hrTimeInZone_1..5 (seconds)
    series_json: str = "{}"            # column-wise {"t": [...], power_w/cadence_rpm/hr_bpm/speed_m_s/altitude_m}
    synced_at: datetime


class GarminIndoorState(SQLModel, table=True):
    """Single row: Garmin's cycling FTP (start value for the eFTP chain) and the backfill marker."""
    __tablename__ = "garmin_indoor_state"

    id: int = Field(default=1, primary_key=True)
    garmin_ftp_w: float | None = None
    ftp_fetched_at: datetime | None = None
    backfilled_at: datetime | None = None


def _json(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _number(value, low=None, high=None) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    if not math.isfinite(number) or (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def parse_title(title: str | None) -> tuple[str | None, str | None]:
    """'Zwift - <Route> in <World>' → (world, route). Tolerant: the last ' in ' splits; without it the
    rest is the route; titles not starting with Zwift yield (None, None)."""
    match = _ZWIFT_TITLE.match(title or "")
    if not match:
        return None, None
    rest = match.group("rest")
    route, separator, world = rest.rpartition(" in ")
    if not separator or not route.strip() or not world.strip():
        return None, rest.strip() or None
    return world.strip(), route.strip()


# ---------------- series math (shared with metrics/cycling) ----------------
def grid(series: dict, key: str, max_gap: float = MAX_GAP_S) -> np.ndarray:
    """1 Hz grid of one channel: each second takes the latest sample ≤ max_gap s old, else NaN."""
    t = np.asarray(series.get("t") or [], float)
    if t.size == 0:
        return np.array([], float)
    values = np.array([np.nan if v is None else v for v in series.get(key) or [None] * t.size], float)
    seconds = np.arange(0, int(math.floor(t[-1])) + 1, dtype=float)
    index = np.searchsorted(t, seconds, side="right") - 1
    out = np.full(seconds.size, np.nan)
    ok = index >= 0
    ok[ok] &= seconds[ok] - t[index[ok]] <= max_gap
    out[ok] = values[index[ok]]
    return out


def best_average(values: np.ndarray, seconds: int) -> float | None:
    """Best mean over a window of `seconds` that is fully covered (no NaN inside)."""
    if seconds <= 0 or values.size < seconds:
        return None
    valid = ~np.isnan(values)
    total = np.concatenate([[0.0], np.cumsum(np.where(valid, values, 0.0))])
    count = np.concatenate([[0], np.cumsum(valid)])
    sums, counts = total[seconds:] - total[:-seconds], count[seconds:] - count[:-seconds]
    full = counts == seconds
    return float(sums[full].max() / seconds) if full.any() else None


def normalized_power(values: np.ndarray) -> float | None:
    """Coggan NP: 30 s rolling mean (fully covered windows), 4th power mean, 4th root."""
    if values.size < 30:
        return None
    valid = ~np.isnan(values)
    total = np.concatenate([[0.0], np.cumsum(np.where(valid, values, 0.0))])
    count = np.concatenate([[0], np.cumsum(valid)])
    sums, counts = total[30:] - total[:-30], count[30:] - count[:-30]
    rolling = sums[counts == 30] / 30
    return float(np.mean(rolling ** 4) ** 0.25) if rolling.size else None


# ---------------- normalization ----------------
def normalize_summary(activity: dict) -> dict:
    activity_id = str(activity["activityId"])
    if not activity_id.isascii() or not activity_id.isdigit() or not 0 < len(activity_id) <= 30 or int(activity_id) <= 0:
        raise ValueError("Ungültige Garmin-Aktivitäts-ID.")
    started = datetime.fromisoformat(str(activity["startTimeGMT"]).replace("Z", "+00:00"))
    started = started.replace(tzinfo=timezone.utc) if started.tzinfo is None else started.astimezone(timezone.utc)
    kind = activity.get("activityType")
    type_key = kind.get("typeKey") if isinstance(kind, dict) else None
    title = activity.get("activityName") if isinstance(activity.get("activityName"), str) else None
    world, route = parse_title(title)
    duration = _number(activity.get("duration"), 0, 7 * 86400)
    elapsed = _number(activity.get("elapsedDuration"), 0, 7 * 86400)
    distance = _number(activity.get("distance"), 0, 2_000_000)
    curve = {}
    for key, value in activity.items():
        match = re.fullmatch(r"maxAvgPower_(\d+)", key) if isinstance(key, str) else None
        watts = _number(value, 0, 2500)
        if match and watts is not None and int(match.group(1)) > 0:
            curve[int(match.group(1))] = watts
    max20 = _number(activity.get("max20MinPower"), 0, 2500)
    if max20 is not None:
        curve.setdefault(1200, max20)
    aerobic = activity.get("aerobicTrainingEffect", activity.get("trainingEffect"))
    return {
        "activity_id": activity_id,
        "activity_type": type_key if isinstance(type_key, str) and len(type_key) <= 64 else None,
        "title": title or "Indoor-Fahrt", "world": world, "route": route,
        "started_at": started.astimezone(ZoneInfo(settings.timezone)).replace(tzinfo=None),
        "started_at_utc": started.isoformat(),
        "duration_seconds": duration,
        "elapsed_duration_seconds": elapsed if elapsed is not None else duration,
        "distance_km": distance / 1000 if distance is not None else None,
        "elevation_gain_m": _number(activity.get("elevationGain"), 0, 50_000),
        "avg_power_w": _number(activity.get("avgPower"), 0, 2500),
        "norm_power_w": _number(activity.get("normPower"), 0, 2500),
        "max_power_w": _number(activity.get("maxPower"), 0, 3000),
        "avg_cadence_rpm": _number(activity.get("averageBikingCadenceInRevPerMinute"), 0, 250),
        "avg_hr": _number(activity.get("averageHR"), 25, 250),
        "max_hr": _number(activity.get("maxHR"), 25, 250),
        "aerobic_te": _number(aerobic, 0, 5),
        "anaerobic_te": _number(activity.get("anaerobicTrainingEffect"), 0, 5),
        "training_load": _number(activity.get("activityTrainingLoad"), 0, 10_000),
        "curve": curve,
        "power_zones": [_number(activity.get(f"powerTimeInZone_{i}"), 0) for i in range(1, 8)],
        "hr_zones": [_number(activity.get(f"hrTimeInZone_{i}"), 0) for i in range(1, 6)],
    }


def normalize_series(summary: dict, details: dict) -> dict:
    """Detail metrics → column-wise series in seconds since start. Only the five channels above are
    read; directLatitude/directLongitude (Zwift's fictional map) never leave this function."""
    descriptors = details.get("metricDescriptors") or []
    indices = {d.get("key"): d.get("metricsIndex") for d in descriptors if isinstance(d, dict)}
    rows = details.get("activityDetailMetrics") or []
    if not isinstance(rows, list) or len(rows) > MAX_POINTS:
        raise ValueError("Ungültige Garmin-Messreihe.")
    start = datetime.fromisoformat(summary["started_at_utc"]).timestamp() * 1000
    limit = (summary.get("elapsed_duration_seconds") or 7 * 86400) + 5

    def value(raw, key, low=None, high=None):
        index = indices.get(key)
        return _number(raw[index], low, high) if isinstance(index, int) and 0 <= index < len(raw) else None

    series: dict[str, list] = {"t": [], **{name: [] for name in SERIES_KEYS}}
    for row in rows:
        raw = row.get("metrics", []) if isinstance(row, dict) else []
        stamp = value(raw, "directTimestamp")
        elapsed = (stamp - start) / 1000 if stamp is not None else None
        if elapsed is None or elapsed < -2 or elapsed > limit:
            continue
        elapsed = round(max(0.0, elapsed), 1)
        if series["t"] and elapsed <= series["t"][-1]:
            continue
        series["t"].append(elapsed)
        for key, (name, low, high) in _CHANNELS.items():
            number = value(raw, key, low, high)
            series[name].append(round(number, 2) if number is not None else None)
    for name in SERIES_KEYS:  # drop empty channels (watch rides have no power)
        if all(v is None for v in series[name]):
            series[name] = []
    return series if series["t"] else {}


def build_values(summary: dict, series: dict) -> dict:
    """Derived per-ride values: work, NP fallback, 60-min curve point, HR plausibility."""
    power = grid(series, "power_w") if series.get("power_w") else np.array([], float)
    hr = grid(series, "hr_bpm") if series.get("hr_bpm") else np.array([], float)
    curve = {int(k): v for k, v in summary["curve"].items()}
    if power.size and not np.isnan(power).all():
        for seconds in CURVE_SECONDS:
            if seconds not in curve:  # Garmin's own keys stay authoritative; 60 min only from the series
                best = best_average(power, seconds)
                if best is not None:
                    curve[seconds] = round(best, 1)
        work = float(np.nansum(power)) / 1000
        norm = summary["norm_power_w"] if summary["norm_power_w"] is not None else normalized_power(power)
        avg = summary["avg_power_w"] if summary["avg_power_w"] is not None else float(np.nanmean(power))
    else:
        avg, norm = summary["avg_power_w"], summary["norm_power_w"]
        work = (avg * summary["duration_seconds"] / 1000
                if avg is not None and summary["duration_seconds"] is not None else None)
    avg_hr = summary["avg_hr"]
    max_hr = summary["max_hr"]
    dropout = None
    if series.get("t"):
        length = int(math.floor(series["t"][-1])) + 1
        dropout = 1.0 if not hr.size else float(np.isnan(hr).sum() / length)
        if hr.size and not np.isnan(hr).all():
            avg_hr = avg_hr if avg_hr is not None else float(np.nanmean(hr))
            max_hr = max_hr if max_hr is not None else float(np.nanmax(hr))
    hr_valid = bool(avg_hr is not None and avg_hr >= HR_MIN_AVG
                    and (dropout is None or dropout <= HR_MAX_DROPOUT))
    values = {key: summary[key] for key in (
        "activity_id", "activity_type", "title", "world", "route", "started_at", "started_at_utc",
        "duration_seconds", "elapsed_duration_seconds", "distance_km", "elevation_gain_m",
        "max_power_w", "avg_cadence_rpm", "aerobic_te", "anaerobic_te", "training_load")}
    values.update({
        "avg_power_w": round(avg, 1) if avg is not None else None,
        "norm_power_w": round(norm, 1) if norm is not None else None,
        "work_kj": round(work, 1) if work is not None else None,
        "avg_hr": round(avg_hr, 1) if avg_hr is not None else None,
        "max_hr": max_hr, "hr_dropout": round(dropout, 3) if dropout is not None else None,
        "hr_valid": hr_valid,
        "power_curve_json": _json({str(k): curve[k] for k in sorted(curve)}),
        "power_zones_json": _json(summary["power_zones"] if any(v is not None for v in summary["power_zones"]) else []),
        "hr_zones_json": _json(summary["hr_zones"] if any(v is not None for v in summary["hr_zones"]) else []),
        "series_json": _json(series),
        "synced_at": datetime.now(timezone.utc).replace(tzinfo=None),
    })
    return values


def save_indoor_ride(values: dict) -> None:
    with Session(engine) as session:
        statement = insert(GarminIndoorRide).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["activity_id"],
            set_={key: getattr(statement.excluded, key) for key in values if key != "activity_id"})
        session.execute(statement)
        session.commit()


# ---------------- state ----------------
def _state(session: Session) -> GarminIndoorState:
    return session.get(GarminIndoorState, 1) or GarminIndoorState(id=1)


def backfilled() -> bool:
    with Session(engine) as session:
        return _state(session).backfilled_at is not None


def garmin_ftp() -> float | None:
    with Session(engine) as session:
        return _state(session).garmin_ftp_w


def _parse_ftp(payload) -> float | None:
    """latestFunctionalThresholdPower/CYCLING: a dict (or list of dicts) with functionalThresholdPower."""
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if isinstance(payload, dict):
        return _number(payload.get("functionalThresholdPower"), 30, 1000)
    return _number(payload, 30, 1000)


def known_ids() -> set[str]:
    with Session(engine) as session:
        return set(session.exec(select(GarminIndoorRide.activity_id)).all())


def sync_indoor(api, activities: list[dict], full: bool = False, listing_complete: bool = True) -> dict:
    """Import indoor rides the cycling listing handed over. Incremental by activity ID; the caller pages
    up to 1,000 rides on the first run or with full=True. Failures are counted, never raised."""
    known = known_ids()
    first = not backfilled()
    result = {"mode": "full" if full else "initial" if first else "incremental",
              "imported": 0, "skipped": 0, "checked": 0, "errors": 0, "without_power": 0}
    for activity in activities:
        result["checked"] += 1
        try:
            summary = normalize_summary(activity)
            if summary["activity_id"] in known and not full:
                result["skipped"] += 1
                continue
            details = api.get_activity_details(summary["activity_id"], maxchart=20000, maxpoly=0)
            reported = _number(details.get("totalMetricsCount"), 0)
            if (reported is not None and 20000 < reported <= MAX_POINTS
                    and len(details.get("activityDetailMetrics", [])) < reported):
                details = api.get_activity_details(summary["activity_id"], maxchart=int(reported), maxpoly=0)
            values = build_values(summary, normalize_series(summary, details))
            save_indoor_ride(values)
            result["imported"] += 1
            result["without_power"] += int(values["avg_power_w"] is None)
        except Exception:
            # No remote payloads in results or logs.
            result["errors"] += 1
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(engine) as session:
        state = _state(session)
        if listing_complete and state.backfilled_at is None:
            state.backfilled_at = now
        if full or state.garmin_ftp_w is None or result["imported"]:
            try:
                ftp = _parse_ftp(api.get_cycling_ftp())
                if ftp is not None:
                    state.garmin_ftp_w, state.ftp_fetched_at = ftp, now
            except Exception:
                result["ftp_error"] = True
        session.add(state)
        session.commit()
        result["garmin_ftp_w"] = state.garmin_ftp_w
    return result
