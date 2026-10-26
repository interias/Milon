"""FTMS remote control — Control Point (0x2AD9) writes and Machine Status (0x2ADA) — no Bluetooth here.

The pad is under a desk, so the rules are strict: commands older than MAX_AGE_S are dropped, speed is
clamped to the pad range and the configured maximum, a missing or failed response is reported, never
retried with a faster speed. Incline cannot be controlled (manual flap; feature bit 3 is off).

The sWalk ignores a speed set while stopped and always starts at 1.0 km/h after a ~3 s countdown, so
"start at X" is a start plus a follow-up: once the belt moves, X is set. The follow-up runs on its
own and any newer command (stop!) cancels it — a stop never waits behind the countdown."""
from __future__ import annotations

import asyncio
import struct
import time
from collections.abc import Awaitable, Callable

MAX_AGE_S = 3.0
START_WAIT_S = 10.0      # countdown + spin-up; the follow-up speed is dropped after this
RESPONSE_TIMEOUT_S = 3.0
MIN_KMH, PAD_MAX_KMH = 1.0, 6.0

OP_REQUEST_CONTROL, OP_SET_SPEED, OP_START, OP_STOP_PAUSE, OP_RESPONSE = 0x00, 0x02, 0x07, 0x08, 0x80
RESULTS = {0x01: "ok", 0x02: "nicht unterstützt", 0x03: "ungültiger Wert", 0x04: "fehlgeschlagen",
           0x05: "keine Steuerberechtigung"}


def encode(action: str, kmh: float | None = None, max_kmh: float = PAD_MAX_KMH) -> bytes:
    if action == "start":
        return bytes([OP_START])
    if action == "stop":
        return bytes([OP_STOP_PAUSE, 0x01])
    if action == "pause":
        return bytes([OP_STOP_PAUSE, 0x02])
    if action == "speed":
        if kmh is None:
            raise ValueError("speed ohne kmh")
        kmh = min(max(kmh, MIN_KMH), max_kmh, PAD_MAX_KMH)
        return struct.pack("<BH", OP_SET_SPEED, round(kmh * 100))
    raise ValueError(f"unbekannte Aktion {action}")


def parse_status(data: bytes) -> dict:
    """Fitness Machine Status notification → the pad's real state."""
    op = data[0] if data else None
    if op == 0x02:
        return {"status": "paused" if len(data) > 1 and data[1] == 0x02 else "stopped"}
    if op == 0x03:
        return {"status": "stopped", "reason": "Sicherheitsschlüssel"}
    if op == 0x04:
        return {"status": "running"}
    if op == 0x05 and len(data) >= 3:
        return {"target_kmh": struct.unpack_from("<H", data, 1)[0] / 100}
    if op == 0x01:
        return {"status": "stopped", "reason": "Reset"}
    if op == 0xFF:
        return {"control": False}
    return {}


class PadControl:
    """Writes Control Point opcodes and waits for the indicated response (0x80, op, result)."""

    def __init__(self, write: Callable[[bytes], Awaitable[None]], max_kmh: float = PAD_MAX_KMH,
                 clock: Callable[[], float] = time.time, speed: Callable[[], float | None] | None = None) -> None:
        self.write, self.max_kmh, self.clock, self.speed = write, max_kmh, clock, speed
        self.has_control = False
        self._pending: tuple[int, asyncio.Future] | None = None
        self.follow_up: asyncio.Task | None = None

    def on_indication(self, data: bytes) -> None:
        if len(data) >= 3 and data[0] == OP_RESPONSE and self._pending and self._pending[0] == data[1]:
            fut = self._pending[1]
            if not fut.done():
                fut.set_result(data[2])

    def on_status(self, status: dict) -> None:
        if status.get("control") is False:
            self.has_control = False

    async def _send(self, payload: bytes) -> int:
        fut = asyncio.get_running_loop().create_future()
        self._pending = (payload[0], fut)
        try:
            await self.write(payload)
            return await asyncio.wait_for(fut, RESPONSE_TIMEOUT_S)
        finally:
            self._pending = None

    async def _control(self) -> bool:
        if not self.has_control:
            self.has_control = await self._send(bytes([OP_REQUEST_CONTROL])) == 0x01
        return self.has_control

    def cancel_follow_up(self) -> None:
        if self.follow_up is not None and not self.follow_up.done():
            self.follow_up.cancel()
        self.follow_up = None

    async def _speed_when_running(self, kmh: float) -> None:
        """Set the wished speed as soon as the belt moves; give up after START_WAIT_S."""
        deadline = self.clock() + START_WAIT_S
        while self.clock() < deadline:
            if (self.speed() or 0) > 0:
                await self._send(encode("speed", kmh, self.max_kmh))
                return
            await asyncio.sleep(0.2)

    async def run(self, cmd: dict) -> dict:
        """Execute one command {action, kmh?, issued_at}; returns {ok, message}."""
        self.cancel_follow_up()  # any newer command wins over a pending "start at X"
        if self.clock() - float(cmd.get("issued_at") or 0) > MAX_AGE_S:
            return {"ok": False, "message": "verworfen (älter als 3 s)"}
        try:
            payload = encode(cmd["action"], cmd.get("kmh"), self.max_kmh)
        except (KeyError, ValueError) as e:
            return {"ok": False, "message": str(e)}
        try:
            if not await self._control():
                return {"ok": False, "message": "Pad gibt die Steuerung nicht frei"}
            result = await self._send(payload)
            if result == 0x05:  # control lost meanwhile (e.g. pad remote): ask once more, same payload
                self.has_control = False
                if self.clock() - float(cmd["issued_at"]) <= MAX_AGE_S and await self._control():
                    result = await self._send(payload)
        except asyncio.TimeoutError:
            return {"ok": False, "message": "keine Antwort vom Pad"}
        if result == 0x01 and cmd["action"] == "start" and cmd.get("kmh") and self.speed is not None:
            self.follow_up = asyncio.create_task(self._speed_when_running(float(cmd["kmh"])))
        return {"ok": result == 0x01, "message": RESULTS.get(result, f"Code {result}")}
