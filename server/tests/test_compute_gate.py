import threading
import time
import concurrent.futures as cf

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.compute_gate import ComputeGate, gated


def test_gated_paths():
    assert gated("/metrics/week")
    assert gated("/hero") and gated("/hero/equip")
    assert gated("/bike-plan") and gated("/walkpad") and gated("/walkpad/daily?days=37".split("?")[0])
    for path in ("/hero/live/state", "/hero/world/tiles", "/hero/world/tile/1_2_3", "/hero/saga",
                 "/metrics/cycling/map/watopia.jpg", "/walkpad/control", "/walkpad/control/next",
                 "/ingest/status", "/coach/ask", "/health", "/heroes"):
        assert not gated(path), path


def _app():
    app = FastAPI()
    app.add_middleware(ComputeGate)
    state = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def work():
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.15)
        with lock:
            state["now"] -= 1
        return {}

    app.get("/metrics/slow")(work)
    app.get("/ingest/status")(lambda: {})
    return app, state


def test_gate_limits_concurrency_and_lets_exempt_paths_pass():
    app, state = _app()
    with TestClient(app) as c, cf.ThreadPoolExecutor(8) as ex:
        slow = [ex.submit(c.get, "/metrics/slow") for _ in range(6)]
        time.sleep(0.05)
        t = time.time()
        assert c.get("/ingest/status").status_code == 200
        assert time.time() - t < 0.1  # wartet nicht hinter den gated Requests
        assert all(f.result().status_code == 200 for f in slow)
    assert state["peak"] == 2
