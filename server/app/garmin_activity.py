"""Source-owned Garmin recordings and conservative canonical running inputs."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import delete, inspect
from sqlmodel import Field, Session, SQLModel, select

from .config import settings, watch_source_for
from .db import engine
from .ingest.run_windows import GARMIN_PACKAGE, MODEL_VERSION, _interpolate
from .models import ExerciseSession, RunBestEffort, RunMinute


SOURCE = "garmin_direct"
PARSER_VERSION = "garmin-recording-v2"
MAX_POINTS = 100_000
BEST_DISTANCES = (1000, 5000, 10000, 15000, 20000)
OUTDOOR_RUN_TYPES = {"running", "trail_running", "track_running", "ultra_run"}


class GarminActivity(SQLModel, table=True):
    __tablename__ = "garmin_activities"

    activity_id: str = Field(primary_key=True)
    started_at: datetime = Field(index=True)
    canonical_external_id: str | None = Field(default=None, index=True)
    summary_json: str
    series_json: str
    laps_json: str
    zones_json: str
    quality_json: str
    fingerprint: str
    parser_version: str = PARSER_VERSION
    fetched_at: datetime
    last_issue: str | None = None


class GarminActivityAlias(SQLModel, table=True):
    __tablename__ = "garmin_activity_aliases"

    external_id: str = Field(primary_key=True)
    activity_id: str = Field(index=True)
    canonical_external_id: str


def _json(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _number(value, low=None, high=None) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(number) or (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def _utc(value) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)


def _activity_id(value) -> str:
    result = str(value)
    if not result.isascii() or not result.isdigit() or not 0 < len(result) <= 30 or int(result) <= 0:
        raise ValueError("Ungültige Garmin-Aktivitäts-ID.")
    return result


def normalize_summary(activity: dict) -> dict:
    raw = activity.get("summaryDTO", activity)
    activity_type = activity.get("activityTypeDTO") or activity.get("activityType") or {}
    started = _utc(raw["startTimeGMT"])
    distance = _number(raw.get("distance"), 0, 1_000_000)
    duration = _number(raw.get("duration"), 0, 7 * 86400)
    elapsed = _number(raw.get("elapsedDuration"), 0, 7 * 86400)
    if distance is None or duration is None or elapsed is None or duration <= 0 or elapsed < duration - 3:
        raise ValueError("Unvollständige Garmin-Laufzusammenfassung.")
    result = {
        "title": activity.get("activityName") or "Lauf",
        "started_at": started.astimezone(ZoneInfo(settings.timezone)).replace(tzinfo=None).isoformat(),
        "started_at_utc": started.isoformat(), "distance_km": distance / 1000,
        "duration_seconds": duration, "elapsed_seconds": elapsed,
        "activity_type": activity_type.get("typeKey") if isinstance(activity_type, dict) else None,
    }
    fields = {
        "avg_hr": ("averageHR", 25, 250), "max_hr": ("maxHR", 25, 250),
        "elevation_gain_m": ("elevationGain", 0, 20000),
        "avg_cadence_spm": ("averageRunCadence", 0, 300),
        "avg_power_w": ("averagePower", 0, 2500),
        "ground_contact_ms": ("groundContactTime", 0, 2000),
        "stride_length_cm": ("strideLength", 0, 500),
        "vertical_oscillation_cm": ("verticalOscillation", 0, 50),
        "vertical_ratio_pct": ("verticalRatio", 0, 100),
        "training_effect": ("trainingEffect", 0, 5),
        "anaerobic_training_effect": ("anaerobicTrainingEffect", 0, 5),
    }
    for name, (key, low, high) in fields.items():
        result[name] = _number(raw.get(key), low, high)
    return result


def normalize_recording(summary: dict, details: dict) -> tuple[list[dict], dict]:
    """Descriptor values are already SI; unit.factor is presentation metadata."""
    descriptors = details.get("metricDescriptors") or []
    indices = {d.get("key"): d.get("metricsIndex") for d in descriptors if isinstance(d, dict)}
    rows = details.get("activityDetailMetrics") or []
    if not isinstance(rows, list) or len(rows) > MAX_POINTS:
        raise ValueError("Ungültige Garmin-Messreihe.")
    start = _utc(summary["started_at_utc"]).timestamp() * 1000
    channels = {
        "distance_m": ("sumDistance", 0, 1_000_000),
        "timer_seconds": ("sumDuration", 0, 7 * 86400),
        "hr_bpm": ("directHeartRate", 25, 250),
        "speed_m_s": ("directSpeed", 0, 12),
        "altitude_m": ("directElevation", -1000, 10000),
        "cadence_spm": ("directDoubleCadence", 0, 300),
        "power_w": ("directPower", 0, 2500),
    }

    def value(raw, key, low=None, high=None):
        index = indices.get(key)
        return _number(raw[index], low, high) if isinstance(index, int) and 0 <= index < len(raw) else None

    series = []
    invalid_timestamps = 0
    for row in rows:
        raw = row.get("metrics", []) if isinstance(row, dict) else []
        stamp = value(raw, "directTimestamp")
        elapsed = (stamp - start) / 1000 if stamp is not None else None
        if elapsed is None or elapsed < -2 or elapsed > summary["elapsed_seconds"] + 5:
            invalid_timestamps += 1
            continue
        point = {name: value(raw, key, low, high) for name, (key, low, high) in channels.items()}
        point["elapsed_seconds"] = max(0.0, elapsed)
        point["gap"] = False
        if series:
            previous = series[-1]
            gap = point["elapsed_seconds"] - previous["elapsed_seconds"]
            if gap <= 0:
                invalid_timestamps += 1
                continue
            timer_gap = (point["timer_seconds"] - previous["timer_seconds"]
                         if point["timer_seconds"] is not None and previous["timer_seconds"] is not None else None)
            point["gap"] = gap > 15 or (timer_gap is not None and timer_gap < gap - 0.5)
        series.append(point)

    reported = _number(details.get("totalMetricsCount"), 0, MAX_POINTS * 100)
    count = _number(details.get("metricsCount"), 0, MAX_POINTS * 100)
    reasons = []
    if not series or reported != len(series) or count != len(series) or invalid_timestamps:
        reasons.append("Die Anzahl der Garmin-Messpunkte ist nicht vollständig bestätigt.")
    if details.get("pendingData") is True or details.get("detailsAvailable") is False:
        reasons.append("Garmin verarbeitet die Aufzeichnung noch.")
    if series:
        first, last = series[0], series[-1]
        tolerance = max(3, summary["elapsed_seconds"] * 0.01)
        if first["elapsed_seconds"] > 3 or abs(last["elapsed_seconds"] - summary["elapsed_seconds"]) > tolerance:
            reasons.append("Die Messreihe deckt den Lauf zeitlich nicht vollständig ab.")
        distance = last["distance_m"]
        if distance is None or abs(distance - summary["distance_km"] * 1000) > max(30, summary["distance_km"] * 20):
            reasons.append("Die aufgezeichnete Distanz passt nicht zur Laufzusammenfassung.")
        timer = last["timer_seconds"]
        if timer is None or abs(timer - summary["duration_seconds"]) > max(3, summary["duration_seconds"] * 0.01):
            reasons.append("Die aktive Dauer der Messreihe ist nicht bestätigt.")
        cadence = [p["cadence_spm"] for p in series if p["cadence_spm"] is not None and p["cadence_spm"] > 0]
        if cadence and summary.get("avg_cadence_spm"):
            if not 0.75 <= float(np.median(cadence)) / summary["avg_cadence_spm"] <= 1.25:
                for point in series:
                    point["cadence_spm"] = None
        speeds = [p["speed_m_s"] for p in series if p["speed_m_s"] is not None]
        expected = summary["distance_km"] * 1000 / summary["duration_seconds"]
        if speeds and expected > 0 and not 0.6 <= float(np.mean(speeds)) / expected <= 1.5:
            reasons.append("Die Geschwindigkeitseinheit stimmt nicht mit der Zusammenfassung überein.")
    def coverage(channel):
        seconds = sum(b["elapsed_seconds"] - a["elapsed_seconds"]
                      for a, b in zip(series, series[1:])
                      if not b["gap"] and a[channel] is not None and b[channel] is not None)
        return min(1.0, seconds / summary["duration_seconds"])

    hr_coverage, speed_coverage = coverage("hr_bpm"), coverage("speed_m_s")
    # A full chart count alone does not prove a dense sensor recording.
    gaps = np.diff([p["elapsed_seconds"] for p in series])
    typical_gap = float(np.median(gaps)) if len(gaps) else None
    if typical_gap is None or typical_gap > 15:
        reasons.append("Die Messpunkte sind für die Laufanalyse zu grob aufgelöst.")
    if hr_coverage < 0.9 or speed_coverage < 0.9:
        reasons.append("Puls oder Tempo fehlen in mehr als zehn Prozent der aktiven Laufzeit.")
    quality = {"complete": not reasons, "canonical": False, "points": len(series),
               "reported_points": int(reported) if reported is not None else None,
               "hr_coverage": round(hr_coverage, 4), "speed_coverage": round(speed_coverage, 4),
               "typical_interval_seconds": typical_gap, "reason": " ".join(reasons) or None,
               "source": SOURCE}
    return series, quality


def normalize_laps(response: dict) -> list[dict]:
    result = []
    for number, lap in enumerate(response.get("lapDTOs", [])[:500], 1):
        duration = _number(lap.get("duration"), 0)
        distance = _number(lap.get("distance"), 0)
        if duration is None or distance is None:
            continue
        result.append({"index": int(lap.get("lapIndex", number)), "distance_m": distance,
                       "duration_seconds": duration, "elapsed_seconds": _number(lap.get("elapsedDuration"), 0),
                       "avg_hr": _number(lap.get("averageHR"), 25, 250),
                       "max_hr": _number(lap.get("maxHR"), 25, 250),
                       "avg_cadence_spm": _number(lap.get("averageRunCadence"), 0, 300),
                       "avg_power_w": _number(lap.get("averagePower"), 0, 2500),
                       "elevation_gain_m": _number(lap.get("elevationGain"), 0, 20000)})
    return result


def normalize_zones(response: list) -> list[dict]:
    zones = []
    for row in response if isinstance(response, list) else []:
        number = _number(row.get("zoneNumber"), 1, 10)
        low = _number(row.get("zoneLowBoundary"), 25, 250)
        seconds = _number(row.get("secsInZone"), 0)
        if number is not None and low is not None and seconds is not None:
            zones.append({"zone": int(number), "hr_low": low, "hr_high": None, "seconds": seconds})
    zones.sort(key=lambda z: z["zone"])
    for current, following in zip(zones, zones[1:]):
        current["hr_high"] = following["hr_low"] - 1
    return zones


def minute_windows(series: list[dict], external_id: str, elapsed: float) -> list[dict]:
    """Use the existing shr-v1 minute definition, with explicit timer-pause gaps."""
    times = np.asarray([p["elapsed_seconds"] * 1000 for p in series])
    speed = np.asarray([p["speed_m_s"] if p["speed_m_s"] is not None else np.nan for p in series])
    hr = np.asarray([p["hr_bpm"] if p["hr_bpm"] is not None else np.nan for p in series])
    rows = []
    pauses = [(a["elapsed_seconds"], b["elapsed_seconds"]) for a, b in zip(series, series[1:]) if b["gap"]]
    for minute in range(int(elapsed // 60)):
        grid = minute * 60_000 + (np.arange(60) + 0.5) * 1000
        velocity, pulse = _interpolate(times, speed, grid), _interpolate(times, hr, grid)
        valid = np.isfinite(velocity) & np.isfinite(pulse)
        for start, end in pauses:
            valid &= ~((grid > start * 1000) & (grid < end * 1000))
        coverage = float(valid.mean())
        mean_speed = float(velocity[valid].mean()) if valid.any() else None
        mean_hr = float(pulse[valid].mean()) if valid.any() else None
        spread = float(np.ptp(np.quantile(velocity[valid], [0.1, 0.9]))) if valid.any() else None
        steady = coverage >= 0.9 and mean_speed is not None and 2 <= mean_speed <= 8 and spread <= 0.5
        rows.append({"external_id": external_id, "minute": minute + 0.5,
                     "speed_m_min": mean_speed * 60 if mean_speed is not None else None,
                     "hr_bpm": mean_hr, "coverage": coverage, "steady": bool(steady),
                     "source": SOURCE, "model_version": MODEL_VERSION})
    return rows


def best_efforts(series: list[dict]) -> dict[int, float]:
    """Fastest continuous distance on elapsed time, never interpolate a sensor gap."""
    chunks, current = [], []
    for point in series:
        distance = point["distance_m"]
        if distance is None:
            if current:
                chunks.append(current)
            current = []
            continue
        if current:
            dt = point["elapsed_seconds"] - current[-1][0]
            dd = distance - current[-1][1]
            if dt > 15 or dt <= 0 or dd < 0 or dd / dt > 12:
                chunks.append(current)
                current = []
        current.append((point["elapsed_seconds"], distance))
    if current:
        chunks.append(current)
    result = {}
    for target in BEST_DISTANCES:
        best = math.inf
        for chunk in chunks:
            if len(chunk) < 2 or chunk[-1][1] - chunk[0][1] < target:
                continue
            times, distances = np.asarray(chunk).T
            # Both boundary families matter when speed changes within a sample.
            for finish in range(1, len(chunk)):
                wanted = distances[finish] - target
                if wanted < distances[0]:
                    continue
                left = int(np.searchsorted(distances, wanted, side="right") - 1)
                start_time = times[left]
                if distances[left] < wanted and left + 1 < len(chunk):
                    fraction = (wanted - distances[left]) / (distances[left + 1] - distances[left])
                    start_time += fraction * (times[left + 1] - times[left])
                best = min(best, times[finish] - start_time)
            for start in range(len(chunk) - 1):
                wanted = distances[start] + target
                if wanted > distances[-1]:
                    continue
                right = int(np.searchsorted(distances, wanted, side="left"))
                end_time = times[right]
                if distances[right] > wanted:
                    fraction = (wanted - distances[right - 1]) / (distances[right] - distances[right - 1])
                    end_time = times[right - 1] + fraction * (times[right] - times[right - 1])
                best = min(best, end_time - times[start])
        if math.isfinite(best) and best > 0:
            result[target] = round(float(best), 1)
    return result


def _matches(summary: dict, candidate) -> bool:
    get = candidate.get if isinstance(candidate, dict) else lambda key: getattr(candidate, key, None)
    start, end, distance = get("started_at"), get("ended_at"), get("distance_km")
    if get("exercise_type") != 33 or start is None or end is None or not distance:
        return False
    expected_start = datetime.fromisoformat(summary["started_at"])
    elapsed = (end - start).total_seconds()
    return (abs((start - expected_start).total_seconds()) <= 120
            and abs(distance - summary["distance_km"]) <= max(0.3, summary["distance_km"] * 0.1)
            and abs(elapsed - summary["elapsed_seconds"]) <= max(120, summary["elapsed_seconds"] * 0.1))


def _canonicalize(session: Session, row: GarminActivity, summary: dict, series: list[dict], quality: dict):
    start = datetime.fromisoformat(summary["started_at"])
    if not quality["complete"]:
        return
    if summary.get("activity_type") not in OUTDOOR_RUN_TYPES:
        quality["reason"] = "Dieser Garmin-Aktivitätstyp wird nicht als Outdoorlauf übernommen; die bisherige Quelle bleibt erhalten."
        return
    if watch_source_for(start.date(), settings) != GARMIN_PACKAGE:
        quality["reason"] = "Vor dem Garmin-Uhrenwechsel bleibt die bisherige Quelle maßgeblich."
        return
    candidates = session.exec(select(ExerciseSession).where(
        ExerciseSession.exercise_type == 33,
        ExerciseSession.started_at >= start - timedelta(seconds=120),
        ExerciseSession.started_at <= start + timedelta(seconds=120))).all()
    matched = [candidate for candidate in candidates if _matches(summary, candidate)]
    if row.canonical_external_id:
        canonical = session.exec(select(ExerciseSession).where(
            ExerciseSession.external_id == row.canonical_external_id)).first()
        if canonical is None:
            quality["reason"] = "Die bisherige Laufzuordnung fehlt; bitte die Datenquelle prüfen."
            return
    elif len(matched) > 1 or (matched and not matched[0].external_id):
        quality["reason"] = "Mehrere mögliche Laufzuordnungen; die bisherige Quelle bleibt erhalten."
        return
    elif matched:
        canonical = matched[0]
    else:
        canonical = ExerciseSession(external_id=f"garmin:{row.activity_id}", exercise_type=33, started_at=start)
    if canonical.external_id in settings.watch_source_legacy_session_ids:
        quality["reason"] = "Dieser Übergangs-Lauf behält bis zur Klärung seine bisherige Quelle."
        return
    external_id = canonical.external_id
    # Elapsed start/end semantics remain compatible with the historical metrics.
    canonical.started_at = start
    canonical.ended_at = start + timedelta(seconds=summary["elapsed_seconds"])
    canonical.distance_km = summary["distance_km"]
    canonical.avg_hr, canonical.max_hr = summary["avg_hr"], summary["max_hr"]
    midpoint = summary["elapsed_seconds"] / 2
    first = [p["hr_bpm"] for p in series if p["hr_bpm"] is not None and p["elapsed_seconds"] < midpoint]
    last = [p["hr_bpm"] for p in series if p["hr_bpm"] is not None and p["elapsed_seconds"] >= midpoint]
    canonical.hr_drift_pct = ((float(np.mean(last)) / float(np.mean(first)) - 1) * 100
                              if midpoint >= 450 and first and last else None)
    canonical.source = SOURCE
    session.add(canonical)
    row.canonical_external_id = external_id
    quality["canonical"] = True
    session.merge(GarminActivityAlias(external_id=external_id, activity_id=row.activity_id,
                                      canonical_external_id=external_id))
    session.execute(delete(RunMinute).where(RunMinute.external_id == external_id))
    session.add_all([RunMinute(**window) for window in minute_windows(series, external_id, summary["elapsed_seconds"])])
    session.execute(delete(RunBestEffort).where(RunBestEffort.external_id == external_id))
    session.add_all([RunBestEffort(external_id=external_id, distance_m=distance, seconds=seconds,
                                  started_at=start, source=SOURCE) for distance, seconds in best_efforts(series).items()])


def protected_hc_ids(session: Session, incoming_sessions: list[dict]) -> set[str]:
    """Call before HC upserts/deletes; aliases never rename a canonical annotation key."""
    if not inspect(session.connection()).has_table(GarminActivity.__tablename__):
        return set()
    records = session.exec(select(GarminActivity).where(GarminActivity.canonical_external_id.is_not(None))).all()
    protected = {row.canonical_external_id for row in records}
    protected.update(session.exec(select(GarminActivityAlias.external_id)).all())
    for incoming in incoming_sessions:
        external_id = incoming.get("external_id")
        if not external_id or external_id in protected or external_id in settings.watch_source_legacy_session_ids:
            continue
        matches = [row for row in records if _matches(json.loads(row.summary_json), incoming)]
        if len(matches) == 1:
            row = matches[0]
            session.merge(GarminActivityAlias(external_id=external_id, activity_id=row.activity_id,
                                              canonical_external_id=row.canonical_external_id))
            protected.add(external_id)
    return protected


def _fingerprint(activity: dict) -> str:
    raw = activity.get("summaryDTO", activity)
    values = {key: raw.get(key) for key in ("startTimeGMT", "distance", "duration", "elapsedDuration",
                                           "averageHR", "maxHR", "lastUpdated", "updateDate")}
    values["title"] = activity.get("activityName")
    activity_type = activity.get("activityTypeDTO") or activity.get("activityType") or {}
    values["activity_type"] = activity_type.get("typeKey") if isinstance(activity_type, dict) else None
    return hashlib.sha256(_json(values).encode()).hexdigest()


def sync_activities(api, activities: list[dict], full: bool = False) -> dict:
    """Reuse the importer's authenticated client and serialized token lifecycle."""
    result = {"imported": 0, "skipped": 0, "canonical": 0, "incomplete": 0, "errors": 0}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for activity in activities:
        try:
            activity_id = _activity_id(activity["activityId"])
            fingerprint = _fingerprint(activity)
            with Session(engine) as session:
                old = session.get(GarminActivity, activity_id)
                if old and not full and old.parser_version == PARSER_VERSION and old.fingerprint == fingerprint:
                    recent = old.started_at >= datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None) - timedelta(days=7)
                    if old.fetched_at > now - timedelta(hours=6) or (not recent and json.loads(old.quality_json)["complete"]):
                        result["skipped"] += 1
                        continue
            raw = api.get_activity(activity_id)
            summary = normalize_summary(raw)
            details = api.get_activity_details(activity_id, maxchart=20000, maxpoly=0)
            reported = _number(details.get("totalMetricsCount"), 0)
            if reported is not None and 20000 < reported <= MAX_POINTS and len(details.get("activityDetailMetrics", [])) < reported:
                details = api.get_activity_details(activity_id, maxchart=int(reported), maxpoly=0)
            series, quality = normalize_recording(summary, details)
            laps, zones = None, None
            try:
                laps = normalize_laps(api.get_activity_splits(activity_id))
            except Exception:
                pass
            try:
                zones = normalize_zones(api.get_activity_hr_in_timezones(activity_id))
            except Exception:
                pass
            with Session(engine) as session:
                old = session.get(GarminActivity, activity_id)
                if old and old.canonical_external_id and not quality["complete"]:
                    old.last_issue = quality["reason"]
                    old.fetched_at, old.fingerprint = now, fingerprint
                    session.add(old)
                    session.commit()
                    result["incomplete"] += 1
                    continue
                row = old or GarminActivity(activity_id=activity_id,
                    started_at=datetime.fromisoformat(summary["started_at"]), summary_json="{}", series_json="[]",
                    laps_json="[]", zones_json="[]", quality_json="{}", fingerprint=fingerprint, fetched_at=now)
                _canonicalize(session, row, summary, series, quality)
                row.started_at = datetime.fromisoformat(summary["started_at"])
                row.summary_json, row.series_json, row.quality_json = _json(summary), _json(series), _json(quality)
                row.laps_json = _json(laps) if laps is not None else row.laps_json
                row.zones_json = _json(zones) if zones is not None else row.zones_json
                row.fingerprint, row.parser_version, row.fetched_at, row.last_issue = fingerprint, PARSER_VERSION, now, None
                session.add(row)
                session.commit()
            result["imported"] += 1
            result["canonical"] += int(quality["canonical"])
            result["incomplete"] += int(not quality["complete"])
        except Exception:
            result["errors"] += 1
            # No remote exception bodies, account identifiers or tokens enter logs.
    return result


