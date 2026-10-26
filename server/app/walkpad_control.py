"""Walking pad remote control: App → server → host recorder (long poll) → FTMS Control Point.

Bluetooth only exists on the host and the pad accepts one connection, so the recorder fetches commands
here (token-guarded long poll) and reports the pad's real state from Fitness Machine Status.
In memory on purpose (single uvicorn worker): a restart drops queued commands, which is the safe side.
Safety: start needs an explicit confirmation, speed is clamped to WALKPAD_MAX_SPEED_KMH, commands
older than MAX_AGE_S are dropped (server and recorder), relative steps are computed here from the
pad's reported speed, and nothing is queued while the recorder or pad is offline. No dead man's
switch: a Wi-Fi hiccup must not stop the belt under the desk."""
from __future__ import annotations

import itertools
import threading
import time
from collections import deque

from .config import settings

MAX_AGE_S = 3.0
ONLINE_S = 35.0          # recorder counts as online this long after its last poll/state
MIN_KMH, PAD_MAX_KMH = 1.0, 6.0
STEPS = (0.1, 0.5)

_cond = threading.Condition()
_queue: deque[dict] = deque()
_ids = itertools.count(1)
_state: dict = {}
_results: dict[int, dict] = {}
_seen = 0.0


class ControlError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def reset() -> None:
    global _seen
    with _cond:
        _queue.clear()
        _state.clear()
        _results.clear()
        _seen = 0.0


def max_kmh() -> float:
    return max(MIN_KMH, min(PAD_MAX_KMH, settings.walkpad_max_speed_kmh))


def _clamp(kmh: float) -> float:
    return round(min(max(kmh, MIN_KMH), max_kmh()), 1)


def state(now: float | None = None) -> dict:
    now = now or time.time()
    with _cond:
        online = now - _seen <= ONLINE_S
        return {"recorder_online": online, "connected": bool(online and _state.get("connected")),
                "status": _state.get("status") if online else None, "speed_kmh": _state.get("speed_kmh"),
                "target_kmh": _state.get("target_kmh"), "device": _state.get("device"),
                "updated_at": _state.get("updated_at"), "max_kmh": max_kmh(), "min_kmh": MIN_KMH,
                "last_result": _results[max(_results)] if _results else None}


def enqueue(action: str, kmh: float | None = None, step: float | None = None, confirm: bool = False,
            now: float | None = None) -> dict:
    """UI command → queue. Raises ControlError (409 offline/refused, 422 invalid)."""
    now = now or time.time()
    current = state(now)
    if not current["connected"]:
        raise ControlError("Laufband nicht verbunden (Recorder oder Pad offline).")
    if action == "start" and not confirm:
        raise ControlError("Start nur mit Bestätigung.", 422)
    if action in ("faster", "slower"):
        if step not in STEPS:
            raise ControlError("Schritt muss 0,1 oder 0,5 km/h sein.", 422)
        base = current["target_kmh"] or current["speed_kmh"]
        if base is None:
            raise ControlError("Aktuelles Tempo unbekannt.")
        kmh, action = base + (step if action == "faster" else -step), "speed"
    if action == "speed":
        if kmh is None:
            raise ControlError("Tempo fehlt.", 422)
        kmh = _clamp(kmh)
    elif action == "start":
        kmh = _clamp(kmh) if kmh is not None else None  # pad starts at 1.0; the recorder sets this once it runs
    elif action not in ("pause", "stop"):
        raise ControlError("Unbekannte Aktion.", 422)
    else:
        kmh = None
    cmd = {"id": next(_ids), "action": action, "kmh": kmh, "issued_at": now}
    with _cond:
        if action == "stop":
            _queue.clear()  # stop overtakes everything still waiting
        else:
            for old in [c for c in _queue if c["action"] == action]:
                _queue.remove(old)  # only the newest speed/start/pause counts
        _queue.append(cmd)
        if kmh is not None:  # optimistic target so quick ±taps add up; the pad's status overwrites it
            _state["target_kmh"] = kmh
        _cond.notify_all()
    return cmd


def next_command(wait: float = 20.0) -> dict | None:
    """Recorder long poll: the oldest fresh command, or None after `wait` seconds."""
    global _seen
    deadline = time.time() + max(0.0, min(wait, 30.0))
    with _cond:
        _seen = time.time()
        while True:
            while _queue and time.time() - _queue[0]["issued_at"] > MAX_AGE_S:
                _queue.popleft()
            if _queue:
                cmd = _queue.popleft()
                # age instead of a timestamp: the Docker VM clock may drift from the host's
                return {**cmd, "age_s": round(time.time() - cmd["issued_at"], 2)}
            left = deadline - time.time()
            if left <= 0:
                return None
            _cond.wait(min(left, 1.0))
            _seen = time.time()


def report_state(payload: dict) -> dict:
    global _seen
    with _cond:
        _seen = time.time()
        pending_speed = any(c["action"] == "speed" for c in _queue)
        for key in ("connected", "status", "speed_kmh", "target_kmh", "device"):
            if key in payload and not (key == "target_kmh" and pending_speed):  # keep the optimistic target
                _state[key] = payload[key]
        _state["updated_at"] = _seen
    return state()


def report_result(cmd_id: int, ok: bool, message: str) -> None:
    with _cond:
        _results[cmd_id] = {"id": cmd_id, "ok": ok, "message": message[:120], "at": time.time()}
        for old in sorted(_results)[:-20]:
            del _results[old]
