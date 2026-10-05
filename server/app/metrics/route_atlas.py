"""Local route families with fixed anchors and descriptive run-level changes."""
from __future__ import annotations

from collections import OrderedDict
import json
import math
from threading import RLock

import numpy as np
from sqlalchemy.orm import defer
from sqlmodel import Session, select

from ..db import engine
from ..garmin_activity import GarminActivity
from ..garmin_routes import GarminRoute
from ..run_reference import _boundaries, _period
from . import run_insights
from .route_overlap import MIN_LENGTH_RATIO, overlap, prepare_route

METHOD = (
    "Jede Runde hat den zeitlich ersten verfügbaren Lauf als festen Anker. Weitere Läufe "
    "brauchen mindestens 97 % beidseitige Streckenüberdeckung bei 30 m GPS-Toleranz, "
    "gleicher Richtung und mindestens 97 % Längenverhältnis. Keine Verkettung über ähnliche "
    "Zwischenläufe. Unterbrochene oder unzureichende GPS-Aufzeichnungen bleiben einzeln sichtbar. "
    "Mehrere Garmin-IDs derselben Einheit zählen einmal. Tempo- und Pulsänderungen vergleichen "
    "den ersten mit dem letzten vollständigen, freigegebenen Lauf der jüngsten Sensorperiode; "
    "jeder Wert stammt aus einem ganzen Lauf. Wetter und Trainingsziel sind nicht bereinigt. "
    "Eine Veränderung allein belegt keine Fitnessverbesserung."
)

# The cache contains only local geometry, keyed by persisted route revision. No
# coordinates leave this process except the normalised contour sent to the UI.
_geometry_cache = OrderedDict()
_group_cache = OrderedDict()
_cache_lock = RLock()


def _contour(route):
    try:
        raw = json.loads(route.segments_json)
    except (TypeError, ValueError):
        return []
    segments, current = [], []
    for segment in raw if isinstance(raw, list) else []:
        if not isinstance(segment, list):
            continue
        current = []
        for point in segment:
            if (not isinstance(point, dict) or not run_insights._number(point.get("lat"))
                    or not run_insights._number(point.get("lon"))
                    or abs(point["lat"]) > 85 or abs(point["lon"]) > 180):
                if current:
                    segments.append(current)
                current = []
                continue
            current.append((point["lon"], point["lat"]))
        if current:
            segments.append(current)
    if not segments:
        return []
    points = np.array([point for segment in segments for point in segment])
    scale = np.array([math.cos(math.radians(float(points[:, 1].mean()))), -1])
    points *= scale
    low, high = points.min(axis=0), points.max(axis=0)
    factor = 180 / max(float((high - low).max()), 1e-9)
    result = []
    for segment in segments:
        # Keep every segment boundary and both endpoints while bounding SVG size.
        indices = np.unique(np.linspace(0, len(segment) - 1, min(220, len(segment))).astype(int))
        projected = (np.array(segment)[indices] * scale - (low + high) / 2) * factor + 100
        result.append([[round(float(x), 2), round(float(y), 2)] for x, y in projected])
    return result


def _geometry(session, metadata):
    key = (id(engine), metadata.activity_id, metadata.synced_at, metadata.point_count, metadata.distance_km)
    with _cache_lock:
        cached = _geometry_cache.get(key)
        if cached is not None:
            _geometry_cache.move_to_end(key)
            return cached
    route = session.get(GarminRoute, metadata.activity_id)
    prepared = prepare_route(route)
    cached = (prepared, _contour(route))
    with _cache_lock:
        _geometry_cache[key] = cached
        while len(_geometry_cache) > 256:
            _geometry_cache.popitem(last=False)
    return cached


def _plausible(first, second):
    if first is None or second is None:
        return False
    if min(first.length_m, second.length_m) / max(first.length_m, second.length_m) < MIN_LENGTH_RATIO:
        return False
    # A geographic bounding-box check avoids expensive comparisons of unrelated
    # routes. Padding is generous; the overlap function makes the final decision.
    latitude = float(first.vertices[:, 1].mean())
    padding = np.array([100 / (111195 * max(.08, math.cos(math.radians(latitude)))), 100 / 111195])
    return bool(np.all(first.vertices.max(axis=0) + padding >= second.vertices.min(axis=0))
                and np.all(second.vertices.max(axis=0) + padding >= first.vertices.min(axis=0)))


