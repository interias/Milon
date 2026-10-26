"""Mein Wochenplan: Soll aus Rad-Plan und Gym-Tagen, Ist aus Fahrten/Läufen/Hevy, Farben, Krankheitstage."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import bike_plan, checkins, garmin_indoor, weather
from app.api import metrics as metrics_api
from app.checkins import CheckIn
from app.metrics import body, cycling, health, run_fitness_service, running, sleep, strength_plan, week_plan
from app.models import ExerciseSession, Workout

from test_bike_plan import START, plan_json
from test_garmin_indoor import store

TODAY = START + timedelta(days=9)  # Mittwoch Woche 2


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'week.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for module in (bike_plan, garmin_indoor, cycling, body, running, health, week_plan, strength_plan, sleep, checkins):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(garmin_indoor.settings, "timezone", "Europe/Berlin")
    monkeypatch.setattr(cycling.settings, "bike_ftp", 0.0)
    monkeypatch.setattr(weather, "today", lambda **kw: {"configured": False})  # nie ins Netz
    monkeypatch.setattr(run_fitness_service, "standardized_hr", lambda: {"pace_series": []})
    yield engine
    engine.dispose()


def _week(offset=0):
    return week_plan.week(offset, today=TODAY)


def _day(w, d: date) -> dict:
    return next(x for x in w["days"] if x["date"] == d.isoformat())


def _items(w, d: date) -> list[tuple]:
    return [(i["type"], i["title"], i["color"]) for i in _day(w, d)["items"]]


def test_without_plan_uses_default_gym_schema(db):
    w = _week()
    assert [d["weekday"] for d in w["days"]] == ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    assert _items(w, START + timedelta(days=7)) == [("gym", "Milon OK", "red")]   # Mo vorbei, nichts gemacht
    assert _items(w, START + timedelta(days=9)) == [("gym", "Milon UK", "open")]  # heute bleibt offen
    assert _items(w, START + timedelta(days=11)) == [("gym", "Milon OK", "open")]
    assert w["plan"] is None and w["totals"]["gym_planned"] == 3 and w["totals"]["missed"] == 1


def test_plan_week_colors_unplanned_and_sick(db):
    data = plan_json()
    data["plan"][1]["days"][0]["gym"] = "Gym Beine"            # Mo Woche 2 → UK
    bike_plan.import_plan(json.dumps(data).encode())
    mo, tu = START + timedelta(days=7), START + timedelta(days=8)
    store(mo, "8101", power=120.0, seconds=2400)                 # 40 von 40 min → im Soll
    store(mo, "8102", power=100.0, seconds=900, title="Zwift - Extra")  # zweite Fahrt → ungeplant
    with Session(db) as s:
        s.add(Workout(external_id="w1", title="Milon UK", started_at=datetime.combine(mo, datetime.min.time()) + timedelta(hours=18)))
        s.add(ExerciseSession(source="health_connect", external_id="r1", exercise_type=running.RUN,
                              started_at=datetime.combine(mo, datetime.min.time()) + timedelta(hours=7),
                              ended_at=datetime.combine(mo, datetime.min.time()) + timedelta(hours=7, minutes=40),
                              distance_km=6.5, avg_hr=140))
        s.add(CheckIn(day=tu, sick=True, updated_at=datetime.now()))
        s.commit()
    w = _week()
    assert w["plan"]["week"] == 2 and w["plan"]["phase"] == "Test"
    assert ("bike", "Z2", "green") in _items(w, mo)
    assert ("gym", "Milon UK", "green") in _items(w, mo)
    assert ("ride", "Zwift - Extra", "grey") in _items(w, mo) and ("run", "Lauf", "grey") in _items(w, mo)
    assert _items(w, tu) == [("bike", "Zwift Ramp Test", "sick")]  # krank: pausiert, nicht verpasst
    t = w["totals"]
    assert (t["bike_done"], t["bike_matched"], t["gym_matched"], t["runs"], t["missed"]) == (2, 1, 1, 1, 0)
    assert t["run_km"] == 6.5 and t["hard_planned"] == 2


def test_short_ride_is_yellow_or_orange(db):
    bike_plan.import_plan(json.dumps(plan_json()).encode())
    store(START + timedelta(days=7), "8201", power=120.0, seconds=1500)   # 25/40 min = 62 %
    assert ("bike", "Z2", "yellow") in _items(_week(), START + timedelta(days=7))


def test_future_week_is_open_with_prescription(db):
    bike_plan.import_plan(json.dumps(plan_json()).encode())
    w = week_plan.week(1, today=START - timedelta(days=3))        # Woche 1 = nächste Woche
    assert {i["color"] for d in w["days"] for i in d["items"]} == {"open"}
    fr = _day(w, START + timedelta(days=4))                       # Ruhetag mit Gym im Plan
    assert [(i["type"], i["title"]) for i in fr["items"]] == [("gym", "Milon OK")]
    assert fr["items"][0]["prescription"] and fr["items"][0]["prescription"][0].endswith("Sätze")


@pytest.mark.parametrize(("ratio", "color"), [(1.0, "green"), (0.8, "green"), (1.2, "green"), (0.62, "yellow"),
                                              (1.4, "yellow"), (0.3, "orange"), (1.8, "orange"), (None, "green")])
def test_ratio_color(ratio, color):
    assert week_plan.ratio_color(ratio) == color


@pytest.mark.parametrize(("label", "program"), [("Gym Beine", "uk"), ("Leg Day", "uk"), ("Milon UK", "uk"),
                                                ("Gym Oberkörper", "ok"), (None, None)])
def test_program_of(label, program):
    assert week_plan.program_of(label) == program


def test_api(db):
    app = FastAPI()
    app.include_router(metrics_api.router)
    http = TestClient(app)
    for offset in (-1, 0, 1):
        r = http.get(f"/metrics/week?offset={offset}")
        assert r.status_code == 200 and len(r.json()["days"]) == 7 and "NaN" not in r.text
    assert http.get("/metrics/week?offset=20").status_code == 422
