"""Indoor/Zwift rides (#69): import without coordinates, HR plausibility, HC dedup, cycling metrics.

Garmin is only ever a fake; every database is a tmp_path SQLite file."""
from datetime import date, datetime, timedelta
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app import config, garmin_activity, garmin_daily, garmin_indoor, garmin_load, garmin_routes, garmin_weather, hero_world
from app.api import metrics as metrics_api
from app.api import settings as settings_api
from app.garmin_indoor import GarminIndoorRide
from app.ingest import garmin
from app.metrics import body, cycling, health, route_atlas, stats
from app.models import BodyMeasurement, ExerciseSession

from test_garmin_sync import FakeGarmin, activity, write_tokens

# Fictional Zwift map coordinates: must never reach the database.
CANARY_LAT, CANARY_LON = -11.6543219, 166.9512347
KEYS = ["directTimestamp", "sumDistance", "directPower", "directBikeCadence", "directHeartRate",
        "directSpeed", "directElevation", "directLatitude", "directLongitude"]
TODAY = date(2025, 6, 30)


def details_for(start_gmt: str, seconds: int, power=None, hr=None):
    """Garmin detail payload in the real shape: one row per second, descriptors with metricsIndex."""
    start = datetime.fromisoformat(start_gmt + "+00:00").timestamp() * 1000
    rows = []
    for s in range(seconds + 1):
        p = power(s) if power else None
        h = hr(s) if hr else None
        rows.append({"metrics": [start + s * 1000, s * 8.0, p, 90 if p else None, h, 8.0, 10.0,
                                 CANARY_LAT + s * 1e-6, CANARY_LON + s * 1e-6]})
    return {"metricDescriptors": [{"key": k, "metricsIndex": i} for i, k in enumerate(KEYS)],
            "activityDetailMetrics": rows, "metricsCount": len(rows), "totalMetricsCount": len(rows)}


def zwift(activity_id, start="2025-01-02 17:00:00", minutes=60, power=200.0, hr=140.0,
          type_key="virtual_ride", title="Zwift - Tempus Fugit in Watopia", **changes):
    values = {"activityName": title, "startTimeGMT": start, "duration": minutes * 60,
              "elapsedDuration": minutes * 60, "distance": minutes * 500.0, "elevationGain": 120.0,
              "activityType": {"typeKey": type_key}, "hasPolyline": True, "averageHR": hr,
              "maxHR": hr + 20 if hr is not None else None,
              "aerobicTrainingEffect": 3.1, "anaerobicTrainingEffect": 0.4, "activityTrainingLoad": 80.0,
              "hrTimeInZone_1": 60.0, "hrTimeInZone_2": 600.0, "hrTimeInZone_3": 0.0,
              "hrTimeInZone_4": 0.0, "hrTimeInZone_5": 0.0}
    if power is not None:
        values.update({"avgPower": power, "normPower": power, "maxPower": power + 150,
                       "averageBikingCadenceInRevPerMinute": 90.0,
                       "maxAvgPower_1": power + 150, "maxAvgPower_5": power + 100, "maxAvgPower_60": power + 30,
                       "maxAvgPower_300": power + 10, "maxAvgPower_1200": power, "maxAvgPower_1800": power,
                       "max20MinPower": power,
                       **{f"powerTimeInZone_{i}": 0.0 for i in range(1, 8)}})
    values.update(changes)
    return activity(activity_id, **values)


class IndoorGarmin(FakeGarmin):
    def __init__(self, runs, rides):
        super().__init__(runs)
        self.rides = rides
        self.details = {}
        self.detail_calls = []
        self.ftp = {"functionalThresholdPower": 203, "sport": "CYCLING"}

    def get_activities(self, start, limit, *, activitytype):
        self.pages.append((start, limit, activitytype))
        source = self.rides if activitytype == "cycling" else self.activities
        return source[start:start + limit]

    def get_activity_details(self, activity_id, maxchart=2000, maxpoly=4000):
        self.detail_calls.append((activity_id, maxchart, maxpoly))
        value = self.details[activity_id]
        if isinstance(value, Exception):
            raise value
        return value

    def get_cycling_ftp(self):
        return self.ftp


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'indoor.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for module in (garmin_routes, garmin_indoor, health, hero_world, route_atlas, cycling, body):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(garmin_routes.settings, "timezone", "Europe/Berlin")
    monkeypatch.setattr(cycling.settings, "bike_ftp", 0.0)
    yield engine
    engine.dispose()


