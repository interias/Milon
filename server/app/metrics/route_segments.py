"""Compare physical route sections without aligning runs by elapsed distance alone."""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime
import json
import math

import numpy as np
from sqlmodel import Session

from ..db import engine
from ..garmin_activity import GarminActivity
from ..garmin_routes import GarminRoute
from . import run_cohort
from .route_overlap import GPS_TOLERANCE_M, prepare_route

SECTION_M = 500
METHOD = (
    "500-m-Abschnitte entlang der GPS-Strecke dieses Laufs; ein Rest ab 100 m wird separat gezeigt. "
    "GPS-Länge und Garmin-Gesamtdistanz können voneinander abweichen. "
    "Verglichen werden ausschließlich andere vollständige, freigegebene Läufe der vorhandenen "
    "97-%-Vergleichsgruppe und derselben Sensorperiode. Zusätzlich müssen die Startpunkte höchstens "
    "30 m auseinanderliegen. Abschnittsgrenzen werden räumlich auf die andere Strecke projiziert, "
    "nicht allein nach Prozent der Gesamtdistanz zugeordnet. Alle 20 m werden Nähe, Laufrichtung "
    "und eindeutiger Fortschritt geprüft. Versetzte Starts, mehrdeutige Runden und Aufzeichnungslücken "
    "bleiben außen vor. Pace = verstrichene Zeit / aufgezeichnete Garmin-Distanz im zugeordneten "
    "Abschnitt; Abschnitte mit Pausen werden nicht verglichen. Puls wird zeitgewichtet über "
    "mindestens 90 % des Abschnitts gemittelt. Ein Vergleichslauf zählt je Abschnitt genau einmal "
    "und benötigt beide Werte. Minimum/Maximum beschreiben die beobachtete Streuung, keine "
    "Unsicherheit oder Signifikanz. Wetter, Trainingsziel und Tagesform sind nicht bereinigt."
)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _stamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.timestamp() if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


@dataclass
class Track:
    points: np.ndarray
    distance: np.ndarray
    times: np.ndarray
    latitude: float

    def xy(self, points):
        return np.asarray(points) * [111195 * math.cos(math.radians(self.latitude)), 111195]

    def point(self, distance):
        return np.array([np.interp(distance, self.distance, self.points[:, axis]) for axis in range(2)])


@dataclass
class Recording:
    origin: float
    series: list[dict]
    times: list[float]


def _recording(row):
    if row is None:
        return None
    summary = json.loads(row.summary_json)
    origin = _stamp(summary.get("started_at_utc"))
    series = json.loads(row.series_json)
    if origin is None or not isinstance(series, list) or len(series) < 2:
        return None
    times = [point.get("elapsed_seconds") for point in series]
    if any(not _finite(value) for value in times) or any(b <= a for a, b in zip(times, times[1:])):
        return None
    return Recording(origin, series, times)


def _track(route):
    if prepare_route(route) is None:
        return None
    raw = json.loads(route.segments_json)[0]
    times = [_stamp(point.get("time")) for point in raw]
    if any(value is None for value in times) or np.any(np.diff(times) <= 0):
        return None
    points = np.array([[point["lon"], point["lat"]] for point in raw])
    latitude = float(points[:, 1].mean())
    xy = points * [111195 * math.cos(math.radians(latitude)), 111195]
    distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    return Track(points, distance, np.array(times), latitude)


def _alignment(reference, other, start, end):
    """Project the entire section; reject ambiguous traversals and temporal gaps."""
    if np.linalg.norm(reference.xy(reference.points[0] - other.points[0])) > GPS_TOLERANCE_M:
        return None
    vertices = reference.xy(other.points)
    vectors = np.diff(vertices, axis=0)
    squared = np.sum(vectors ** 2, axis=1)
    directions = vectors / np.maximum(np.sqrt(squared[:, None]), 1e-9)
    samples = np.unique(np.r_[start, np.arange(start, end, 20), end])
    positions = []
    for distance in samples:
        point = reference.xy(reference.point(distance))
        vector = reference.xy(reference.point(min(reference.distance[-1], distance + 10))
                              - reference.point(max(0, distance - 10)))
        length = np.linalg.norm(vector)
        if length < 1:
            return None
        fractions = np.clip(np.sum((point - vertices[:-1]) * vectors, axis=1)
                            / np.maximum(squared, 1e-9), 0, 1)
        residual = np.linalg.norm(point - vertices[:-1] - fractions[:, None] * vectors, axis=1)
        path_distance = other.distance[:-1] + fractions * np.diff(other.distance)
        expected = distance / reference.distance[-1] * other.distance[-1]
        valid = ((residual <= GPS_TOLERANCE_M) & (directions @ (vector / length) >= .5)
                 & (np.abs(path_distance - expected) <= max(75, reference.distance[-1] * .03)))
        indices = np.flatnonzero(valid)
        if not len(indices):
            return None
        # Neighbouring line segments describe one location; separate passes do not.
        if np.ptp(path_distance[indices]) > 75:
            return None
        best = indices[np.argmin(residual[indices])]
        positions.append(float(path_distance[best]))
    if np.any(np.diff(positions) < -1) or not .85 <= (positions[-1] - positions[0]) / (end - start) <= 1.15:
        return None
    left, right = positions[0], positions[-1]
    if not _continuous(other, left, right):
        return None
    return float(np.interp(left, other.distance, other.times)), float(np.interp(right, other.distance, other.times))


