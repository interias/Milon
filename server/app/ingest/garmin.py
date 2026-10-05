"""Synchronize Garmin routes, complete running records and daily watch metrics."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import tempfile
import threading
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from ..config import DATA_DIR, settings

SESSION_FILE = DATA_DIR / "garmin" / ".env"
TOKEN_KEYS = ("di_token", "di_refresh_token", "di_client_id")
PAGE_SIZE = 50
HISTORY_LIMIT = 1000
RECENT_LIMIT = 30
_import_lock = threading.Lock()


class GarminSyncError(RuntimeError):
    """Only fixed messages and aggregate counts may reach the sync log/API."""

    def __init__(self, message: str, result: dict | None = None):
        super().__init__(message)
        self.result = result


def configured() -> bool:
    """Status checks never open credentials or contact Garmin."""
    return SESSION_FILE.is_file()


def _valid_tokens(value) -> bool:
    return isinstance(value, dict) and all(
        isinstance(value.get(key), str) and value[key].strip() for key in TOKEN_KEYS
    )


def _load_tokens() -> dict:
    try:
        encoded = None
        for line in SESSION_FILE.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "GARMIN_SESSION_B64":
                encoded = value.strip().strip("\"'")
        tokens = json.loads(base64.b64decode(encoded or "", validate=True))
        if not _valid_tokens(tokens):
            raise ValueError
        return {key: tokens[key] for key in TOKEN_KEYS}
    except Exception:
        raise GarminSyncError("Gespeicherte Garmin-Anmeldung ist ungültig; bitte neu verbinden.") from None


def _persist_tokens(tokens: dict) -> None:
    """Replace only the session value, atomically and without exposing token data."""
    temporary: Path | None = None
    try:
        encoded = base64.b64encode(json.dumps(tokens, separators=(",", ":")).encode()).decode()
        lines = SESSION_FILE.read_text(encoding="utf-8").splitlines()
        result = []
        replaced = False
        for line in lines:
            if line.partition("=")[0].strip() == "GARMIN_SESSION_B64":
                if not replaced:
                    result.append(f"GARMIN_SESSION_B64={encoded}")
                replaced = True
            else:
                result.append(line)
        if not replaced:
            result.append(f"GARMIN_SESSION_B64={encoded}")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=SESSION_FILE.parent, prefix=".session-", delete=False) as file:
            temporary = Path(file.name)
            os.chmod(temporary, 0o600)
            file.write("\n".join(result) + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, SESSION_FILE)
    except Exception:
        raise GarminSyncError("Garmin-Anmeldung konnte nicht sicher gespeichert werden; bitte erneut verbinden.") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _new_client():
    from garminconnect import Garmin

    return Garmin()


@contextmanager
def _private_library_logs():
    # Upstream debug errors can include response bodies or inline token JSON.
    names = {"garminconnect", "garminconnect.client"} | {
        name for name in logging.Logger.manager.loggerDict if name.startswith("garminconnect.")
    }
    previous = [(logging.getLogger(name), logging.getLogger(name).disabled) for name in names]
    try:
        for logger, _ in previous:
            logger.disabled = True
        yield
    finally:
        for logger, disabled in previous:
            logger.disabled = disabled


def _known_route_ids() -> set[str]:
    from .. import garmin_routes

    with Session(garmin_routes.engine) as session:
        return set(session.exec(select(garmin_routes.GarminRoute.activity_id)).all())


def _number(value) -> float | None:
    if value is None:
        return None
    number = float(value)
    if isinstance(value, bool) or not math.isfinite(number) or number < 0:
        raise ValueError
    return number


def _summary(activity: dict) -> dict:
    activity_id = str(activity["activityId"])
    if not activity_id.isascii() or not activity_id.isdigit() or int(activity_id) <= 0:
        raise ValueError
    started = datetime.fromisoformat(activity["startTimeGMT"].replace("Z", "+00:00"))
    started = started.replace(tzinfo=timezone.utc) if started.tzinfo is None else started.astimezone(timezone.utc)
    duration = _number(activity.get("duration"))
    elapsed = _number(activity.get("elapsedDuration"))
    distance = _number(activity.get("distance"))
    return {
        "activity_id": activity_id,
        "title": activity.get("activityName") if isinstance(activity.get("activityName"), str) else None,
        "started_at": started.astimezone(ZoneInfo(settings.timezone)).replace(tzinfo=None),
        "started_at_utc": started.isoformat(),
        "distance_km": distance / 1000 if distance is not None else None,
        "duration_seconds": duration,
        "elapsed_duration_seconds": elapsed if elapsed is not None else duration,
        "elevation_gain_m": _number(activity.get("elevationGain")),
    }


def _pull_routes(api, full: bool, collected: list[dict] | None = None) -> dict:
    from .. import garmin_routes

    known = _known_route_ids()
    limit = HISTORY_LIMIT if full or not known else RECENT_LIMIT
    result = {"mode": "full" if full else "incremental" if known else "initial",
              "imported": 0, "skipped": 0, "no_route": 0, "checked": 0, "errors": 0,
              "history_limited": False}
    seen: set[str] = set()
    offset = 0
    while offset < limit:
        page_size = min(PAGE_SIZE, limit - offset)
        try:
            activities = api.get_activities(offset, page_size, activitytype="running")
            if not isinstance(activities, list):
                raise ValueError
        except Exception:
            raise GarminSyncError("Garmin-Aktivitäten konnten nicht vollständig gelesen werden.", result) from None
        for activity in activities[:page_size]:
            result["checked"] += 1
            if collected is not None and isinstance(activity, dict):
                collected.append(activity)
            try:
                summary = _summary(activity)
                activity_id = summary["activity_id"]
                if activity_id in seen or (activity_id in known and not full):
                    result["skipped"] += 1
                    continue
                seen.add(activity_id)
                if activity.get("hasPolyline") is False:
                    result["no_route"] += 1
                    continue
                raw = api.download_activity(activity_id, dl_fmt=api.ActivityDownloadFormat.GPX)
                if raw == b"":
                    result["no_route"] += 1
                    continue
                segments = garmin_routes.parse_gpx(raw)
                if not segments:
                    result["no_route"] += 1
                    continue
                garmin_routes.save_route(summary, segments)
                result["imported"] += 1
            except Exception:
                result["errors"] += 1
        offset += page_size
        if len(activities) < page_size:
            break
    result["history_limited"] = offset >= limit and result["checked"] >= limit
    if result["errors"]:
        raise GarminSyncError(
            f"Garmin-Import teilweise fehlgeschlagen: {result['imported']} gespeichert, "
            f"{result['errors']} Aktivitäten mit Fehlern.", result,
        )
    return result


def _pull_metrics(api, activities: list[dict], full: bool, force_daily: bool = False) -> dict:
    from .. import garmin_activity, garmin_daily, garmin_weather, garmin_load

    outcomes = {}
    for name, pull in (
        ("activities", lambda: garmin_activity.sync_activities(api, activities, full=full)),
        ("daily", lambda: garmin_daily.sync_daily(api, full=full, force=force_daily)),
        ("weather", lambda: garmin_weather.sync_weather(api, activities, full=full)),
        ("running_tolerance", lambda: garmin_load.sync_tolerance(api, full=full, force=force_daily)),
    ):
        try:
            outcomes[name] = pull()
        except Exception:
            # A failed category must not suppress the other categories or leak payloads.
            outcomes[name] = {"errors": 1, "status": "error"}
    return outcomes


def _pull_all(api, full: bool, force_daily: bool = False) -> dict:
    activities: list[dict] = []
    route_failed = False
    try:
        result = _pull_routes(api, full, activities)
    except GarminSyncError as failure:
        route_failed = True
        result = failure.result or {"mode": "full" if full else "incremental", "imported": 0,
                                    "skipped": 0, "no_route": 0, "checked": 0,
                                    "errors": 1, "history_limited": False}
    result.update(_pull_metrics(api, activities, full, force_daily=True) if force_daily
                  else _pull_metrics(api, activities, full))
    metric_errors = sum(outcome.get("errors", 0) for outcome in
                        (result["activities"], result["daily"]))
    result["errors"] += metric_errors
    if route_failed or metric_errors:
        raise GarminSyncError(
            "Garmin-Import teilweise fehlgeschlagen; vorhandene Daten bleiben erhalten. "
            f"{result['imported']} Strecken gespeichert, "
            f"{max(1, result['errors'])} Importfehler. Bitte erneut aktualisieren.", result,
        ) from None
    return result


def import_garmin(full: bool = False, force_daily: bool = False) -> dict:
    """Bounded initial/backfill sync; later pulls inspect the latest 30 running activities."""
    if not configured():
        return {"mode": "not_configured", "imported": 0, "skipped": 0,
                "no_route": 0, "checked": 0, "errors": 0, "history_limited": False}
    if not _import_lock.acquire(blocking=False):
        raise GarminSyncError("Ein Garmin-Import läuft bereits.")
    api = None
    try:
        try:
            tokens = _load_tokens()
            api = _new_client()
            with _private_library_logs():
                api.login(tokenstore=json.dumps(tokens))
                return _pull_all(api, full, force_daily=force_daily)
        except GarminSyncError:
            raise
        except Exception:
            raise GarminSyncError("Garmin-Import fehlgeschlagen; Verbindung oder Anmeldung prüfen.") from None
        finally:
            if api is not None:
                tokens = {key: getattr(api.client, key, None) for key in TOKEN_KEYS}
                if _valid_tokens(tokens):
                    _persist_tokens(tokens)
    finally:
        _import_lock.release()