@pytest.fixture
def synced(db, tmp_path, monkeypatch):
    path = tmp_path / ".env"
    write_tokens(path)
    monkeypatch.setattr(garmin, "SESSION_FILE", path)
    monkeypatch.setattr(garmin, "settings", SimpleNamespace(timezone="Europe/Berlin"))
    monkeypatch.setattr(garmin_activity, "sync_activities", lambda api, items, full=False: {"errors": 0})
    monkeypatch.setattr(garmin_weather, "sync_weather", lambda api, items, full=False: {"errors": 0})
    monkeypatch.setattr(garmin_daily, "sync_daily", lambda api, full=False, force=False: {"errors": 0})
    monkeypatch.setattr(garmin_load, "sync_tolerance", lambda api, full=False, force=False: {"errors": 0})
    api = IndoorGarmin([activity(1)], [zwift(5), zwift(6, start="2025-01-03 06:00:00", power=None, hr=120.0,
                                                          type_key="indoor_cycling", title="Indoor Cycling")])
    api.details["5"] = details_for("2025-01-02T17:00:00", 3600, power=lambda s: 200.0, hr=lambda s: 140.0)
    api.details["6"] = details_for("2025-01-03T06:00:00", 3600, hr=lambda s: 120.0)
    monkeypatch.setattr(garmin, "_new_client", lambda: api)
    return SimpleNamespace(engine=db, api=api)


def stored(engine, activity_id):
    with Session(engine) as session:
        return session.get(GarminIndoorRide, activity_id)


# ---------------- import ----------------
def test_import_stores_indoor_rides_without_any_coordinates(synced):
    result = garmin.import_garmin()
    assert result["rides"]["indoor"] == 2 and result["rides"]["imported"] == 0
    assert result["indoor_rides"]["imported"] == 2 and result["indoor_rides"]["errors"] == 0
    assert result["indoor_rides"]["garmin_ftp_w"] == 203
    assert all(maxpoly == 0 for _, _, maxpoly in synced.api.detail_calls)  # no polyline requested
    assert synced.api.downloads == ["1"]  # no GPX for indoor rides
    with Session(synced.engine) as session:
        assert session.exec(select(garmin_routes.GarminRide)).all() == []  # never a GPS ride
        assert [r.activity_id for r in session.exec(select(garmin_routes.GarminRoute))] == ["1"]
    with synced.engine.connect() as con:
        columns = {row[1] for row in con.exec_driver_sql("PRAGMA table_info(garmin_indoor_rides)")}
        dump = "\n".join(con.connection.iterdump())
    assert not {c for c in columns if "lat" in c or "lon" in c or "poly" in c}
    for canary in (f"{CANARY_LAT:.4f}", f"{CANARY_LON:.4f}", f"{CANARY_LAT:.2f}", f"{CANARY_LON:.2f}",
                   "Latitude", "Longitude"):  # .2f: series values are stored rounded to 2 digits
        assert canary not in dump  # anywhere in the database
    indoor_rows = [line for line in dump.splitlines() if "garmin_indoor" in line]
    assert indoor_rows and not any('"lat"' in line or '"lon"' in line for line in indoor_rows)
    ride = stored(synced.engine, "5")
    assert (ride.world, ride.route, ride.activity_type) == ("Watopia", "Tempus Fugit", "virtual_ride")
    assert ride.started_at == datetime(2025, 1, 2, 18)  # local wall time
    assert ride.distance_km == 30 and ride.elevation_gain_m == 120
    assert ride.avg_power_w == 200 and ride.norm_power_w == 200 and ride.work_kj == pytest.approx(720, abs=1)
    assert ride.hr_valid and ride.aerobic_te == 3.1 and ride.training_load == 80
    curve = json.loads(ride.power_curve_json)
    assert curve["1200"] == 200 and curve["1"] == 350 and curve["3600"] == 200  # 60 min from the series
    series = json.loads(ride.series_json)
    assert set(series) == {"t", "power_w", "cadence_rpm", "hr_bpm", "speed_m_s", "altitude_m"}
    watch = stored(synced.engine, "6")
    assert watch.avg_power_w is None and watch.work_kj is None and json.loads(watch.power_curve_json) == {}
    assert watch.avg_hr == 120 and watch.hr_valid and json.loads(watch.series_json)["power_w"] == []


