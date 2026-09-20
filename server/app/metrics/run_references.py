"""Observed, sustained exercise-HR reference proposals, never physiological HRmax."""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3

import numpy as np

from app.ingest.run_windows import _series

METHOD_VERSION = "sustained-hr-v1"


def observed_hr_reference(path: str | Path, source_package: str, *, today: date | None = None) -> dict:
    """Propose a fixed reference from corroborated high-HR minutes on distinct days.

    Engineering quality rules, not a validated HRmax estimator: complete 60-second
    coverage, gaps <=5 seconds, no jumps >15 bpm, within-minute P90-P10 <=12 bpm.
    The minute's P10 is its sustained level; two days must agree within 3 bpm.
    Selecting the lower corroborating level avoids using a lone record. The 140
    bpm floor merely rejects obviously low-effort candidates. Optical artifacts
    sustained across a minute can still pass, so every proposal is provisional.
    This function reads only and never changes an accepted reference.
    """
    result = {
        "status": "unavailable", "candidate_bpm": None,
        "source_package": source_package, "method_version": METHOD_VERSION,
        "evidence": [], "qualifying_days": 0,
        "reason": "raw_source_unavailable",
        "rules": {"window_seconds": 60, "maximum_gap_seconds": 5,
                  "maximum_sample_jump_bpm": 15, "maximum_p90_p10_bpm": 12,
                  "minimum_sustained_bpm": 140, "corroborating_days": 2,
                  "corroboration_tolerance_bpm": 3, "sustained_percentile": 10},
        "caveat": "Observed exercise reference, not measured HRmax; sustained sensor artifacts remain possible.",
    }
    path = Path(path)
    if not path.is_file() or not source_package:
        return result
    today = today or datetime.now(timezone.utc).date()
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
            apps = [r[0] for r in con.execute(
                "SELECT row_id FROM application_info_table WHERE package_name=?", (source_package,))]
            if not apps:
                result["reason"] = "source_package_missing"
                return result
            marks = ",".join("?" for _ in apps)
            columns = {r[1] for r in con.execute("PRAGMA table_info(exercise_session_record_table)")}
            offset = "COALESCE(start_zone_offset,0)" if "start_zone_offset" in columns else "0"
            sessions = con.execute(
                f"SELECT uuid,start_time,end_time,exercise_type,{offset} "
                f"FROM exercise_session_record_table WHERE app_info_id IN ({marks}) "
                "AND end_time > start_time ORDER BY start_time", apps).fetchall()
            sessions = [s for s in sessions if s[1] is not None and s[2] - s[1] <= 86400000
                        and s[1] >= 0 and datetime.fromtimestamp(
                            (s[1] + s[4] * 1000) / 1000, timezone.utc).date() <= today]
            if not sessions:
                result["reason"] = "exercise_sessions_missing"
                return result
            times, values = _series(con, "heart_rate_record_series_table", "heart_rate_record_table",
                                    "beats_per_minute", apps, min(s[1] for s in sessions),
                                    max(s[2] for s in sessions), (25, 230))
    except (sqlite3.Error, ValueError, OverflowError, OSError):
        result["reason"] = "raw_schema_or_data_unavailable"
        return result

    daily = {}
    for session_id, start, end, exercise_type, offset in sessions:
        first, last = np.searchsorted(times, [start, end], side="left")
        ts, hr = times[first:last + 1], values[first:last + 1]
        inside = (ts >= start) & (ts <= end)
        ts, hr = ts[inside], hr[inside]
        if len(ts) < 13:
            continue
        best = None
        for window_start in range(int(start), int(end) - 60000 + 1, 10000):
            left = np.searchsorted(ts, window_start, side="right") - 1
            right = np.searchsorted(ts, window_start + 60000, side="left")
            if left < 0 or right >= len(ts):
                continue
            wt, wh = ts[left:right + 1], hr[left:right + 1]
            if (not np.isfinite(wh).all() or np.max(np.diff(wt)) > 5000
                    or np.max(np.abs(np.diff(wh))) > 15):
                continue
            samples = np.interp(np.arange(window_start, window_start + 60001, 1000), wt, wh)
            low, high = np.percentile(samples, [10, 90])
            if low < 140 or high - low > 12:
                continue
            if best is None or low > best[0]:
                best = (float(low), window_start)
        if best is None:
            continue
        day = datetime.fromtimestamp((best[1] + offset * 1000) / 1000, timezone.utc).date()
        if day > today:
            continue
        item = {"date": day.isoformat(), "session_id": session_id.hex()
                if isinstance(session_id, bytes) else str(session_id), "exercise_type": exercise_type,
                "sustained_bpm": round(best[0], 1), "duration_seconds": 60,
                "window_start_epoch_ms": best[1]}
        # Mirrors and multiple workouts on the same day never add corroboration.
        if day not in daily or item["sustained_bpm"] > daily[day]["sustained_bpm"]:
            daily[day] = item
    ranked = sorted(daily.values(), key=lambda item: item["sustained_bpm"], reverse=True)
    result.update(status="insufficient_data", reason="no_corroborated_high_hr", qualifying_days=len(ranked))
    for first, second in zip(ranked, ranked[1:]):
        if first["sustained_bpm"] - second["sustained_bpm"] <= 3:
            result.update(status="candidate", reason=None, candidate_bpm=second["sustained_bpm"],
                          evidence=[first, second])
            break
    return result
