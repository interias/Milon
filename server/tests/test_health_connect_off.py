"""HEALTH_CONNECT_ENABLED=false: no scan, no pull, manual import refused, the status page shows the scale instead."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from app import scale
from app.config import settings
from app.metrics import source_status as status_module
from app.sync import scheduler

NOW = datetime(2026, 11, 23, 10, tzinfo=timezone.utc)


@pytest.fixture
def off(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for module in (status_module, scheduler, scale):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(status_module, "garmin_configured", lambda: True)
    monkeypatch.setattr(status_module, "INCOMING_DIR", tmp_path)
    monkeypatch.setattr(settings, "health_connect_enabled", False)
    monkeypatch.setattr(settings, "hc_drive_file_id", "synthetic-drive-id")
    yield engine
    engine.dispose()


def test_scheduler_jobs_do_nothing(off, monkeypatch, tmp_path):
    hc_db = tmp_path / "health_connect_export.db"
    hc_db.write_bytes(b"not a db")
    monkeypatch.setattr(scheduler, "HC_DB", hc_db)
    called = []
    monkeypatch.setattr(scheduler.health_connect, "import_health_connect", lambda *a, **k: called.append("import"))
    scheduler.sync_hc_if_new()
    scheduler.sync_hc_drive()
    assert called == []


def test_manual_import_is_refused(off):
    from app.main import app
    http = TestClient(app)
    assert http.post("/ingest/health-connect").status_code == 409
    assert http.post("/ingest/health-connect-pull").status_code == 409


def test_status_page_lists_the_scale_instead_of_health_connect(off):
    keys = [row["key"] for row in status_module.source_status(now=NOW)["sources"]]
    assert "health_connect" not in keys and "arboleaf" not in keys
    scale_row = next(row for row in status_module.source_status(now=NOW)["sources"] if row["key"] == "scale")
    assert (scale_row["status"], scale_row["latest_data_date"]) == ("never", None)
    scale.save(measured_at=datetime(2026, 11, 23, 7, 10), weight_kg=73.4, r1=None, r2=None, source="stored",
               protocol_type=255, raw_hex=None, now=datetime(2026, 11, 23, 8))
    scale_row = next(row for row in status_module.source_status(now=NOW)["sources"] if row["key"] == "scale")
    assert (scale_row["status"], scale_row["latest_data_date"]) == ("ok", "2026-11-23")
