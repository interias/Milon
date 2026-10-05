"""Source-owned Garmin days and conservative projection into canonical watch metrics."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import inspect
from sqlmodel import Field, Session, SQLModel, select

from .config import settings, watch_source_for
from .db import engine
from .models import SleepSession, StepsDaily, Vo2Max

SOURCE = "garmin_direct"
PACKAGE = "com.garmin.android.apps.connectmobile"
METHODS = {"summary": "get_user_summary", "sleep": "get_sleep_data", "hrv": "get_hrv_data",
           "vo2": "get_max_metrics", "readiness": "get_training_readiness"}


class GarminDaily(SQLModel, table=True):
    __tablename__ = "garmin_daily"

    day: date = Field(primary_key=True)
    normalized_json: str = "{}"
    raw_json: str = "{}"
    status_json: str = "{}"
    synced_at: datetime | None = None
    parser_version: int = 1


class GarminDailySync(SQLModel, table=True):
    __tablename__ = "garmin_daily_sync"

    key: str = Field(default="daily", primary_key=True)
    attempted_at: datetime


def _number(value, minimum=0, maximum=1_000_000) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and minimum <= number <= maximum else None
    except (TypeError, ValueError, OverflowError):
        return None


def _utc(value) -> datetime | None:
    """These call sites exclusively use explicitly GMT fields, never local pseudo-epochs."""
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value / 1000, timezone.utc)
        if isinstance(value, str) and value:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def _eligible(day: date) -> bool:
    return watch_source_for(day, settings) == PACKAGE


def _summary(payload, day: date) -> dict:
    if not isinstance(payload, dict) or payload.get("calendarDate") != day.isoformat():
        return {}
    steps = _number(payload.get("totalSteps"), 0, 200_000)
    if payload.get("includesWellnessData") is False or (steps == 0 and payload.get("includesWellnessData") is not True):
        steps = None
    return {"steps": int(steps) if steps is not None else None,
            "rhr_bpm": _number(payload.get("restingHeartRate"), 25, 200),
            "stress": _number(payload.get("averageStressLevel"), 0, 100),
            "body_battery": _number(payload.get("bodyBatteryMostRecentValue"), 0, 100)}


def _sleep(payload, day: date) -> dict:
    if not isinstance(payload, dict):
        return {}
    dto = payload.get("dailySleepDTO") or {}
    if not isinstance(dto, dict):
        return {}
    start, end = _utc(dto.get("sleepStartTimestampGMT")), _utc(dto.get("sleepEndTimestampGMT"))
    if start is None or end is None or end <= start:
        return {}
    zone = ZoneInfo(settings.timezone)
    waking_day = end.astimezone(zone).date()
    window = (end - start).total_seconds()
    if waking_day != day or not 60 <= window <= 24 * 3600:
        return {}
    # Garmin's sampled level durations agree with DTO totals: 0 deep, 1 light, 2 REM, 3 awake.
    # Reject overlapping intervals instead of manufacturing coverage from duplicated stages.
    levels = payload.get("sleepLevels") or []
    known, asleep, awake, overlap = 0.0, 0.0, 0.0, False
    intervals = []
    for level in levels if isinstance(levels, list) else []:
        if not isinstance(level, dict):
            continue
        left, right = _utc(level.get("startGMT")), _utc(level.get("endGMT"))
        code = level.get("activityLevel")
        if left is None or right is None or right <= left:
            continue
        left, right = max(left, start), min(right, end)
        if right > left:
            intervals.append((left, right, code))
    previous_end = None
    for left, right, code in sorted(intervals, key=lambda item: item[:2]):
        if previous_end is not None and left < previous_end:
            overlap = True
        previous_end = max(previous_end or right, right)
        seconds = (right - left).total_seconds()
        if code in (0, 1, 2, 3):
            known += seconds
            asleep += seconds if code != 3 else 0
            awake += seconds if code == 3 else 0
    if not levels:
        # Explicit aggregate stage durations also establish coverage; an interval alone never does.
        totals = [_number(dto.get(key), 0, 86400) for key in
                  ("deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds", "awakeSleepSeconds")]
        if all(value is not None for value in totals):
            asleep, awake = sum(totals[:3]), totals[3]
            known = asleep + awake
    coverage = known / window if not overlap and known <= window + 1 else 0.0
    reported = _number(dto.get("sleepTimeSeconds"), 0, 86400)
    consistent = reported is None or abs(reported - asleep) <= max(60, reported * .01)
    complete = .98 <= coverage <= 1.0001 and consistent and asleep > 0
    scores = dto.get("sleepScores") or {}
    overall = scores.get("overall") or {} if isinstance(scores, dict) else {}
    return {"started_at": start.astimezone(zone).replace(tzinfo=None).isoformat(),
            "ended_at": end.astimezone(zone).replace(tzinfo=None).isoformat(),
            "started_at_utc": start.isoformat(), "ended_at_utc": end.isoformat(),
            "duration_window_minutes": window / 60, "stage_coverage": min(1.0, coverage),
            "asleep_minutes": asleep / 60 if complete else None,
            "awake_minutes": awake / 60 if complete else None,
            "main_sleep": window >= 7200,
            "sleep_score": _number(overall.get("value"), 0, 100) if isinstance(overall, dict) else None}


def _hrv(payload, day: date) -> dict:
    if not isinstance(payload, dict):
        return {}
    summary = payload.get("hrvSummary") or {}
    if not isinstance(summary, dict) or summary.get("calendarDate") != day.isoformat():
        return {}
    baseline = summary.get("baseline") or {}
    baseline = baseline if isinstance(baseline, dict) else {}
    status = summary.get("status")
    status = status if isinstance(status, str) and status.upper() not in {"NONE", "UNKNOWN", "NO_DATA"} else None
    end = _utc(payload.get("sleepEndTimestampGMT")) or _utc(payload.get("endTimestampGMT"))
    return {"hrv_ms": _number(summary.get("lastNightAvg"), 1, 500),
            "measured_at": end.isoformat() if end else None,
            "baseline_low_ms": _number(baseline.get("balancedLow"), 1, 500),
            "baseline_high_ms": _number(baseline.get("balancedUpper"), 1, 500),
            "hrv_status": status}


def _vo2(payload, day: date) -> dict:
    for item in payload if isinstance(payload, list) else [payload]:
        generic = item.get("generic") if isinstance(item, dict) else None
        if not isinstance(generic, dict) or generic.get("calendarDate") != day.isoformat():
            continue
        value = _number(generic.get("vo2MaxPreciseValue"), 5, 100)
        if value is None:
            value = _number(generic.get("vo2MaxValue"), 5, 100)
        if value is not None:
            return {"vo2": value}
    return {}


def _readiness(payload, day: date) -> dict:
    candidates = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or item.get("calendarDate") != day.isoformat():
            continue
        timestamp = _utc(item.get("timestamp"))
        score = _number(item.get("score"), 0, 100)
        if timestamp is not None and score is not None and item.get("primaryActivityTracker") is not False:
            candidates.append((timestamp, item))
    if not candidates:
        return {}
    timestamp, value = max(candidates, key=lambda pair: pair[0])
    recovery = _number(value.get("recoveryTime"), 0, 60 * 168)
    return {"readiness": _number(value.get("score"), 0, 100), "readiness_at": timestamp.isoformat(),
            "recovery_hours": recovery / 60 if recovery is not None else None,
            "context": value.get("inputContext") if isinstance(value.get("inputContext"), str) else None}


NORMALIZERS = {"summary": _summary, "sleep": _sleep, "hrv": _hrv, "vo2": _vo2, "readiness": _readiness}


def _has_values(category: str, normalized: dict) -> bool:
    keys = {"summary": ("steps", "rhr_bpm", "stress", "body_battery"), "sleep": ("started_at",),
            "hrv": ("hrv_ms",), "vo2": ("vo2",), "readiness": ("readiness",)}
    return any(normalized.get(key) is not None for key in keys[category])


def sync_daily(api, full: bool = False, *, force: bool = False, now: datetime | None = None) -> dict:
    """Use the caller's authenticated client and import lock; never manage tokens here."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp, today = now.replace(tzinfo=None), now.astimezone(ZoneInfo(settings.timezone)).date()
    cutoff = settings.watch_source_switch_date or today - timedelta(days=89)
    start = cutoff if full else max(cutoff, today - timedelta(days=89))
    with Session(engine) as session:
        cursor = session.get(GarminDailySync, "daily")
        if not full and not force and cursor and stamp - cursor.attempted_at < timedelta(hours=1):
            return {"mode": "throttled", "days": 0, "requests": 0, "errors": 0}
        days, retries = [], 0
        for offset in range(max(0, (today - start).days + 1)):
            day = start + timedelta(days=offset)
            previous = session.get(GarminDaily, day)
            failed = previous is not None and any(status.get("status") == "error" for status in json.loads(previous.status_json).values())
            retry = failed and retries < 7
            if _eligible(day) and (full or day >= today - timedelta(days=2) or previous is None or retry):
                days.append(day)
                if retry and day < today - timedelta(days=2):
                    retries += 1
        if not days:
            return {"mode": "no_days", "days": 0, "requests": 0, "errors": 0}
        session.add(GarminDailySync(key="daily", attempted_at=stamp) if cursor is None else cursor)
        if cursor:
            cursor.attempted_at = stamp
        session.commit()
    result = {"mode": "full" if full else "incremental", "days": 0, "requests": 0, "errors": 0,
              "available": 0, "empty": 0, "unsupported": 0}
    for day in days:
        with Session(engine) as session:
            row = session.get(GarminDaily, day) or GarminDaily(day=day)
            normalized, raw, statuses = (json.loads(row.normalized_json), json.loads(row.raw_json), json.loads(row.status_json))
            for category, method_name in METHODS.items():
                status = statuses.get(category, {})
                status["attempted_at"] = now.isoformat()
                method = getattr(api, method_name, None)
                if not callable(method):
                    status["status"] = "unsupported"
                    result["unsupported"] += 1
                else:
                    result["requests"] += 1
                    try:
                        payload = method(day.isoformat())
                        value = NORMALIZERS[category](payload, day)
                        # Serialize inside the guarded path: provider schema changes are partial failures.
                        json.dumps(payload, allow_nan=False)
                        raw[category] = payload
                        if _has_values(category, value):
                            previous = normalized.get(category, {})
                            if category == "sleep" and previous.get("asleep_minutes") is not None and value.get("asleep_minutes") is None:
                                # A new incomplete window does not refresh the age of an older complete night.
                                status["status"] = "empty"
                                result["empty"] += 1
                            else:
                                observations = dict(previous.get("_observed_at", {}))
                                observations.update({key: now.isoformat() for key, item in value.items() if item is not None})
                                merged = {**previous, **{key: item for key, item in value.items() if item is not None}}
                                if category == "hrv":
                                    for key in ("baseline_low_ms", "baseline_high_ms", "hrv_status"):
                                        merged[key] = value.get(key)
                                merged["_observed_at"] = observations
                                normalized[category] = merged
                                status.update(status="available", last_success_at=now.isoformat())
                                row.synced_at = stamp
                                result["available"] += 1
                        else:
                            status["status"] = "empty"
                            result["empty"] += 1
                    except Exception:
                        # Only category/count statuses escape this boundary, never raw responses or tokens.
                        status["status"] = "error"
                        result["errors"] += 1
                statuses[category] = status
            row.normalized_json = json.dumps(normalized, allow_nan=False)
            row.raw_json = json.dumps(raw, allow_nan=False)
            row.status_json = json.dumps(statuses)
            session.add(row)
            session.commit()
            result["days"] += 1
    with Session(engine) as session:
        result["canonical"] = apply_daily(session)
        session.commit()
    return result


