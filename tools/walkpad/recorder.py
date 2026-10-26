"""Milon walking-pad recorder — runs on the Windows host (Docker Desktop has no Bluetooth).

Connects to the pad (FTMS 0x1826), listens to Treadmill Data (0x2ACD) read-only and posts each
finished session to Milon (POST /api/walkpad/sessions, header X-Walkpad-Token). Sessions wait in a
spool folder until the server accepts them. Never writes the FTMS Control Point.

Config (environment or tools/walkpad/.env): WALKPAD_TOKEN (required), WALKPAD_URL
(default http://localhost/api/walkpad/sessions), WALKPAD_NAME (name prefix, default "sWalk"),
WALKPAD_ADDRESS (optional MAC), WALKPAD_INCLINE_PCT (optional; empty = server setting)."""
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
from ftms import SessionTracker, parse_treadmill_data  # noqa: E402

FTMS_SERVICE = "00001826-0000-1000-8000-00805f9b34fb"
TREADMILL_DATA = "00002acd-0000-1000-8000-00805f9b34fb"
HOME = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "milon-walkpad"
SPOOL = HOME / "spool"
REJECTED = HOME / "rejected"
log = logging.getLogger("walkpad")


def _load_env() -> None:
    env = Path(__file__).resolve().parent / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _spool(sessions: list[dict]) -> None:
    SPOOL.mkdir(parents=True, exist_ok=True)
    for s in sessions:
        (SPOOL / f"{s['id']}.json").write_text(json.dumps(s), encoding="utf-8")
        log.info("session %s: %.0f m, %.0f min → spool", s["id"], s["distance_m"],
                 (s["ended_at"] - s["started_at"]) / 60)
    sessions.clear()


def deliver(url: str, token: str) -> None:
    """Post spooled sessions; 2xx deletes, 422 moves aside, anything else retries later."""
    for path in sorted(SPOOL.glob("*.json")) if SPOOL.is_dir() else []:
        req = urllib.request.Request(url, data=path.read_bytes(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Walkpad-Token": token})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                log.info("session %s delivered (%s)", path.stem, resp.status)
            path.unlink()
        except urllib.error.HTTPError as e:
            if e.code == 422:
                REJECTED.mkdir(parents=True, exist_ok=True)
                path.replace(REJECTED / path.name)
                log.warning("session %s rejected: %s", path.stem, e.read()[:200])
            else:
                log.warning("session %s not delivered: HTTP %s", path.stem, e.code)
                return
        except OSError as e:
            log.info("server not reachable (%s); retry later", e)
            return


async def run() -> None:
    from bleak import BleakClient, BleakScanner

    _load_env()
    token = os.environ.get("WALKPAD_TOKEN", "")
    url = os.environ.get("WALKPAD_URL", "http://localhost/api/walkpad/sessions")
    prefix = os.environ.get("WALKPAD_NAME", "sWalk").lower()
    address = os.environ.get("WALKPAD_ADDRESS", "").upper()
    incline = os.environ.get("WALKPAD_INCLINE_PCT", "").strip()
    if not token:
        raise SystemExit("WALKPAD_TOKEN fehlt (tools/walkpad/.env oder Umgebung).")
    tracker = SessionTracker(incline_pct=float(incline) if incline else None)

    def match(device, adv) -> bool:
        if address:
            return device.address.upper() == address
        return (device.name or adv.local_name or "").lower().startswith(prefix)

    async def housekeeping() -> None:
        tracker.tick(time.time())  # tracker lives on the event loop (BLE callbacks); only HTTP goes to a thread
        if tracker.finished:
            _spool(tracker.finished)
        await asyncio.to_thread(deliver, url, token)

    while True:
        await housekeeping()
        device = await BleakScanner.find_device_by_filter(match, timeout=20)
        if device is None:
            continue
        tracker.device = device.name or ""
        try:
            async with BleakClient(device, timeout=20) as client:
                log.info("connected to %s", tracker.device)

                def on_data(_, data: bytearray) -> None:
                    try:
                        tracker.packet(parse_treadmill_data(bytes(data)), time.time())
                    except Exception:  # noqa: BLE001 -- one corrupt packet must not stop recording
                        log.exception("bad packet %s", bytes(data).hex())

                await client.start_notify(TREADMILL_DATA, on_data)
                while client.is_connected:
                    await asyncio.sleep(10)
                    await housekeeping()
            log.info("disconnected")
        except Exception as e:  # noqa: BLE001 -- pad switched off, taken by the phone app, …
            log.info("connection failed: %s", e)
            await asyncio.sleep(10)


def main() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(HOME / "recorder.log", encoding="utf-8"),
                                  logging.StreamHandler()])
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
