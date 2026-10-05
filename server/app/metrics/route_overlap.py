"""Conservative, local-only comparison of the distance covered by GPS routes.

Coverage uses 20 m path intervals, not the number of recorded GPS points. Each
interval's midpoint must lie within 30 m of the other polyline, face a similar
direction, and occur at a similar position in the route. The latter avoids
counting a repeatedly traversed section as an entirely different set of laps.
This is approximate geometric coverage, not GPS accuracy or a statistical CI.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math

import numpy as np

from ..garmin_routes import GarminRoute, MAX_ROUTE_POINTS


GPS_TOLERANCE_M = 30.0
SAMPLE_DISTANCE_M = 20.0
MIN_LENGTH_RATIO = .97
_METRES_PER_DEGREE = 111195.0
_MIN_DIRECTION_COSINE = .5


@dataclass(frozen=True)
class PreparedRoute:
    """Internal geometry only; never serialize these coordinates into API output."""

    vertices: np.ndarray
    centers: np.ndarray
    directions: np.ndarray
    weights: np.ndarray
    positions: np.ndarray
    length_m: float
    reported_length_m: float | None
    closed: bool


def _finite(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _xy(points, latitude):
    return points * np.array([_METRES_PER_DEGREE * math.cos(math.radians(latitude)), _METRES_PER_DEGREE])


def prepare_route(route: GarminRoute | None) -> PreparedRoute | None:
    """Validate and resample one continuous 1–200 km route without joining gaps.

    Recording jumps over 150 m and moving gaps over 30 s are excluded. The GPS
    path must be within 15% of the device's reported distance when available.
    Stationary pauses may retain a timestamp gap; they add no path distance.
    """
    if route is None:
        return None
    try:
        segments = json.loads(route.segments_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(segments, list) or len(segments) != 1 or not isinstance(segments[0], list):
        return None
    points = segments[0]
    if not 20 <= len(points) <= MAX_ROUTE_POINTS:
        return None
    if any(not isinstance(p, dict) or not _finite(p.get("lat")) or not _finite(p.get("lon"))
           or not -85 <= p["lat"] <= 85 or not -180 <= p["lon"] <= 180 for p in points):
        return None
    coordinates = np.array([[p["lon"], p["lat"]] for p in points])
    xy = _xy(coordinates, float(coordinates[:, 1].mean()))
    steps = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    if np.any(steps > 150):
        return None
    previous_time = None
    for index, point in enumerate(points):
        value = point.get("time")
        try:
            recorded_at = datetime.fromisoformat(value) if value is not None else None
            if recorded_at is not None and recorded_at.tzinfo is None:
                return None
            if recorded_at is not None and previous_time is not None:
                elapsed = (recorded_at - previous_time).total_seconds()
                if elapsed < 0 or elapsed == 0 and steps[index - 1] > 10 or elapsed > 30 and steps[index - 1] > 30:
                    return None
            previous_time = recorded_at
        except (TypeError, ValueError, OverflowError):
            return None
    distance = np.r_[0., np.cumsum(steps)]
    length = float(distance[-1])
    if not 1000 <= length <= 200_000:
        return None
    reported = route.distance_km
    if reported is not None:
        if not _finite(reported) or reported <= 0:
            return None
        reported *= 1000
        if not .85 <= length / reported <= 1.15:
            return None
    keep = np.r_[True, steps > 0]
    distance, coordinates = distance[keep], coordinates[keep]

    def interpolate(at):
        return np.column_stack([np.interp(at, distance, coordinates[:, axis]) for axis in range(2)])

    grid = np.r_[np.arange(0., length, SAMPLE_DISTANCE_M), length]
    midpoints = (grid[:-1] + grid[1:]) / 2
    directions = interpolate(np.minimum(length, midpoints + 10)) - interpolate(np.maximum(0, midpoints - 10))
    return PreparedRoute(vertices=interpolate(grid), centers=interpolate(midpoints), directions=directions,
        weights=np.diff(grid), positions=midpoints / length, length_m=length, reported_length_m=reported,
        closed=bool(np.linalg.norm(xy[-1] - xy[0]) <= GPS_TOLERANCE_M))


class _RouteIndex:
    def __init__(self, route, latitude):
        self.route = route
        self.vertices = _xy(route.vertices, latitude)
        self.centers = _xy(route.centers, latitude)
        directions = _xy(route.directions, latitude)
        norms = np.linalg.norm(directions, axis=1)
        self.directions = directions / np.maximum(norms[:, None], 1e-9)
        self.starts = self.vertices[:-1]
        self.vectors = np.diff(self.vertices, axis=0)
        self.squared_lengths = np.sum(self.vectors ** 2, axis=1)
        self.cells = {}
        for index, (start, end) in enumerate(zip(self.vertices[:-1], self.vertices[1:])):
            lower = np.floor((np.minimum(start, end) - GPS_TOLERANCE_M) / 60).astype(int)
            upper = np.floor((np.maximum(start, end) + GPS_TOLERANCE_M) / 60).astype(int)
            for x in range(lower[0], upper[0] + 1):
                for y in range(lower[1], upper[1] + 1):
                    self.cells.setdefault((x, y), []).append(index)

    def matches(self, point, direction):
        indices = self.cells.get(tuple(np.floor(point / 60).astype(int)), [])
        if not indices:
            return np.array([], dtype=int), np.array([])
        indices = np.asarray(indices)
        vectors = self.vectors[indices]
        fraction = np.clip(np.sum((point - self.starts[indices]) * vectors, axis=1)
                           / np.maximum(self.squared_lengths[indices], 1e-9), 0, 1)
        distances = np.linalg.norm(point - self.starts[indices] - fraction[:, None] * vectors, axis=1)
        allowed = (distances <= GPS_TOLERANCE_M) & (self.directions[indices] @ direction >= _MIN_DIRECTION_COSINE)
        return indices[allowed], distances[allowed]


def _coverage(first, second, candidates, phase, cyclic):
    # Permit distance-recording differences and a short start/finish variation;
    # do not match a completely different traversal of the same crossing/lap.
    tolerance = max(.03, 75 / max(first.route.length_m, second.route.length_m))
    covered = 0.
    for index, matches in enumerate(candidates):
        offsets = np.abs(second.route.positions[matches] - (first.route.positions[index] + phase))
        if cyclic:
            offsets %= 1
            offsets = np.minimum(offsets, 1 - offsets)
        if np.any(offsets <= tolerance):
            covered += first.route.weights[index]
    return covered / first.route.length_m


def _start_phases(first, second):
    matches, distances = second.matches(first.centers[0], first.directions[0])
    phases = [0.]
    # A handful of distinct starting laps suffices; ambiguous repeated
    # geometries are treated conservatively rather than searched without a bound.
    for index in np.argsort(distances):
        phase = float(second.route.positions[matches[index]] - first.route.positions[0])
        if all(min(abs(phase - previous) % 1, 1 - abs(phase - previous) % 1) > .005 for previous in phases):
            phases.append(phase)
        if len(phases) >= 8:
            break
    return phases


def overlap(first: PreparedRoute, second: PreparedRoute) -> float:
    """Return symmetric covered distance in percent, without rounding at 97%.

    Both GPS lengths and, if present, both reported distances must agree within
    3%. Direction may differ by at most 60 degrees locally. Closed routes may
    start at different points; reversed routes do not count as the same route.
    The 20 m integration resolution leaves about one interval of edge error.
    """
    if min(first.length_m, second.length_m) / max(first.length_m, second.length_m) < MIN_LENGTH_RATIO:
        return 0.
    if first.reported_length_m and second.reported_length_m:
        if min(first.reported_length_m, second.reported_length_m) / max(first.reported_length_m, second.reported_length_m) < MIN_LENGTH_RATIO:
            return 0.
    latitude = float(np.mean([first.centers[:, 1].mean(), second.centers[:, 1].mean()]))
    a, b = _RouteIndex(first, latitude), _RouteIndex(second, latitude)
    ab = [b.matches(point, direction)[0] for point, direction in zip(a.centers, a.directions)]
    ba = [a.matches(point, direction)[0] for point, direction in zip(b.centers, b.directions)]
    cyclic = first.closed and second.closed
    phases = [0.]
    if cyclic:
        # Collect alignments from both starts so argument order cannot change
        # the result when either recording begins near a crossing.
        phases = _start_phases(a, b) + [-phase for phase in _start_phases(b, a)]
    covered = max(min(_coverage(a, b, ab, phase, cyclic), _coverage(b, a, ba, -phase, cyclic)) for phase in phases)
    return float(min(100., max(0., 100 * covered)))
