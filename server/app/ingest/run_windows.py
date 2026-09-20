"""Source-matched, measured minute windows for experimental running analysis."""
from __future__ import annotations

import logging
import math
import sqlite3

import numpy as np

log = logging.getLogger(__name__)
MODEL_VERSION = "shr-v1"


def _series(con, table, parent, field, app_ids, start, end, limits):
    marks = ",".join("?" for _ in app_ids)
    # Aggregate duplicates before interpolation; invalid readings retain their time
    # position so removing them cannot bridge a sensor failure.
    rows = con.execute(
        f'SELECT s.epoch_millis, s.{field} FROM "{table}" s '
        f'JOIN "{parent}" p ON p.row_id=s.parent_key '
        f'WHERE p.app_info_id IN ({marks}) AND s.epoch_millis >= ? '
        'AND s.epoch_millis <= ? ORDER BY s.epoch_millis', (*app_ids, start, end),
    )
    times, values, group = [], [], []
    previous = None
    for stamp, value in rows:
        try:
            stamp, value = float(stamp), float(value)
        except (TypeError, ValueError, OverflowError):
            try:
                stamp = float(stamp)
            except (TypeError, ValueError, OverflowError):
                continue
            value = float("nan")
        if not math.isfinite(stamp):
            continue
        if previous is not None and stamp != previous:
            times.append(previous)
            values.append(group[0] if len(group) == 1 else float(np.median(group)))
            group = []
        previous = stamp
        group.append(value if math.isfinite(value) and limits[0] <= value <= limits[1]
                     else float("nan"))
    if group:
        times.append(previous)
        values.append(group[0] if len(group) == 1 else float(np.median(group)))
    return np.asarray(times), np.asarray(values)


def _interpolate(times, values, grid):
    result = np.full(len(grid), np.nan)
    if len(times) < 2:
        return result
    right = np.searchsorted(times, grid, side="right")
    inside = (right > 0) & (right < len(times))
    right = right.clip(1, len(times) - 1)
    left = right - 1
    valid = inside & (times[right] - times[left] <= 15_000)
    valid &= np.isfinite(values[left]) & np.isfinite(values[right])
    result[valid] = (values[left[valid]] + (values[right[valid]] - values[left[valid]])
                     * (grid[valid] - times[left[valid]])
                     / (times[right[valid]] - times[left[valid]]))
    return result


def read_run_windows(con: sqlite3.Connection, sessions: list[dict], source_package: str) -> dict:
    """Read complete UTC minute bins without falling back to other applications.

    Only session_ids represented in both raw series may replace stored windows.
    Missing tables/source/session samples leave previous windows intact.
    """
    unavailable = {"rows": [], "session_ids": [], "available": False}
    if not source_package:
        return unavailable
    wanted = {str(s["external_id"]) for s in sessions if s.get("exercise_type") == 33}
    if not wanted:
        return unavailable
    try:
        apps = [r[0] for r in con.execute(
            "SELECT row_id FROM application_info_table WHERE package_name=?", (source_package,))]
        if not apps:
            return unavailable
        marks = ",".join("?" for _ in apps)
        raw = con.execute(
            "SELECT uuid,start_time,end_time FROM exercise_session_record_table "
            f"WHERE exercise_type=33 AND app_info_id IN ({marks})", apps)
        matched = []
        for uuid, start, end in raw:
            external_id = uuid.hex() if isinstance(uuid, (bytes, bytearray)) else str(uuid)
            if external_id not in wanted:
                continue
            try:
                start, end = float(start), float(end)
            except (TypeError, ValueError, OverflowError):
                continue
            # Corrupt timestamps must not allocate unbounded windows (seven days).
            if not (math.isfinite(start) and math.isfinite(end)
                    and 0 < end - start <= 7 * 24 * 3600 * 1000):
                continue
            matched.append((external_id, start, end))
        if not matched:
            return unavailable
        first, last = min(r[1] for r in matched), max(r[2] for r in matched)
        speed_t, speed_v = _series(con, "speed_record_table", "SpeedRecordTable", "speed",
                                   apps, first, last, (0, 12))
        hr_t, hr_v = _series(con, "heart_rate_record_series_table", "heart_rate_record_table",
                             "beats_per_minute", apps, first, last, (25, 250))
    except sqlite3.Error as exc:
        log.warning("Minute-window source unavailable: %s", exc)
        return unavailable
    if not len(speed_t) or not len(hr_t):
        return unavailable

    rows, session_ids = [], []
    for external_id, start, end in matched:
        si = np.searchsorted(speed_t, [start, end], side="left")
        hi = np.searchsorted(hr_t, [start, end], side="left")
        st, sv = speed_t[si[0]:si[1]], speed_v[si[0]:si[1]]
        ht, hv = hr_t[hi[0]:hi[1]], hr_v[hi[0]:hi[1]]
        if not len(st) or not len(ht):
            continue
        session_ids.append(external_id)
        for minute in range(int((end - start) // 60_000)):
            grid = start + minute * 60_000 + (np.arange(60) + 0.5) * 1000
            speed, hr = _interpolate(st, sv, grid), _interpolate(ht, hv, grid)
            valid = np.isfinite(speed) & np.isfinite(hr)
            coverage = float(valid.mean())
            mean_speed = float(speed[valid].mean()) if valid.any() else None
            mean_hr = float(hr[valid].mean()) if valid.any() else None
            spread = float(np.ptp(np.quantile(speed[valid], [0.1, 0.9]))) if valid.any() else None
            steady = (coverage >= 0.9 and mean_speed is not None
                      and 2 <= mean_speed <= 8 and spread <= 0.5)
            rows.append({"external_id": external_id, "minute": minute + 0.5,
                         "speed_m_min": mean_speed * 60 if mean_speed is not None else None,
                         "hr_bpm": mean_hr, "coverage": coverage, "steady": bool(steady),
                         "source": "health_connect", "model_version": MODEL_VERSION})
    return {"rows": rows, "session_ids": session_ids, "available": bool(session_ids)}
