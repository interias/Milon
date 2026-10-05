"""Synthetic provider payloads; no credentials, production DB or network requests."""
from datetime import date, datetime, timedelta, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app import garmin_daily as daily
from app.api.garmin_daily import router
from app.models import BodyMeasurement, RestingHrDaily, SleepSession, StepsDaily, Vo2Max


NOW = datetime(2026, 10, 3, 10, tzinfo=timezone.utc)
DAY = date(2026, 10, 3)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(daily, "engine", engine)
    monkeypatch.setattr(daily.settings, "watch_source_switch_date", date(2026, 10, 1))
    monkeypatch.setattr(daily.settings, "watch_source_package", daily.PACKAGE)
    monkeypatch.setattr(daily.settings, "steps_source_package", "com.sec.android.app.shealth")
    monkeypatch.setattr(daily.settings, "timezone", "Europe/Berlin")
    yield engine
    engine.dispose()


def sleep_payload(day=DAY, *, complete=True):
    end = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=6)
    start = end - timedelta(hours=8)
    return {"dailySleepDTO": {"calendarDate": day.isoformat(),
            "sleepStartTimestampGMT": start.timestamp() * 1000, "sleepEndTimestampGMT": end.timestamp() * 1000,
            "sleepTimeSeconds": 8 * 3600, "sleepScores": {"overall": {"value": 80}}},
            "sleepLevels": [{"startGMT": start.isoformat(), "endGMT": (end if complete else end - timedelta(hours=1)).isoformat(), "activityLevel": 1}]}


class FakeGarmin:
    def __init__(self):
        self.calls = []
        self.fail = set()
        self.empty = set()
        self.steps = 6000

    def _get(self, category, day, payload):
        self.calls.append((category, day))
        if category in self.fail:
            raise RuntimeError("private response and token must never escape")
        return {} if category in self.empty else payload

    def get_user_summary(self, day):
        return self._get("summary", day, {"calendarDate": day, "totalSteps": self.steps,
                         "includesWellnessData": True, "restingHeartRate": 50,
                         "bodyBatteryMostRecentValue": 65, "averageStressLevel": 20})

    def get_sleep_data(self, day):
        return self._get("sleep", day, sleep_payload(date.fromisoformat(day)))

    def get_hrv_data(self, day):
        return self._get("hrv", day, {"hrvSummary": {"calendarDate": day, "lastNightAvg": 55,
                         "status": "NONE", "baseline": None}, "sleepEndTimestampGMT": day + "T06:00:00"})

    def get_max_metrics(self, day):
        return self._get("vo2", day, [{"generic": {"calendarDate": day, "vo2MaxPreciseValue": 45.6}}] if day.endswith("01") else [])

    def get_training_readiness(self, day):
        return self._get("readiness", day, [{"calendarDate": day, "timestamp": day + "T08:00:00",
                         "score": 70, "recoveryTime": 180, "inputContext": "UPDATE_REALTIME_VARIABLES"}])


def store(day, normalized, session):
    session.add(daily.GarminDaily(day=day, normalized_json=json.dumps(normalized)))
    session.commit()


def test_source_projection_is_idempotent_and_keeps_resting_hr_separate(db):
    with Session(db) as session:
        session.add(StepsDaily(day=DAY, steps=4000, source="health_connect"))
        session.add(RestingHrDaily(day=DAY, bpm=45, source="health_connect"))
        session.commit()
    api = FakeGarmin()
    first = daily.sync_daily(api, now=NOW)
    assert (first["days"], first["requests"], first["errors"]) == (3, 15, 0)
    api.steps = 6200
    daily.sync_daily(api, now=NOW + timedelta(hours=1))
    with Session(db) as session:
        assert session.get(StepsDaily, DAY).steps == 6200
        assert session.get(StepsDaily, DAY).source == daily.SOURCE
        assert session.get(RestingHrDaily, DAY).bpm == 45
        assert len(session.exec(select(SleepSession)).all()) == 3
        assert len(session.exec(select(Vo2Max)).all()) == 1
        assert len(session.exec(select(daily.GarminDaily)).all()) == 3


