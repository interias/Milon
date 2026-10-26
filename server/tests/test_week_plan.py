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


# ---------------- Etappe 2: Kraft-Tage planen + Regeln über alle Sportarten ----------------
def test_gym_override_outside_plan_and_swap(db):
    mo, tu, we = START + timedelta(days=7), START + timedelta(days=8), START + timedelta(days=9)
    week_plan.set_gym(tu, "uk")
    assert week_plan.gym_program(tu) == "uk"
    week_plan.move_gym(mo, we)                       # Mo OK → Mi (dort UK) = Tausch
    assert (week_plan.gym_program(mo), week_plan.gym_program(we)) == ("uk", "ok")
    week_plan.set_gym(START + timedelta(days=11), None)  # Fr ausdrücklich ohne Kraft
    assert week_plan.gym_program(START + timedelta(days=11)) is None
    titles = [[i["title"] for i in d["items"]] for d in _week()["days"]]
    assert titles[0] == ["Milon UK"] and titles[1] == ["Milon UK"] and titles[4] == []
    with pytest.raises(ValueError, match="kein Krafttraining"):
        week_plan.move_gym(START + timedelta(days=12), mo)


def test_gym_inside_plan_writes_plan_label(db):
    bike_plan.import_plan(json.dumps(plan_json()).encode())
    week_plan.set_gym(START + timedelta(days=12), "uk")  # Sa Woche 2 = harte Einheit, liegt noch vor uns
    di = _day(_week(), START + timedelta(days=12))
    assert ("gym", "Milon UK") in [(i["type"], i["title"]) for i in di["items"]]
    bike = next(i for i in di["items"] if i["type"] == "bike")
    assert bike["hard"] and bike["warnings"] == ["Harte Einheit am Beintag: mindestens 6 h Abstand, Kraft zuerst"]


def _it(kind, *, hard=False, program=None, start=None, minutes=60, color="open", done=None):
    out = {"type": kind, "planned": kind in ("bike", "gym"), "hard": hard, "program": program, "color": color, "done": done}
    if start:
        s = datetime(2025, 6, 2, *start)
        out.update(start=s.isoformat(), end=(s + timedelta(minutes=minutes)).isoformat())
    return out


def test_rules_gap_order_and_neighbours():
    days = [
        {"items": [_it("ride", hard=True, start=(8, 0)), _it("strength", program="uk", start=(11, 0))]},   # 2 h Abstand
        {"items": [_it("run", hard=True, start=(7, 0)), _it("strength", program="uk", start=(18, 0))]},    # 10 h
        {"items": [_it("bike", hard=True)]},                                                              # Tag nach Bein
        {"items": [_it("bike", hard=True), _it("gym", program="ok")]},                                   # hart+hart, Gym
    ]
    count = week_plan.apply_rules(days)
    assert count == 4
    assert days[0]["items"][0]["warnings"] == ["Nur 2,0 h Abstand zum Beintraining (empfohlen ≥ 6 h)"]
    assert days[1]["items"][0]["warnings"] == ["Tag nach dem Beintag — Beine noch nicht erholt", "Zwei harte Tage hintereinander"]
    assert days[2]["items"][0]["warnings"] == ["Tag nach dem Beintag — Beine noch nicht erholt", "Zwei harte Tage hintereinander"]
    assert days[3]["items"][0]["warnings"] == ["Harte Einheit am Gym-Tag", "Zwei harte Tage hintereinander"]


def test_hard_runs_count_in_week_warning(db, monkeypatch):
    monkeypatch.setattr(running.settings, "run_hr_max", 180.0)
    with Session(db) as s:
        for i in range(3):                           # drei harte Läufe (Ø 150 ≥ 144 = 80 % von 180)
            day = START + timedelta(days=7 + 2 * i)
            s.add(ExerciseSession(source="health_connect", external_id=f"hr{i}", exercise_type=running.RUN,
                                  started_at=datetime.combine(day, datetime.min.time()) + timedelta(hours=7),
                                  ended_at=datetime.combine(day, datetime.min.time()) + timedelta(hours=7, minutes=40),
                                  distance_km=8.0, avg_hr=150))
        s.commit()
    w = _week()
    assert w["totals"]["hard_done"] == 3
    assert w["warnings"] == ["3 harte Einheiten (Rad + Lauf, Regel: höchstens 2 pro Woche)"]
    run = next(i for i in _day(w, START + timedelta(days=9))["items"] if i["type"] == "run")
    assert run["hard"] and "Harte Einheit am Beintag: mindestens 6 h Abstand, Kraft zuerst" in run["warnings"]


def test_week_gym_api(db):
    app = FastAPI()
    app.include_router(metrics_api.router)
    http = TestClient(app)
    day = (START + timedelta(days=8)).isoformat()
    assert http.put("/metrics/week/gym", json={"day": day, "program": "uk"}).json() == {"day": day, "program": "uk"}
    assert http.put("/metrics/week/gym", json={"day": day, "program": "beine"}).status_code == 422
    moved = http.post("/metrics/week/gym/move", json={"from_day": day, "to_day": (START + timedelta(days=10)).isoformat()})
    assert moved.json() == {"from": None, "to": "uk"}
    assert http.post("/metrics/week/gym/move", json={"from_day": day, "to_day": day}).status_code == 422