def test_indoor_sync_is_incremental_and_full_refetches(synced):
    synced.api.rides.append(activity(7, activityName="Synthetic ride", activityType={"typeKey": "road_biking"},
                                     startTimeGMT="2025-01-05 12:00:00"))  # a known GPS ride → 30 newest later
    garmin.import_garmin()
    second = garmin.import_garmin()
    assert (0, 30, "cycling") in synced.api.pages
    assert second["indoor_rides"]["mode"] == "incremental" and second["indoor_rides"]["skipped"] == 2
    assert len(synced.api.detail_calls) == 2
    third = garmin.import_garmin(full=True)
    assert third["indoor_rides"]["mode"] == "full" and third["indoor_rides"]["imported"] == 2
    assert synced.api.pages.count((0, 50, "cycling")) == 2  # initial + full page up to 1,000


def test_indoor_failure_never_fails_the_running_sync(synced):
    synced.api.details["5"] = RuntimeError("synthetic remote failure")
    result = garmin.import_garmin()
    assert result["indoor_rides"]["errors"] == 1 and result["errors"] == 0
    assert "synthetic remote failure" not in str(result)
    assert stored(synced.engine, "5") is None and stored(synced.engine, "6") is not None
    synced.api.details["5"] = details_for("2025-01-02T17:00:00", 3600, power=lambda s: 200.0, hr=lambda s: 140.0)
    assert garmin.import_garmin()["indoor_rides"]["imported"] == 1  # retried on the next sync


def test_parse_title_is_tolerant():
    assert garmin_indoor.parse_title("Zwift - Tempus Fugit in Watopia") == ("Watopia", "Tempus Fugit")
    assert garmin_indoor.parse_title("Zwift – Road to Sky in Watopia") == ("Watopia", "Road to Sky")
    assert garmin_indoor.parse_title("Zwift - Rolling in the Deep in New York") == ("New York", "Rolling in the Deep")
    assert garmin_indoor.parse_title("Zwift - Group Ride") == (None, "Group Ride")
    assert garmin_indoor.parse_title("Indoor Cycling") == (None, None)
    assert garmin_indoor.parse_title(None) == (None, None)


# ---------------- puls plausibility ----------------
def _values(activity_id, start, seconds=1800, power=200.0, hr=lambda s: 140.0, **changes):
    summary = garmin_indoor.normalize_summary(zwift(activity_id, start=start, minutes=seconds // 60, power=power,
                                                    hr=changes.pop("avg_hr", 140.0), **changes))
    series = garmin_indoor.normalize_series(summary, details_for(start.replace(" ", "T"), seconds,
                                                                 power=(lambda s: power) if power else None, hr=hr))
    return garmin_indoor.build_values(summary, series)


def test_hr_plausibility_flags_dropouts_and_low_average():
    assert _values(1, "2025-01-02 17:00:00")["hr_valid"]
    assert not _values(2, "2025-01-02 17:00:00", avg_hr=35.0, hr=lambda s: 35.0)["hr_valid"]
    gaps = _values(3, "2025-01-02 17:00:00", hr=lambda s: None if s % 10 < 3 else 140.0)
    assert gaps["hr_dropout"] == pytest.approx(0.3, abs=0.01) and not gaps["hr_valid"]
    few = _values(4, "2025-01-02 17:00:00", hr=lambda s: None if s % 10 == 0 else 140.0)
    assert few["hr_valid"]


