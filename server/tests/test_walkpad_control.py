"""Walking pad remote control: server queue + safety rules, recorder side against a simulated FTMS pad."""
import asyncio
import struct
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import walkpad_control as wc
from app.config import settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "walkpad"))
import ftms_control as fc  # noqa: E402


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    wc.reset()
    monkeypatch.setattr(settings, "walkpad_max_speed_kmh", 6.0)
    yield
    wc.reset()


def online(speed=3.0, status="running"):
    wc.report_state({"connected": True, "status": status, "speed_kmh": speed, "target_kmh": speed, "device": "sim"})


class SimPad:
    """Simulated FTMS treadmill: answers Control Point writes with indications like a real pad."""

    def __init__(self, grant=True, answer=True):
        self.grant, self.answer = grant, answer
        self.writes: list[bytes] = []
        self.speed, self.running, self.control = 0.0, False, None

    async def write(self, payload: bytes) -> None:
        self.writes.append(payload)
        op = payload[0]
        if op == fc.OP_REQUEST_CONTROL:
            result = 0x01 if self.grant else 0x05
        elif op == fc.OP_SET_SPEED:
            kmh = struct.unpack_from("<H", payload, 1)[0] / 100
            result = 0x01 if 1.0 <= kmh <= 6.0 else 0x03
            if result == 0x01:
                self.speed = kmh
        elif op == fc.OP_START:
            self.running, result = True, 0x01
        elif op == fc.OP_STOP_PAUSE:
            self.running, result = False, 0x01
        else:
            result = 0x02
        if self.answer:
            asyncio.get_running_loop().call_soon(self.control.on_indication, bytes([0x80, op, result]))


def run(pad: SimPad, *cmds, clock=None):
    async def go():
        control = fc.PadControl(pad.write, clock=clock or (lambda: 1000.0))
        pad.control = control
        return [await control.run(c) for c in cmds]
    return asyncio.run(go())


# ---------------- recorder side ----------------
def test_sim_pad_start_speed_stop():
    pad = SimPad()
    out = run(pad, {"action": "start", "issued_at": 999.5}, {"action": "speed", "kmh": 3.4, "issued_at": 999.5},
              {"action": "stop", "issued_at": 999.9})
    assert all(r["ok"] for r in out)
    assert pad.writes[0] == b"\x00"  # control requested once, first
    assert pad.writes[1:] == [b"\x07", struct.pack("<BH", 2, 340), b"\x08\x01"]
    assert pad.speed == 3.4 and not pad.running


def test_stale_command_is_never_written():
    pad = SimPad()
    out = run(pad, {"action": "speed", "kmh": 5.0, "issued_at": 996.0})
    assert not out[0]["ok"] and "verworfen" in out[0]["message"] and pad.writes == []


def test_speed_is_clamped_to_pad_range():
    assert fc.encode("speed", 9.0) == struct.pack("<BH", 2, 600)
    assert fc.encode("speed", 0.2) == struct.pack("<BH", 2, 100)
    assert fc.encode("speed", 5.5, max_kmh=4.0) == struct.pack("<BH", 2, 400)
    assert fc.encode("pause") == b"\x08\x02"


def test_refused_control_and_silent_pad(monkeypatch):
    out = run(SimPad(grant=False), {"action": "start", "issued_at": 1000})
    assert not out[0]["ok"] and "Steuerung" in out[0]["message"]
    monkeypatch.setattr(fc, "RESPONSE_TIMEOUT_S", 0.05)
    out = run(SimPad(answer=False), {"action": "stop", "issued_at": 1000})
    assert not out[0]["ok"] and "keine Antwort" in out[0]["message"]


def test_status_parsing():
    assert fc.parse_status(b"\x02\x02") == {"status": "paused"}
    assert fc.parse_status(b"\x02\x01") == {"status": "stopped"}
    assert fc.parse_status(b"\x04") == {"status": "running"}
    assert fc.parse_status(struct.pack("<BH", 5, 350)) == {"target_kmh": 3.5}
    assert fc.parse_status(b"\xff") == {"control": False}


# ---------------- server side ----------------
def test_offline_refuses_everything():
    with pytest.raises(wc.ControlError):
        wc.enqueue("stop")
    wc.report_state({"connected": False})
    with pytest.raises(wc.ControlError):
        wc.enqueue("speed", kmh=3)


def test_start_needs_confirmation_and_speed_is_clamped(monkeypatch):
    online()
    with pytest.raises(wc.ControlError) as e:
        wc.enqueue("start")
    assert e.value.status == 422
    assert wc.enqueue("start", confirm=True)["action"] == "start"
    monkeypatch.setattr(settings, "walkpad_max_speed_kmh", 4.5)
    assert wc.enqueue("speed", kmh=6)["kmh"] == 4.5
    assert wc.enqueue("speed", kmh=0.3)["kmh"] == 1.0


