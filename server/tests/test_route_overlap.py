import json
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from app.metrics.route_overlap import overlap, prepare_route


def route(xy, *, distance=None, segments=None):
    points = [{"lat": 51 + y / 111195, "lon": 6 + x / (111195 * math.cos(math.radians(51)))} for x, y in xy]
    if distance is None:
        distance = float(np.linalg.norm(np.diff(xy, axis=0), axis=1).sum()) / 1000
    return SimpleNamespace(segments_json=json.dumps(segments if segments is not None else [points]), distance_km=distance)


def line(length=10_000, step=10, offset=0):
    return np.column_stack([np.r_[np.arange(0, length, step), length], np.full(math.ceil(length / step) + 1, offset)])


def circle(radius=400, start=0, center=(0, 0), count=1001):
    angles = np.linspace(start, start + 2 * math.pi, count)
    return np.column_stack([radius * np.cos(angles) + center[0], radius * np.sin(angles) + center[1]])


def score(a, b):
    return overlap(prepare_route(route(a)), prepare_route(route(b)))


def test_same_path_is_independent_of_recording_density_and_stationary_samples():
    sparse = line(step=25)
    dense = np.concatenate([line(step=2)[:2000], np.repeat(line(step=2)[2000:2001], 500, axis=0), line(step=2)[2000:]])
    assert score(sparse, dense) == pytest.approx(100)


def test_jitter_within_explicit_gps_tolerance_matches_but_parallel_road_does_not():
    original = line()
    jitter = original.copy()
    jitter[:, 1] = 3 * np.sin(np.arange(len(jitter)) / 5)
    assert score(original, jitter) >= 99
    assert score(original, line(offset=29)) >= 99
    assert score(original, line(offset=31)) == 0


def test_symmetric_distance_coverage_and_three_percent_length_guard():
    long, short = prepare_route(route(line())), prepare_route(route(line(9701)))
    result = overlap(long, short)
    assert 97 <= result <= 98
    assert overlap(short, long) == pytest.approx(result)
    assert score(line(), line(9699)) == 0


def test_reported_distance_guard_is_additional_to_geometry():
    geometry = line()
    first = prepare_route(route(geometry, distance=10))
    second = prepare_route(route(geometry, distance=10.4))
    assert first is not None and second is not None
    assert overlap(first, second) == 0


def test_reverse_direction_and_an_extra_lap_are_not_the_same_route():
    loop = circle()
    assert score(loop, loop[::-1]) == 0
    assert score(line(), line()[::-1]) == 0
    assert score(loop, np.concatenate([loop, loop[1:]])) == 0


def test_closed_loop_can_start_at_a_different_position():
    assert score(circle(), circle(start=1.2)) >= 99


@pytest.mark.parametrize("shift", [.05, .5, 1.2, 2.1, 3.1])
def test_closed_route_overlap_is_symmetric_despite_start_and_recording_density(shift):
    a = circle()
    b = circle(start=shift, count=501)
    b[:, 0] += 20
    assert score(a, b) == pytest.approx(score(b, a), abs=1e-9)


def test_dense_maximum_recording_is_resampled_before_spatial_comparison():
    coordinates = np.column_stack([np.linspace(0, 10_000, 100_000), np.zeros(100_000)])
    prepared = prepare_route(route(coordinates))
    assert prepared is not None
    assert len(prepared.centers) <= 501
    assert overlap(prepared, prepare_route(route(line()))) == pytest.approx(100)
    excessive = np.vstack([coordinates, coordinates[-1]])
    assert prepare_route(route(excessive)) is None


def test_out_and_back_keeps_both_directions():
    outward = line(length=3000)
    returning = np.concatenate([outward, outward[-2::-1]])
    shifted = returning.copy()
    shifted[:, 1] += 4
    assert score(returning, shifted) >= 99


def test_coverage_respects_changed_lap_multiplicity():
    left = circle(radius=250, center=(-250, 0))
    right = circle(radius=250, center=(250, 0), start=math.pi)
    first = np.concatenate([left, left[1:], right[1:]])
    second = np.concatenate([left, right[1:], right[1:]])
    assert score(first, second) < 90


def test_local_detour_loses_distance_coverage_instead_of_counting_only_endpoints():
    original = line()
    slight = original.copy()
    slight[:, 1] = np.maximum(0, 60 * (1 - np.abs(slight[:, 0] - 5000) / 200))
    larger = original.copy()
    larger[:, 1] = np.maximum(0, 120 * (1 - np.abs(larger[:, 0] - 5000) / 300))
    assert score(original, slight) >= 97
    assert score(original, larger) < 97


@pytest.mark.parametrize("segments", [None, {}, [], [[], []], [[{"lat": 51, "lon": 6}]], [[None] * 20],
    [[{"lat": True, "lon": 6}] * 20], [[{"lat": float("nan"), "lon": 6}] * 20],
    [[{"lat": 91, "lon": 6}] * 20], [[{"lat": 10 ** 400, "lon": 6}] * 20]])
def test_malformed_or_interrupted_geometry_is_not_prepared(segments):
    assert prepare_route(SimpleNamespace(segments_json=json.dumps(segments), distance_km=10)) is None


def test_missing_broken_short_or_inconsistent_geometry_is_not_prepared():
    assert prepare_route(None) is None
    assert prepare_route(SimpleNamespace(segments_json="{", distance_km=10)) is None
    assert prepare_route(route(line(length=500))) is None
    assert prepare_route(route(line(), distance=5)) is None
    jumping = line()
    jumping[400, 1] = 200
    assert prepare_route(route(jumping)) is None


def test_moving_recording_gap_is_not_joined_but_stationary_pause_is_allowed():
    candidate = route(line())
    segments = json.loads(candidate.segments_json)
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for index, point in enumerate(segments[0]):
        point["time"] = (start + timedelta(seconds=index * 3 + (90 if index >= 500 else 0))).isoformat()
    segments[0][500]["lon"] = segments[0][499]["lon"]
    candidate.segments_json = json.dumps(segments)
    assert prepare_route(candidate) is not None
    segments[0][500]["lon"] = segments[0][499]["lon"] + 100 / (111195 * math.cos(math.radians(51)))
    candidate.segments_json = json.dumps(segments)
    assert prepare_route(candidate) is None
