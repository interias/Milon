import base64
from datetime import datetime
import json
import logging
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app import garmin_routes
from app.ingest import garmin
from app.models import ExerciseSession


TOKENS = {key: f"synthetic-{key}" for key in garmin.TOKEN_KEYS}
ROTATED = {key: f"renewed-{key}" for key in garmin.TOKEN_KEYS}
CANARY = "synthetic-private-value-must-never-escape"
GPX = b'''<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1">
<trk><trkseg><trkpt lat="1.0" lon="2.0"><ele>10</ele><time>2025-01-01T12:00:00Z</time></trkpt>
<trkpt lat="1.001" lon="2.001"><ele>11</ele><time>2025-01-01T12:01:00Z</time></trkpt>
</trkseg></trk></gpx>'''


def activity(activity_id=1, **changes):
    return {"activityId": activity_id, "activityName": "Synthetic run",
            "startTimeGMT": "2025-01-01 12:00:00", "startTimeLocal": "1900-01-01 00:00:00",
            "duration": 60, "elapsedDuration": 90, "distance": 1000,
            "elevationGain": 1, "hasPolyline": True, **changes}


def write_tokens(path, tokens=TOKENS):
    encoded = base64.b64encode(json.dumps(tokens).encode()).decode()
    path.write_text(f"# Keep this comment\nGARMIN_SESSION_B64={encoded}\nOTHER_SETTING=preserved\n", encoding="utf-8")


def read_tokens(path):
    value = next(line.partition("=")[2] for line in path.read_text().splitlines()
                 if line.startswith("GARMIN_SESSION_B64="))
    return json.loads(base64.b64decode(value))