def _display_series(series: list[dict], limit: int = 600) -> list[dict]:
    if len(series) <= limit:
        return [{k: v for k, v in p.items() if k != "timer_seconds"} for p in series]
    selected = sorted(set([0, len(series) - 1] + [round(i * (len(series) - 1) / (limit - 1)) for i in range(limit)]))
    result, previous = [], -1
    for index in selected:
        point = {key: value for key, value in series[index].items() if key != "timer_seconds"}
        section = series[previous + 1:index + 1]
        point["gap"] = any(p["gap"] for p in section)
        # A display sample must not bridge a missing channel between selected points.
        for key in ("hr_bpm", "speed_m_s", "altitude_m", "cadence_spm", "power_w"):
            if any(p[key] is None for p in section):
                point[key] = None
        result.append(point)
        previous = index
    return result


def activity_detail(activity_id: str) -> dict:
    with Session(engine) as session:
        row = session.get(GarminActivity, activity_id)
        if row is None:
            return {"activity_id": activity_id, "available": False, "canonical_external_id": None,
                    "summary": None, "quality": None, "series": [], "laps": [], "zones": [],
                    "zone_source": "garmin_recorded", "synced_at": None}
        quality = json.loads(row.quality_json)
        quality["last_issue"] = row.last_issue
        return {"activity_id": row.activity_id, "available": True,
                "canonical_external_id": row.canonical_external_id, "summary": json.loads(row.summary_json),
                "quality": quality, "series": _display_series(json.loads(row.series_json)),
                "laps": json.loads(row.laps_json), "zones": json.loads(row.zones_json),
                "zone_source": "garmin_recorded", "synced_at": row.fetched_at.replace(tzinfo=timezone.utc).isoformat()}
