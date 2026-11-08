"""Begrenzt, wie viele rechenlastige Lese-Requests gleichzeitig laufen.

Die Seiten feuern 10–20 Requests parallel ab. Jeder läuft in einem eigenen Thread
und liest viele Zeilen aus SQLite; sqlite3 gibt den GIL je Zeile frei, und bei
vielen gleichzeitigen Threads kostet jede Übergabe einen Kontextwechsel
(GIL-Convoy). Gemessen auf der Übersicht: 12 Requests parallel ≈ 15 s Wand / 25 s
CPU, mit höchstens zwei gleichzeitig ≈ 3,5 s / 3,7 s. Die Schranke sitzt im
Event-Loop (wartende Requests belegen keinen Thread). Netzwerk-, Live- und
LLM-Endpunkte bleiben außen vor, damit sie nichts blockieren und nicht warten.
"""
import asyncio
import weakref

LIMIT = 2

_GATED_PREFIXES = ("/metrics/", "/hero/", "/bike-plan/", "/walkpad/daily")
_GATED_EXACT = ("/hero", "/bike-plan", "/walkpad")
_EXEMPT_PREFIXES = (
    "/hero/live",          # Uhr/Handy während des Laufs
    "/hero/world/tile",    # holt OSM-Kacheln aus dem Netz
    "/hero/saga",          # LLM-Aufruf
    "/metrics/cycling/map/",  # holt Zwift-Karten vom CDN
)


def gated(path: str) -> bool:
    if path.startswith(_EXEMPT_PREFIXES):
        return False
    return path in _GATED_EXACT or path.startswith(_GATED_PREFIXES)


class ComputeGate:
    """Reine ASGI-Middleware: höchstens LIMIT gated Requests gleichzeitig."""

    def __init__(self, app, limit: int = LIMIT):
        self.app = app
        self.limit = limit
        # je Event-Loop eine Semaphore (TestClient startet je Instanz einen neuen Loop)
        self._sems: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
            weakref.WeakKeyDictionary())

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not gated(scope["path"]):
            return await self.app(scope, receive, send)
        loop = asyncio.get_running_loop()
        sem = self._sems.get(loop)
        if sem is None:
            sem = self._sems[loop] = asyncio.Semaphore(self.limit)
        async with sem:
            return await self.app(scope, receive, send)