def apply_daily(session: Session) -> dict:
    """Restore direct priority after HC upserts in the same transaction; preserve older sensors."""
    result = {"steps": 0, "sleep": 0, "vo2": 0}
    if not inspect(session.connection()).has_table(GarminDaily.__tablename__):
        return result
    for row in session.exec(select(GarminDaily).order_by(GarminDaily.day)).all():
        if not _eligible(row.day):
            continue
        values = json.loads(row.normalized_json)
        steps = values.get("summary", {}).get("steps")
        if steps is not None:
            target = session.get(StepsDaily, row.day)
            if target is None:
                target = StepsDaily(day=row.day, steps=steps, source=SOURCE)
            elif target.source not in {"health_connect", SOURCE}:
                target = None
            if target is not None:
                target.steps, target.source = steps, SOURCE
                session.add(target)
                result["steps"] += 1
        sleep = values.get("sleep")
        if sleep:
            start, end = datetime.fromisoformat(sleep["started_at"]), datetime.fromisoformat(sleep["ended_at"])
            candidates = session.exec(select(SleepSession).where(SleepSession.day == row.day,
                                      SleepSession.source_package == PACKAGE)).all()
            matches = []
            for candidate in candidates:
                overlap = max(0, (min(end, candidate.ended_at) - max(start, candidate.started_at)).total_seconds())
                smaller = min(sleep["duration_window_minutes"], candidate.duration_window_minutes) * 60
                if overlap >= smaller * .5 and smaller > 0:
                    matches.append(candidate)
            known_hc = any(candidate.source == "health_connect" and candidate.asleep_minutes is not None for candidate in matches)
            if sleep.get("asleep_minutes") is not None or not known_hc:
                external_id = f"garmin-sleep:{row.day.isoformat()}"
                target = next((candidate for candidate in candidates if candidate.external_id == external_id), None)
                for candidate in matches:
                    if candidate.source == "health_connect":
                        session.delete(candidate)
                fields = {key: sleep[key] for key in ("duration_window_minutes", "stage_coverage", "main_sleep")}
                fields.update(asleep_minutes=sleep.get("asleep_minutes"), awake_minutes=sleep.get("awake_minutes"),
                              started_at=start, ended_at=end, day=row.day, source=SOURCE)
                if target is None:
                    target = SleepSession(external_id=external_id, source_package=PACKAGE, **fields)
                else:
                    for key, value in fields.items():
                        setattr(target, key, value)
                session.add(target)
                result["sleep"] += 1
        vo2 = values.get("vo2", {}).get("vo2")
        if vo2 is not None:
            start = datetime.combine(row.day, time.min)
            candidates = session.exec(select(Vo2Max).where(Vo2Max.measured_at >= start,
                                      Vo2Max.measured_at < start + timedelta(days=1))).all()
            # Direct maxima carry date resolution, not a fabricated workout timestamp.
            target = next((candidate for candidate in candidates if candidate.source == SOURCE), None)
            foreign = any(candidate.source not in {SOURCE, "health_connect"} for candidate in candidates)
            if not foreign:
                for candidate in candidates:
                    if candidate is not target:
                        session.delete(candidate)
                session.flush()
                if target is None:
                    target = Vo2Max(measured_at=start, vo2=vo2, source=SOURCE)
                else:
                    target.vo2 = vo2
                session.add(target)
                result["vo2"] += 1
    session.flush()
    return result


