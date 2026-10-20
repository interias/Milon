"""Fitness & Frische (#71): pulse-based TRIMP over runs + indoor rides, CTL/ATL/TSB, rides as training days.

Every database is a tmp_path SQLite file; Garmin is never contacted."""
import json
import math
from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import garmin_indoor
from app.api import metrics as metrics_api
from app.garmin_indoor import GarminIndoorRide
from app.metrics import activity, body, cycling, sleep, endurance, health, running, strength, weekly_journal
from app.models import ExerciseSession

TODAY = date(2026, 6, 30)
REST, HRMAX = 60.0, 180.0


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'endurance.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for module in (running, cycling, health, activity, weekly_journal, strength, body, sleep):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(activity.settings, "timezone", "Europe/Berlin")
    monkeypatch.setattr(running.settings, "run_hr_max", HRMAX)
    yield engine
    engine.dispose()


def trimp(minutes, hr):
    hrr = (hr - REST) / (HRMAX - REST)
    return minutes * hrr * 0.64 * math.exp(1.92 * hrr)


def add_run(engine, started, minutes=60, hr=150, km=None):
    with Session(engine) as session:
        session.add(ExerciseSession(exercise_type=33, started_at=started, ended_at=started + timedelta(minutes=minutes),
                                    distance_km=km or minutes / 6, avg_hr=hr, max_hr=(hr + 15) if hr else None))
        session.commit()


def add_ride(engine, activity_id, started, minutes=60, hr=140.0, valid=True, norm_power=250.0):
    with Session(engine) as session:
        session.add(GarminIndoorRide(activity_id=activity_id, activity_type="virtual_ride", title="Zwift", started_at=started,
                                     duration_seconds=minutes * 60, elapsed_duration_seconds=minutes * 60,
                                     distance_km=minutes / 2, avg_power_w=norm_power, norm_power_w=norm_power,
                                     avg_hr=hr, hr_valid=valid, synced_at=started))
        session.commit()


def test_banister_matches_running_trimp_scale(db):
    assert endurance.banister(60, 150, REST, HRMAX) == pytest.approx(trimp(60, 150))
    assert trimp(60, 150) == pytest.approx(121.55, abs=0.01)
    # same formula as running.trimp_weekly for the same run (hr_max = setting 180 = floor of observed max)
    add_run(db, datetime(2026, 6, 20, 8), minutes=60, hr=150)
    weekly = running.trimp_weekly()["series"][0]["trimp"]
    assert weekly == pytest.approx(trimp(60, 150), abs=1)


def test_ctl_atl_tsb_follow_the_exponential_formula(db):
    add_run(db, datetime(2026, 6, 26, 8), minutes=60, hr=150)  # one load, then three empty days
    load = trimp(60, 150)
    result = endurance.fitness(days=30, today=TODAY)
    rows = {r["date"]: r for r in result["series"]}
    assert len(result["series"]) == 5 and result["history_days"] == 5
    for n in range(1, 6):
        row = rows[(date(2026, 6, 26) + timedelta(days=n - 1)).isoformat()]
        assert row["ctl"] == pytest.approx(load / 42 * (41 / 42) ** (n - 1), abs=0.06)
        assert row["atl"] == pytest.approx(load / 7 * (6 / 7) ** (n - 1), abs=0.06)
        prev_ctl = load / 42 * (41 / 42) ** (n - 2) if n > 1 else 0.0
        prev_atl = load / 7 * (6 / 7) ** (n - 2) if n > 1 else 0.0
        assert row["tsb"] == pytest.approx(prev_ctl - prev_atl, abs=0.06)  # form = previous evening
    today = result["today"]
    assert today["date"] == TODAY.isoformat() and today["has_load_today"] is False
    assert today["tsb"] < 0 and today["form"] == "belastet"
    assert result["unrated"] == {"runs": 0, "rides": 0}


def test_ride_without_valid_hr_has_no_load_and_watt_tss_never_counts(db, monkeypatch):
    monkeypatch.setattr(cycling.settings, "bike_ftp", 200.0)  # without an eFTP the watt TSS would be NaN and prove nothing
    add_ride(db, "r1", datetime(2026, 6, 28, 18), minutes=60, hr=140.0, valid=True)
    add_ride(db, "r2", datetime(2026, 6, 29, 18), minutes=90, hr=95.0, valid=False, norm_power=400.0)
    tss = cycling._with_load(cycling.indoor_rides()).set_index("activity_id")["tss"]
    assert tss["r2"] > 100  # the watt-based load exists, but must stay out of the pulse-based chain
    result = endurance.fitness(days=30, today=TODAY)
    by_id = {s["activity_id"]: s for s in result["sessions"]}
    assert by_id["r1"]["trimp"] == pytest.approx(round(trimp(60, 140), 1), abs=0.1)
    assert by_id["r2"]["trimp"] is None and by_id["r2"]["note"] == "kein gültiger Puls"
    assert result["unrated"] == {"runs": 0, "rides": 1}
    loads = {r["date"]: r["load"] for r in result["series"]}
    assert loads["2026-06-29"] == 0.0 and loads["2026-06-28"] == pytest.approx(trimp(60, 140), abs=0.1)


