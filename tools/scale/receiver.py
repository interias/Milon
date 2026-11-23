"""Milon scale receiver — "step on, done". Runs on the Windows host (Docker Desktop has no Bluetooth), next to the
walkpad recorder.

Scans for the scale (name prefix SCALE_NAME, default "QN"). Stepping on wakes the scale and it advertises; the receiver
connects, runs the QN handshake (tools/scale/qn.py), asks the scale memory every 3 s until the weighing arrives (live
0x10 or stored 0x23), and posts every reading to Milon (POST /api/scale/measurements — the same endpoint as the
phone). Older records from the scale memory are posted with their own time. Readings wait in a spool folder while
Milon is down. Every packet is logged as hex (%LOCALAPPDATA%\\milon-scale\\receiver.log).

The scale takes one connection at a time: while the receiver holds it, the phone's "Wiegen" cannot connect.

Config (environment or tools/scale/.env): SCALE_URL (default http://127.0.0.1/api/scale/measurements),
SCALE_NAME (default "QN"), SCALE_ADDRESS (optional MAC)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qn import QnSession, hexs  # noqa: E402

u16 = "0000{:04x}-0000-1000-8000-00805f9b34fb".format
NOTIFY = [u16(0xFFF1), u16(0xFFE1), u16(0xFFE2)]
WRITE = [u16(0xFFF2), u16(0xFFE3)]
TIME = [u16(0xFFF2), u16(0xFFE4)]
POLL_S = 3.0
SESSION_S = 120.0   # give up a connection without a weighing after this
COOLDOWN_S = 30.0   # the scale keeps advertising for a while after a weighing
HOME = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "milon-scale"
SPOOL = HOME / "spool"
REJECTED = HOME / "rejected"
log = logging.getLogger("scale")


def _load_env() -> None:
    env = Path(__file__).resolve().parent / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def spool(readings: list[dict]) -> None:
    SPOOL.mkdir(parents=True, exist_ok=True)
    for r in readings:
        name = r["timestamp"].replace(":", "").replace(".", "") + ".json"
        (SPOOL / name).write_text(json.dumps(r), encoding="utf-8")
        log.info("reading %.2f kg (%s, %s) → spool", r["weightKg"], r["source"], r["timestamp"])


def deliver(url: str) -> None:
    """Post spooled readings; 2xx deletes (200 = already known), 422 moves aside, anything else retries later."""
    for path in sorted(SPOOL.glob("*.json")) if SPOOL.is_dir() else []:
        req = urllib.request.Request(url, data=path.read_bytes(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                log.info("reading %s delivered (%s%s)", path.stem, resp.status, ", duplicate" if resp.status == 200 else "")
            path.unlink()
        except urllib.error.HTTPError as e:
            if e.code == 422:
                REJECTED.mkdir(parents=True, exist_ok=True)
                path.replace(REJECTED / path.name)
                log.warning("reading %s rejected: %s", path.stem, e.read()[:200])
            else:
                log.warning("reading %s not delivered: HTTP %s", path.stem, e.code)
                return
        except OSError as e:
            log.info("server not reachable (%s); retry later", e)
            return


async def weigh(client) -> QnSession:
    """One connection: handshake, poll the memory, return when the weighing is in (or the time is up)."""
    chars = {c.uuid: c for s in client.services for c in s.characteristics}
    log.info("characteristics: %s", ", ".join(f"{u[4:8]}[{','.join(c.properties)}]" for u, c in chars.items()))
    write = next((chars[u] for u in WRITE if u in chars), None)
    timec = next((chars[u] for u in TIME if u in chars), None)
    if write is None:
        raise RuntimeError("no QN write characteristic (FFF2/FFE3)")
    session = QnSession(time.time())
    lock = asyncio.Lock()  # one GATT write at a time
    done = asyncio.Event()

    async def send(target: str, data: bytes | None) -> None:
        if not data:
            return
        char = write if target == "write" else timec
        async with lock:
            log.info("→ %s", hexs(data))
            await client.write_gatt_char(char, data, response="write" in char.properties)

    async def handle(data: bytes) -> None:
        for target, out in session.on_packet(data, time.time()):
            await send(target, out)
        if session.final:
            done.set()

    def on_notify(_, data: bytearray) -> None:
        log.info("← %s", hexs(bytes(data)))
        asyncio.get_running_loop().create_task(handle(bytes(data)))

    for u in NOTIFY:
        if u in chars:
            await client.start_notify(chars[u], on_notify)
            log.info("notifications on %s", u[4:8])
    started = time.monotonic()
    while client.is_connected and not done.is_set() and time.monotonic() - started < SESSION_S:
        try:
            await asyncio.wait_for(done.wait(), POLL_S)
        except asyncio.TimeoutError:
            await send("write", session.history_query())
    if session.final:
        await asyncio.sleep(1.0)  # let the ack go out
    return session


async def run() -> None:
    from bleak import BleakClient, BleakScanner

    _load_env()
    url = os.environ.get("SCALE_URL", "http://127.0.0.1/api/scale/measurements")
    prefix = os.environ.get("SCALE_NAME", "QN").lower()
    address = os.environ.get("SCALE_ADDRESS", "").upper()

    def match(device, adv) -> bool:
        if address:
            return device.address.upper() == address
        return (device.name or adv.local_name or "").lower().startswith(prefix)

    log.info("waiting for the scale (%s)", address or f"name {prefix}*")
    while True:
        await asyncio.to_thread(deliver, url)
        device = await BleakScanner.find_device_by_filter(match, timeout=60)
        if device is None:
            continue
        log.info("scale awake: %s %s", device.name, device.address)
        session = None
        try:
            async with BleakClient(device, timeout=15) as client:
                log.info("connected")
                session = await weigh(client)
            log.info("disconnected")
        except Exception as e:  # noqa: BLE001 -- scale went back to sleep, taken by the phone, …
            log.info("connection failed: %s", e)
        if session is not None:
            readings = session.backlog + ([session.final] if session.final else [])
            if session.final:
                log.info("weighing: %.2f kg (%s)", session.final["weightKg"], session.final["source"])
            elif session.last_live is not None:
                log.info("no stable weighing (last live value %.2f kg)", session.last_live)
            else:
                log.info("no weighing in this connection")
            spool(readings)
            await asyncio.to_thread(deliver, url)
        await asyncio.sleep(COOLDOWN_S if session and session.final else 5)


def main() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(HOME / "receiver.log", encoding="utf-8"),
                                  logging.StreamHandler()])
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