def test_empty_provider_results_do_not_erase_last_successful_values(db):
    api = FakeGarmin()
    daily.sync_daily(api, now=NOW)
    api.empty = set(daily.METHODS)
    result = daily.sync_daily(api, now=NOW + timedelta(hours=1))
    assert result["errors"] == 0 and result["empty"] == 15
    data = daily.recovery(now=NOW + timedelta(hours=1))
    assert data["latest"]["hrv_ms"]["value"] == 55
    assert data["latest"]["hrv_ms"]["synced_at"] == NOW.isoformat()
    assert data["availability"]["hrv"]["status"] == "empty"
    with Session(db) as session:
        assert session.get(StepsDaily, DAY).steps == 6000


def test_partial_failure_preserves_data_and_exposes_only_sanitized_status(db):
    api = FakeGarmin()
    daily.sync_daily(api, now=NOW)
    api.fail = {"sleep", "hrv"}
    result = daily.sync_daily(api, now=NOW + timedelta(hours=1))
    assert result["errors"] == 6
    assert "private" not in json.dumps(result)
    data = daily.recovery(now=NOW + timedelta(hours=1))
    assert data["latest"]["hrv_ms"]["stale"] is True
    assert data["latest"]["sleep_hours"]["value"] == 8
    assert data["availability"]["sleep"]["status"] == "error"


def test_poll_is_hourly_and_recent_three_days_are_revisited(db):
    api = FakeGarmin()
    daily.sync_daily(api, now=NOW)
    api.calls.clear()
    assert daily.sync_daily(api, now=NOW + timedelta(minutes=59))["mode"] == "throttled"
    assert api.calls == []
    result = daily.sync_daily(api, now=NOW + timedelta(days=4))
    assert result["days"] == 4  # Three recent days plus the previously unseen fourth day.
    assert len({day for _, day in api.calls}) == 4


def test_initial_backfill_is_bounded_and_explicit_full_uses_cutoff(db, monkeypatch):
    monkeypatch.setattr(daily.settings, "watch_source_switch_date", DAY - timedelta(days=95))
    api = FakeGarmin()
    assert daily.sync_daily(api, now=NOW)["days"] == 90
    assert daily.sync_daily(api, full=True, now=NOW)["days"] == 96


def test_unsupported_methods_are_distinct_from_missing_measurements(db):
    result = daily.sync_daily(object(), now=NOW)
    assert result["unsupported"] == 15 and result["requests"] == 0
    data = daily.recovery(now=NOW)
    assert data["availability"]["hrv"]["status"] == "unsupported"
    assert data["series"] == [] and data["latest"]["hrv_ms"] is None


def test_today_is_provisional_missing_baseline_is_not_an_assessment(db):
    daily.sync_daily(FakeGarmin(), now=NOW)
    value = daily.recovery(now=NOW)
    assert value["series"][-1]["provisional"] is True
    assert value["series"][-2]["provisional"] is False
    assert value["latest"]["hrv_ms"]["baseline_ready"] is False
    assert value["latest"]["hrv_ms"]["status"] is None
    assert value["latest"]["readiness"]["measured_at"] == "2026-10-03T08:00:00+00:00"
    assert value["latest"]["body_battery"]["measured_at"] is None
    assert value["coverage"]["sleep_nights"] == 3


def test_utc_sleep_duration_survives_berlin_dst_fallback(db):
    day = date(2026, 10, 25)
    payload = sleep_payload(day)
    value = daily._sleep(payload, day)
    wall_start = datetime.fromisoformat(value["started_at"])
    wall_end = datetime.fromisoformat(value["ended_at"])
    assert (wall_end - wall_start).total_seconds() / 3600 == 7
    assert value["duration_window_minutes"] == 480
    assert value["asleep_minutes"] == 480


def test_sleep_waking_day_comes_from_gmt_not_local_pseudo_epoch(db):
    payload = sleep_payload()
    payload["dailySleepDTO"]["sleepStartTimestampLocal"] = 0
    payload["dailySleepDTO"]["sleepEndTimestampLocal"] = 0
    assert daily._sleep(payload, DAY)["asleep_minutes"] == 480
    assert daily._sleep(payload, DAY - timedelta(days=1)) == {}


