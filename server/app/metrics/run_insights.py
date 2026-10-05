"""Descriptive comparisons from complete Garmin recordings, without fitness verdicts."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
from sqlmodel import Session, select

from ..config import settings, watch_source_for
from ..db import engine
from ..garmin_activity import GarminActivity, OUTDOOR_RUN_TYPES, _display_series
from ..garmin_routes import GarminRoute
from ..ingest.run_windows import GARMIN_PACKAGE
from ..models import RunAnnotation
from .run_zones import ZONE_DEFS

MATCH_METHOD = (
    "Beschreibender Vergleich gleichmäßiger Minuten nach 10 Minuten Einlaufen, ohne die letzten "
    "2 Minuten und mit 2 Minuten Abstand nach Pausen. Mindestens 90 % gemeinsame Puls-, Tempo- "
    "und Höhenabdeckung; 2–6,5 m/s, Tempo-P10–P90 höchstens 0,5 m/s, Gefälle/Steigung netto höchstens ±2 %. "
    "15-Sekunden-Teilsteigungen höchstens ±3 %, deren P10–P90 höchstens 3 Prozentpunkte; "
    "Minuten werden einmalig gepaart: Tempo höchstens 0,1 m/s, Steigung höchstens 0,5 Prozentpunkte "
    "auseinander. Mindestens 6 Paare. Kein Signifikanztest; Wetter, Untergrund und Pulsverzögerung bleiben Einflüsse."
)
ZONE_METHOD = (
    "Zeitgewichtete Pulsintervalle der vollständigen Garmin-Aufzeichnung, Pausen ausgeschlossen. "
    "Alle Läufe werden mit der aktuell in Milon gespeicherten HFmax und 50/60/70/80/90/100 % "
    "neu eingeordnet. Das sind nicht die aufgezeichneten Garmin-Zonen. Fehlender Puls bleibt unbekannt; "
    "Werte unter 50 % oder über 100 % stehen separat."
)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _load(row):
    return json.loads(row.summary_json), json.loads(row.series_json), json.loads(row.quality_json)


def _eligible(row, summary, quality, annotations):
    annotation = annotations.get(row.canonical_external_id)
    return (quality.get("complete") and quality.get("canonical")
            and summary.get("activity_type") in OUTDOOR_RUN_TYPES
            and watch_source_for(row.started_at.date(), settings) == GARMIN_PACKAGE
            and row.canonical_external_id not in settings.watch_source_legacy_session_ids
            and not (annotation and (annotation.exclude or annotation.category not in {"auto", "normal"})))


def _intervals(series):
    """Keep timer pauses and unknown intervals out of time-weighted calculations."""
    for left, right in zip(series, series[1:]):
        duration = right["elapsed_seconds"] - left["elapsed_seconds"]
        if not 0 < duration <= 15 or right.get("gap"):
            continue
        timer_a, timer_b = left.get("timer_seconds"), right.get("timer_seconds")
        if _number(timer_a) and _number(timer_b) and timer_b - timer_a < duration - .5:
            continue
        yield left, right, duration


def zone_summary(summary, series, hr_max=None):
    maximum = settings.run_hr_max if hr_max is None else hr_max
    valid = _number(maximum) and 100 <= maximum <= 250
    zones = [{"zone": z, "label": label, "hr_low": maximum * low / 100,
              "hr_high": maximum * high / 100, "seconds": 0.0}
             for z, label, low, high in ZONE_DEFS] if valid else []
    outside, counted = 0.0, 0.0
    if valid:
        for left, right, duration in _intervals(series):
            if not all(_number(point.get("hr_bpm")) for point in (left, right)):
                continue
            # Piecewise linear HR: allocate crossing intervals to each zone exactly.
            first, last = left["hr_bpm"], right["hr_bpm"]
            cuts = [0., 1.]
            if first != last:
                cuts += [(bound - first) / (last - first) for bound in
                         [maximum * percent / 100 for percent in (50, 60, 70, 80, 90, 100)]
                         if 0 < (bound - first) / (last - first) < 1]
            cuts.sort()
            for start, end in zip(cuts, cuts[1:]):
                hr = first + (last - first) * (start + end) / 2
                seconds = (end - start) * duration
                matched = next((zone for zone in zones if zone["hr_low"] <= hr < zone["hr_high"]
                                or zone["zone"] == 5 and hr == zone["hr_high"]), None)
                if matched is None:
                    outside += seconds
                else:
                    matched["seconds"] += seconds
                counted += seconds
    total = max(0.0, summary.get("duration_seconds") or 0.0)
    # Inconsistent timer totals should never create more classified than active time.
    if counted > total + max(3, total * .01):
        for zone in zones:
            zone["seconds"] = 0.0
        counted, outside = 0.0, 0.0
    for zone in zones:
        zone["seconds"] = round(zone["seconds"], 2)
    return {"source": "milon_hrmax", "label": "Milon · %HFmax", "hr_max": maximum if valid else None,
            "zones": zones, "known_seconds": round(counted, 2), "outside_seconds": round(outside, 2),
            "unknown_seconds": round(max(0, total - counted), 2), "total_seconds": round(total, 2),
            "method": ZONE_METHOD}


def steady_minutes(summary, series):
    """Full-resolution interval aggregation; altitude is required, never assumed flat."""
    buckets = defaultdict(list)
    terrain = defaultdict(lambda: {"seconds": 0., "distance": 0., "climb": 0.})
    elapsed = summary.get("elapsed_seconds") or 0
    pause_ends = [right["elapsed_seconds"] for left, right in zip(series, series[1:])
                  if right.get("gap") or right["elapsed_seconds"] - left["elapsed_seconds"] > 15]
    for left, right, duration in _intervals(series):
        keys = ("hr_bpm", "speed_m_s", "altitude_m", "distance_m")
        if not all(_number(point.get(key)) for point in (left, right) for key in keys):
            continue
        distance = right["distance_m"] - left["distance_m"]
        if not 0 < distance <= duration * 12:
            continue
        begin, end = left["elapsed_seconds"], right["elapsed_seconds"]
        for block in range(int(begin // 15), int(end // 15) + 1):
            seconds = min(end, (block + 1) * 15) - max(begin, block * 15)
            if seconds > 0:
                terrain[block]["seconds"] += seconds
                terrain[block]["distance"] += distance * seconds / duration
                terrain[block]["climb"] += (right["altitude_m"] - left["altitude_m"]) * seconds / duration
        for minute in range(int(begin // 60), int(end // 60) + 1):
            lo, hi = max(begin, minute * 60), min(end, (minute + 1) * 60)
            if hi <= lo:
                continue
            ratio = (hi - lo) / duration
            fraction = ((lo + hi) / 2 - begin) / duration
            buckets[minute].append({"seconds": hi - lo,
                "hr": left["hr_bpm"] + fraction * (right["hr_bpm"] - left["hr_bpm"]),
                "speed": left["speed_m_s"] + fraction * (right["speed_m_s"] - left["speed_m_s"]),
                "distance": distance * ratio,
                "climb": (right["altitude_m"] - left["altitude_m"]) * ratio})
    result = []
    for minute, parts in sorted(buckets.items()):
        start, end = minute * 60, (minute + 1) * 60
        if start < 600 or end > elapsed - 120 or any(start < pause + 120 and end > pause for pause in pause_ends):
            continue
        seconds = sum(p["seconds"] for p in parts)
        if seconds < 54:
            continue
        blocks = [terrain[minute * 4 + index] for index in range(4)]
        if any(block["seconds"] < 12 or block["distance"] <= 0 for block in blocks):
            continue
        grades = [block["climb"] / block["distance"] * 100 for block in blocks]
        if max(map(abs, grades)) > 3 or float(np.diff(np.quantile(grades, [.1, .9]))[0]) > 3:
            continue
        speed = sum(p["speed"] * p["seconds"] for p in parts) / seconds
        hr = sum(p["hr"] * p["seconds"] for p in parts) / seconds
        ordered = sorted(parts, key=lambda p: p["speed"])
        positions = (np.cumsum([p["seconds"] for p in ordered]) - np.array([p["seconds"] for p in ordered]) / 2) / seconds
        spread = np.diff(np.interp([.1, .9], positions, [p["speed"] for p in ordered]))[0]
        grade = sum(p["climb"] for p in parts) / sum(p["distance"] for p in parts) * 100
        if 2 <= speed <= 6.5 and spread <= .5 and abs(grade) <= 2:
            result.append({"minute": minute + .5, "speed": speed, "hr": hr, "grade": grade})
    return result


def _match(first, second):
    edges = [(abs(a["speed"] - b["speed"]) / .1 + abs(a["grade"] - b["grade"]) / .5, i, j)
             for i, a in enumerate(first) for j, b in enumerate(second)
             if abs(a["speed"] - b["speed"]) <= .1 and abs(a["grade"] - b["grade"]) <= .5]
    used_a, used_b, pairs = set(), set(), []
    for _, i, j in sorted(edges):
        if i not in used_a and j not in used_b:
            pairs.append((first[i], second[j]))
            used_a.add(i)
            used_b.add(j)
    return pairs


def _comparison(pairs, allowed=True):
    enough = len(pairs) >= 6 and allowed
    first_hr = float(np.mean([a["hr"] for a, _ in pairs])) if enough else None
    second_hr = float(np.mean([b["hr"] for _, b in pairs])) if enough else None
    return {"status": "observed" if enough else "insufficient" if allowed else "excluded",
            "matched_pairs": len(pairs), "hr_delta_bpm": round(second_hr - first_hr, 2) if enough else None,
            "pace_delta_seconds": round(float(np.mean([1000 / b["speed"] - 1000 / a["speed"] for a, b in pairs])), 2) if enough else None,
            "first_hr": round(first_hr, 2) if enough else None, "second_hr": round(second_hr, 2) if enough else None,
            "reason": "Vergleichbare Abschnitte; beschreibender Unterschied, kein Fitnessurteil." if enough else
            "Noch keine 6 passenden Minutenpaare mit ausreichenden Puls-, Tempo- und Höhendaten." if allowed else
            "Unvollständiger, ausgeschlossener oder nicht vergleichbarer Lauf.", "method": MATCH_METHOD}


def drift(summary, series, allowed=True):
    minutes = steady_minutes(summary, series) if allowed else []
    midpoint = (600 + max(600, (summary.get("elapsed_seconds") or 0) - 120)) / 120
    first = [point for point in minutes if point["minute"] < midpoint]
    second = [point for point in minutes if point["minute"] >= midpoint]
    result = _comparison(_match(first, second), allowed)
    a, b = result["first_hr"], result["second_hr"]
    return {**result, "value_pct": round((b / a - 1) * 100, 2) if a and b else None,
            "paired_minutes": result["matched_pairs"] * 2, "early_hr": a, "late_hr": b}


def _route_signature(route):
    if route is None:
        return None
    segments = json.loads(route.segments_json)
    if len(segments) != 1 or len(segments[0]) < 20:
        return None
    points = segments[0]
    lat = np.array([p["lat"] for p in points])
    lon = np.array([p["lon"] for p in points])
    y, x = lat * 111195, lon * 111195 * math.cos(math.radians(float(lat.mean())))
    steps = np.hypot(np.diff(x), np.diff(y))
    if np.any(steps > 150):
        return None
    distances = np.r_[0, np.cumsum(steps)]
    if distances[-1] < 1000:
        return None
    grid = np.linspace(0, distances[-1], 101)
    return np.column_stack([np.interp(grid, distances, lat), np.interp(grid, distances, lon)])


def similar_route(first, second):
    a, b = _route_signature(first), _route_signature(second)
    if a is None or b is None:
        return False
    lat_mean = float(np.mean(np.r_[a[:, 0], b[:, 0]]))
    distance = np.hypot((a[:, 0] - b[:, 0]) * 111195,
                        (a[:, 1] - b[:, 1]) * 111195 * math.cos(math.radians(lat_mean)))
    return bool(np.quantile(distance, .9) <= 120 and distance[0] <= 150 and distance[-1] <= 150)


def _annotations(session):
    return {item.external_id: item for item in session.exec(select(RunAnnotation)).all()}


def _brief(row, include_series=False):
    summary = json.loads(row.summary_json)
    result = {"activity_id": row.activity_id, "title": summary.get("title") or "Lauf",
              "started_at": row.started_at.isoformat(), "distance_km": summary.get("distance_km")}
    if include_series:
        result["series"] = []
        gap, previous = False, None
        for point in _display_series(json.loads(row.series_json)):
            if point["distance_m"] is None:
                gap = True
                continue
            current = point["distance_m"]
            result["series"].append({"distance_m": current, "hr_bpm": point["hr_bpm"],
                "pace_seconds": 1000 / point["speed_m_s"] if point["speed_m_s"] and point["speed_m_s"] >= 1 else None,
                "gap": gap or point["gap"] or previous is not None and current < previous})
            gap, previous = False, current
    return result


def activity_insights(activity_id):
    with Session(engine) as session:
        row = session.get(GarminActivity, activity_id)
        if row is None:
            return {"activity_id": activity_id, "available": False, "drift": None, "zones": None, "candidates": []}
        summary, series, quality = _load(row)
        annotations = _annotations(session)
        allowed = _eligible(row, summary, quality, annotations)
        route = session.get(GarminRoute, activity_id)
        candidates = []
        others = session.exec(select(GarminActivity).where(GarminActivity.activity_id != activity_id)
                              .order_by(GarminActivity.started_at.desc()).limit(100)).all()
        for other in others:
            other_summary, other_quality = json.loads(other.summary_json), json.loads(other.quality_json)
            if not _eligible(other, other_summary, other_quality, annotations):
                continue
            distance_a, distance_b = summary.get("distance_km") or 0, other_summary.get("distance_km") or 0
            close_distance = distance_a > 0 and abs(distance_b / distance_a - 1) <= .2
            same = close_distance and similar_route(route, session.get(GarminRoute, other.activity_id))
            candidates.append({**_brief(other), "similar_route": same,
                               "similarity_label": "Ähnlicher Streckenverlauf" if same else "Ähnliche Distanz" if close_distance else "Anderer Lauf",
                               "rank": 0 if same else 1 if close_distance else 2})
        candidates.sort(key=lambda item: item["rank"])
        candidates = [{k: v for k, v in item.items() if k != "rank"} for item in candidates[:30]]
        return {"activity_id": activity_id, "available": True, "drift": drift(summary, series, allowed),
                "zones": zone_summary(summary, series), "candidates": candidates}


def compare(first, second):
    with Session(engine) as session:
        a, b = session.get(GarminActivity, first), session.get(GarminActivity, second)
        if a is None or b is None:
            return None
        sa, points_a, qa = _load(a)
        sb, points_b, qb = _load(b)
        annotations = _annotations(session)
        allowed = first != second and _eligible(a, sa, qa, annotations) and _eligible(b, sb, qb, annotations)
        pairs = _match(steady_minutes(sa, points_a), steady_minutes(sb, points_b)) if allowed else []
        result = _comparison(pairs, allowed)
        distance_a, distance_b = sa.get("distance_km") or 0, sb.get("distance_km") or 0
        result["similar_route"] = bool(distance_a > 0 and abs(distance_b / distance_a - 1) <= .2 and
            similar_route(session.get(GarminRoute, first), session.get(GarminRoute, second)))
        return {"first": _brief(a, True), "second": _brief(b, True), "comparison": result}


def weekly_zones(weeks=8, today=None):
    today = today or datetime.now(ZoneInfo(settings.timezone)).date()
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(weeks=weeks - 1)
    empty = zone_summary({"duration_seconds": 0}, [])
    grouped = {}
    for offset in range(weeks):
        day = start + timedelta(weeks=offset)
        grouped[day] = {**zone_summary({"duration_seconds": 0}, []), "week": day.isoformat(), "runs": 0, "excluded_runs": 0}
    with Session(engine) as session:
        annotations = _annotations(session)
        rows = session.exec(select(GarminActivity).where(GarminActivity.started_at >= datetime.combine(start, datetime.min.time()),
            GarminActivity.started_at < datetime.combine(today + timedelta(days=1), datetime.min.time()))).all()
        for row in rows:
            week = row.started_at.date() - timedelta(days=row.started_at.weekday())
            summary, series, quality = _load(row)
            bucket = grouped[week]
            # Intensity totals include varying workloads, but not explicitly invalid recordings.
            annotation = annotations.get(row.canonical_external_id)
            if (not quality.get("complete") or not quality.get("canonical")
                    or watch_source_for(row.started_at.date(), settings) != GARMIN_PACKAGE
                    or row.canonical_external_id in settings.watch_source_legacy_session_ids
                    or annotation and (annotation.exclude or annotation.category == "measurement_error")):
                bucket["excluded_runs"] += 1
                continue
            zones = zone_summary(summary, series)
            bucket["runs"] += 1
            for key in ("known_seconds", "unknown_seconds", "outside_seconds", "total_seconds"):
                bucket[key] += zones[key]
            for target, source in zip(bucket["zones"], zones["zones"]):
                target["seconds"] += source["seconds"]
    return {"source": empty["source"], "label": empty["label"], "hr_max": empty["hr_max"],
            "weeks": list(grouped.values()), "method": ZONE_METHOD,
            "note": "Nur vollständig importierte Garmin-Läufe; leere Wochen sind keine Aussage über fehlendes Training."}
