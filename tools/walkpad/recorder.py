"""Milon walking-pad recorder — runs on the Windows host (Docker Desktop has no Bluetooth).

Connects to the pad (FTMS 0x1826), listens to Treadmill Data (0x2ACD) and posts each finished
session to Milon (POST /api/walkpad/sessions, header X-Walkpad-Token). Sessions wait in a spool
folder until the server accepts them.

Remote control (WALKPAD_REMOTE, default on): long-polls Milon for commands and writes them to the
FTMS Control Point (0x2AD9); the pad's real state comes from Fitness Machine Status (0x2ADA) and is
reported back. Commands older than 3 s are dropped (ftms_control).

Config (environment or tools/walkpad/.env): WALKPAD_TOKEN (required), WALKPAD_URL
(default http://127.0.0.1/api/walkpad/sessions), WALKPAD_NAME (name prefix, default "sWalk"),
WALKPAD_ADDRESS (optional MAC), WALKPAD_INCLINE_PCT (optional; empty = server setting),
WALKPAD_REMOTE (0 = never write the Control Point)."""
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
from ftms_control import PadControl, parse_status  # noqa: E402

FTMS_SERVICE = "00001826-0000-1000-8000-00805f9b34fb"
TREADMILL_DATA = "00002acd-0000-1000-8000-00805f9b34fb"
CONTROL_POINT = "00002ad9-0000-1000-8000-00805f9b34fb"
MACHINE_STATUS = "00002ada-0000-1000-8000-00805f9b34fb"
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


def _call(url: str, token: str, payload: dict | None = None, timeout: float = 10) -> dict | None:
    """Small JSON call to Milon; None on 204 or any error (control is best effort, recording is not)."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", "X-Walkpad-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return json.loads(body) if resp.status == 200 and body else None
    except (OSError, ValueError):
        return None


async def run() -> None:
    from bleak import BleakClient, BleakScanner

    _load_env()
    token = os.environ.get("WALKPAD_TOKEN", "")
    url = os.environ.get("WALKPAD_URL", "http://127.0.0.1/api/walkpad/sessions")
    prefix = os.environ.get("WALKPAD_NAME", "sWalk").lower()
    address = os.environ.get("WALKPAD_ADDRESS", "").upper()
    incline = os.environ.get("WALKPAD_INCLINE_PCT", "").strip()
    if not token:
        raise SystemExit("WALKPAD_TOKEN fehlt (tools/walkpad/.env oder Umgebung).")
    tracker = SessionTracker(incline_pct=float(incline) if incline else None)
    remote = os.environ.get("WALKPAD_REMOTE", "1").strip() not in ("0", "false", "no")
    control_url = url.rsplit("/sessions", 1)[0] + "/control"
    pad = {"connected": False, "status": None, "speed_kmh": None, "target_kmh": None, "device": None}

    async def report() -> None:
        if remote:
            await asyncio.to_thread(_call, control_url + "/state", token, dict(pad))

    def match(device, adv) -> bool:
        if address:
            return device.address.upper() == address
        return (device.name or adv.local_name or "").lower().startswith(prefix)

    async def housekeeping() -> None:
        tracker.tick(time.time())  # tracker lives on the event loop (BLE callbacks); only HTTP goes to a thread
        if tracker.finished:
            _spool(tracker.finished)
        await asyncio.to_thread(deliver, url, token)
        await report()

    async def commands(client, control: PadControl) -> None:
        """Long poll; a command's age comes from the server, measured on its own clock."""
        while client.is_connected:
            cmd = await asyncio.to_thread(_call, control_url + "/next?wait=20", token, None, 30)
            if not cmd:
                await asyncio.sleep(0.2)
                continue
            cmd["issued_at"] = time.time() - float(cmd.get("age_s", 99))
            result = await control.run(cmd)
            log.info("command %s %s → %s", cmd.get("action"), cmd.get("kmh") or "", result["message"])
            await asyncio.to_thread(_call, control_url + "/result", token, {"id": cmd.get("id"), **result})

    while True:
        pad.update(connected=False, status=None)
        await housekeeping()
        device = await BleakScanner.find_device_by_filter(match, timeout=20)
        if device is None:
            continue
        tracker.device = pad["device"] = device.name or ""
        try:
            async with BleakClient(device, timeout=20) as client:
                log.info("connected to %s", tracker.device)

                def on_data(_, data: bytearray) -> None:
                    try:
                        parsed = parse_treadmill_data(bytes(data))
                        tracker.packet(parsed, time.time())
                        pad["speed_kmh"] = round(parsed.get("speed_kmh") or 0.0, 2)
                        if pad["status"] is None:
                            pad["status"] = "running" if pad["speed_kmh"] > 0 else "stopped"
                    except Exception:  # noqa: BLE001 -- one corrupt packet must not stop recording
                        log.exception("bad packet %s", bytes(data).hex())

                pad.update(connected=True)
                await client.start_notify(TREADMILL_DATA, on_data)
                poller = None
                if remote:
                    control = PadControl(lambda payload: client.write_gatt_char(CONTROL_POINT, payload, response=True),
                                         speed=lambda: pad["speed_kmh"])

                    def on_status(_, data: bytearray) -> None:
                        update = parse_status(bytes(data))
                        control.on_status(update)
                        pad.update({k: v for k, v in update.items() if k in ("status", "target_kmh")})

                    await client.start_notify(CONTROL_POINT, lambda _, d: control.on_indication(bytes(d)))
                    await client.start_notify(MACHINE_STATUS, on_status)
                    poller = asyncio.create_task(commands(client, control))
                ticks = 0
                while client.is_connected:
                    await asyncio.sleep(2)
                    ticks += 1
                    if ticks % 5 == 0:
                        await housekeeping()
                    else:
                        await report()
                if poller:
                    poller.cancel()
                    control.cancel_follow_up()
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