def test_weekly_run_bike_share_and_same_day_sum(db):
    add_run(db, datetime(2026, 6, 24, 7), minutes=60, hr=150)   # Wednesday
    add_ride(db, "r1", datetime(2026, 6, 24, 19), minutes=60, hr=150.0)
    add_ride(db, "r2", datetime(2026, 6, 26, 19), minutes=30, hr=130.0)
    result = endurance.fitness(days=30, today=TODAY)
    week = next(w for w in result["weeks"] if w["week"] == "2026-06-22")
    run, bike = trimp(60, 150), trimp(60, 150) + trimp(30, 130)
    assert week["run"] == pytest.approx(run, abs=0.1) and week["bike"] == pytest.approx(bike, abs=0.1)
    assert week["run_share"] == pytest.approx(run / (run + bike) * 100, abs=0.1)
    assert week["runs"] == 1 and week["rides"] == 2
    day = next(r for r in result["series"] if r["date"] == "2026-06-24")
    assert day["load"] == pytest.approx(run + trimp(60, 150), abs=0.1)


def test_run_without_hr_is_unrated(db):
    add_run(db, datetime(2026, 6, 27, 8), hr=None)
    add_run(db, datetime(2026, 6, 28, 8), hr=150)
    result = endurance.fitness(days=30, today=TODAY)
    assert result["unrated"] == {"runs": 1, "rides": 0}
    assert [s["trimp"] is None for s in result["sessions"]] == [True, False]


def test_empty_fitness(db):
    result = endurance.fitness(days=30, today=TODAY)
    assert result["series"] == [] and result["today"] is None and result["weeks"] == []


def test_rides_count_as_training_days_everywhere(db):
    now = datetime.now(activity.ZoneInfo("Europe/Berlin"))
    day = now.date() - timedelta(days=1)
    add_ride(db, "indoor", datetime.combine(day, datetime.min.time()) + timedelta(hours=18), minutes=45)
    add_run(db, datetime.combine(day - timedelta(days=4), datetime.min.time()) + timedelta(hours=8), km=5)
    # outdoor: 40 min counts, a 10 min commute does not
    for offset, minutes in ((2, 40), (3, 10)):
        start = datetime.combine(now.date() - timedelta(days=offset), datetime.min.time()) + timedelta(hours=7)
        with Session(db) as session:
            session.add(ExerciseSession(exercise_type=4, started_at=start, ended_at=start + timedelta(minutes=minutes),
                                        distance_km=minutes * 0.35))
            session.commit()

    result = activity.consistency(7)
    by_date = {d["date"]: d for d in result["days"]}
    ride_day = by_date[day.isoformat()]
    assert ride_day["level"] == 3 and ride_day["trained"] and ride_day["ride"]
    assert by_date[(now.date() - timedelta(days=2)).isoformat()]["ride"] is True
    assert by_date[(now.date() - timedelta(days=3)).isoformat()]["ride"] is False
    assert result["trained_days"] == 3 and result["streak"] == 2

    overview = activity.overview(now)
    assert overview["cycling"]["current_sessions"] == 2 and overview["cycling"]["current_minutes"] == 85.0
    assert overview["cycling"]["previous_sessions"] == 0
    recent = activity.recent(10)
    assert {"run", "ride"} <= {item["kind"] for item in recent}
    assert activity.compare(7)["cycling"]["current_sessions"] == 2

    journal = weekly_journal.journal(now=now + timedelta(days=1))  # complete week ending today
    rides = [ride for d in journal["days"] for ride in d["rides"]]
    assert len(rides) == 2 and journal["summary"]["cycling_sessions"] == 2


def test_ride_days_pause_streak_across_sick_days(db):
    from app import checkins
    today = datetime.now(activity.ZoneInfo("Europe/Berlin")).date()
    for back in (4, 5):
        add_ride(db, f"s{back}", datetime.combine(today - timedelta(days=back), datetime.min.time()) + timedelta(hours=18), minutes=45)
    with Session(db) as session:
        for back in (1, 2, 3):
            session.add(checkins.CheckIn(day=today - timedelta(days=back), sick=True, updated_at=datetime.now()))
        session.commit()
    result = activity.consistency(7)
    assert [d["ride"] for d in result["days"]] == [False, True, True, False, False, False, False]
    assert result["sick_days"] == 3 and result["streak"] == 2  # rides count, sick days neither count nor break


def test_fitness_endpoint_is_200_and_nan_free(db):
    app = FastAPI()
    app.include_router(metrics_api.router)

    def strict(text):
        return json.loads(text, parse_constant=lambda c: pytest.fail(f"non-finite {c}"))

    with TestClient(app) as client:
        empty = client.get("/metrics/endurance/fitness")
        assert empty.status_code == 200 and strict(empty.text)["series"] == []
        today = datetime.now()
        add_run(db, today - timedelta(days=3), minutes=50, hr=148)
        add_ride(db, "e1", today - timedelta(days=2), minutes=40, hr=135.0)
        add_ride(db, "e2", today - timedelta(days=1), minutes=40, hr=90.0, valid=False)
        full = client.get("/metrics/endurance/fitness?days=60")
        assert full.status_code == 200
        body = strict(full.text)
    assert body["today"]["ctl"] > 0 and body["unrated"]["rides"] == 1
    assert set(body) >= {"series", "weeks", "sessions", "today", "unrated", "hr_rest", "hr_max", "caveat"}
