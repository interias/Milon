"""Rechnet die schweren Seiten-Abfragen im Hintergrund vor, damit jede Seite sofort lädt.

Beim Start einmal, danach immer, wenn sich der Datenstand ändert (`data_cache.version`:
tracker.db, Health-Connect-Export, Einstellungen, Datum), und spätestens alle `REFRESH`
Sekunden (Uhrzeit-Abhängiges wie Wetter). Die Abfragen laufen im Prozess über die ASGI-App
(kein Netzwerk), strikt nacheinander — höchstens eine zusätzliche Last neben echten Requests.
Füllt dieselben Zwischenspeicher, die die Seiten nutzen (`data_cache` und die eigenen Caches
von Route-Atlas, Weltkarte und Lauf-Referenz).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

import httpx

from . import data_cache

log = logging.getLogger(__name__)

CHECK_S = 15.0      # so oft auf geänderte Daten prüfen
REFRESH = 240.0     # spätestens dann neu rechnen (< data_cache.TTL)

# Die schweren Abfragen der Seiten (Stand: Browser-Mitschnitt aller Seiten, 2026-11-08)
URLS = [
    # Übersicht
    "/hero", "/metrics/overview/history", "/metrics/week?offset=0", "/metrics/week/today",
    "/metrics/activity/day-badge", "/metrics/body/summary", "/metrics/body/tdee",
    "/metrics/running/standardized-hr", "/metrics/running/fitness", "/metrics/strength/index?period=3m",
    "/metrics/activity/active-kcal?days=14", "/metrics/activity/consistency?days=0",
    # Woche
    "/metrics/activity/journal?offset=0", "/metrics/endurance/fitness?days=60",
    # Körper, Ernährung
    "/metrics/body/weight?days=180", "/metrics/body/weight-rate", "/metrics/body/composition",
    "/metrics/body/progress?weeks=8&measure=abdomen_navel",
    "/metrics/nutrition/summary", "/metrics/nutrition/protein?days=60", "/metrics/nutrition/kcal?days=60",
    # Gesundheit
    "/metrics/activity/active-kcal?days=30", "/walkpad?weeks=12", "/metrics/sleep/overview?days=90",
    "/metrics/garmin/recovery?days=30", "/metrics/sources", "/metrics/health/overview",
    "/metrics/health/steps?days=30", "/metrics/garmin/nights?days=14",
    # Laufen
    "/metrics/running/week-overview", "/metrics/running/volume?weeks=12", "/metrics/running/best-efforts?top=3",
    "/metrics/running/achievements", "/metrics/running/zones", "/metrics/running/insights/zones?weeks=8",
    "/metrics/running/route-atlas", "/running/reference?days=365", "/metrics/endurance/fitness?days=365",
    "/metrics/running/mechanics/load?weeks=4",
    # Rad
    "/metrics/cycling/summary", "/metrics/cycling/rides?limit=0", "/metrics/cycling/power-curve",
    "/metrics/cycling/eftp?weeks=26", "/metrics/cycling/hr-at-power", "/metrics/cycling/efficiency",
    "/metrics/cycling/zones?weeks=12", "/metrics/cycling/wkg-hr", "/metrics/cycling/worlds",
    "/bike-plan", "/bike-plan/checkpoints",
    # Kraft
    "/metrics/strength/plan", "/metrics/strength/volume", "/metrics/strength/exercises",
    "/metrics/strength/tonnage?weeks=12", "/metrics/strength/records?days=30&limit=200",
    # Laufband
    "/walkpad/daily?days=37",
]

_stop: threading.Event | None = None


async def warm(client: httpx.AsyncClient) -> float:
    """Alle URLs einmal abrufen; Fehler einzelner Abfragen nur protokollieren. Liefert die Dauer."""
    t = time.monotonic()
    for url in URLS:
        try:
            r = await client.get(url)
            if r.status_code >= 500:
                log.warning("Vorwärmen %s: HTTP %s", url, r.status_code)
        except Exception:  # noqa: BLE001 -- ein Fehler darf den Vorwärmer nie beenden
            log.exception("Vorwärmen %s fehlgeschlagen", url)
    return time.monotonic() - t


async def _loop(app, stop: threading.Event) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://warmer", timeout=120) as client:
        last, at = None, 0.0
        while not stop.is_set():
            current = data_cache.version()
            stale = time.monotonic() - at >= REFRESH
            if current != last or stale:
                if stale and last is not None:
                    data_cache.expire(REFRESH)  # gleiche Daten, aber Uhrzeit-Abhängiges neu
                took = await warm(client)
                log.info("Seiten vorgerechnet in %.1f s", took)
                # Stand nach dem Rechnen: was das Vorwärmen selbst schreibt, löst kein neues aus
                last, at = data_cache.version(), time.monotonic()
            await asyncio.to_thread(stop.wait, CHECK_S)


def start(app) -> None:
    global _stop
    if not data_cache.ENABLED or _stop is not None:
        return  # Tests: abgeschaltet
    _stop = threading.Event()
    stop = _stop
    threading.Thread(target=lambda: asyncio.run(_loop(app, stop)), name="cache-warmer", daemon=True).start()


def stop() -> None:
    global _stop
    if _stop is not None:
        _stop.set()
        _stop = None