# ---------------- dedup / outdoor km ----------------
def add_hc_ride(engine, external_id, start, minutes, km):
    with Session(engine) as session:
        session.add(ExerciseSession(external_id=external_id, exercise_type=health.BIKE, started_at=start,
                                    ended_at=start + timedelta(minutes=minutes), distance_km=km))
        session.commit()


def test_hc_mirror_of_indoor_ride_drops_and_indoor_km_stay_off_the_health_page(synced):
    garmin.import_garmin()  # Zwift ride 2025-01-02 18:00-19:00 local, 30 virtual km
    add_hc_ride(synced.engine, "hc-zwift-mirror", datetime(2025, 1, 2, 18, 1), 58, 29.0)
    add_hc_ride(synced.engine, "hc-commute", datetime(2025, 1, 4, 8), 10, 2.5)
    assert [(r["date"], r["km"]) for r in health.cycling_recent(limit=0)] == [("2025-01-04T08:00:00", 2.5)]
    assert health.cycling_summary(datetime(2025, 1, 10, 12).astimezone())["total_km"] == 2.5


# ---------------- metrics on stored rides ----------------
def store(day: date, activity_id: str, power=200.0, avg_hr=140.0, curve=None, seconds=1800, hr=None,
          series_power=None, **changes):
    start = f"{day.isoformat()} 16:00:00"
    summary = garmin_indoor.normalize_summary(zwift(activity_id, start=start, minutes=seconds // 60,
                                                    power=power, hr=avg_hr, **changes))
    if curve is not None:
        summary["curve"] = dict(curve)
    p = series_power or ((lambda s: power) if power else None)
    series = garmin_indoor.normalize_series(summary, details_for(start.replace(" ", "T"), seconds, power=p,
                                                                 hr=hr or (lambda s: avg_hr)))
    garmin_indoor.save_indoor_ride(garmin_indoor.build_values(summary, series))


def set_garmin_ftp(engine, watts):
    with Session(engine) as session:
        session.add(garmin_indoor.GarminIndoorState(id=1, garmin_ftp_w=watts))
        session.commit()


