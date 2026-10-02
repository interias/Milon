from datetime import datetime
from unittest import TestCase, main
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine
from sqlalchemy.pool import StaticPool

from app.api import ingest
from app.models import SyncState
from app.sync import scheduler


class SyncTests(TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        SyncState.__table__.create(self.engine)
        self.engine_patch = patch.object(scheduler, "engine", self.engine)
        self.engine_patch.start()
        self.addCleanup(self.engine_patch.stop)
        self.addCleanup(self.engine.dispose)

    def test_sync_status_accepts_existing_naive_timestamps_and_preserves_cursor(self):
        with Session(self.engine) as session:
            session.add(SyncState(source="hevy", last_sync=datetime(2026, 10, 1), cursor="previous"))
            session.commit()
        scheduler.record_sync("hevy", "ok", "Imported")
        scheduler.record_sync("hevy", "error", "Provider unavailable")
        with Session(self.engine) as session:
            row = session.get(SyncState, "hevy")
            self.assertEqual(row.status, "error")
            self.assertEqual(row.detail, "Provider unavailable")
            self.assertEqual(row.cursor, "previous")
            self.assertGreater(row.last_sync, datetime(2026, 10, 1))

    def test_refresh_records_each_source_and_continues_after_provider_error(self):
        app = FastAPI()
        app.include_router(ingest.router)
        with (
            patch.object(ingest.hevy, "import_hevy", return_value={"events": 0}),
            patch.object(ingest.fddb, "import_fddb", side_effect=RuntimeError("Provider unavailable")),
            patch.object(ingest.settings, "hc_drive_file_id", "test-file"),
            patch.object(ingest.drive, "pull", return_value={"new_body": 1}),
            patch.object(ingest, "HC_DB") as hc_db,
            TestClient(app) as client,
        ):
            hc_db.exists.return_value = False
            response = client.post("/ingest/refresh")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["hevy"], {"events": 0})
            self.assertIn("error", response.json()["fddb"])
            self.assertEqual(response.json()["health_connect"], {"new_body": 1})
            states = {row["source"]: row["status"] for row in client.get("/ingest/status").json()["state"]}
            self.assertEqual(states, {"hevy": "ok", "fddb": "error", "health_connect": "ok"})


if __name__ == "__main__":
    main()
