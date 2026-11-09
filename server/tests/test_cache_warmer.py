import asyncio
import threading
from urllib.parse import urlsplit

from fastapi import FastAPI
from starlette.routing import Match

from app import cache_warmer, data_cache
from app.main import app as milon_app


def test_every_warm_url_hits_a_real_endpoint():
    for url in cache_warmer.URLS:
        scope = {"type": "http", "path": urlsplit(url).path, "method": "GET", "root_path": ""}
        assert any(r.matches(scope)[0] == Match.FULL for r in milon_app.router.routes), url


def test_warms_at_start_and_again_only_after_a_data_change(monkeypatch):
    hits: list[str] = []
    app = FastAPI()

    @app.get("/a")
    def a():
        hits.append("a")
        return {}

    state = {"version": 1}
    monkeypatch.setattr(cache_warmer, "URLS", ["/a"])
    monkeypatch.setattr(cache_warmer, "CHECK_S", 0.02)
    monkeypatch.setattr(cache_warmer, "REFRESH", 3600)
    monkeypatch.setattr(data_cache, "version", lambda: state["version"])
    stop = threading.Event()
    th = threading.Thread(target=lambda: asyncio.run(cache_warmer._loop(app, stop)))
    th.start()
    try:
        _wait(lambda: len(hits) == 1)
        threading.Event().wait(0.15)
        assert len(hits) == 1  # nichts geändert → kein neues Vorrechnen
        state["version"] = 2
        _wait(lambda: len(hits) == 2)
    finally:
        stop.set()
        th.join(2)


def test_refresh_expires_old_entries_and_rewarms(monkeypatch):
    hits: list[str] = []
    expired: list[float] = []
    app = FastAPI()
    app.get("/a")(lambda: hits.append("a") or {})
    monkeypatch.setattr(cache_warmer, "URLS", ["/a"])
    monkeypatch.setattr(cache_warmer, "CHECK_S", 0.02)
    monkeypatch.setattr(cache_warmer, "REFRESH", 0.05)
    monkeypatch.setattr(data_cache, "version", lambda: 1)
    monkeypatch.setattr(data_cache, "expire", expired.append)
    stop = threading.Event()
    th = threading.Thread(target=lambda: asyncio.run(cache_warmer._loop(app, stop)))
    th.start()
    try:
        _wait(lambda: len(hits) >= 3)
        assert expired and expired[0] == 0.05
    finally:
        stop.set()
        th.join(2)


def test_disabled_in_tests():
    assert data_cache.ENABLED is False
    cache_warmer.start(milon_app)
    assert cache_warmer._stop is None


def test_expire_drops_only_old_entries(monkeypatch):
    monkeypatch.setattr(data_cache, "_store", {("old",): (0.0, 1), ("new",): (10**12, 2)})
    data_cache.expire(60)
    assert list(data_cache._store) == [("new",)]


def _wait(cond, timeout=3.0):
    ev = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        ev.wait(0.01)
    raise AssertionError("Bedingung nicht erreicht")
