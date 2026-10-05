"""Exploratory day-level associations, with explicit timing and source boundaries."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo

import numpy as np
from sqlmodel import Session, select

from ..checkins import CheckIn
from ..config import settings, watch_source_for
from ..db import engine
from ..garmin_daily import GarminDaily, PACKAGE
from . import sleep

METRICS = {"sleep": ("Schlafdauer", "h"), "hrv": ("Nächtliche HRV", "ms"),
           "energy": ("Energie im Check-in", "1–5")}
MISSING = {"no_measurement": "ohne passenden Messwert", "unknown_timing": "ohne belegte zeitliche Zuordnung",
           "after_training": "Messung erst nach Trainingsbeginn", "other_session": "Check-in für anderes Training",
           "no_outcome": "ohne geeigneten Leistungswert", "excluded": "ausgeschlossen"}


def _local(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(ZoneInfo(settings.timezone)).replace(tzinfo=None) if parsed.tzinfo else parsed


def _rank(values: np.ndarray) -> np.ndarray:
    """Average ranks preserve ties on the five-point energy scale."""
    _, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    return (np.cumsum(counts) - (counts - 1) / 2)[inverse]


def _r(x: np.ndarray, y: np.ndarray) -> float | None:
    if np.std(x) <= 1e-8 or np.std(y) <= 1e-8:
        return None
    value = float(np.corrcoef(x, y)[0, 1])
    return round(value, 3) if np.isfinite(value) else None


def _statistics(points: list[dict], metric: str) -> dict:
    n = len(points)
    span = (date.fromisoformat(points[-1]["date"]) - date.fromisoformat(points[0]["date"])).days if n else 0
    result = {"correlation": None, "detrended_correlation": None, "span_days": span,
              "statistic": "ρ" if metric == "energy" else "r", "status": "collecting",
              "status_label": f"{n} {'Trainingstag' if n == 1 else 'Trainingstage'} · ab 10 Tagen zeigen wir einen beschreibenden Zusammenhang.",
              "detrended_label": "Zeitbereinigung ab 20 Trainingstagen über mindestens 28 Tage."}
    if n < 10:
        return result
    x = np.array([point["predictor"] for point in points], float)
    y = np.array([point["value"] for point in points], float)
    if metric == "energy":
        x, y = _rank(x), _rank(y)
    result["correlation"] = _r(x, y)
    if result["correlation"] is None:
        result.update(status="no_variation", status_label="Zu wenig Streuung für einen Zusammenhang.")
        return result
    result.update(status="exploratory", status_label="Beschreibender Zusammenhang; gemeinsame Zeittrends können ihn erzeugen.")
    if n >= 20 and span >= 28:
        t = np.array([date.fromisoformat(point["date"]).toordinal() for point in points], float)
        design = np.column_stack((np.ones(n), t - t.mean()))
        residual_x = x - design @ np.linalg.lstsq(design, x, rcond=None)[0]
        residual_y = y - design @ np.linalg.lstsq(design, y, rcond=None)[0]
        result["detrended_correlation"] = _r(residual_x, residual_y)
        result["detrended_label"] = ("Linearer Zeittrend entfernt; andere Einflüsse bleiben bestehen."
                                     if result["detrended_correlation"] is not None else
                                     "Nach Entfernen des Zeittrends bleibt zu wenig Streuung.")
    return result


def _measurements(metric: str, days: int, today: date) -> dict:
    if metric == "sleep":
        return {day: {"value": row.asleep_minutes / 60 if row.asleep_minutes is not None else None,
                      "measured_at": row.ended_at, "timing_source": "sleep_end"}
                for day, row in sleep._main_by_day(sleep._sleep_rows(days, today)).items()}
    with Session(engine) as session:
        model = GarminDaily if metric == "hrv" else CheckIn
        rows = session.exec(select(model).where(model.day >= today - timedelta(days=days - 1),
                                                model.day <= today)).all()
    result = {}
    for row in rows:
        if metric == "energy":
            result[row.day] = {"value": row.energy if row.energy in range(1, 6) else None,
                               "measured_at": None, "timing_source": "self_report_day",
                               "session_id": row.session_external_id, "session_kind": row.session_kind}
            continue
        if watch_source_for(row.day, settings) != PACKAGE:
            continue
        data = json.loads(row.normalized_json)
        hrv, night = data.get("hrv", {}), data.get("sleep", {})
        end = _local(hrv.get("measured_at"))
        timing_source = "hrv_end"
        # lastNightAvg belongs to the provider's validated calendar day. A recorded sleep
        # end on that same day establishes ordering even when sleep stages are incomplete.
        if end is None and night.get("main_sleep") is True:
            end = _local(night.get("ended_at_utc"))
            timing_source = "sleep_end"
        if end is not None and end.date() != row.day:
            end = None
        value = hrv.get("hrv_ms")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or not 1 <= value <= 500:
            value = None
        result[row.day] = {"value": value, "measured_at": end, "timing_source": timing_source}
    return result


def performance(metric: str = "sleep", kind: str = "run", source: str = "current", days: int = 180,
                today: date | None = None) -> dict:
    today = today or sleep._today()
    measurements = _measurements(metric, days, today)
    outcomes = sleep._run_outcomes() if kind == "run" else sleep._strength_outcomes()
    packages = {watch_source_for(today, settings)} if source == "current" else {settings.steps_source_package}
    if source == "all":
        packages |= {watch_source_for(today, settings)}
    buckets = {package: {"days": defaultdict(list), "missing": {key: 0 for key in MISSING}}
               for package in sorted(packages)}
    for outcome in outcomes:
        start = outcome["started_at"]
        day = start.date()
        if not today - timedelta(days=days - 1) <= day <= today:
            continue
        package = watch_source_for(day, settings)
        if package not in buckets:
            continue
        bucket, measurement = buckets[package], measurements.get(day)
        reason = None
        if outcome["excluded"]:
            reason = "excluded"
        elif outcome["value"] is None or not np.isfinite(outcome["value"]):
            reason = "no_outcome"
        elif measurement is None or measurement["value"] is None:
            reason = "no_measurement"
        elif metric != "energy" and measurement["measured_at"] is None:
            reason = "unknown_timing"
        elif metric != "energy" and measurement["measured_at"] >= start:
            reason = "after_training"
        elif metric == "energy" and measurement.get("session_id") and (
                measurement["session_id"] != outcome["session_id"] or measurement["session_kind"] != kind):
            reason = "other_session"
        if reason:
            bucket["missing"][reason] += 1
        else:
            bucket["days"][day].append(outcome)
    groups = []
    for package, bucket in buckets.items():
        points = []
        for day, paired in sorted(bucket["days"].items()):
            measurement = measurements[day]
            points.append({"date": day.isoformat(), "predictor": measurement["value"],
                           "value": float(np.median([item["value"] for item in paired])),
                           "title": " · ".join(item["title"] for item in paired),
                           "session_id": paired[0]["session_id"], "session_count": len(paired),
                           "measured_at": measurement["measured_at"].isoformat() if measurement["measured_at"] else None,
                           "timing_source": measurement["timing_source"]})
        groups.append({"package": package, "label": sleep.LABELS.get(package, package), "n": len(points),
                       "points": points, "missing": bucket["missing"], **_statistics(points, metric)})
    method = {
        "sleep": "Hauptschlaf der vorherigen Nacht: gemessene Schlafdauer mit Training nach dem Aufwachen am selben lokalen Tag. Nickerchen zählen nicht.",
        "hrv": "Nächtlicher Garmin-HRV-Mittelwert, nur ab dem Uhrenwechsel. HRV-Ende oder dokumentiertes Schlafende desselben Tages muss vor Trainingsbeginn liegen. Fehlende Zeitstempel bleiben ohne Paar; keine Fortschreibung.",
        "energy": "Freiwillige Energie-Selbstauskunft (1–5) und Training desselben Tages. Bei einer Trainingsverknüpfung zählt nur diese Einheit. Der gespeicherte Änderungszeitpunkt belegt keinen Erfassungszeitpunkt vor dem Training; daher keine Vorhersage. Rückwirkende Einträge bleiben Selbstauskunft.",
    }[metric]
    method += (" Mehrere geeignete Einheiten pro Tag werden zum Median zusammengefasst, ein Punkt je Tag. "
               "Uhren werden getrennt ausgewertet. "
               + ("ρ = Spearman-Rangkorrelation mit mittleren Rängen bei Gleichständen. " if metric == "energy" else "r = Pearson-Korrelation ungerundeter Tagespaare. ")
               + "Zeitbereinigung entfernt einen linearen Datumstrend aus beiden Größen (bei Energie aus den Rängen); sie beweist weder Unabhängigkeit noch Ursache. Keine Signifikanztests.")
    method += (" Laufeffizienz = Geschwindigkeit / mittlere HF, nicht vollständig intensitätsbereinigt."
               if kind == "run" else " Kraftwert = gleich gewichtete logarithmische e1RM-Veränderungen gleicher Übungen gegenüber der letzten Einheit (12 Stunden bis 60 Tage), Epley bis 12 Wiederholungen; neue Übungen ohne Baseline zählen nicht.")
    return {"metric": metric, "kind": kind, "source": source, "days": days,
            "predictor_label": METRICS[metric][0], "predictor_unit": METRICS[metric][1],
            "timing": "same_day_self_report" if metric == "energy" else "prior_night",
            "outcome_label": "Aerobe Laufeffizienz" if kind == "run" else "e1RM-Veränderung zu vorherigen Übungseinheiten",
            "outcome_unit": "m/Herzschlag" if kind == "run" else "%",
            "groups": groups, "missing_labels": MISSING, "method": method,
            "caveat": sleep.CAVEAT + (" Freiwillige Check-ins können durch die Auswahl der Eintragstage verzerrt sein."
                                     if metric == "energy" else "")}
