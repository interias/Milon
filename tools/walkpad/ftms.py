"""FTMS Treadmill Data (0x2ACD) parser and session detection — pure logic, no Bluetooth.

The pad's own counters (distance, energy, elapsed time) are the session totals: a recorder that
connects mid-walk still gets the whole walk. A session ends when the counters reset, after
IDLE_END_S without movement, or after DISCONNECT_END_S without any packet."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

IDLE_END_S = 300
DISCONNECT_END_S = 180
MIN_SECONDS = 120
MIN_DISTANCE_M = 100

# (flag bit, field name, struct format, scale) in spec order; bit 0 is inverted ("more data" = 0 → speed present)
_FIELDS = (
    (1, "avg_speed_kmh", "<H", 0.01),
    (2, "distance_m", "<3s", 1),
    (3, "incline", "<hh", 0.1),
    (4, "elevation", "<HH", 0.1),
    (5, "pace", "<B", 0.1),
    (6, "avg_pace", "<B", 0.1),
    (7, "energy", "<HHB", 1),
    (8, "hr_bpm", "<B", 1),
    (9, "met", "<B", 0.1),
    (10, "elapsed_s", "<H", 1),
    (11, "remaining_s", "<H", 1),
    (12, "force_power", "<hh", 1),
)


def parse_treadmill_data(data: bytes) -> dict:
    """Decode one Treadmill Data notification; unknown trailing bytes are ignored."""
    flags = struct.unpack_from("<H", data, 0)[0]
    pos, out = 2, {"flags": flags}
    if not flags & 0x0001:
        out["speed_kmh"] = struct.unpack_from("<H", data, pos)[0] * 0.01
        pos += 2
    for bit, name, fmt, scale in _FIELDS:
        if not flags & (1 << bit):
            continue
        size = struct.calcsize(fmt)
        if pos + size > len(data):
            break
        raw = struct.unpack_from(fmt, data, pos)
        pos += size
        if name == "distance_m":
            out[name] = int.from_bytes(raw[0], "little")
        elif name == "energy":
            total, per_hour, per_min = raw
            out["kcal"] = None if total == 0xFFFF else total
            out["kcal_per_hour"] = None if per_hour == 0xFFFF else per_hour
            out["kcal_per_min"] = None if per_min == 0xFF else per_min
        elif name == "hr_bpm":
            out[name] = raw[0] or None  # 0 = no hand/strap contact
        elif len(raw) == 1:
            out[name] = raw[0] * scale
        else:
            out[name] = tuple(v * scale for v in raw)
    return out


@dataclass
class _Active:
    start: float                 # wall clock (epoch s) = first packet time − pad elapsed time
    base: dict = field(default_factory=dict)      # pad counters at start when the pad did not reset
    samples: list = field(default_factory=list)   # [t_rel, speed, distance, hr]
    last: dict = field(default_factory=dict)
    last_packet: float = 0.0
    last_motion: float = 0.0


class SessionTracker:
    """Feed packets with their wall-clock time; collect finished sessions from .finished."""

    def __init__(self, device: str = "", incline_pct: float | None = None) -> None:
        self.device = device
        self.incline_pct = incline_pct
        self.active: _Active | None = None
        self.finished: list[dict] = []
        self.counters: dict = {}  # last pad counters of a finished session (pause without reset)

    def packet(self, data: dict, now: float) -> None:
        speed = data.get("speed_kmh") or 0.0
        dist = data.get("distance_m")
        elapsed = data.get("elapsed_s")
        a = self.active
        if a is not None:
            prev_d, prev_e = a.last.get("distance_m"), a.last.get("elapsed_s")
            reset = (dist is not None and prev_d is not None and dist < prev_d) or \
                    (elapsed is not None and prev_e is not None and elapsed + 5 < prev_e)
            if reset:
                self._finish()
                self.counters = {}
                a = None
        if a is None:
            if speed <= 0:
                return
            paused = (dist or 0) >= self.counters.get("distance_m", 0) > 0 \
                and (elapsed or 0) >= self.counters.get("elapsed_s", 0)
            base = self.counters if paused else {}
            a = self.active = _Active(start=now - ((elapsed or 0) - base.get("elapsed_s", 0)), base=dict(base))
            a.last_motion = now
        if speed > 0 or (dist is not None and dist > a.last.get("distance_m", -1)):
            a.last_motion = now
        a.last_packet = now
        a.last = {**a.last, **{k: v for k, v in data.items() if v is not None}}
        d = dist if dist is not None else a.last.get("distance_m", 0)
        a.samples.append([round(now - a.start, 1), round(speed, 2), d - a.base.get("distance_m", 0), data.get("hr_bpm")])
        if speed == 0 and now - a.last_motion >= IDLE_END_S:
            self._finish()

    def tick(self, now: float) -> None:
        """Called periodically; ends a session after idling or losing the pad."""
        a = self.active
        if a is not None and (now - a.last_packet >= DISCONNECT_END_S or now - a.last_motion >= IDLE_END_S):
            self._finish()

    def flush(self) -> None:
        """End the running session now (recorder shutdown)."""
        if self.active is not None:
            self._finish()

    def _finish(self) -> None:
        a, self.active = self.active, None
        if a is None:
            return
        self.counters = {k: a.last[k] for k in ("distance_m", "elapsed_s", "kcal") if a.last.get(k) is not None}
        elapsed = (a.last.get("elapsed_s") or 0) - a.base.get("elapsed_s", 0)
        end = a.start + max((s[0] for s in a.samples if s[1] > 0), default=a.samples[-1][0] if a.samples else 0)
        end = max(end, a.start + elapsed)
        distance = (a.last.get("distance_m") or 0) - a.base.get("distance_m", 0)
        kcal = a.last.get("kcal")
        if kcal is not None:
            kcal -= a.base.get("kcal", 0)
        if end - a.start < MIN_SECONDS or distance < MIN_DISTANCE_M:
            return
        cut = end - a.start
        session = {
            "id": f"wp-{int(a.start)}",
            "started_at": round(a.start, 1), "ended_at": round(end, 1),
            "elapsed_s": elapsed, "distance_m": distance, "kcal": kcal,
            "device": self.device or None,
            "samples": [s for s in a.samples if s[0] <= cut + 1],
        }
        if self.incline_pct is not None:
            session["incline_pct"] = self.incline_pct
        self.finished.append(session)