def _continuous(track, start, end):
    overlaps = (track.distance[1:] > start) & (track.distance[:-1] < end)
    return bool(np.any(overlaps) and np.all(np.diff(track.times)[overlaps] <= 15))


def _window(row, start, end, expected_m):
    recording = _recording(row) if isinstance(row, GarminActivity) else row
    if recording is None or not 0 < end - start <= 3600:
        return None
    series, times = recording.series, recording.times
    start, end = start - recording.origin, end - recording.origin
    if start < times[0] or end > times[-1]:
        return None
    first, last = max(0, bisect_left(times, start) - 1), min(len(series) - 1, bisect_left(times, end))
    covered = hr_seconds = hr_total = distance = 0.
    for left, right in zip(series[first:last], series[first + 1:last + 1]):
        dt = right["elapsed_seconds"] - left["elapsed_seconds"]
        a, b = max(start, left["elapsed_seconds"]), min(end, right["elapsed_seconds"])
        if b <= a:
            continue
        if right.get("gap") or dt > 15:
            return None
        ld, rd = left.get("distance_m"), right.get("distance_m")
        lt, rt = left.get("timer_seconds"), right.get("timer_seconds")
        if (not all(_finite(value) for value in (ld, rd, lt, rt)) or rd < ld
                or rd - ld > dt * 12 or abs((rt - lt) - dt) > .5):
            return None
        covered += b - a
        distance += (rd - ld) * (b - a) / dt
        lh, rh = left.get("hr_bpm"), right.get("hr_bpm")
        if all(_finite(value) and 25 <= value <= 250 for value in (lh, rh)):
            ha = lh + (rh - lh) * (a - left["elapsed_seconds"]) / dt
            hb = lh + (rh - lh) * (b - left["elapsed_seconds"]) / dt
            hr_total += (ha + hb) / 2 * (b - a)
            hr_seconds += b - a
    duration = end - start
    if covered < duration - .01 or not .85 <= distance / expected_m <= 1.15:
        return None
    return {"pace_seconds": duration * 1000 / distance,
            "avg_hr": hr_total / hr_seconds if hr_seconds >= duration * .9 else None,
            "hr_coverage_pct": round(100 * hr_seconds / duration, 1), "distance_m": round(distance, 1)}


def comparison(activity_id, today=None):
    cohort = run_cohort.comparison(activity_id, today=today)
    if cohort is None:
        return None
    result = {"activity_id": activity_id, "status": "unavailable", "reason": cohort["reason"],
              "selected": cohort["selected"], "cohort_runs": len(cohort["cohort"]),
              "section_m": SECTION_M, "sections": [], "contour": [], "method": METHOD}
    if cohort["status"] == "unavailable":
        return result
    with Session(engine) as session:
        recording = _recording(session.get(GarminActivity, activity_id))
        reference = _track(session.get(GarminRoute, activity_id))
        if reference is None:
            result["reason"] = "Für Abschnitte fehlen eindeutige UTC-Zeitstempel oder durchgehende GPS-Daten."
            return result
        others = [(item, _recording(session.get(GarminActivity, item["activity_id"])),
                   _track(session.get(GarminRoute, item["activity_id"]))) for item in cohort["cohort"]]
        xy = reference.xy(reference.points) * [1, -1]
        low, high = xy.min(axis=0), xy.max(axis=0)
        scale = 180 / max(float((high - low).max()), 1)

        def contour(start, end):
            grid = np.r_[start, np.arange(start + 20, end, 20), end]
            points = np.array([reference.xy(reference.point(at)) * [1, -1] for at in grid])
            return np.round((points - (low + high) / 2) * scale + 100, 2).tolist()

        result["contour"] = contour(0, reference.distance[-1])
        for index, start in enumerate(np.arange(0, reference.distance[-1], SECTION_M)):
            end = min(start + SECTION_M, reference.distance[-1])
            # A tiny GPS remainder is not a meaningful additional section.
            if end - start < 100:
                continue
            selected = None
            if _continuous(reference, start, end):
                selected = _window(recording, float(np.interp(start, reference.distance, reference.times)),
                                   float(np.interp(end, reference.distance, reference.times)), end - start)
            runs = []
            for item, other, track in others:
                aligned = _alignment(reference, track, start, end) if track else None
                value = _window(other, *aligned, end - start) if aligned else None
                if value and value["avg_hr"] is not None:
                    runs.append({"activity_id": item["activity_id"], "started_at": item["started_at"], **value})
            result["sections"].append({"index": index, "start_m": round(float(start)),
                "end_m": round(float(end)), "contour": contour(start, end), "selected": selected,
                "runs": runs, "n": len(runs), "omitted_runs": len(others) - len(runs),
                "metrics": {key: run_cohort.distribution(selected.get(key) if selected else None,
                    [value[key] for value in runs]) for key in ("pace_seconds", "avg_hr")}})
        result.update(status="ready" if result["sections"] else "unavailable",
                      reason=None if result["sections"] else "Die Strecke ist für 500-m-Abschnitte zu kurz.")
        return result