def recovery(days: int = 30, *, now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = now.astimezone(ZoneInfo(settings.timezone)).date()
    with Session(engine) as session:
        rows = session.exec(select(GarminDaily).where(GarminDaily.day >= today - timedelta(days=days - 1),
                            GarminDaily.day <= today).order_by(GarminDaily.day)).all()
    rows = [row for row in rows if _eligible(row.day)]
    keys = ("hrv_ms", "rhr_bpm", "readiness", "recovery_hours", "body_battery", "stress", "sleep_hours", "sleep_score")
    latest, series = dict.fromkeys(keys), []
    availability = {category: {"status": "never", "attempted_at": None, "last_success_at": None} for category in METHODS}
    for row in rows:
        data, statuses = json.loads(row.normalized_json), json.loads(row.status_json)
        summary, hrv, sleep, readiness = (data.get(key, {}) for key in ("summary", "hrv", "sleep", "readiness"))
        point = {"date": row.day.isoformat(), "provisional": row.day == today,
                 "hrv_ms": hrv.get("hrv_ms"), "rhr_bpm": summary.get("rhr_bpm"),
                 "readiness": readiness.get("readiness"), "readiness_at": readiness.get("readiness_at"),
                 "recovery_hours": readiness.get("recovery_hours"), "body_battery": summary.get("body_battery"),
                 "stress": summary.get("stress"),
                 "sleep_hours": sleep["asleep_minutes"] / 60 if sleep.get("asleep_minutes") is not None else None,
                 "sleep_score": sleep.get("sleep_score"), "baseline_low_ms": hrv.get("baseline_low_ms"),
                 "baseline_high_ms": hrv.get("baseline_high_ms"), "hrv_status": hrv.get("hrv_status")}
        if any(point[key] is not None for key in keys):
            series.append(point)
        for category, status in statuses.items():
            if category in availability:
                successes = [value for value in (availability[category]["last_success_at"], status.get("last_success_at")) if value]
                availability[category] = {"status": status.get("status", "never"),
                                          "attempted_at": status.get("attempted_at"),
                                          "last_success_at": max(successes) if successes else None}
        for key in keys:
            if point[key] is None:
                continue
            category = "hrv" if key == "hrv_ms" else "sleep" if key.startswith("sleep_") else "readiness" if key in {"readiness", "recovery_hours"} else "summary"
            status = statuses.get(category, {})
            data_key = "asleep_minutes" if key == "sleep_hours" else key
            synced_at = data.get(category, {}).get("_observed_at", {}).get(data_key) or status.get("last_success_at")
            synced = _utc(synced_at)
            measured = hrv.get("measured_at") if category == "hrv" else sleep.get("ended_at_utc") if category == "sleep" else readiness.get("readiness_at") if category == "readiness" else None
            metric = {"value": point[key], "date": point["date"], "measured_at": measured,
                      "synced_at": synced_at or _iso(row.synced_at), "provisional": point["provisional"],
                      "stale": row.day < today - timedelta(days=1) or synced is None or now - synced > timedelta(hours=24) or status.get("status") == "error"}
            if key == "hrv_ms":
                low, high = point["baseline_low_ms"], point["baseline_high_ms"]
                metric.update(baseline_low_ms=low, baseline_high_ms=high, status=point["hrv_status"],
                              baseline_ready=low is not None and high is not None and low <= high and point["hrv_status"] is not None)
            latest[key] = metric
    updated = max((row.synced_at for row in rows if row.synced_at is not None), default=None)
    stale = updated is None or now - updated.replace(tzinfo=timezone.utc) > timedelta(hours=24)
    return {"source": SOURCE, "updated_at": _iso(updated), "stale": stale, "series": series, "latest": latest,
            "coverage": {"days": len(series), "hrv_nights": sum(p["hrv_ms"] is not None for p in series),
                         "resting_hr_days": sum(p["rhr_bpm"] is not None for p in series),
                         "sleep_nights": sum(p["sleep_hours"] is not None for p in series)},
            "availability": availability,
            "notes": ["Garmin-Schätzwerte; Readiness und Body Battery verwenden teilweise dieselben Eingangsdaten.",
                      "Garmin-Ruhepuls bleibt getrennt von den bisherigen HC-Ruhepuls-Einträgen.",
                      "Ohne persönliche HRV-Baseline wird kein Erholungsurteil abgeleitet.",
                      "Heute ist vorläufig; fehlende Werte werden nicht als null Messwert ergänzt."]}


def coach_summary(days: int = 14) -> dict:
    value = recovery(days)
    return {"source": value["source"], "latest": value["latest"], "coverage": value["coverage"],
            "stale": value["stale"], "notes": value["notes"]}
