import threading
import time

import pytest
from sqlalchemy import text
from sqlmodel import create_engine

from app import data_cache, db


@pytest.fixture
def cache_on(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}")
    with engine.begin() as con:
        con.execute(text("CREATE TABLE t (x INTEGER)"))
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(data_cache, "ENABLED", True)
    data_cache.clear()
    yield engine
    data_cache.clear()


def test_hit_until_data_changes_and_returns_copies(cache_on):
    calls = []

    @data_cache.cached
    def compute(n: int = 1, today=None):
        calls.append(n)
        return {"rows": [n]}

    a = compute(1)
    a["rows"].append(99)  # Aufrufer verändert seine Kopie
    assert compute(1) == {"rows": [1]}
    assert compute(n=1, today=None) == {"rows": [1]}  # gleiche Bindung = gleicher Eintrag
    assert calls == [1]
    compute(2)
    assert calls == [1, 2]

    time.sleep(0.01)
    with cache_on.begin() as con:
        con.execute(text("INSERT INTO t VALUES (1)"))
    compute(1)
    assert calls == [1, 2, 1]


def test_ttl_expires(cache_on, monkeypatch):
    calls = []

    @data_cache.cached
    def compute():
        calls.append(1)
        return 1

    compute()
    monkeypatch.setattr(data_cache, "TTL", 0.0)
    compute()
    assert len(calls) == 2


def test_parallel_misses_compute_once(cache_on):
    calls = []

    @data_cache.cached
    def slow():
        calls.append(1)
        time.sleep(0.2)
        return 7

    threads = [threading.Thread(target=slow) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1


def test_disabled_always_computes(cache_on, monkeypatch):
    monkeypatch.setattr(data_cache, "ENABLED", False)
    calls = []

    @data_cache.cached
    def compute():
        calls.append(1)

    compute(); compute()
    assert len(calls) == 2


def test_new_health_connect_export_invalidates(cache_on, monkeypatch, tmp_path):
    monkeypatch.setattr(data_cache, "INCOMING_DIR", tmp_path)
    calls = []

    @data_cache.cached
    def compute():
        calls.append(1)

    compute(); compute()
    assert len(calls) == 1
    (tmp_path / "health_connect_export.db").write_bytes(b"neu")
    compute()
    assert len(calls) == 2
