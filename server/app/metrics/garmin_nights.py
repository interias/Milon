"""Read-only night timelines from Garmin's retained provider responses."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median, quantiles
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from ..config import settings
from ..db import engine
from ..garmin_daily import GarminDaily, SOURCE, _eligible, _number, _sleep, _utc


STAGES = {0: "deep", 1: "light", 2: "rem", 3: "awake"}
# The retained Garmin sleep payload uses two-, three- and five-minute observations.
SERIES = {
    "heart_rate": ("sleepHeartRate", 25, 220, 180),
    "stress": ("sleepStress", 0, 100, 270),
    "body_battery": ("sleepBodyBattery", 0, 100, 270),
    "hrv": ("hrvData", 1, 500, 450),
}


def _object(value: str) -> dict:
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _phases(payload: dict, start: datetime, end: datetime) -> tuple[list[dict], bool]:
    intervals = []
    levels = payload.get("sleepLevels")
    for level in levels if isinstance(levels, list) else []:
        if not isinstance(level, dict):
            continue
        left, right = _utc(level.get("startGMT")), _utc(level.get("endGMT"))
        if left is None or right is None:
            continue
        left, right = max(start, left), min(end, right)
        if left < right:
            code = level.get("activityLevel")
            stage = STAGES.get(code, "unknown") if isinstance(code, (int, float)) and not isinstance(code, bool) else "unknown"
            intervals.append({"start_seconds": (left - start).total_seconds(),
                              "end_seconds": (right - start).total_seconds(), "stage": stage})
    intervals.sort(key=lambda item: (item["start_seconds"], item["end_seconds"]))
    edge = 0
    for interval in intervals:
        if interval["start_seconds"] < edge:
            # Conflicting classifications cannot both describe the same instant.
            return [], True
        edge = interval["end_seconds"]
    return intervals, False


def _series(payload: dict, key: str, start: datetime, end: datetime, *, downsample: bool = True) -> dict:
    field, minimum, maximum, gap_seconds = SERIES[key]
    entries = payload.get(field)
    samples = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        stamp = _utc(entry.get("startGMT"))
        if stamp is None or not start <= stamp <= end:
            continue
        value = _number(entry.get("value"), minimum, maximum)
        # Conflicting values at the same instant remain a gap, rather than last-write-wins.
        if stamp in samples and samples[stamp] != value:
            samples[stamp] = None
        else:
            samples[stamp] = value
    segments, current = [], []
    previous = None
    for stamp, value in sorted(samples.items()):
        if value is None or (previous is not None and (stamp - previous).total_seconds() > gap_seconds):
            if current:
                segments.append(current)
                current = []
        if value is not None:
            current.append({"seconds": (stamp - start).total_seconds(), "value": value})
        previous = stamp
    if current:
        segments.append(current)
    count = sum(len(segment) for segment in segments)
    # Keep each segment's endpoints and local extrema. Never connect across a gap.
    if len(segments) > 180:
        selected = sorted({round(index * (len(segments) - 1) / 179) for index in range(180)})
        retained = [segments[index] for index in selected]
    else:
        retained = segments
    retained_count = sum(len(segment) for segment in retained)
    extra = 720 - 2 * len(retained)
    display = []
    for segment in retained:
        target = 2 + int(extra * len(segment) / max(1, retained_count))
        buckets = max(1, (target - 2) // 2)
        stride = max(1, math.ceil(len(segment) / buckets))
        indexes = {0, len(segment) - 1}
        for offset in range(0, len(segment), stride) if target >= 4 else []:
            batch = range(offset, min(offset + stride, len(segment)))
            indexes.add(min(batch, key=lambda index: segment[index]["value"]))
            indexes.add(max(batch, key=lambda index: segment[index]["value"]))
        display.append([segment[index] for index in sorted(indexes)])
    values = [point["value"] for segment in segments for point in segment]
    if not downsample:
        display = segments
    return {"segments": display, "samples": count,
            "display_samples": sum(len(segment) for segment in display),
            "minimum": min(values) if values else None, "maximum": max(values) if values else None,
            "gap_seconds": gap_seconds}


def _night(row: GarminDaily, *, detail: bool = False) -> dict | None:
    if not _eligible(row.day):
        return None
    raw = _object(row.raw_json)
    payload = raw.get("sleep")
    normalized = _sleep(payload, row.day)
    if not normalized or not normalized["main_sleep"]:
        return None
    start, end = _utc(normalized["started_at_utc"]), _utc(normalized["ended_at_utc"])
    zone = ZoneInfo(settings.timezone)
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    status = _object(row.status_json).get("sleep") or {}
    status = status if isinstance(status, dict) else {}
    value = {"day": row.day.isoformat(), "started_at": local_start.isoformat(), "ended_at": local_end.isoformat(),
             "started_at_utc": start.isoformat(), "ended_at_utc": end.isoformat(),
             "window_minutes": normalized["duration_window_minutes"],
             "asleep_minutes": normalized["asleep_minutes"], "awake_minutes": normalized["awake_minutes"],
             "complete": normalized["asleep_minutes"] is not None,
             "stage_coverage": normalized["stage_coverage"],
             "clock_change": local_start.utcoffset() != local_end.utcoffset(),
             "synced_at": status.get("last_success_at"), "sync_issue": status.get("status") == "error"}
    if detail:
        phases, conflict = _phases(payload, start, end)
        series = {key: _series(payload, key, start, end) for key in SERIES}
        battery = series["body_battery"]
        segments = battery["segments"]
        # Only a continuous series close to both night boundaries supports a charge delta.
        charge = None
        if len(segments) == 1 and len(segments[0]) >= 3:
            first, last = segments[0][0], segments[0][-1]
            if first["seconds"] <= 600 and (end - start).total_seconds() - last["seconds"] <= 600:
                charge = last["value"] - first["value"]
        value.update(source=SOURCE, timezone=settings.timezone, phases=phases, stage_conflict=conflict,
                     series=series, battery_change=charge)
    return value


def nights(days: int = 14, *, now: datetime | None = None, end: date | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = now.astimezone(ZoneInfo(settings.timezone)).date()
    if end is not None:
        today = min(today, end)
    first = today - timedelta(days=days - 1)
    with Session(engine) as session:
        rows = session.exec(select(GarminDaily).where(GarminDaily.day >= first, GarminDaily.day <= today)
                            .order_by(GarminDaily.day)).all()
        values = [value for row in rows if (value := _night(row)) is not None]
    return {"source": SOURCE, "timezone": settings.timezone, "from_date": first.isoformat(),
            "to_date": today.isoformat(), "nights": values,
            "complete_nights": sum(value["complete"] for value in values)}


def _reference(rows: list[GarminDaily], selected: dict) -> dict:
    day = date.fromisoformat(selected["day"])
    first = day - timedelta(days=28)
    selected_start = _utc(selected["started_at_utc"])
    complete = []
    for row in rows:
        if not first <= row.day < day:
            continue
        summary = _night(row)
        if summary and summary["complete"] and _utc(summary["ended_at_utc"]) <= selected_start:
            complete.append((row, summary))
    result = {"status": "ready" if len(complete) >= 7 else "collecting", "complete_nights": len(complete),
              "minimum_nights": 7, "min_bin_nights": 5, "bin_minutes": 5,
              "from_date": first.isoformat(), "to_date": (day - timedelta(days=1)).isoformat(),
              "metrics": {key: {"bins": [], "nights": 0} for key in SERIES},
              "method": "Vorherige vollständige Garmin-Hauptnächte der letzten 28 Tage; ausgewählte Nacht ausgeschlossen. "
                        "Zeit seit Schlafbeginn, keine Streckung auf gleiche Nachtdauer. Je 5-Minuten-Abschnitt ein Median "
                        "der vorhandenen Messwerte je Nacht; ab fünf Nächten Median und mittlere 50 %. "
                        "Keine Interpolation, kein Normbereich und kein Konfidenzintervall."}
    if len(complete) < 7:
        return result
    duration = selected["window_minutes"] * 60
    by_metric = {key: defaultdict(list) for key in SERIES}
    for row, summary in complete:
        payload = _object(row.raw_json).get("sleep")
        start, end = _utc(summary["started_at_utc"]), _utc(summary["ended_at_utc"])
        for key in SERIES:
            series = _series(payload, key, start, end, downsample=False)
            by_bin = defaultdict(list)
            for segment in series["segments"]:
                for point in segment:
                    if point["seconds"] < min(duration, summary["window_minutes"] * 60):
                        by_bin[int(point["seconds"] // 300)].append(point["value"])
            if by_bin:
                result["metrics"][key]["nights"] += 1
            for index, values in by_bin.items():
                # Repeated or more frequent samples never give a night extra votes.
                by_metric[key][index].append(median(values))
    for key, bins in by_metric.items():
        for index, values in sorted(bins.items()):
            if len(values) < 5:
                continue
            q1, middle, q3 = quantiles(values, n=4, method="inclusive")
            result["metrics"][key]["bins"].append({"start_seconds": index * 300,
                "end_seconds": min((index + 1) * 300, duration), "nights": len(values),
                "median": round(middle, 2), "q1": round(q1, 2), "q3": round(q3, 2)})
    return result


def night(day: date) -> dict | None:
    with Session(engine) as session:
        row = session.get(GarminDaily, day)
        value = _night(row, detail=True) if row else None
        if value is None:
            return None
        previous = session.exec(select(GarminDaily).where(GarminDaily.day >= day - timedelta(days=28),
                                GarminDaily.day < day).order_by(GarminDaily.day)).all()
        value["reference"] = _reference(previous, value)
        return value