class FakeGarmin:
    ActivityDownloadFormat = SimpleNamespace(GPX="gpx")

    def __init__(self, activities):
        self.activities = activities
        self.client = SimpleNamespace(**{key: None for key in garmin.TOKEN_KEYS})
        self.pages = []
        self.downloads = []
        self.gpx = {}
        self.login_error = False
        self.list_error = False
        self.loaded = None

    def login(self, *, tokenstore):
        self.loaded = json.loads(tokenstore)
        for key, value in ROTATED.items():
            setattr(self.client, key, value)
        logging.getLogger("garminconnect.client").warning(CANARY)
        if self.login_error:
            raise RuntimeError(CANARY)

    def get_activities(self, start, limit, *, activitytype):
        self.pages.append((start, limit, activitytype))
        if self.list_error:
            raise RuntimeError(CANARY)
        return self.activities[start:start + limit]

    def download_activity(self, activity_id, *, dl_fmt):
        assert dl_fmt == "gpx"
        self.downloads.append(activity_id)
        value = self.gpx.get(activity_id, GPX)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    write_tokens(path)
    engine = create_engine(f"sqlite:///{tmp_path / 'routes.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(garmin, "SESSION_FILE", path)
    monkeypatch.setattr(garmin, "settings", SimpleNamespace(timezone="Europe/Berlin"))
    monkeypatch.setattr(garmin_routes, "engine", engine)
    monkeypatch.setattr(garmin, "_pull_metrics", lambda api, activities, full:
                        {"activities": {"errors": 0}, "daily": {"errors": 0}})
    api = FakeGarmin([activity()])
    monkeypatch.setattr(garmin, "_new_client", lambda: api)
    yield SimpleNamespace(path=path, engine=engine, api=api)
    engine.dispose()


def route_ids(engine):
    with Session(engine) as session:
        return set(session.exec(select(garmin_routes.GarminRoute.activity_id)).all())


def test_configured_never_opens_credentials_or_connects(isolated, monkeypatch):
    monkeypatch.setattr(type(isolated.path), "read_text", lambda *a, **k: pytest.fail("Credentials were read"))
    monkeypatch.setattr(garmin, "_new_client", lambda: pytest.fail("Network client was created"))
    assert garmin.configured()
    isolated.path.unlink()
    assert not garmin.configured()
    assert garmin.import_garmin()["mode"] == "not_configured"


def test_route_stage_is_independent_and_persists_rotated_tokens(isolated, caplog):
    result = garmin.import_garmin()
    assert {key: value for key, value in result.items() if key not in ("activities", "daily")} == {"mode": "initial", "imported": 1, "skipped": 0, "no_route": 0,
                      "checked": 1, "errors": 0, "history_limited": False}
    assert isolated.api.loaded == TOKENS
    assert isolated.api.pages == [(0, 50, "running")]
    assert read_tokens(isolated.path) == ROTATED
    assert "# Keep this comment" in isolated.path.read_text()
    assert "OTHER_SETTING=preserved" in isolated.path.read_text()
    assert CANARY not in caplog.text
    with Session(isolated.engine) as session:
        route = session.exec(select(garmin_routes.GarminRoute)).one()
        assert route.started_at == datetime(2025, 1, 1, 13)
        assert route.distance_km == 1
        assert route.duration_seconds == 60
        assert route.elapsed_duration_seconds == 90
        assert session.exec(select(ExerciseSession)).all() == []


def test_bounded_history_paginates_and_skips_non_route_activities(isolated, monkeypatch):
    monkeypatch.setattr(garmin, "PAGE_SIZE", 2)
    monkeypatch.setattr(garmin, "HISTORY_LIMIT", 3)
    isolated.api.activities = [activity(1), activity(2, hasPolyline=False), activity(3), activity(4)]
    result = garmin.import_garmin()
    assert isolated.api.pages == [(0, 2, "running"), (2, 1, "running")]
    assert isolated.api.downloads == ["1", "3"]
    assert result["checked"] == 3 and result["imported"] == 2 and result["no_route"] == 1
    assert result["history_limited"]
    assert route_ids(isolated.engine) == {"1", "3"}


def test_incremental_skips_existing_routes_but_full_refreshes_them(isolated):
    garmin.import_garmin()
    second = garmin.import_garmin()
    assert second["mode"] == "incremental" and second["skipped"] == 1
    assert isolated.api.pages[-1] == (0, 30, "running")
    assert isolated.api.downloads == ["1"]
    third = garmin.import_garmin(full=True)
    assert third["mode"] == "full" and third["imported"] == 1
    assert isolated.api.downloads == ["1", "1"]
    assert route_ids(isolated.engine) == {"1"}


def test_incremental_window_is_bounded_and_full_can_backfill(isolated, monkeypatch):
    garmin.import_garmin()
    monkeypatch.setattr(garmin, "RECENT_LIMIT", 2)
    isolated.api.activities = [activity(4), activity(3), activity(2), activity(1)]
    result = garmin.import_garmin()
    assert result["checked"] == 2
    assert route_ids(isolated.engine) == {"1", "3", "4"}
    garmin.import_garmin(full=True)
    assert route_ids(isolated.engine) == {"1", "2", "3", "4"}


@pytest.mark.parametrize("failure", ["login_error", "list_error"])
def test_rotated_tokens_survive_remote_failure_without_secret_disclosure(isolated, failure, caplog):
    setattr(isolated.api, failure, True)
    with pytest.raises(garmin.GarminSyncError) as error:
        garmin.import_garmin()
    assert CANARY not in str(error.value) and CANARY not in caplog.text
    assert error.value.__suppress_context__
    assert read_tokens(isolated.path) == ROTATED
    assert not garmin._import_lock.locked()


@pytest.mark.parametrize("raw", ["GARMIN_SESSION_B64=%%%", "GARMIN_SESSION_B64=e30=", "OTHER_SETTING=test"])
def test_invalid_credentials_never_construct_client_or_replace_file(isolated, monkeypatch, raw):
    isolated.path.write_text(raw)
    monkeypatch.setattr(garmin, "_new_client", lambda: pytest.fail("Client created for invalid tokens"))
    with pytest.raises(garmin.GarminSyncError, match="ungültig"):
        garmin.import_garmin()
    assert isolated.path.read_text() == raw
    assert not garmin._import_lock.locked()


def test_bad_gpx_preserves_old_route_and_reports_partial_failure(isolated):
    garmin.import_garmin()
    with Session(isolated.engine) as session:
        old = session.exec(select(garmin_routes.GarminRoute)).one().model_dump()
    isolated.api.activities = [activity(1, activityName="Must not replace"), activity(2)]
    isolated.api.gpx["1"] = b"invalid xml"
    with pytest.raises(garmin.GarminSyncError) as error:
        garmin.import_garmin(full=True)
    assert error.value.result["imported"] == 1 and error.value.result["errors"] == 1
    assert route_ids(isolated.engine) == {"1", "2"}
    with Session(isolated.engine) as session:
        unchanged = session.exec(select(garmin_routes.GarminRoute).where(
            garmin_routes.GarminRoute.activity_id == "1")).one().model_dump()
    assert unchanged == old


def test_download_failure_is_aggregated_without_remote_text(isolated):
    isolated.api.gpx["1"] = RuntimeError(CANARY)
    with pytest.raises(garmin.GarminSyncError) as error:
        garmin.import_garmin()
    assert error.value.result["errors"] == 1
    assert error.value.result["imported"] == 0
    assert CANARY not in str(error.value)
    assert read_tokens(isolated.path) == ROTATED


def test_empty_downloads_and_duplicate_records_are_not_saved(isolated):
    isolated.api.activities = [activity(1), activity(1), activity(2, hasPolyline=False)]
    isolated.api.gpx["1"] = b""
    result = garmin.import_garmin()
    assert result["no_route"] == 2 and result["skipped"] == 1 and result["imported"] == 0
    assert route_ids(isolated.engine) == set()


def test_failed_atomic_replace_keeps_previous_credentials_and_releases_lock(isolated, monkeypatch):
    before = isolated.path.read_bytes()

    def fail_replace(*args):
        raise OSError(CANARY)

    monkeypatch.setattr(garmin.os, "replace", fail_replace)
    with pytest.raises(garmin.GarminSyncError, match="sicher gespeichert") as error:
        garmin.import_garmin()
    assert CANARY not in str(error.value)
    assert isolated.path.read_bytes() == before
    assert list(isolated.path.parent.glob(".session-*")) == []
    assert not garmin._import_lock.locked()


def test_concurrent_import_is_rejected_without_client_creation(isolated, monkeypatch):
    monkeypatch.setattr(garmin, "_new_client", lambda: pytest.fail("Concurrent client created"))
    garmin._import_lock.acquire()
    try:
        with pytest.raises(garmin.GarminSyncError, match="bereits"):
            garmin.import_garmin()
    finally:
        garmin._import_lock.release()


def test_metadata_uses_utc_not_remote_local_clock_and_keeps_active_duration(isolated):
    summary = garmin._summary(activity(startTimeGMT="2025-07-01 12:00:00", elapsedDuration=None))
    assert summary["started_at"] == datetime(2025, 7, 1, 14)
    assert summary["started_at_utc"] == "2025-07-01T12:00:00+00:00"
    assert summary["elapsed_duration_seconds"] == summary["duration_seconds"] == 60


@pytest.mark.parametrize("changes", [{"distance": float("nan")}, {"activityId": "bad"},
                                      {"duration": -1}, {"startTimeGMT": "bad"}])
def test_invalid_activity_metadata_is_counted_without_saving(isolated, changes):
    isolated.api.activities = [activity(**changes)]
    with pytest.raises(garmin.GarminSyncError) as error:
        garmin.import_garmin()
    assert error.value.result["errors"] == 1
    assert route_ids(isolated.engine) == set()


def test_existing_routes_still_supply_activity_summaries_to_metrics(isolated, monkeypatch):
    garmin.import_garmin()
    received = []
    def pull(api, activities, full):
        received.extend(activities)
        return {"activities": {"errors": 0, "imported": 1}, "daily": {"errors": 0}}
    monkeypatch.setattr(garmin, "_pull_metrics", pull)
    result = garmin.import_garmin()
    assert result["skipped"] == 1
    assert len(received) == 1 and received[0]["activityId"] == 1
    assert result["activities"]["imported"] == 1


def test_route_failure_does_not_prevent_daily_and_activity_sync(isolated, monkeypatch):
    isolated.api.gpx["1"] = RuntimeError(CANARY)
    received = []
    monkeypatch.setattr(garmin, "_pull_metrics", lambda api, activities, full:
                        received.append(activities) or {"activities": {"errors": 0}, "daily": {"errors": 0}})
    with pytest.raises(garmin.GarminSyncError) as failure:
        garmin.import_garmin()
    assert received and len(received[0]) == 1
    assert CANARY not in str(failure.value)
    assert read_tokens(isolated.path) == ROTATED


def test_partial_metric_failure_is_reported_after_routes_are_saved(isolated, monkeypatch):
    monkeypatch.setattr(garmin, "_pull_metrics", lambda api, activities, full:
                        {"activities": {"errors": 2}, "daily": {"errors": 0}})
    with pytest.raises(garmin.GarminSyncError) as failure:
        garmin.import_garmin()
    assert route_ids(isolated.engine) == {"1"}
    assert failure.value.result["errors"] == 2
    assert read_tokens(isolated.path) == ROTATED