def test_np_if_tss_on_known_series(db, monkeypatch):
    monkeypatch.setattr(cycling.settings, "bike_ftp", 200.0)
    store(TODAY, "10", power=200.0, seconds=3600, normPower=None)
    blocks = lambda s: 100.0 if (s // 60) % 2 == 0 else 300.0  # noqa: E731 -- 1-min on/off intervals
    store(TODAY - timedelta(days=1), "11", power=200.0, seconds=3600, normPower=None, series_power=blocks)
    rows = {r["activity_id"]: r for r in cycling.rides()}
    steady, intervals = rows["10"], rows["11"]
    assert steady["np"] == 200 and steady["if"] == 1.0 and steady["tss"] == 100 and steady["eftp"] == 200
    values = garmin_indoor.normalized_power(np.array([blocks(s) for s in range(3600)], float))
    assert values > 220 and intervals["np"] == pytest.approx(values, abs=1)
    assert intervals["tss"] > 100 and intervals["avg_power"] == 200


def test_eftp_fallback_chain(db, monkeypatch):
    assert cycling.eftp(today=TODAY)["value"] is None
    set_garmin_ftp(db, 203.0)
    assert (cycling.eftp(today=TODAY)["value"], cycling.eftp(today=TODAY)["source"]) == (203, "garmin")
    # Usable ride without a 20-min value → critical-power fit over the curve (2–10 min).
    store(TODAY - timedelta(days=5), "20", power=180.0, seconds=900,
          curve={60: 400.0, 120: 350.0, 180: 320.0, 300: 290.0, 600: 260.0})
    fit = cycling.eftp(today=TODAY)
    cp = np.polyfit([120, 180, 300, 600], [120 * 350, 180 * 320, 300 * 290, 600 * 260], 1)[0]
    assert fit["source"] == "fit" and fit["value"] == round(0.95 * cp)
    # Best 20 min within 90 days wins.
    store(TODAY - timedelta(days=10), "21", power=250.0, seconds=1800)
    best = cycling.eftp(today=TODAY)
    assert best["source"] == "20min" and best["value"] == round(0.95 * 250)
    # Rides older than 90 days do not count → back to Garmin's FTP.
    later = TODAY + timedelta(days=120)
    assert cycling.eftp(today=later)["source"] == "garmin"
    # The setting overrides everything.
    monkeypatch.setattr(cycling.settings, "bike_ftp", 300.0)
    assert (cycling.eftp(today=TODAY)["value"], cycling.eftp(today=TODAY)["source"]) == (300, "setting")


def test_eftp_weekly_series_and_wkg(db):
    with Session(db) as session:
        for offset in range(10):
            session.add(BodyMeasurement(measured_at=datetime.combine(TODAY - timedelta(days=offset), datetime.min.time()),
                                        weight_kg=80.0, source="test"))
        session.commit()
    store(TODAY - timedelta(days=40), "30", power=200.0)
    store(TODAY - timedelta(days=3), "31", power=240.0)
    result = cycling.eftp(weeks=8, today=TODAY)
    assert result["value"] == 228 and result["wkg"] == round(228 / 80, 2) and result["weight_kg"] == 80
    values = [w["eftp"] for w in result["series"] if w["eftp"] is not None]
    assert values[0] == 190 and values[-1] == 228 and values == sorted(values)
    assert [z["lo_pct"] for z in result["zones"]] == [0, 55, 75, 90, 105, 120, 150]


def test_power_curve_compares_windows_and_keeps_all_time_best(db):
    store(TODAY - timedelta(days=10), "40", power=210.0)
    store(TODAY - timedelta(days=120), "41", power=230.0)
    rows = {row["seconds"]: row for row in cycling.power_curve(today=TODAY)["durations"]}
    assert rows[1200]["recent"] == 210 and rows[1200]["previous"] == 230
    assert rows[1200]["best"] == 230 and rows[1200]["best_date"] == (TODAY - timedelta(days=120)).isoformat()
    assert rows[1]["label"] == "1 s" and rows[1200]["label"] == "20 min"


def _ride_set(db, fitter: bool, seed: int):
    """20 rides over ~4 months with varying power; HR depends on power (+ time if fitter) plus noise."""
    rng = np.random.default_rng(seed)
    for i in range(20):
        day = TODAY - timedelta(days=120 - i * 6)
        power = float(180 + (i * 37) % 20)
        avg_hr = 60 + 0.45 * power - (0.08 * i * 6 if fitter else 0.0) + float(rng.normal(0, 2.0))
        store(day, f"{100 + i}", power=power, avg_hr=round(avg_hr, 1), seconds=1800)


def test_hr_at_power_and_efficiency_detect_real_improvement(db):
    _ride_set(db, fitter=True, seed=7)
    hr = cycling.hr_at_power()
    assert hr["trend"]["verdict"] == "besser" and hr["trend"]["significant"]
    assert hr["trend"]["delta_bpm"] < -5 and len(hr["series"]) == 20 and hr["ref_power"] % 5 == 0
    eff = cycling.efficiency()
    assert eff["trend"]["verdict"] == "besser" and eff["rides"] == 20


def test_hr_at_power_and_efficiency_stay_neutral_on_noise(db):
    _ride_set(db, fitter=False, seed=11)
    assert cycling.hr_at_power()["trend"]["verdict"] == "unklar"
    assert cycling.efficiency()["trend"]["verdict"] == "unklar"


def test_invalid_hr_rides_never_enter_hr_metrics(db):
    _ride_set(db, fitter=True, seed=7)
    store(TODAY, "999", power=200.0, avg_hr=35.0, hr=lambda s: 35.0)
    assert cycling.hr_at_power()["trend"]["n"] == 20
    assert cycling.efficiency()["rides"] == 20


def test_decoupling_only_for_steady_rides(db):
    store(TODAY, "50", power=200.0, seconds=3600, hr=lambda s: 130.0 + 10.0 * s / 3600)
    store(TODAY - timedelta(days=1), "51", power=200.0, seconds=3600,
          series_power=lambda s: 100.0 if (s // 60) % 2 == 0 else 300.0)
    store(TODAY - timedelta(days=2), "52", power=200.0, seconds=1500)  # too short after trimming
    dec = {d["activity_id"]: d for d in cycling.efficiency()["decoupling"]}
    assert set(dec) == {"50"}
    assert 2 < dec["50"]["decoupling_pct"] < 6 and dec["50"]["minutes"] == 48


def test_zones_weekly_from_series(db, monkeypatch):
    monkeypatch.setattr(cycling.settings, "bike_ftp", 200.0)
    store(TODAY, "60", power=200.0, seconds=1800)  # 100 % FTP → Z4 (90–105 %)
    store(TODAY, "61", power=None, seconds=1800)    # watch ride without power
    result = cycling.zones(weeks=4, today=TODAY)
    assert result["unzoned_rides"] == 1 and len(result["weeks"]) == 1
    seconds = result["weeks"][0]["seconds"]
    assert seconds[3] == 1801 and sum(seconds) == 1801


def test_worlds_and_routes(db):
    store(TODAY, "70", title="Zwift - Tempus Fugit in Watopia")
    store(TODAY - timedelta(days=1), "71", title="Zwift - Tempus Fugit in Watopia")
    store(TODAY - timedelta(days=2), "72", title="Zwift - Greatest London Loop in London")
    store(TODAY - timedelta(days=3), "73", title="Indoor Cycling")
    result = cycling.worlds()
    assert [w["world"] for w in result["worlds"]] == ["Watopia", "London"] and result["other_rides"] == 1
    watopia = result["worlds"][0]
    assert watopia["rides"] == 2 and watopia["km"] == 30 and watopia["elevation_m"] == 240
    assert watopia["routes"] == [{"route": "Tempus Fugit", "rides": 2, "km": 30.0, "elevation_m": 240.0,
                                  "hours": 1.0, "last": TODAY.isoformat()}]


# ---------------- REST + settings ----------------
def _assert_finite(value):
    if isinstance(value, dict):
        for v in value.values():
            _assert_finite(v)
    elif isinstance(value, list):
        for v in value:
            _assert_finite(v)
    elif isinstance(value, float):
        assert math.isfinite(value)


@pytest.mark.parametrize("populated", [False, True])
def test_cycling_endpoints_are_200_and_nan_free(db, populated):
    if populated:
        _ride_set(db, fitter=True, seed=7)
        store(TODAY, "80", power=None, avg_hr=None, hr=lambda s: None)  # nothing but time
        store(TODAY, "81", power=200.0, seconds=3600, hr=lambda s: 130.0 + 10.0 * s / 3600)
    app = FastAPI()
    app.include_router(metrics_api.router)
    http = TestClient(app)
    for path in ("summary", "power-curve", "eftp", "hr-at-power", "efficiency", "zones", "rides", "worlds"):
        response = http.get(f"/metrics/cycling/{path}")
        assert response.status_code == 200, path
        assert "NaN" not in response.text and "Infinity" not in response.text
        _assert_finite(response.json())
    ride = http.get("/metrics/cycling/ride/81" if populated else "/metrics/cycling/ride/1")
    assert ride.status_code == (200 if populated else 404)
    if populated:
        body_ = ride.json()
        _assert_finite(body_)
        assert body_["series"] and len(body_["series"]) <= 600 and len(body_["zones"]) == 7
        assert not any(k in json.dumps(body_) for k in ("lat", "lon"))


def test_bike_ftp_setting_is_live_and_persisted(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("# Kommentar\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    monkeypatch.setattr(settings_api.settings, "bike_ftp", 0.0)
    app = FastAPI()
    app.include_router(settings_api.router)
    http = TestClient(app)
    assert http.get("/settings").json()["bike_ftp"] == 0
    response = http.put("/settings", json={"bike_ftp": 245})
    assert response.status_code == 200 and response.json()["bike_ftp"] == 245
    assert settings_api.settings.bike_ftp == 245 and "BIKE_FTP=245" in env_file.read_text(encoding="utf-8")
    assert http.put("/settings", json={"bike_ftp": -5}).status_code == 422
    assert http.put("/settings", json={"bike_ftp": 5000}).status_code == 422
    assert settings_api.settings.bike_ftp == 245