def test_relative_steps_add_up_and_respect_max():
    online(3.0)
    assert wc.enqueue("faster", step=0.5)["kmh"] == 3.5
    assert wc.enqueue("faster", step=0.1)["kmh"] == 3.6  # from the new target, not the old speed
    assert wc.enqueue("slower", step=0.5)["kmh"] == 3.1
    with pytest.raises(wc.ControlError):
        wc.enqueue("faster", step=1.0)
    for _ in range(10):
        wc.enqueue("faster", step=0.5)
    assert wc.state()["target_kmh"] == 6.0


def test_queue_stop_overtakes_and_stale_commands_drop(monkeypatch):
    online()
    wc.enqueue("speed", kmh=4)
    wc.enqueue("speed", kmh=4.2)  # replaces the first one
    cmd = wc.next_command(0)
    assert cmd["kmh"] == 4.2 and cmd["age_s"] < 1 and wc.next_command(0) is None
    wc.enqueue("speed", kmh=5)
    wc.enqueue("stop")
    assert wc.next_command(0)["action"] == "stop" and wc.next_command(0) is None
    wc.enqueue("speed", kmh=5, now=wc.time.time() - 10)  # issued 10 s ago
    assert wc.next_command(0) is None


def test_end_to_end_queue_to_sim_pad():
    online(2.0)
    wc.enqueue("faster", step=0.5)
    pad = SimPad()
    cmd = wc.next_command(0)
    cmd["issued_at"] = 1000.0 - cmd["age_s"]
    result = run(pad, cmd)[0]
    wc.report_result(cmd["id"], **result)
    assert pad.speed == 2.5 and wc.state()["last_result"]["ok"]


def test_api_token_and_flow(monkeypatch):
    from app.main import app
    http = TestClient(app)
    monkeypatch.setattr(settings, "walkpad_token", "secret")
    h = {"X-Walkpad-Token": "secret"}
    assert http.get("/walkpad/control/next?wait=0").status_code == 401
    assert http.post("/walkpad/control", json={"action": "stop"}).status_code == 409
    http.post("/walkpad/control/state", json={"connected": True, "status": "stopped", "speed_kmh": 0}, headers=h)
    assert http.get("/walkpad/control").json()["connected"]
    assert http.post("/walkpad/control", json={"action": "start"}).status_code == 422
    assert http.post("/walkpad/control", json={"action": "start", "confirm": True}).status_code == 200
    assert http.post("/walkpad/control", json={"action": "fly"}).status_code == 422
    cmd = http.get("/walkpad/control/next?wait=0", headers=h).json()
    assert cmd["action"] == "start"
    assert http.get("/walkpad/control/next?wait=0", headers=h).status_code == 204
    http.post("/walkpad/control/result", json={"id": cmd["id"], "ok": True, "message": "ok"}, headers=h)
    assert http.get("/walkpad/control").json()["last_result"]["id"] == cmd["id"]


class CountdownPad(SimPad):
    """Like the sWalk: ignores speed while stopped, starts at 1.0 km/h after a countdown."""

    def __init__(self, countdown=0.3):
        super().__init__()
        self.countdown, self.belt = countdown, 0.0

    async def write(self, payload: bytes) -> None:
        await super().write(payload)
        if payload[0] == fc.OP_START:
            asyncio.get_running_loop().call_later(self.countdown, lambda: setattr(self, "belt", 1.0))
        if payload[0] == fc.OP_SET_SPEED and self.belt > 0:
            self.belt = self.speed
        if payload[0] == fc.OP_STOP_PAUSE:
            self.belt = 0.0


def run_live(pad, *steps):
    """Commands with real time; ("sleep", s) entries wait between them."""
    async def go():
        control = fc.PadControl(pad.write, speed=lambda: pad.belt)
        pad.control = control
        for step in steps:
            if step[0] == "sleep":
                await asyncio.sleep(step[1])
            else:
                await control.run({**step[1], "issued_at": fc.time.time()})
        if control.follow_up:
            await asyncio.wait_for(control.follow_up, 3)
    asyncio.run(go())


def test_start_with_wished_speed_sets_it_once_the_belt_moves():
    pad = CountdownPad()
    run_live(pad, ("cmd", {"action": "start", "kmh": 2.0}))
    assert pad.writes[-1] == struct.pack("<BH", 2, 200) and pad.belt == 2.0


def test_stop_during_countdown_cancels_the_wished_speed():
    pad = CountdownPad(countdown=0.3)
    run_live(pad, ("cmd", {"action": "start", "kmh": 4.0}), ("sleep", 0.1), ("cmd", {"action": "stop"}), ("sleep", 0.6))
    assert pad.writes[-1] == b"\x08\x01"
    assert struct.pack("<BH", 2, 400) not in pad.writes  # never sped up after the stop


def test_server_start_speed_is_clamped(monkeypatch):
    online(0, "stopped")
    monkeypatch.setattr(settings, "walkpad_max_speed_kmh", 4.0)
    assert wc.enqueue("start", kmh=5.5, confirm=True)["kmh"] == 4.0
    assert wc.enqueue("start", confirm=True)["kmh"] is None
    assert wc.enqueue("stop", kmh=3)["kmh"] is None
