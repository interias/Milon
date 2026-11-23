"""QN-Scale protocol (Chipsea/Yolanda; Arboleaf CS20L) without Bluetooth — same logic as client/lib/scale/qnScale.ts.

`QnSession` takes notification packets and returns what to write back; readings come out in the shape of the
browser driver's ScaleReading, ready for POST /api/scale/measurements.

Learned on the real CS20L (2026-11-23): protocol type 0xff, weight factor /10, newer firmware (0x21 → 0xA0/0xA1).
A weighing it does not stream live ends up in its memory (0x23); the scale deletes a record once it has sent it,
so every valid record is kept (older ones with their own time)."""
from __future__ import annotations

from datetime import datetime, timezone

QN_EPOCH_OFFSET = 946_702_800
FRESH_S = 90  # a stored record this young (vs. session start) is "this weighing"


def with_checksum(values: list[int]) -> bytes:
    out = bytearray(v & 0xFF for v in values)
    out[-1] = sum(out[:-1]) & 0xFF
    return bytes(out)


def hexs(d: bytes) -> str:
    return " ".join(f"{b:02x}" for b in d)


def qn_now(now: float) -> int:
    return int(now) - QN_EPOCH_OFFSET


def le4(t: int) -> list[int]:
    return [t & 0xFF, (t >> 8) & 0xFF, (t >> 16) & 0xFF, (t >> 24) & 0xFF]


def parse_info(d: bytes, factor: int) -> int:
    return (100 if d[10] == 1 else 10) if len(d) > 10 else factor


def parse_live(d: bytes, factor: int, protocol_type: int) -> dict | None:
    new_layout = len(d) >= 11 and d[4] <= 0x02 and factor == 10
    if new_layout:
        stable = d[4] == 0x02 or (d[4] == 0x01 and protocol_type != 0xFF)
        raw, r1, r2 = (d[5] << 8) | d[6], (d[7] << 8) | d[8], (d[9] << 8) | d[10]
    else:
        if len(d) < 10:
            return None
        stable = d[5] == 1
        raw, r1, r2 = (d[3] << 8) | d[4], (d[6] << 8) | d[7], (d[8] << 8) | d[9]
    kg = raw / factor
    if kg <= 5 or kg >= 250:
        kg /= 10
    return {"stable": stable, "kg": kg, "r1": r1, "r2": r2, "new_layout": new_layout}


def parse_stored(d: bytes) -> dict | None:
    if len(d) < 17:
        return None
    return {"kg": ((d[10] << 8) | d[11]) / 100,
            "rec_time": d[6] | (d[7] << 8) | (d[8] << 16) | (d[9] << 24),
            "r1": d[13] | (d[14] << 8), "r2": d[15] | (d[16] << 8)}


def qn_time_to_iso(rec_time: int, now: float) -> str | None:
    """Record time → ISO UTC, or None if the scale clock is implausible (unset, > 1 year old, future)."""
    t = rec_time + QN_EPOCH_OFFSET
    if t < now - 365 * 86400 or t > now + 600:
        return None
    return iso(t)


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class QnSession:
    """One connection. `on_packet` returns [(target, bytes)] with target "write" (FFF2/FFE3) or "time" (FFF2/FFE4)."""

    def __init__(self, now: float, unit_lb: bool = False):
        self.protocol_type = -1
        self.factor = 100
        self.config_sent = False
        self.start_qn = qn_now(now)
        self.unit = 0x02 if unit_lb else 0x01
        self.history_ready = False      # scale announced history support (0x21)
        self.backlog: list[dict] = []   # older stored records, to save with their own time
        self.final: dict | None = None  # this weighing
        self.last_live: float | None = None

    def _reading(self, kg: float, r1: int, r2: int, source: str, ts: str, d: bytes) -> dict:
        return {"weightKg": round(kg, 2), "r1": r1, "r2": r2, "source": source,
                "protocolType": self.protocol_type, "timestamp": ts, "rawHex": hexs(d)}

    def history_query(self) -> bytes | None:
        if not self.history_ready or self.final:
            return None
        return with_checksum([0x22, 0x06, self.protocol_type, 0x00, 0x03, 0x00])

    def ack(self) -> bytes:
        return with_checksum([0x1F, 0x05, self.protocol_type, 0x10, 0x00])

    def on_packet(self, d: bytes, now: float) -> list[tuple[str, bytes]]:
        if len(d) < 3 or self.final:
            return []
        if self.protocol_type < 0:
            self.protocol_type = d[2]
        pt, op = self.protocol_type, d[0]
        if op == 0x12:
            self.factor = parse_info(d, self.factor)
            if self.config_sent:
                return []
            self.config_sent = True
            return [("write", with_checksum([0x13, 0x09, pt, self.unit, 0x10, 0, 0, 0, 0])),
                    ("time", bytes([0x02, *le4(qn_now(now))]))]
        if op == 0x14:
            return [("write", with_checksum([0x20, 0x08, pt, *le4(qn_now(now)), 0]))]
        if op == 0x21:
            self.history_ready = True
            return [("write", with_checksum([0xA0, 0x0D, 0x04, 0xFE, 0, 0, 0, 0, 0, 0, 0, 0, 0])),
                    ("write", with_checksum([0xA0, 0x0D, 0x02, 0x01, 0x00, 0x08, 0x00, 0x21, 0x06, 0xB8, 0x04, 0x02, 0])),
                    ("write", self.history_query())]
        if op == 0x10:
            f = parse_live(d, self.factor, pt)
            if not f:
                return []
            self.last_live = round(f["kg"], 2)
            if f["stable"] and f["kg"] > 5:
                self.final = self._reading(f["kg"], f["r1"], f["r2"], "live", iso(now), d)
                return [("write", self.ack())]
            return []
        if op == 0x23:
            f = parse_stored(d)
            if not f or (f["kg"] == 0 and f["rec_time"] == 0) or not 5 < f["kg"] < 300:
                return []
            reading = self._reading(f["kg"], f["r1"], f["r2"], "stored",
                                    qn_time_to_iso(f["rec_time"], now) or iso(now), d)
            if f["rec_time"] + FRESH_S >= self.start_qn:
                self.final = reading
                return [("write", self.ack())]
            self.backlog.append(reading)
        return []
