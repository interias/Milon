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
    nxt = week_plan.week(1, today=START + timedelta(days=9))     # kommende Woche: zweimal Oberkörper
    assert [(i["title"], i["variant"]) for d in nxt["days"] for i in d["items"] if i["type"] == "gym"] == [
        ("Milon OK", "ok"), ("Milon UK", "uk"), ("Milon OK", "ok")]


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


# ---------------- Etappe 3: Heute dran, Briefing, Wochenbericht, Coach ----------------
def _day_ctx(items, sleep_h=None, energy=None, weather=None):
    return {"items": items, "context": {"sleep_h": sleep_h, "energy": energy, "sick": False, "weather": weather}}


HARD_OPEN = {"type": "bike", "planned": True, "color": "open", "hard": True, "kind": "hard", "title": "VO2max 4 × 4",
             "run_alternative": "Lauf 4×4 min"}
Z2_OPEN = {"type": "bike", "planned": True, "color": "open", "hard": False, "kind": "z2", "title": "Z2",
           "run_alternative": "Lauf locker 60 min"}
GOOD_WEATHER = {"rain_prob": 10, "run": {"start": "2025-06-11T07:20", "end": "2025-06-11T08:20", "clothing": "kurz"}}


def test_adjustments_tired_and_weather():
    tired = week_plan.adjustments(_day_ctx([HARD_OPEN], sleep_h=5.2, energy=2), {"tsb": -30})
    assert tired == ["VO2max 4 × 4 heute lieber locker: Z2 45–60 min nach Puls (nur 5,2 h Schlaf, Energie 2/5, Form -30); "
                     "die harte Einheit auf einen frischen Tag schieben."]
    fresh = week_plan.adjustments(_day_ctx([Z2_OPEN], sleep_h=8, weather=GOOD_WEATHER), {"tsb": 5})
    assert fresh == ["Gutes Laufwetter 07:20–08:20: statt Rad geht auch „Lauf locker 60 min“."]
    rainy = dict(GOOD_WEATHER, rain_prob=70)
    assert week_plan.adjustments(_day_ctx([Z2_OPEN], weather=rainy), None) == []
    assert week_plan.adjustments(_day_ctx([Z2_OPEN], energy=1), None) == [
        "Heute eher müde (Energie 1/5): locker bleiben, Puls-Deckel ernst nehmen."]


def test_today_focus_status_and_lines(db):
    bike_plan.import_plan(json.dumps(plan_json()).encode())
    f = week_plan.today_focus(TODAY)                        # Mi Woche 2: Z2 offen, im Plan ohne Gym
    assert f["status"] == "open" and [i["title"] for i in f["open"]] == ["Z2"] and f["headline"] is None
    week_plan.set_gym(TODAY, "uk")
    lines = week_plan.briefing_lines(TODAY)
    assert lines[0].startswith("WOCHE BISHER (erledigt bis heute von geplant Mo–So): Rad 0 von")
    assert lines[1].startswith("KRAFT HEUTE: Milon UK")
    store(TODAY, "8301", power=120.0, seconds=2400)
    with Session(db) as s:
        s.add(Workout(external_id="w9", title="Milon UK", started_at=datetime.combine(TODAY, datetime.min.time()) + timedelta(hours=18)))
        s.commit()
    assert week_plan.today_focus(TODAY)["status"] == "done"
    assert week_plan.today_focus(START + timedelta(days=12))["status"] == "open"   # Sa: harte Einheit offen


def test_today_focus_sick_and_rest(db):
    with Session(db) as s:
        s.add(CheckIn(day=TODAY, sick=True, updated_at=datetime.now()))
        s.commit()
    f = week_plan.today_focus(TODAY)
    assert f["status"] == "sick" and f["adjustments"] == []
    assert week_plan.today_focus(START + timedelta(days=10))["status"] == "rest"     # Do ohne Plan und ohne Gym


def test_compact_and_tools(db):
    from app.coach import tools
    from app.mcp import server as mcp_server
    bike_plan.import_plan(json.dumps(plan_json()).encode())
    c = week_plan.compact(0, today=TODAY)
    assert len(c["days"]) == 7 and "totals" in c and "hinweis" in c
    assert all("prescription" not in it and "execution" not in it for d in c["days"] for it in d["items"])
    assert "get_week_plan" in [t["function"]["name"] for t in tools.TOOLS]
    assert len(tools.dispatch("get_week_plan", {"offset": 99})["days"]) == 7   # auf 8 Wochen begrenzt
    assert len(mcp_server.get_week_plan(-1)["days"]) == 7


def test_today_api(db):
    app = FastAPI()
    app.include_router(metrics_api.router)
    r = TestClient(app).get("/metrics/week/today")
    assert r.status_code == 200 and r.json()["status"] in ("open", "done", "rest", "sick")


# ---------------- Zielwoche: Cardio-Plätze (Lauf oder Rad) + Arme zu Hause ----------------
def _run(s, day: date, minutes: int, km: float, hour: int = 7, ext: str = "r"):
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour)
    s.add(ExerciseSession(source="garmin", external_id=f"{ext}{day}{hour}", exercise_type=running.RUN, started_at=start,
                          ended_at=start + timedelta(minutes=minutes), distance_km=km, avg_hr=135))


