"""Synthetic night responses only; the production database is never opened."""
from datetime import date, datetime, timedelta, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.garmin_nights import router
from app.garmin_daily import GarminDaily, PACKAGE
from app.metrics import garmin_nights as nights


DAY = date(2026, 10, 5)
NOW = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine, tables=[GarminDaily.__table__])
    monkeypatch.setattr(nights, "engine", engine)
    monkeypatch.setattr(nights.settings, "timezone", "Europe/Berlin")
    monkeypatch.setattr(nights.settings, "watch_source_package", PACKAGE)
    monkeypatch.setattr(nights.settings, "watch_source_switch_date", date(2026, 9, 25))
    monkeypatch.setattr(nights.settings, "steps_source_package", "com.sec.android.app.shealth")
    yield engine
    engine.dispose()


def payload(day=DAY):
    end = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=6)
    start = end - timedelta(hours=8)
    stages = [{"startGMT": (start + timedelta(hours=index * 2)).isoformat(),
               "endGMT": (start + timedelta(hours=(index + 1) * 2)).isoformat(), "activityLevel": code}
              for index, code in enumerate([0, 1, 2, 3])]
    def series(seconds, value):
        return [{"startGMT": (start + timedelta(seconds=offset)).timestamp() * 1000,
                 "value": value + offset / 3600} for offset in range(0, 8 * 3600 + 1, seconds)]
    return {"dailySleepDTO": {"sleepStartTimestampGMT": start.timestamp() * 1000,
                             "sleepEndTimestampGMT": end.timestamp() * 1000, "sleepTimeSeconds": 6 * 3600},
            "sleepLevels": stages, "sleepHeartRate": series(120, 50), "sleepStress": series(180, 10),
            "sleepBodyBattery": series(180, 30), "hrvData": series(300, 45)}


def save(engine, data=None, day=DAY):
    with Session(engine) as session:
        session.add(GarminDaily(day=day, raw_json=json.dumps({"sleep": data if data is not None else payload(day)}),
                                status_json=json.dumps({"sleep": {"status": "available", "last_success_at": NOW.isoformat()}})))
        session.commit()


def test_night_reuses_sleep_coverage_and_maps_actual_stage_codes(db):
    save(db)
    value = nights.night(DAY)
    assert value["complete"] and value["asleep_minutes"] == 360 and value["awake_minutes"] == 120
    assert [phase["stage"] for phase in value["phases"]] == ["deep", "light", "rem", "awake"]
    assert value["started_at"] == "2026-10-05T00:00:00+02:00"
    assert value["battery_change"] == 8
    assert value["series"]["heart_rate"]["samples"] == 241
    assert "raw_json" not in value


@pytest.mark.parametrize("day,start_offset,end_offset", [
    (date(2026, 10, 25), "+02:00", "+01:00"),
    (date(2026, 3, 29), "+01:00", "+02:00"),
    (date(2028, 2, 29), "+01:00", "+01:00"),
])
def test_dst_and_leap_day_use_elapsed_utc_not_wall_time(db, monkeypatch, day, start_offset, end_offset):
    monkeypatch.setattr(nights.settings, "watch_source_switch_date", date(2026, 1, 1))
    save(db, day=day)
    value = nights.night(day)
    assert value["window_minutes"] == 480
    assert value["started_at"].endswith(start_offset)
    assert value["ended_at"].endswith(end_offset)
    assert value["clock_change"] == (start_offset != end_offset)
    assert value["series"]["heart_rate"]["segments"][0][-1]["seconds"] == 28800


def test_invalid_values_duplicates_and_missing_samples_remain_gaps(db):
    data = payload()
    data["sleepHeartRate"][1]["value"] = -1
    data["sleepHeartRate"].append({**data["sleepHeartRate"][4], "value": 99})
    del data["sleepHeartRate"][10:14]
    save(db, data)
    series = nights.night(DAY)["series"]["heart_rate"]
    assert len(series["segments"]) == 4
    assert series["samples"] == 235
    assert all(point["value"] >= 25 for segment in series["segments"] for point in segment)


