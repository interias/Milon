"""Read-only source freshness: retrieval success is not the date of the last workout."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlmodel import Session, select

from ..config import INCOMING_DIR, settings
from ..db import engine
from ..garmin_activity import GarminActivity
from ..garmin_daily import GarminDaily, METHODS
from ..ingest.garmin import configured as garmin_configured
from ..models import BodyMeasurement, ExerciseSession, NutritionEntry, RestingHrDaily, SleepSession, StepsDaily, SyncState, Vo2Max, Workout


def _object(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _instant(value: datetime | str | None, *, local=False) -> datetime | None:
    if value is None:
        return None
    try:
        value = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo(settings.timezone) if local else timezone.utc)
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _latest(session: Session, queries) -> str | None:
    values = [session.exec(query).one() for query in queries]
    dates = [value.date() if isinstance(value, datetime) else value for value in values if value is not None]
    return max(dates).isoformat() if dates else None


def _garmin_categories(rows: list[GarminDaily], today: date) -> list[dict]:
    labels = {"summary": "Alltag", "sleep": "Schlaf", "hrv": "HRV", "vo2": "VO₂max", "readiness": "Trainingsbereitschaft"}
    result = []
    for key in METHODS:
        records = [(row.day, _object(row.status_json).get(key, {})) for row in rows]
        records = [(day, status) for day, status in records if isinstance(status, dict)]
        attempts = [_instant(status.get("attempted_at")) for _, status in records]
        latest_attempt = max((value for value in attempts if value), default=None)
        recent = [(day, status) for day, status in records if day >= today - timedelta(days=2)]
        relevant = recent or records[-1:]
        statuses = {status.get("status") for _, status in relevant}
        successes = [_instant(status.get("last_success_at")) for _, status in records]
        last_success = max((value for value in successes if value), default=None)
        status = "error" if "error" in statuses else "available" if "available" in statuses else "unsupported" if "unsupported" in statuses else "empty" if "empty" in statuses else "never"
        result.append({"key": key, "label": labels[key], "status": status,
                       "last_attempt_at": _iso(latest_attempt), "last_success_at": _iso(last_success)})
    return result


def source_status(*, now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = now.astimezone(ZoneInfo(settings.timezone)).date()
    food = "biss" if settings.nutrition_source == "biss" else "fddb"  # only the active food diary is shown
    with Session(engine) as session:
        states = {row.source: row for row in session.exec(select(SyncState)).all()}
        days = session.exec(select(GarminDaily).where(GarminDaily.day <= today).order_by(GarminDaily.day)).all()
        categories = _garmin_categories(days, today)
        hc_rhr = {row.day: row.bpm for row in session.exec(select(RestingHrDaily).where(RestingHrDaily.source == "health_connect")).all()}
        pairs = [(hc_rhr[row.day], _object(row.normalized_json).get("summary", {}).get("rhr_bpm"))
                 for row in days if row.day in hc_rhr]
        pairs = [(left, right) for left, right in pairs if isinstance(right, (int, float))]
        hc_queries = [
            select(func.max(BodyMeasurement.measured_at)).where(BodyMeasurement.source == "health_connect"),
            select(func.max(ExerciseSession.started_at)).where(ExerciseSession.source == "health_connect"),
            select(func.max(SleepSession.ended_at)).where(SleepSession.source == "health_connect"),
            select(func.max(StepsDaily.day)).where(StepsDaily.source == "health_connect"),
            select(func.max(RestingHrDaily.day)).where(RestingHrDaily.source == "health_connect"),
            select(func.max(Vo2Max.measured_at)).where(Vo2Max.source == "health_connect"),
        ]
        latest = {
            "health_connect": _latest(session, hc_queries),
            "arboleaf": _latest(session, hc_queries[:1]),
            "hevy": _latest(session, [select(func.max(Workout.started_at)).where(Workout.source == "hevy")]),
            food: _latest(session, [select(func.max(NutritionEntry.eaten_at)).where(NutritionEntry.source == food)]),
            "garmin": _latest(session, [select(func.max(GarminActivity.started_at))]),
        }
        garmin_days = [row.day.isoformat() for row in days if any(
            isinstance(value, dict) and any(item is not None for name, item in value.items() if not name.startswith("_"))
            for value in _object(row.normalized_json).values())]
        latest["garmin"] = max([value for value in [latest["garmin"], *garmin_days] if value], default=None)

    configured = {"garmin": garmin_configured(), "health_connect": bool(settings.hc_drive_file_id) or (INCOMING_DIR / "health_connect_export.db").is_file(),
                  "arboleaf": bool(settings.body_source_package), "hevy": bool(settings.hevy_api_key),
                  "fddb": bool(settings.fddb_cookie or (settings.fddb_user and settings.fddb_pw)),
                  "biss": bool(settings.biss_url)}
    specs = [
        ("garmin", "Garmin", "Uhrdaten direkt", 24, "Neue Uhrdaten erscheinen nach der Synchronisierung mit Garmin Connect."),
        ("health_connect", "Health Connect", "Täglicher Export", 48, "Ein erfolgreicher Import kann denselben Export erneut einlesen; das Messdatum bleibt maßgeblich."),
        ("arboleaf", "Arboleaf", "Waage via Health Connect", 48, "Messungen kommen über den Health-Connect-Export. Ohne neue Wägung bleibt das Messdatum unverändert."),
        ("hevy", "Hevy", "Krafttraining", 18, "Ein erfolgreicher Abruf ohne neues Training ist aktuell; Ruhetage sind keine Synchronisationslücke."),
        ("biss", "BISS", "Ernährungsprotokoll, minütlich", 1, "Das Datenende zeigt den letzten protokollierten Eintrag, nicht die Vollständigkeit eines Tages.")
        if food == "biss" else
        ("fddb", "FDDB", "Ernährungsprotokoll", 48, "Das Datenende zeigt den letzten protokollierten Eintrag, nicht die Vollständigkeit eines Tages."),
    ]
    if not settings.health_connect_enabled:
        # Health Connect aus: die Waage kommt direkt per Bluetooth (scale_measurements), ohne Abruf-Zustand.
        specs = [spec for spec in specs if spec[0] not in ("health_connect", "arboleaf")]
    sources = []
    for key, label, purpose, hours, note in specs:
        state = states.get("health_connect" if key == "arboleaf" else key)
        last_attempt = _instant(state.last_sync, local=True) if state else None
        last_success = _instant(state.last_success_at, local=True) if state else None
        detail = _object(state.detail) if state else {}
        if last_success is None and state and state.status == "ok" and detail and detail.get("mode") != "not_configured":
            last_success = last_attempt
        old = last_success is not None and now - last_success > timedelta(hours=hours)
        failed = bool(state and state.status == "error")
        cat_errors = key == "garmin" and any(item["status"] == "error" for item in categories)
        cat_success = key == "garmin" and any(item["last_success_at"] and _instant(item["last_success_at"]) >= now - timedelta(hours=24) for item in categories)
        if not configured[key]:
            status = "not_configured"
        elif failed or cat_errors:
            status = "partial" if key == "garmin" and cat_success else "error"
        elif last_success is None:
            status = "never"
        elif old:
            status = "old"
        else:
            status = "ok"
        if key == "arboleaf" and not configured["health_connect"]:
            status = "not_configured"
        data_old = latest[key] is not None and date.fromisoformat(latest[key]) < today - timedelta(days=2)
        sources.append({"key": key, "label": label, "purpose": purpose, "status": status,
                        "last_attempt_at": _iso(last_attempt), "last_success_at": _iso(last_success),
                        "latest_data_date": latest[key], "data_old": data_old, "note": note,
                        "categories": categories if key == "garmin" else []})
    if not settings.health_connect_enabled:
        from .. import scale
        latest_scale = scale.history(36500)[:1]
        day = latest_scale[0]["measured_at"][:10] if latest_scale else None
        sources.insert(1, {"key": "scale", "label": "Waage", "purpose": "Arboleaf per Bluetooth, direkt im Handy",
                           "status": "ok" if day else "never", "last_attempt_at": None,
                           "last_success_at": latest_scale[0]["created_at"] if latest_scale else None,
                           "latest_data_date": day,
                           "data_old": day is not None and date.fromisoformat(day) < today - timedelta(days=2),
                           "note": "Kein Abruf: jede Wiegung kommt sofort beim Wiegen an. Health Connect ist abgeschaltet.",
                           "categories": []})
    different = any(left != right for left, right in pairs)
    resting_note = ("Die lokalen Tageswerte stimmen nicht durchgehend überein. Die genaue Export- oder Aktualisierungsursache ist noch offen."
                    if different else "Gleiche Tageswerte allein belegen keine identische Berechnung oder Exportsemantik."
                    if pairs else "Für einen Quellenvergleich fehlen noch gemeinsame Messtage.")
    return {"generated_at": now.isoformat(), "scheduler_enabled": settings.scheduler_enabled, "sources": sources,
            "resting_hr_note": "Der Ruhepuls kommt von Garmin; Garmin-Tageswerte ersetzen ältere Health-Connect-Werte. " + resting_note}