def _arms_b(s, day: date):
    from app.models import WorkoutSet
    w = Workout(external_id=f"arme{day}", title="Arme", source="hevy",
                started_at=datetime.combine(day, datetime.min.time()) + timedelta(hours=19))
    s.add(w)
    s.flush()
    for i, (name, tid, kg, reps) in enumerate([("Skullcrusher (Barbell)", "875F585F", 22.5, 10),
                                               ("Triceps Dip", "28BB4A95", None, 9)]):
        s.add(WorkoutSet(workout_id=w.id, exercise=name, exercise_template_id=tid, set_index=i, set_type="normal",
                         weight_kg=kg, reps=reps, rpe=9))


def test_target_week_floating_cardio_and_home_slots(db, monkeypatch):
    monkeypatch.setattr(week_plan, "SCHEMA_FROM", START)
    mo, tu = START + timedelta(days=7), START + timedelta(days=8)
    with Session(db) as s:
        _run(s, mo, 61, 10.1)      # Mo-Lauf: einzige Cardio-Einheit → Platz „lang“ (So), noch offen
        _arms_b(s, tu)             # Arme B am Dienstag → erfüllt den Do-Platz (passendes Programm)
        s.commit()
    w = _week()
    sa, so, th = START + timedelta(days=12), START + timedelta(days=13), START + timedelta(days=10)
    assert ("run", "Lauf", "green") in _items(w, mo)
    run = next(i for i in _day(w, mo)["items"] if i["type"] == "run")
    assert run["slot"] == "Cardio lang"
    long = next(i for i in _day(w, so)["items"] if i["type"] == "cardio")
    assert long["color"] == "open" and long["done"]["kind"] == "Lauf" and long["done"]["minutes"] == 61
    assert _items(w, sa) == [("cardio", "Cardio · Z2", "open")]
    assert _items(w, tu)[0] == ("home", "Milon Arme A", "red")               # Di vorbei, kein Arme A
    assert ("strength", "Arme", "green") in _items(w, tu)                    # zählt als Arme B (Do)
    assert _items(w, th) == [("home", "Milon Arme B", "green")]
    t = w["totals"]
    assert (t["cardio_planned"], t["cardio_done"], t["cardio_min"], t["home_planned"], t["home_done"]) == (2, 0, 61, 2, 1)
    assert ("gym", "Milon OK", "red") in _items(w, mo)                       # Lauf ersetzt kein Gym


def test_target_week_same_day_hit_and_past_colors(db, monkeypatch):
    monkeypatch.setattr(week_plan, "SCHEMA_FROM", START)
    sa, so = START + timedelta(days=5), START + timedelta(days=6)
    with Session(db) as s:
        _run(s, sa, 50, 8.0)
        _run(s, so, 60, 10.0)      # längste → „lang“: 60/90 = 0,67 → gelb (Woche vorbei)
        s.commit()
    w = _week(-1)
    assert _items(w, so) == [("cardio", "Cardio lang", "yellow")]           # gleicher Tag: Lauf steckt im Platz
    assert _items(w, sa) == [("cardio", "Cardio · Z2", "green")]            # 50 ≥ 0,8 × 45
    assert w["totals"]["cardio_done"] == 1


def test_target_week_starts_at_schema_date(db):
    w = _week()  # Testwochen liegen vor SCHEMA_FROM → nur das alte Gym-Schema
    assert all(i["type"] not in ("cardio", "home") for d in w["days"] for i in d["items"])


def test_slot_helpers():
    pool = [{"minutes": 100, "day": START}, {"minutes": 40, "day": START}]
    sa, so = START + timedelta(days=5), START + timedelta(days=6)
    hits = week_plan._assign_cardio([sa, so], pool)
    assert hits[so]["minutes"] == 100 and hits[sa]["minutes"] == 40
    assert week_plan._slot_color(0.85, sa, so) == "green"
    assert week_plan._slot_color(0.6, sa, so) == "yellow" and week_plan._slot_color(0.3, sa, so) == "orange"
    assert week_plan._slot_color(0.3, so, so) == "open"


def test_end_bike_plan_switches_to_target_week(db, monkeypatch):
    monkeypatch.setattr(week_plan, "SCHEMA_FROM", START)
    plan = bike_plan.import_plan(json.dumps(plan_json()).encode())
    bike_plan.end_plan(plan["id"], START + timedelta(days=6))
    ov = bike_plan.overview(today=TODAY)
    assert [x["week"] for x in ov["weeks"]] == [1] and ov["plan"]["planned_end"] == (START + timedelta(days=13)).isoformat()
    w = _week()
    assert w["plan"] is None and w["totals"]["bike_planned"] == 0 and w["totals"]["cardio_planned"] == 2
    assert _week(-1)["plan"]["week"] == 1                                    # Historie bleibt
    bike_plan.end_plan(plan["id"], START + timedelta(days=30))              # ab dem alten Ende: zurückgenommen
    ov = bike_plan.overview(today=TODAY)
    assert len(ov["weeks"]) == 2 and ov["plan"]["planned_end"] is None
    with pytest.raises(ValueError):
        bike_plan.end_plan(plan["id"], START - timedelta(days=1))


def test_end_bike_plan_api(db):
    from app.api import bike_plan as bike_api
    app = FastAPI()
    app.include_router(bike_api.router)
    http = TestClient(app)
    assert http.post("/bike-plan/end", json={}).status_code == 404
    bike_plan.import_plan(json.dumps(plan_json()).encode())
    r = http.post("/bike-plan/end", json={"day": (START + timedelta(days=6)).isoformat()})
    assert r.status_code == 200 and r.json()["plan"]["end"] == (START + timedelta(days=6)).isoformat()