@pytest.mark.parametrize("change", ["incomplete", "overlap", "unknown", "unknown_overlap", "inconsistent"])
def test_unknown_or_contradictory_stages_never_become_known_sleep(db, change):
    payload = sleep_payload(complete=change != "incomplete")
    if change == "overlap":
        payload["sleepLevels"].append(dict(payload["sleepLevels"][0]))
    elif change == "unknown":
        payload["sleepLevels"][0]["activityLevel"] = 99
    elif change == "unknown_overlap":
        payload["sleepLevels"].append({**payload["sleepLevels"][0], "activityLevel": 99})
    elif change == "inconsistent":
        payload["dailySleepDTO"]["sleepTimeSeconds"] = 120
    value = daily._sleep(payload, DAY)
    assert value["asleep_minutes"] is None


def test_explicit_stage_totals_establish_coverage_without_fabrication(db):
    payload = sleep_payload()
    payload.pop("sleepLevels")
    dto = payload["dailySleepDTO"]
    dto.update(deepSleepSeconds=7200, lightSleepSeconds=14400, remSleepSeconds=7200, awakeSleepSeconds=0)
    assert daily._sleep(payload, DAY)["asleep_minutes"] == 480
    dto.pop("remSleepSeconds")
    assert daily._sleep(payload, DAY)["asleep_minutes"] is None


def test_absent_sleep_is_not_a_zero_night(db):
    assert daily._sleep({"dailySleepDTO": {"sleepTimeSeconds": 0}}, DAY) == {}
    assert daily._sleep({}, DAY) == {}
    assert daily._summary({"calendarDate": DAY.isoformat(), "totalSteps": 0}, DAY)["steps"] is None
    assert daily._summary({"calendarDate": DAY.isoformat(), "totalSteps": 0, "includesWellnessData": True}, DAY)["steps"] == 0


def test_vo2_only_records_explicit_measurement_days_and_excludes_cycling(db):
    assert daily._vo2([], DAY) == {}
    assert daily._vo2([{"cycling": {"calendarDate": DAY.isoformat(), "vo2MaxValue": 60}}], DAY) == {}
    assert daily._vo2([{"generic": {"calendarDate": "2026-10-01", "vo2MaxValue": 60}}], DAY) == {}


def test_readiness_uses_latest_primary_snapshot_not_assumed_morning(db):
    payload = [{"calendarDate": DAY.isoformat(), "timestamp": "2026-10-03T06:00:00", "score": 75,
                "inputContext": "AFTER_WAKEUP_RESET", "recoveryTime": 120},
               {"calendarDate": DAY.isoformat(), "timestamp": "2026-10-03T09:00:00", "score": 60,
                "inputContext": "UPDATE_REALTIME_VARIABLES", "recoveryTime": 300},
               {"calendarDate": DAY.isoformat(), "timestamp": "2026-10-03T10:00:00", "score": 90,
                "primaryActivityTracker": False}]
    value = daily._readiness(payload, DAY)
    assert value["readiness"] == 60 and value["recovery_hours"] == 5
    assert value["context"] == "UPDATE_REALTIME_VARIABLES"


def hc_sleep(external_id="hc-night", *, nap=False, known=True):
    start = datetime(2026, 10, 3, 13) if nap else datetime(2026, 10, 3, 0)
    end = start + timedelta(minutes=30 if nap else 480)
    return SleepSession(external_id=external_id, source_package=daily.PACKAGE, source="health_connect", day=DAY,
                        started_at=start, ended_at=end, duration_window_minutes=30 if nap else 480,
                        asleep_minutes=(30 if nap else 480) if known else None,
                        stage_coverage=1 if known else 0, main_sleep=not nap)


def test_direct_sleep_replaces_mirror_but_preserves_naps_and_samsung_history(db):
    with Session(db) as session:
        session.add(hc_sleep())
        session.add(hc_sleep("hc-nap", nap=True))
        historical = hc_sleep("samsung-history")
        historical.day = date(2026, 9, 30)
        historical.source_package = "com.sec.android.app.shealth"
        session.add(historical)
        store(DAY, {"sleep": daily._sleep(sleep_payload(), DAY)}, session)
        daily.apply_daily(session)
        session.commit()
        rows = session.exec(select(SleepSession)).all()
        assert {row.external_id for row in rows} == {"garmin-sleep:2026-10-03", "hc-nap", "samsung-history"}


