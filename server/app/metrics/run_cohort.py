"""Describe one run against all other eligible recordings of the same route."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy.orm import defer
from sqlmodel import Session, select

from ..config import settings
from ..db import engine
from ..garmin_activity import GarminActivity
from ..garmin_routes import GarminRoute
from ..run_reference import _boundaries, _period
from . import run_insights as insights
from .route_overlap import GPS_TOLERANCE_M, MIN_LENGTH_RATIO, overlap, prepare_route

THRESHOLD_PCT = 97
METHOD = (
    "Alle anderen vollständigen, freigegebenen Garmin-Läufe derselben eingetragenen Sensorperiode, "
    "auch spätere Läufe als der ausgewählte. Ausgeschlossene und als Sonderlauf markierte "
    "Aufzeichnungen bleiben draußen. Mindestens 97 % beidseitige, längengewichtete "
    "Streckenüberdeckung mit 30 m GPS-Toleranz, gleicher Laufrichtung und ähnlicher Streckenlänge "
    "(kürzere/längere Distanz mindestens 97 %). Die Geometrie wird in 20-m-Abschnitten geprüft; "
    "die Prozentzahl ist eine Näherung, keine GPS-Genauigkeit. Lokale Richtungen dürfen "
    "höchstens 60° und Positionen im Verlauf höchstens 3 % oder 75 m auseinanderliegen; "
    "geschlossene Runden dürfen versetzt starten. Jeder Lauf zählt einmal; "
    "mehrere Garmin-IDs derselben kanonischen Einheit werden entdoppelt. Der ausgewählte Lauf "
    "gehört nicht zur Vergleichsgruppe. Pace = aktive Garmin-Dauer / Distanz, "
    "Puls = Garmin-Durchschnitt des gesamten Laufs. Fehlende Werte bleiben je Kennzahl außen vor. "
    "Punkte zeigen einzelne Läufe, die Linie Minimum bis Maximum und die Markierung den Median. "
    "Ab fünf Vergleichswerten zeigt das Band die mittleren 50 % (linear interpoliertes 25./75. Perzentil). "
    "Das ist eine Darstellungsregel, keine statistische Mindestgröße. Die Streuung ist kein "
    "Konfidenzintervall und kein Signifikanztest. Wetter, Trainingsziel und Tagesform können "
    "Tempo und Puls verändern; daraus allein folgt keine Fitnessverbesserung."
)


def _brief(row, summary):
    distance, duration, hr = (summary.get(key) for key in ("distance_km", "duration_seconds", "avg_hr"))
    pace = duration / distance if all(insights._number(value) and value > 0 for value in (distance, duration)) else None
    return {"activity_id": row.activity_id, "title": summary.get("title") or "Lauf",
            "started_at": row.started_at.isoformat(), "distance_km": distance,
            "pace_seconds": pace, "avg_hr": hr if insights._number(hr) and 25 <= hr <= 250 else None}


def distribution(selected, values):
    """Run-level observations; never treat samples within a run as independent runs."""
    values = [value for value in values if insights._number(value)]
    n = len(values)
    median = float(np.median(values)) if n else None
    q1, q3 = map(float, np.quantile(values, [.25, .75], method="linear")) if n >= 5 else (None, None)
    return {"n": n, "selected": selected, "median": median,
            "min": min(values) if n else None, "max": max(values) if n else None,
            "q1": q1, "q3": q3,
            "delta": selected - median if insights._number(selected) and median is not None else None}


def comparison(activity_id, today=None):
    today = today or datetime.now(ZoneInfo(settings.timezone)).date()
    with Session(engine) as session:
        row = session.exec(select(GarminActivity).options(defer(GarminActivity.series_json),
            defer(GarminActivity.laps_json), defer(GarminActivity.zones_json))
            .where(GarminActivity.activity_id == activity_id)).first()
        if row is None:
            return None
        summary, quality = json.loads(row.summary_json), json.loads(row.quality_json)
        selected = _brief(row, summary)
        result = {"activity_id": activity_id, "status": "unavailable", "reason": None,
                  "selected": selected, "cohort": [], "threshold_pct": THRESHOLD_PCT,
                  "tolerance_m": GPS_TOLERANCE_M, "sensor_since": None, "sensor_label": "Garmin",
                  "period_start": None, "period_end": None,
                  "metrics": {key: distribution(selected[key], []) for key in ("pace_seconds", "avg_hr")},
                  "method": METHOD}
        annotations = insights._annotations(session)
        if not insights._eligible(row, summary, quality, annotations) or row.started_at.date() > today:
            result["reason"] = "Dieser Lauf ist unvollständig, ausgeschlossen oder für den Vergleich nicht freigegeben."
            return result
        route = prepare_route(session.get(GarminRoute, activity_id))
        if route is None:
            result["reason"] = "Für diesen Lauf fehlt eine verlässliche, durchgehende GPS-Strecke von mindestens 1 km."
            return result
        distance = selected["distance_km"]
        if not insights._number(distance) or distance <= 0:
            result["reason"] = "Für diesen Lauf fehlt eine gültige Distanz."
            return result
        boundaries = _boundaries(session)
        period = _period(row.started_at.date(), boundaries)
        result.update(sensor_since=period[0].isoformat() if period[0] != date.min else None, sensor_label=period[1])
        others = session.exec(select(GarminActivity).options(defer(GarminActivity.series_json),
            defer(GarminActivity.laps_json), defer(GarminActivity.zones_json)).where(
            GarminActivity.activity_id != activity_id,
            GarminActivity.started_at < datetime.combine(today + timedelta(days=1), datetime.min.time()))
            .order_by(GarminActivity.fetched_at.desc(), GarminActivity.activity_id)).all()
        seen = set()
        for other in others:
            key = other.canonical_external_id or f"garmin:{other.activity_id}"
            if key in seen or row.canonical_external_id and other.canonical_external_id == row.canonical_external_id:
                continue
            other_summary, other_quality = json.loads(other.summary_json), json.loads(other.quality_json)
            if not insights._eligible(other, other_summary, other_quality, annotations) or _period(other.started_at.date(), boundaries) != period:
                continue
            other_distance = other_summary.get("distance_km")
            if (not insights._number(other_distance) or other_distance <= 0
                    or min(distance, other_distance) / max(distance, other_distance) < MIN_LENGTH_RATIO):
                continue
            other_route = prepare_route(session.get(GarminRoute, other.activity_id))
            if other_route is None:
                continue
            coverage = overlap(route, other_route)
            if coverage < THRESHOLD_PCT:
                continue
            seen.add(key)
            result["cohort"].append({**_brief(other, other_summary), "overlap_pct": round(coverage, 2)})
        cohort = result["cohort"]
        cohort.sort(key=lambda item: (item["started_at"], item["activity_id"]))
        result.update(status="ready" if cohort else "empty",
                      reason=None if cohort else "Noch kein anderer Lauf mit mindestens 97 % Streckenüberdeckung in derselben Sensorperiode.",
                      period_start=cohort[0]["started_at"] if cohort else None,
                      period_end=cohort[-1]["started_at"] if cohort else None,
                      metrics={key: distribution(selected[key], [item[key] for item in cohort])
                               for key in ("pace_seconds", "avg_hr")})
        return result
