"""Zwischenspeicher für teure, geteilte Berechnungen — gültig bis sich die Daten ändern.

Mehrere Endpunkte rechnen dieselben Bausteine (Verbrauchsmodell, Kraft-Vorschlag, Woche)
je Aufruf neu. `@cached` merkt sich das Ergebnis unter einem Schlüssel aus Argumenten,
lokalem Datum, Einstellungen und Datenstand (mtime + Größe von tracker.db und des
Health-Connect-Exports; die DB läuft im Journal-Modus „delete“, jede Schreib-Transaktion
ändert die Datei). `app.cache_warmer` rechnet nach jeder Änderung vor. Höchstens `TTL`
Sekunden, damit Uhrzeit-Abhängiges (Wetter, „heute offen“) nicht hängen bleibt.
Rückgabe ist immer eine tiefe Kopie, Aufrufer dürfen sie verändern.
"""
from __future__ import annotations

import copy
import functools
import inspect
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import INCOMING_DIR, settings

TTL = 300.0
ENABLED = True  # Tests schalten ab (conftest), weil sie Engines je Modul austauschen

_store: dict = {}
_locks: dict = {}
_guard = threading.Lock()


def _stat(path) -> tuple:
    try:
        st = os.stat(path)
        return (str(path), st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        return (str(path), None)
    except (OSError, TypeError):
        return (str(path), time.time())  # unbekannt → nie treffen


def _data_version() -> tuple:
    """tracker.db + Health-Connect-Export (Lauf-Analysen lesen ihn direkt)."""
    from .db import engine
    return (_stat(engine.url.database), _stat(INCOMING_DIR / "health_connect_export.db"))


def version() -> tuple:
    """Alles, wovon ein Eintrag abhängt (ohne Argumente) — der Vorwärmer erkennt daran Änderungen."""
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return (today, repr(settings.model_dump()), _data_version())


def _key(fn, call: tuple) -> tuple:
    return (fn.__module__, fn.__qualname__, call, version())


def cached(fn):
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not ENABLED:
            return fn(*args, **kwargs)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()  # week(0) und week(0, today=None) = derselbe Eintrag
        call = tuple(bound.arguments.items())
        key = _key(fn, call)
        hit = _store.get(key)
        if hit is not None and time.monotonic() - hit[0] < TTL:
            return copy.deepcopy(hit[1])
        with _guard:
            lock = _locks.setdefault(key[:3], threading.Lock())
        with lock:  # gleiche Anfrage parallel: nur einer rechnet
            hit = _store.get(key)
            if hit is None or time.monotonic() - hit[0] >= TTL:
                value = fn(*args, **kwargs)
                key = _key(fn, call)  # Stand nach dem Rechnen: manche Leser schreiben selbst (Caches)
                with _guard:
                    for k in [k for k in _store if k[:3] == key[:3]]:
                        del _store[k]  # alte Datenstände derselben Anfrage verwerfen
                    _store[key] = hit = (time.monotonic(), value)
        return copy.deepcopy(hit[1])

    return wrapper


def clear() -> None:
    with _guard:
        _store.clear()


def expire(older_than: float) -> None:
    """Einträge älter als `older_than` Sekunden verwerfen (der Vorwärmer rechnet sie danach neu)."""
    now = time.monotonic()
    with _guard:
        for k in [k for k, (at, _) in _store.items() if now - at >= older_than]:
            del _store[k]