@pytest.mark.parametrize("change", ["missing", "broken", "partial"])
def test_charge_needs_continuous_samples_near_both_boundaries(db, change):
    data = payload()
    if change == "missing":
        data.pop("sleepBodyBattery")
    elif change == "broken":
        del data["sleepBodyBattery"][20:30]
    else:
        data["sleepBodyBattery"] = data["sleepBodyBattery"][20:]
    save(db, data)
    assert nights.night(DAY)["battery_change"] is None


def test_overlapping_stages_hidden_instead_of_doubled(db):
    data = payload()
    data["sleepLevels"].append(data["sleepLevels"][0].copy())
    save(db, data)
    value = nights.night(DAY)
    assert value["stage_conflict"] and value["phases"] == []
    assert not value["complete"] and value["asleep_minutes"] is None
    assert value["series"]["heart_rate"]["samples"] > 0


def test_partial_unknown_stages_dont_claim_complete_sleep(db):
    data = payload()
    data["sleepLevels"][0]["activityLevel"] = -1
    save(db, data)
    value = nights.night(DAY)
    assert value["phases"][0]["stage"] == "unknown"
    assert value["asleep_minutes"] is None and value["awake_minutes"] is None
    assert value["stage_coverage"] == .75


def test_complete_aggregates_do_not_manufacture_phase_timeline(db):
    data = payload()
    del data["sleepLevels"]
    data["dailySleepDTO"].update(deepSleepSeconds=7200, lightSleepSeconds=7200,
                                 remSleepSeconds=7200, awakeSleepSeconds=7200)
    save(db, data)
    value = nights.night(DAY)
    assert value["complete"] and value["phases"] == [] and not value["stage_conflict"]


def test_requested_period_source_and_nap_filters_do_not_fallback_to_old_data(db):
    save(db, day=date(2026, 9, 24))
    save(db, day=date(2026, 9, 25))
    save(db, day=date(2026, 10, 6))
    save(db, day=DAY)
    value = nights.nights(14, now=NOW)
    assert [item["day"] for item in value["nights"]] == ["2026-09-25", "2026-10-05"]
    assert nights.night(date(2026, 9, 24)) is None
    assert nights.nights(14, now=NOW + timedelta(days=30))["nights"] == []
    data = payload(DAY - timedelta(days=1))
    data["dailySleepDTO"]["sleepStartTimestampGMT"] = data["dailySleepDTO"]["sleepEndTimestampGMT"] - 3600_000
    save(db, data, DAY - timedelta(days=1))
    assert nights.night(DAY - timedelta(days=1)) is None


def test_invalid_raw_wrong_waking_day_and_empty_series_are_safe(db):
    save(db, {})
    assert nights.night(DAY) is None
    save(db, payload(DAY), day=DAY - timedelta(days=1))
    assert nights.night(DAY - timedelta(days=1)) is None
    data = payload(DAY + timedelta(days=1))
    for field, *_ in nights.SERIES.values():
        data.pop(field)
    save(db, data, DAY + timedelta(days=1))
    assert all(item["segments"] == [] for item in nights.night(DAY + timedelta(days=1))["series"].values())


def test_downsampling_is_bounded_preserves_endpoints_and_gaps(db):
    data = payload()
    start = data["dailySleepDTO"]["sleepStartTimestampGMT"]
    data["sleepHeartRate"] = [{"startGMT": start + offset * 1000, "value": 40 + offset % 50}
                             for offset in range(28_801) if offset != 14_000]
    save(db, data)
    series = nights.night(DAY)["series"]["heart_rate"]
    assert series["samples"] == 28_800
    assert series["display_samples"] <= 720
    assert series["segments"][0][0]["seconds"] == 0
    assert series["segments"][-1][-1]["seconds"] == 28_800


def test_api_validates_calendar_days_and_supported_periods(db):
    save(db)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/metrics/garmin/nights/2026-10-05").status_code == 200
    assert client.get("/metrics/garmin/nights/2026-02-30").status_code == 422
    assert client.get("/metrics/garmin/nights/2026-10-04").status_code == 404
    assert client.get("/metrics/garmin/nights?days=14").status_code == 200
    assert client.get("/metrics/garmin/nights?days=30").status_code == 200
    assert client.get("/metrics/garmin/nights?days=365").status_code == 422