def test_incomplete_direct_night_does_not_replace_known_hc_sleep(db):
    with Session(db) as session:
        session.add(hc_sleep())
        store(DAY, {"sleep": daily._sleep(sleep_payload(complete=False), DAY)}, session)
        daily.apply_daily(session)
        session.commit()
        rows = session.exec(select(SleepSession)).all()
        assert len(rows) == 1 and rows[0].external_id == "hc-night" and rows[0].asleep_minutes == 480


def test_hc_full_reimport_reapplies_direct_values_in_transaction(db):
    daily.sync_daily(FakeGarmin(), now=NOW)
    with Session(db) as session:
        # HC source-scoped deletion leaves direct rows, but its day upsert can overwrite steps.
        session.exec(delete(SleepSession).where(SleepSession.source == "health_connect"))
        target = session.get(StepsDaily, DAY)
        target.steps, target.source = 4000, "health_connect"
        session.add(hc_sleep())
        session.add(Vo2Max(measured_at=datetime(2026, 10, 1, 12), vo2=40, source="health_connect"))
        session.flush()
        daily.apply_daily(session)
        session.commit()
        assert session.get(StepsDaily, DAY).steps == 6000
        assert len(session.exec(select(SleepSession).where(SleepSession.day == DAY)).all()) == 1
        vo2 = session.exec(select(Vo2Max)).all()
        assert len(vo2) == 1 and vo2[0].source == daily.SOURCE and vo2[0].vo2 == 45.6


def test_projector_noop_on_legacy_database_without_staging_table():
    legacy = create_engine("sqlite://")
    with Session(legacy) as session:
        assert daily.apply_daily(session) == {"steps": 0, "sleep": 0, "vo2": 0}
    legacy.dispose()


def test_source_policy_retains_pre_cutoff_canonical_values(db):
    day = date(2026, 9, 30)
    with Session(db) as session:
        session.add(StepsDaily(day=day, steps=1234, source="health_connect"))
        store(day, {"summary": {"steps": 9000}}, session)
        daily.apply_daily(session)
        session.commit()
        assert session.get(StepsDaily, day).steps == 1234


def test_foreign_manual_sources_are_not_overwritten(db):
    with Session(db) as session:
        session.add(StepsDaily(day=DAY, steps=1111, source="manual"))
        session.add(Vo2Max(measured_at=datetime.combine(DAY, datetime.min.time()), vo2=42, source="lab"))
        store(DAY, {"summary": {"steps": 9000}, "vo2": {"vo2": 55}}, session)
        daily.apply_daily(session)
        session.commit()
        assert session.get(StepsDaily, DAY).steps == 1111
        assert session.exec(select(Vo2Max)).one().vo2 == 42


def test_api_contract_and_bounds(db, monkeypatch):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    empty = client.get("/metrics/garmin/recovery").json()
    assert set(empty) == {"source", "updated_at", "stale", "series", "latest", "coverage", "availability", "notes"}
    assert client.get("/metrics/garmin/recovery?days=0").status_code == 422
    assert client.get("/metrics/garmin/recovery?days=366").status_code == 422


def test_failed_historical_category_retries_after_the_poll_interval(db):
    api = FakeGarmin()
    api.fail = {"hrv"}
    daily.sync_daily(api, now=NOW)
    api.fail.clear()
    api.calls.clear()
    daily.sync_daily(api, now=NOW + timedelta(days=5))
    assert ("hrv", "2026-10-01") in api.calls


def test_new_partial_summary_does_not_refresh_old_metric_timestamp(db):
    api = FakeGarmin()
    daily.sync_daily(api, now=NOW)
    api.get_user_summary = lambda day: {"calendarDate": day, "totalSteps": 8000, "includesWellnessData": True}
    daily.sync_daily(api, now=NOW + timedelta(hours=1))
    value = daily.recovery(now=NOW + timedelta(hours=1))
    assert value["latest"]["rhr_bpm"]["synced_at"] == NOW.isoformat()
    assert value["latest"]["rhr_bpm"]["value"] == 50