def group_routes(items, geometry):
    """Chronological fixed-anchor clustering: A~B and B~C never implies A~C."""
    groups = []
    for item in sorted(items, key=lambda row: (row.started_at, row.activity_id)):
        prepared, contour = geometry(item)
        for group in groups:
            if _plausible(group["prepared"], prepared) and overlap(group["prepared"], prepared) >= 97:
                group["ids"].append(item.activity_id)
                break
        else:
            groups.append({"anchor_id": item.activity_id, "ids": [item.activity_id],
                           "prepared": prepared, "contour": contour})
    return [{key: value for key, value in group.items() if key != "prepared"} for group in groups]


def atlas():
    with Session(engine) as session:
        routes = session.exec(select(GarminRoute).options(defer(GarminRoute.segments_json))
            .order_by(GarminRoute.started_at, GarminRoute.activity_id)).all()
        activities = session.exec(select(GarminActivity).options(defer(GarminActivity.series_json),
            defer(GarminActivity.laps_json), defer(GarminActivity.zones_json))
            .order_by(GarminActivity.fetched_at.desc(), GarminActivity.activity_id)).all()
        by_id = {row.activity_id: row for row in activities}
        route_ids = {route.activity_id for route in routes}
        aliases, kept = set(), set()
        for row in activities:
            key = row.canonical_external_id or f"garmin:{row.activity_id}"
            if row.activity_id in route_ids and key not in aliases:
                kept.add(row.activity_id)
                aliases.add(key)
        routes = [route for route in routes if route.activity_id not in by_id or route.activity_id in kept]
        fingerprint = (id(engine), tuple((row.activity_id, row.synced_at, row.point_count, row.distance_km,
                                         row.started_at) for row in routes))
        with _cache_lock:
            grouped = _group_cache.get(fingerprint)
        if grouped is None:
            grouped = group_routes(routes, lambda row: _geometry(session, row))
            with _cache_lock:
                _group_cache[fingerprint] = grouped
                while len(_group_cache) > 3:
                    _group_cache.popitem(last=False)
        metadata = {route.activity_id: route for route in routes}
        annotations, boundaries = run_insights._annotations(session), _boundaries(session)
        groups = []
        for group in grouped:
            members, eligible = [], []
            for activity_id in group["ids"]:
                route, row = metadata[activity_id], by_id.get(activity_id)
                pace = route.duration_seconds / route.distance_km if route.distance_km and route.distance_km > 0 and route.duration_seconds and route.duration_seconds > 0 else None
                member = {"activity_id": activity_id, "title": route.title or "Lauf",
                          "started_at": route.started_at.isoformat(), "distance_km": route.distance_km,
                          "pace_seconds": pace, "avg_hr": None}
                if row:
                    summary, quality = json.loads(row.summary_json), json.loads(row.quality_json)
                    distance, duration = summary.get("distance_km"), summary.get("duration_seconds")
                    if all(run_insights._number(value) and value > 0 for value in (distance, duration)):
                        member["pace_seconds"] = duration / distance
                    hr = summary.get("avg_hr")
                    member["avg_hr"] = hr if run_insights._number(hr) and 25 <= hr <= 250 else None
                    if run_insights._eligible(row, summary, quality, annotations):
                        eligible.append((member, _period(row.started_at.date(), boundaries)))
                members.append(member)
            members.sort(key=lambda member: (member["started_at"], member["activity_id"]))
            eligible.sort(key=lambda pair: pair[0]["started_at"])
            current_period = _period(metadata[members[-1]["activity_id"]].started_at.date(), boundaries)
            comparable = [member for member, period in eligible if period == current_period]
            changes = {}
            for metric in ("pace_seconds", "avg_hr"):
                observations = [member for member in comparable if run_insights._number(member[metric])]
                changes[metric] = ({"first": observations[0][metric], "last": observations[-1][metric],
                                    "delta": observations[-1][metric] - observations[0][metric],
                                    "from": observations[0]["started_at"], "to": observations[-1]["started_at"],
                                    "n": len(observations)} if len(observations) >= 2 else None)
            groups.append({"anchor_id": group["anchor_id"], "contour": group["contour"],
                           "count": len(members), "latest": members[-1], "members": list(reversed(members)),
                           "changes": changes, "sensor_label": current_period[1]})
        groups.sort(key=lambda group: (group["latest"]["started_at"], group["anchor_id"]), reverse=True)
        return {"groups": groups, "total_runs": len(routes), "threshold_pct": 97, "tolerance_m": 30,
                "method": METHOD}
