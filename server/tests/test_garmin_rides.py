"""Garmin cycling tracks: synced apart from runs, visible in cycling metrics, deduplicated against HC."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app import garmin_activity, garmin_daily, garmin_indoor, garmin_load, garmin_routes, garmin_weather, hero_world
from app.garmin_activity import GarminActivity
from app.ingest import garmin
from app.metrics import health, route_atlas
from app.models import ExerciseSession, RunBestEffort, RunMinute

from test_garmin_sync import FakeGarmin, activity, write_tokens

RIDE_GPX = b'''<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1">
<trk><trkseg><trkpt lat="1.0" lon="2.0"><time>2025-01-02T12:00:00Z</time></trkpt>
<trkpt lat="1.01" lon="2.01"><time>2025-01-02T12:30:00Z</time></trkpt>
</trkseg></trk></gpx>'''


def ride(activity_id, type_key="road_biking", **changes):
    return activity(activity_id, activityName="Synthetic ride", startTimeGMT="2025-01-02 12:00:00",
                    duration=3000, elapsedDuration=3600, distance=20000,
                    activityType={"typeKey": type_key}, **changes)


class TypedGarmin(FakeGarmin):
    """Garmin filters by activitytype server-side; the fake does the same."""

    def __init__(self, runs, rides):
        super().__init__(runs)
        self.rides = rides

    def get_activities(self, start, limit, *, activitytype):
        self.pages.append((start, limit, activitytype))
        source = self.rides if activitytype == "cycling" else self.activities
        return source[start:start + limit]


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    write_tokens(path)
    engine = create_engine(f"sqlite:///{tmp_path / 'rides.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(garmin, "SESSION_FILE", path)
    monkeypatch.setattr(garmin, "settings", SimpleNamespace(timezone="Europe/Berlin"))
    monkeypatch.setattr(garmin_routes.settings, "timezone", "Europe/Berlin")
    for module in (garmin_routes, garmin_indoor, health, hero_world, route_atlas):
        monkeypatch.setattr(module, "engine", engine)
    # Run-only consumers record what the sync hands them; nothing here may contact Garmin.
    handed = SimpleNamespace(activities=None, weather=None)

    def activities(api, items, full=False):
        handed.activities = [str(item["activityId"]) for item in items]
        return {"errors": 0}

    def weather(api, items, full=False):
        handed.weather = [str(item["activityId"]) for item in items]
        return {"errors": 0}

    monkeypatch.setattr(garmin_activity, "sync_activities", activities)
    monkeypatch.setattr(garmin_weather, "sync_weather", weather)
    monkeypatch.setattr(garmin_daily, "sync_daily", lambda api, full=False, force=False: {"errors": 0})
    monkeypatch.setattr(garmin_load, "sync_tolerance", lambda api, full=False, force=False: {"errors": 0})
    api = TypedGarmin([activity(1)], [ride(2), ride(3, "indoor_cycling"), ride(4, "virtual_ride")])
    api.gpx["2"] = RIDE_GPX
    monkeypatch.setattr(garmin, "_new_client", lambda: api)
    yield SimpleNamespace(engine=engine, api=api, handed=handed)
    engine.dispose()


def ids(engine, model):
    with Session(engine) as session:
        return set(session.exec(select(model.activity_id)).all())


def test_sync_fetches_cycling_with_gps_and_marks_it_as_ride(isolated):
    result = garmin.import_garmin()
    assert (0, 50, "cycling") in isolated.api.pages and (0, 50, "running") in isolated.api.pages
    # Indoor/virtual rides are handed to garmin_indoor (#69) instead of being dropped as no_route.
    assert result["rides"] == {"mode": "initial", "imported": 1, "skipped": 0, "no_route": 0, "indoor": 2,
                               "checked": 3, "errors": 0}
    assert result["indoor_rides"]["checked"] == 2
    assert isolated.api.downloads == ["1", "2"]  # indoor/virtual rides have no real track
    assert ids(isolated.engine, garmin_routes.GarminRide) == {"2"}
    assert ids(isolated.engine, garmin_routes.GarminRoute) == {"1"}
    with Session(isolated.engine) as session:
        stored = session.get(garmin_routes.GarminRide, "2")
        assert stored.activity_type == "road_biking"
        assert stored.started_at == datetime(2025, 1, 2, 13)
        assert stored.distance_km == 20 and stored.elapsed_duration_seconds == 3600
    # Rides never reach run canonicalization or run weather.
    assert isolated.handed.activities == ["1"] and isolated.handed.weather == ["1"]


def test_rides_are_incremental_and_full_backfills(isolated):
    garmin.import_garmin()
    second = garmin.import_garmin()
    assert second["rides"]["mode"] == "incremental" and second["rides"]["skipped"] == 1
    assert (0, 30, "cycling") in isolated.api.pages
    assert isolated.api.downloads == ["1", "2"]
    third = garmin.import_garmin(full=True)
    assert third["rides"]["mode"] == "full" and third["rides"]["imported"] == 1
    assert isolated.api.downloads.count("2") == 2
    assert ids(isolated.engine, garmin_routes.GarminRide) == {"2"}


def test_ride_failure_is_reported_without_failing_the_running_sync(isolated):
    isolated.api.gpx["2"] = RuntimeError("synthetic remote failure")
    result = garmin.import_garmin()
    assert result["rides"]["errors"] == 1 and result["errors"] == 0
    assert "synthetic remote failure" not in str(result)
    assert ids(isolated.engine, garmin_routes.GarminRoute) == {"1"}
    assert ids(isolated.engine, garmin_routes.GarminRide) == set()


def test_run_consumers_never_see_ride_tracks(isolated):
    """Regression: every GarminRoute reader (routes API, atlas, world map, run records) stays run-only."""
    garmin.import_garmin()
    listed = garmin_routes.list_routes()
    assert listed["total"] == 1 and [item["activity_id"] for item in listed["items"]] == ["1"]
    assert garmin_routes.route_detail("2") is None
    assert [day.isoformat() for day, _ in hero_world._routes()] == ["2025-01-01"]
    atlas = route_atlas.atlas()
    assert atlas["total_runs"] == 1
    assert {m["activity_id"] for group in atlas["groups"] for m in group["members"]} == {"1"}
    with Session(isolated.engine) as session:
        assert session.exec(select(ExerciseSession)).all() == []
        assert session.exec(select(RunMinute)).all() == []
        assert session.exec(select(RunBestEffort)).all() == []
        assert session.exec(select(GarminActivity)).all() == []


def test_ride_never_duplicates_an_existing_run_id(isolated):
    isolated.api.rides = [ride(1)]
    result = garmin.import_garmin()
    assert result["rides"]["skipped"] == 1
    assert ids(isolated.engine, garmin_routes.GarminRide) == set()


def add_hc_ride(engine, external_id, start, minutes, km):
    with Session(engine) as session:
        session.add(ExerciseSession(external_id=external_id, exercise_type=health.BIKE, started_at=start,
                                    ended_at=start + timedelta(minutes=minutes), distance_km=km))
        session.commit()


def test_cycling_metrics_include_garmin_rides_and_garmin_wins_overlap(isolated):
    garmin.import_garmin()  # Garmin ride: 2025-01-02 13:00-14:00 local, 20 km
    add_hc_ride(isolated.engine, "hc-mirror", datetime(2025, 1, 2, 13, 2), 55, 19.4)  # same trip via HC
    add_hc_ride(isolated.engine, "hc-commute", datetime(2025, 1, 3, 8), 10, 2.5)     # separate trip
    recent = health.cycling_recent(limit=0)
    assert [(r["date"], r["km"]) for r in recent] == [("2025-01-03T08:00:00", 2.5), ("2025-01-02T13:00:00", 20.0)]
    assert recent[1]["dur_min"] == 60 and recent[1]["speed"] == 20.0
    summary = health.cycling_summary(datetime(2025, 1, 10, 12, tzinfo=timezone.utc))
    assert summary["rides"] == 2 and summary["total_km"] == 22.5
    assert sum(week["rides"] for week in health.cycling_weekly()) == 2


def test_cycling_metrics_without_ride_table_fall_back_to_hc(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'hc.db'}")
    SQLModel.metadata.create_all(engine, tables=[ExerciseSession.__table__])
    monkeypatch.setattr(health, "engine", engine)
    add_hc_ride(engine, "hc-only", datetime(2025, 1, 3, 8), 10, 2.5)
    assert [r["km"] for r in health.cycling_recent()] == [2.5]
    engine.dispose()
