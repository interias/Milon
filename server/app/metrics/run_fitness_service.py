"""Versioned references and cached, sensor-separated personal running estimates."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from functools import lru_cache
from threading import RLock
from zoneinfo import ZoneInfo

import pandas as pd
from sqlmodel import Session, select

from ..config import INCOMING_DIR, settings
from ..db import engine
from ..models import RunAnalysisCache, RunFitnessReference
from . import run_fitness, run_references
from .run_analysis import _SESSION_SQL

_lock = RLock()
SERVICE_VERSION = "fitness-reference-v1"


@lru_cache(maxsize=2)
def _candidate(path, modified, size, package, day):
    return run_references.observed_hr_reference(path, package, today=date.fromisoformat(day))


def reference_candidate(today):
    path = INCOMING_DIR / "health_connect_export.db"
    if not path.exists():
        return {"status": "unavailable", "candidate_bpm": None,
                "reason": "Health-Connect-Rohdaten für die Belastungsreferenz fehlen."}
    stat = path.stat()
    return _candidate(str(path), stat.st_mtime_ns, stat.st_size,
                      settings.steps_source_package, today.isoformat())


def _load_reference(candidate, now):
    with Session(engine) as session:
        row = session.exec(select(RunFitnessReference).order_by(RunFitnessReference.id.desc())).first()
        if row is None:
            payload = {"max_hr": candidate.get("candidate_bpm"), "rest_hr": 60.0,
                       "rest_source": "Vorläufige Modellannahme, keine Ruhemessung",
                       "provisional": True, "sensor_changes": [],
                       "high_hr_source": "Wiederholt beobachtete Belastungsreferenz; keine gemessene HFmax",
                       "high_hr_evidence": candidate}
            row = RunFitnessReference(created_at=now, payload=json.dumps(payload, ensure_ascii=False))
            session.add(row)
            session.commit()
            session.refresh(row)
        return {**json.loads(row.payload), "revision": row.id, "created_at": row.created_at.isoformat()}


def _equivalent(hr, max_hr, rest_hr, pace_seconds=360):
    if hr is None or max_hr is None or rest_hr is None or not rest_hr < hr <= max_hr:
        return None
    return round(3.5 + (0.2 * 60000 / pace_seconds) * (max_hr - rest_hr) / (hr - rest_hr), 2)


def _convert(result, calibration):
    high, rest = calibration["max_hr"], calibration["rest_hr"]
    for point in result["points"]:
        point["vo2_eq"] = _equivalent(point["hr"], high, rest)
        # The inverse mapping reverses interval endpoints. Never truncate invalid tails.
        lo = _equivalent(point.get("ci_high"), high, rest)
        hi = _equivalent(point.get("ci_low"), high, rest)
        point["vo2_low"], point["vo2_high"] = (lo, hi) if lo is not None and hi is not None else (None, None)
        scenarios = [] if high is None or point["hr"] is None else [
            _equivalent(point["hr"], high + high_delta, rest + rest_delta)
            for high_delta in (-10, 10) for rest_delta in (-10, 10)]
        # Missing corners are not evidence for a narrower sensitivity range.
        scenarios = scenarios if len(scenarios) == 4 and all(v is not None for v in scenarios) else []
        point["vo2_sensitivity_low"] = min(scenarios) if scenarios else None
        point["vo2_sensitivity_high"] = max(scenarios) if scenarios else None
        if point["hr"] is not None and point["vo2_eq"] is None:
            point["reasons"].append("Puls liegt außerhalb der gewählten Reserve-Referenzen; VO₂-Äquivalent fehlt.")
    for point in result["observations"]:
        point["vo2_eq"] = _equivalent(point["hr"], high, rest, point.get("pace_seconds", 360))
    result["vo2_status"] = "unavailable" if high is None else "provisional" if calibration["provisional"] else "estimated"
    result["vo2_caveat"] = (
        "VO₂-Äquivalent aus ebener Laufkosten-Näherung und Herzfrequenzreserve, keine gemessene VO₂max. "
        "Die beobachtete Belastungsreferenz kann unter der tatsächlichen HFmax liegen. "
        "Intervalle gelten nur für die Stichprobe bei festen Modellannahmen, nicht für die physiologische Genauigkeit."
    )


def _analyze_segments(windows, sessions, changes, today):
    boundaries = [date.fromisoformat(c["date"]) for c in changes if date.fromisoformat(c["date"]) <= today]
    boundaries = sorted(set(boundaries))
    results = []
    started = pd.to_datetime(sessions.started_at).dt.date
    for i in range(len(boundaries) + 1):
        lower = boundaries[i - 1] if i else date.min
        upper = boundaries[i] if i < len(boundaries) else None
        part = sessions[(started >= lower) & ((started < upper) if upper else True)]
        if part.empty and upper is not None:
            continue
        endpoint = (pd.Timestamp(upper) - pd.Timedelta(days=1)).date() if upper else today
        data = run_fitness.analyze(windows, part, today=endpoint)
        if not data["points"]:
            data["points"] = [dict(date=endpoint.isoformat(), hr=None, ci_low=None, ci_high=None,
                                   runs=0, local_runs=0, status="insufficient",
                                   reasons=["Noch keine geeigneten Läufe in diesem Sensorabschnitt."])]
        for key in ("points", "observations", "durability"):
            for point in data.get(key, []):
                point["segment_id"] = i
        for series in data.get("pace_series", []):
            for point in series["points"]:
                point["segment_id"] = i
        results.append(data)
    result = dict(results[-1])
    for key in ("points", "observations", "durability"):
        result[key] = [p for data in results for p in data.get(key, [])]
    paces = sorted({s["pace_seconds"] for data in results for s in data.get("pace_series", [])})
    result["pace_series"] = []
    for pace in paces:
        points = []
        for data in results:
            matching = next((s for s in data.get("pace_series", []) if s["pace_seconds"] == pace), None)
            points.extend(matching["points"] if matching else [
                {**p, "hr": None, "ci_low": None, "ci_high": None, "local_runs": 0,
                 "status": "insufficient", "reasons": ["Referenzpace in diesem Sensorabschnitt nicht ausreichend belegt."]}
                for p in data["points"]])
        result["pace_series"].append({"pace_seconds": pace, "reference_minute": 30, "points": points})
    return result


def fitness() -> dict:
    with _lock:
        now = datetime.now(ZoneInfo(settings.timezone))
        candidate = reference_candidate(now.date())
        reference = _load_reference(candidate, now)
        with engine.connect() as con:
            sessions = pd.read_sql(_SESSION_SQL, con, parse_dates=["started_at", "ended_at"])
            windows = pd.read_sql("SELECT external_id, minute, speed_m_min, hr_bpm, coverage, steady "
                                  "FROM run_minutes WHERE model_version='shr-v1' ORDER BY external_id, minute", con)
        fingerprint = hashlib.sha256((SERVICE_VERSION + run_fitness.MODEL_VERSION + now.date().isoformat()
                                      + json.dumps(reference, sort_keys=True) + json.dumps(candidate, sort_keys=True)
                                      + sessions.to_json(date_format="iso") + windows.to_json()).encode()).hexdigest()
        with Session(engine) as session:
            cached = session.get(RunAnalysisCache, "running_fitness")
            if cached and cached.fingerprint == fingerprint:
                return json.loads(cached.payload)
        result = _analyze_segments(windows, sessions, reference["sensor_changes"], now.date())
        _convert(result, reference)
        result["calibration"] = {**reference, "candidate": candidate}
        result["updated_at"] = now.isoformat()
        with Session(engine) as session:
            session.merge(RunAnalysisCache(key="running_fitness", fingerprint=fingerprint,
                                          payload=json.dumps(result, ensure_ascii=False, allow_nan=False)))
            session.commit()
        return result


def update_reference(patch: dict) -> dict:
    with _lock:
        now = datetime.now(ZoneInfo(settings.timezone))
        candidate = reference_candidate(now.date())
        reference = _load_reference(candidate, now)
        reference.pop("revision")
        reference.pop("created_at")
        if "rest_hr" in patch:
            rest = patch["rest_hr"]
            source = patch.get("rest_source", "").strip()
            if not isinstance(rest, (int, float)) or not math.isfinite(rest) or not 25 <= rest <= 120 or not source:
                raise ValueError("Ruhepuls zwischen 25 und 120 und eine Beschreibung der Messung sind erforderlich.")
            reference.update(rest_hr=float(rest), rest_source=source, provisional=False)
        if "max_hr" in patch:
            high = candidate.get("candidate_bpm")
            if high is None or patch["max_hr"] != high:
                raise ValueError("Es kann nur die aktuell geprüfte Belastungsreferenz übernommen werden.")
            if reference["max_hr"] is not None and high <= reference["max_hr"]:
                raise ValueError("Eine neue Belastungsreferenz muss über der bisherigen liegen.")
            reference.update(max_hr=high, high_hr_evidence=candidate)
        if reference["max_hr"] is not None and reference["rest_hr"] >= reference["max_hr"]:
            raise ValueError("Der Ruhepuls muss unter der Belastungsreferenz liegen.")
        if "sensor_change" in patch:
            change = patch["sensor_change"]
            day = date.fromisoformat(change["date"])
            label = change["label"].strip()
            if day > now.date() or not label:
                raise ValueError("Sensorwechsel benötigen ein bisheriges Datum und eine Bezeichnung.")
            changes = {c["date"]: c for c in reference["sensor_changes"]}
            changes[day.isoformat()] = {"date": day.isoformat(), "label": label}
            reference["sensor_changes"] = sorted(changes.values(), key=lambda c: c["date"])
        with Session(engine) as session:
            session.add(RunFitnessReference(created_at=now, payload=json.dumps(reference, ensure_ascii=False)))
            session.commit()
        return fitness()


def standardized_hr() -> dict:
    data = fitness()
    return {"reference_minute": 30, "pace_step_seconds": 30, "window_days": 56,
            "model_version": data["model_version"], "caveat": data["caveat"],
            "empty_reason": "Noch keine ausreichend belegte Referenzpace." if not data["pace_series"] else None,
            "pace_series": [{"pace_seconds": s["pace_seconds"], "comparison": None,
                             "points": [{**p, "month": p["date"], "exploratory_hr": None} for p in s["points"]]}
                            for s in data["pace_series"]], "updated_at": data["updated_at"]}