def test_sleep_regression_keeps_known_duration_and_original_observation_time(db):
    api = FakeGarmin()
    daily.sync_daily(api, now=NOW)
    api.get_sleep_data = lambda day: sleep_payload(date.fromisoformat(day), complete=False)
    daily.sync_daily(api, now=NOW + timedelta(hours=1))
    value = daily.recovery(now=NOW + timedelta(hours=1))
    assert value["latest"]["sleep_hours"]["value"] == 8
    assert value["latest"]["sleep_hours"]["synced_at"] == NOW.isoformat()


def test_manual_force_refresh_bypasses_throttle_without_reloading_history(db):
    api = FakeGarmin()
    daily.sync_daily(api, now=NOW)
    result = daily.sync_daily(api, force=True, now=NOW + timedelta(minutes=1))
    assert result["days"] == 3
    assert result["mode"] == "incremental"


@pytest.mark.parametrize("full", [False, True], ids=["incremental", "full"])
def test_real_hc_import_preserves_daily_priority_and_historical_sources(db, monkeypatch, full):
    from app.ingest import health_connect as hc

    monkeypatch.setattr(hc, "engine", db)
    daily.sync_daily(FakeGarmin(), now=NOW)
    past_day = date(2026, 9, 30)
    historical = hc_sleep("samsung-history")
    historical.day = past_day
    historical.started_at, historical.ended_at = datetime(2026, 9, 29, 22), datetime(2026, 9, 30, 6)
    historical.source_package = "com.sec.android.app.shealth"
    body_time = datetime(2026, 9, 30, 9)
    historical_vo2_time = datetime(2026, 9, 30, 12)
    sleep_rows = [historical.model_dump(exclude={"id"}), hc_sleep().model_dump(exclude={"id"}),
                  hc_sleep("hc-nap", nap=True).model_dump(exclude={"id"})]
    with Session(db) as session:
        session.add(historical)
        session.add(StepsDaily(day=past_day, steps=1234, source="health_connect"))
        session.add(Vo2Max(measured_at=historical_vo2_time, vo2=43, source="health_connect"))
        session.add(BodyMeasurement(measured_at=body_time, weight_kg=75, source="health_connect"))
        session.commit()
    parsed = {"body": {body_time: {"weight_kg": 75}}, "sessions": [], "best_efforts": [],
              "best_efforts_invalid_ids": [], "skipped_body": 0,
              "vo2": [{"measured_at": historical_vo2_time, "vo2": 43, "source": "health_connect"},
                      {"measured_at": datetime(2026, 10, 1, 12), "vo2": 40, "source": "health_connect"}],
              "steps": [{"day": past_day, "steps": 1234, "source": "health_connect"},
                        {"day": DAY, "steps": 3000, "source": "health_connect"}],
              "resting": [{"day": DAY, "bpm": 45, "source": "health_connect"}],
              "sleep": {"rows": sleep_rows, "stages_available": True, "available": True},
              "run_windows": {"rows": [], "session_ids": [], "available": False}}
    monkeypatch.setattr(hc, "read_health_connect", lambda path: parsed)
    for _ in range(2):
        hc.import_health_connect("synthetic-only.db", full=full)
    with Session(db) as session:
        assert (session.get(StepsDaily, DAY).steps, session.get(StepsDaily, DAY).source) == (6000, daily.SOURCE)
        assert (session.get(StepsDaily, past_day).steps, session.get(StepsDaily, past_day).source) == (1234, "health_connect")
        sleeps = session.exec(select(SleepSession)).all()
        assert len(sleeps) == 5
        assert sum(row.source == daily.SOURCE for row in sleeps) == 3
        assert {row.external_id for row in sleeps if row.source == "health_connect"} == {"samsung-history", "hc-nap"}
        vo2 = session.exec(select(Vo2Max).order_by(Vo2Max.measured_at)).all()
        assert [(row.vo2, row.source) for row in vo2] == [(43, "health_connect"), (45.6, daily.SOURCE)]
        assert session.exec(select(BodyMeasurement)).one().weight_kg == 75
        assert session.get(RestingHrDaily, DAY).bpm == 45
