"""Rad-Trainingsplan: Import, Plan-FTP (Ramp-Test, Handwert), Abgleich, Ausführung, .zwo, Messpunkte."""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import bike_plan, garmin_indoor
from app.api import bike_plan as bike_plan_api
from app.metrics import body, cycling, run_fitness_service, running
from app.models import ExerciseSession

from test_garmin_indoor import store

START = date(2025, 6, 2)  # Montag
TODAY = START + timedelta(days=9)  # Mittwoch Woche 2


def _session(kind="z2", title="Z2", steering="heart_rate", hr=(115, 125), steps=None, optional=False):
    steps = steps or [{"label": "Einrollen", "duration_min": 5, "power_pct": [40, 50], "cadence_rpm": {"min": 85, "max": 90}},
                      {"label": "Z2", "duration_min": 30, "power_pct": [55, 64]},
                      {"label": "Ausrollen", "duration_min": 5, "power_pct": [40, 50]}]
    return {"title": title, "kind": kind, "optional": optional, "steering": steering, "duration_min": 40,
            "hr_target_bpm": {"min": hr[0], "max": hr[1]} if hr else None, "steps": steps,
            "run_alternative": "Lauf locker", "note": None, "zwift_workout": None}


HARD = _session("hard", "Sweet Spot 2 × 8", "power_erg", None, [
    {"label": "Einrollen", "duration_min": 5, "power_pct": [40, 50]},
    {"label": "Sweet Spot", "duration_min": 8, "power_pct": [88, 92]},
    {"label": "Pause", "duration_min": 4, "power_pct": [50, 55]},
    {"label": "Sweet Spot", "duration_min": 8, "power_pct": [88, 92]},
    {"label": "Ausrollen", "duration_min": 5, "power_pct": [40, 50]}])
TEST = _session("test", "Zwift Ramp Test", "power_erg", None, [
    {"label": "Einrollen", "duration_min": 5, "power_pct": [40, 50]}, {"label": "Rampe", "duration_min": None}])


def plan_json(ftp=200.0) -> dict:
    def day(offset, session, gym=None):
        d = START + timedelta(days=offset)
        return {"day": bike_plan.WEEKDAYS[d.weekday()], "date": d.isoformat(), "gym": gym, "session": session}
    weeks = [
        {"week": 1, "start": START.isoformat(), "end": (START + timedelta(days=6)).isoformat(), "phase": "Eingewöhnung",
         "goal": "Z2", "days": [day(0, _session()), day(1, HARD), day(2, _session("z2_optional", optional=True, hr=(None, 120))),
                                day(3, _session()), day(4, None, "Gym")]},
        {"week": 2, "start": (START + timedelta(days=7)).isoformat(), "end": (START + timedelta(days=13)).isoformat(),
         "phase": "Test", "goal": "FTP", "days": [day(7, _session()), day(8, TEST), day(9, _session()), day(12, HARD)]},
    ]
    return {"schema": "rad-grundlagenblock/agent-context@1", "ftp": {"value_w": ftp},
            "power_zones_pct_ftp": [{"zone": "Z2", "from_pct": 56, "to_pct": 75}],
            "metrics": {"definitions": [
                {"key": "ftp", "name": "FTP", "unit": "W", "better": "up", "target_w8": "+10 %"},
                {"key": "cad", "name": "Kadenz", "unit": "U/min", "better": "eq", "target_w8": "85–90"},
                {"key": "hr630", "name": "Puls bei 6:30", "unit": "bpm", "better": "down", "target_w8": "≤ 133"},
                {"key": "rhr", "name": "Ruhepuls", "unit": "bpm", "better": "down", "target_w8": "–"}],
                "checkpoints": {"start": {"date": START.isoformat(), "values": {"rhr": 52, "cad": 80},
                                          "estimated": ["cad"]}, "w2": None}},
            "plan": weeks}


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'plan.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for module in (bike_plan, garmin_indoor, cycling, body, running):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(garmin_indoor.settings, "timezone", "Europe/Berlin")
    monkeypatch.setattr(cycling.settings, "bike_ftp", 0.0)
    monkeypatch.setattr(run_fitness_service, "standardized_hr", lambda: {"pace_series": [
        {"pace_seconds": 390, "points": [{"date": START.isoformat(), "hr": 136.0}]}]})
    yield engine
    engine.dispose()


def _import(data: dict | None = None) -> dict:
    return bike_plan.import_plan(json.dumps(data or plan_json()).encode())


def _overview():
    return bike_plan.overview(today=TODAY)


def _find(ov, day: date) -> dict:
    return next(s for w in ov["weeks"] for s in w["sessions"] if s["date"] == day.isoformat())


# ---------------- Import ----------------
def test_import_json_and_html_wrapper_and_duplicates(db):
    result = _import()
    assert result["weeks"] == 2 and result["sessions"] == 8
    with pytest.raises(bike_plan.Duplicate):
        bike_plan.import_plan(json.dumps(plan_json()).encode())
    html = ('<html><script type="application/json" id="agent-context">'
            + json.dumps(plan_json(ftp=210)) + "</script></html>").encode()
    second = bike_plan.import_plan(html)  # anderer Inhalt → neuer, aktiver Plan
    assert second["id"] != result["id"] and bike_plan.active_plan().id == second["id"]
    with pytest.raises(ValueError, match="Wochen"):
        bike_plan.import_plan(b'{"plan": []}')
    with pytest.raises(ValueError, match="Keine Plandaten"):
        bike_plan.import_plan(b"<html>nichts</html>")
    assert bike_plan.delete_plan(second["id"]) and not bike_plan.delete_plan("plan-unbekannt")


# ---------------- Plan-FTP ----------------
def test_ftp_from_plan_ramp_and_manual(db):
    plan_id = _import()["id"]
    assert _overview()["ftp"]["watts"] == 200 and _overview()["ftp"]["source"] == "plan"
    curve = {60: 280.0, 300: 220.0, 1200: 190.0}
    store(START + timedelta(days=8), "9001", power=180.0, seconds=1200, curve=curve, title="Zwift - Ramp Test")
    ov = _overview()
    assert ov["ftp"]["source"] == "ramp" and ov["ftp"]["watts"] == 210  # 0,75 × 280
    assert _find(ov, START + timedelta(days=8))["execution"] == {"type": "test", "ftp": 210}
    # Watt einer Einheit folgen der FTP am Tag: Woche 1 noch 200, ab dem Test 210.
    assert _find(ov, START + timedelta(days=1))["steps"][1]["watts"] == [176, 184]
    assert _find(ov, START + timedelta(days=12))["steps"][1]["watts"] == [185, 193]
    bike_plan.set_manual_ftp(plan_id, 205, TODAY)
    ov = _overview()
    assert (ov["ftp"]["watts"], ov["ftp"]["source"]) == (205, "manual")
    manual = next(e for e in ov["ftp"]["history"] if e["source"] == "manual")
    assert bike_plan.delete_manual_ftp(manual["id"]) and _overview()["ftp"]["source"] == "ramp"


# ---------------- Abgleich + Ausführung ----------------
def test_match_status_and_hr_band_execution(db):
    _import()
    store(START, "9002", power=120.0, seconds=2400, hr=lambda s: 120.0)                   # Mo: im Band
    db_session = Session(db)
    db_session.add(ExerciseSession(source="health_connect", external_id="run1", exercise_type=running.RUN,
                                   started_at=datetime.combine(START + timedelta(days=3), datetime.min.time()) + timedelta(hours=7),
                                   ended_at=datetime.combine(START + timedelta(days=3), datetime.min.time()) + timedelta(hours=8),
                                   distance_km=9.0, avg_hr=134))
    db_session.commit()
    ov = _overview()
    mo, di, mi, do = (_find(ov, START + timedelta(days=i)) for i in range(4))
    assert mo["status"] == "done" and mo["execution"]["type"] == "hr_band" and mo["execution"]["in_band_pct"] == 100
    assert di["status"] == "missed" and mi["status"] == "skipped" and do["status"] == "run"
    assert do["run"]["km"] == 9.0
    assert _find(ov, TODAY)["status"] == "today" and _find(ov, START + timedelta(days=12))["status"] == "planned"
    assert ov["progress"] == {"core": 7, "core_done": 2, "optional_done": 0, "missed": 3}


def _follow(steps, ftp, offset_s, scale=1.0):
    timeline = []
    for st in steps:
        mid = sum(st["power_pct"]) / 2 * ftp / 100 * scale
        timeline += [mid] * int(st["duration_min"] * 60)
    return lambda s: 90.0 if s < offset_s else timeline[min(len(timeline) - 1, s - offset_s)]


def test_interval_execution_finds_start_and_scores_hits(db):
    _import()
    day = START + timedelta(days=1)
    store(day, "9003", power=150.0, seconds=2100, series_power=_follow(HARD["steps"], 200, 120))
    ex = _find(_overview(), day)["execution"]
    assert ex["type"] == "intervals" and ex["shift_s"] in (115, 120, 125)
    assert ex["hit_pct"] >= 95 and [s["label"] for s in ex["steps"]] == ["Sweet Spot 1", "Sweet Spot 2"]
    assert ex["steps"][0]["target_w"] == [176, 184]


def test_interval_execution_low_power_scores_low(db):
    _import()
    day = START + timedelta(days=1)
    store(day, "9004", power=120.0, seconds=2000, series_power=_follow(HARD["steps"], 200, 0, scale=0.8))
    assert _find(_overview(), day)["execution"]["hit_pct"] < 10


# ---------------- .zwo ----------------
def test_zwo_export(db):
    _import()
    hard = _find(_overview(), START + timedelta(days=1))
    xml, filename = bike_plan.zwo(hard["id"], today=TODAY)
    root = ET.fromstring(xml)
    blocks = list(root.find("workout"))
    assert [b.tag for b in blocks] == ["Warmup", "SteadyState", "SteadyState", "SteadyState", "Cooldown"]
    assert blocks[1].get("Power") == "0.900" and blocks[0].get("Duration") == "300"
    assert filename.endswith(".zwo") and "Sweet_Spot" in filename
    assert "176–184 W" in root.findtext("description")
    assert bike_plan.zwo(_find(_overview(), START + timedelta(days=8))["id"]) is None  # Ramp: Zwift-eigener Test


# ---------------- Messpunkte ----------------
def test_checkpoints_sources_and_verdicts(db):
    plan_id = _import()["id"]
    store(START - timedelta(days=5), "9005", power=110.0, seconds=2400, averageBikingCadenceInRevPerMinute=78.0)
    store(TODAY - timedelta(days=1), "9006", power=110.0, seconds=2400, averageBikingCadenceInRevPerMinute=86.0)
    result = bike_plan.checkpoints(today=TODAY)
    assert [c["key"] for c in result["checkpoints"]] == ["start", "w2"]
    assert result["checkpoints"][1]["date"] == (START + timedelta(days=13)).isoformat()
    rows = {m["key"]: m for m in result["metrics"]}
    assert rows["ftp"]["values"]["start"]["value"] == 200 and rows["ftp"]["values"]["w2"] is None
    assert rows["cad"]["values"]["start"]["source"] == "auto" and rows["cad"]["now"]["value"] == 86
    assert rows["cad"]["verdict"] == "up"                       # näher an 85–90
    assert rows["rhr"]["values"]["start"] == {"value": 52, "source": "plan", "estimated": False, "note": None}
    assert rows["hr630"]["values"]["start"]["value"] == 136
    bike_plan.set_checkpoint(plan_id, "start", "cad", 70.0, estimated=True)
    rows = {m["key"]: m for m in bike_plan.checkpoints(today=TODAY)["metrics"]}
    assert rows["cad"]["values"]["start"]["source"] == "manual" and rows["cad"]["delta"] == 16
    bike_plan.set_checkpoint(plan_id, "start", "cad", None)
    assert {m["key"]: m for m in bike_plan.checkpoints(today=TODAY)["metrics"]}["cad"]["values"]["start"]["source"] == "auto"


@pytest.mark.parametrize(("better", "start", "latest", "target", "expected"), [
    ("up", 100, 110, None, "up"), ("down", 100, 110, None, "down"), ("down", 100, 100.2, None, "eq"),
    ("eq", 80, 86, "85–90", "up"), ("eq", 88, 95, "85–90", "down"), ("none", 70, 72, None, None)])
def test_verdict(better, start, latest, target, expected):
    assert bike_plan._verdict(better, start, latest, target) == expected


# ---------------- REST ----------------
def _finite(value):
    if isinstance(value, dict):
        return all(_finite(v) for v in value.values())
    if isinstance(value, list):
        return all(_finite(v) for v in value)
    return not (isinstance(value, float) and not math.isfinite(value))


def test_api(db):
    app = FastAPI()
    app.include_router(bike_plan_api.router)
    http = TestClient(app)
    assert http.get("/bike-plan").json() == {"plan": None}
    assert http.post("/bike-plan/ftp", json={"watts": 200}).status_code == 404
    assert http.post("/bike-plan", files={"file": ("p.txt", b"kaputt")}).status_code == 422
    created = http.post("/bike-plan", files={"file": ("p.json", json.dumps(plan_json()).encode())})
    assert created.status_code == 200
    assert http.post("/bike-plan", files={"file": ("p.json", json.dumps(plan_json()).encode())}).status_code == 409
    store(START, "9007", power=120.0, seconds=2400, hr=lambda s: 120.0)
    for path in ("/bike-plan", "/bike-plan/checkpoints"):
        r = http.get(path)
        assert r.status_code == 200 and "NaN" not in r.text and _finite(r.json())
    assert http.post("/bike-plan/ftp", json={"watts": 215}).json()["watts"] == 215
    assert http.put("/bike-plan/checkpoints", json={"checkpoint": "start", "key": "ftp", "value": 190}).status_code == 200
    session_id = http.get("/bike-plan").json()["weeks"][0]["sessions"][1]["id"]
    zwo = http.get(f"/bike-plan/session/{session_id}.zwo")
    assert zwo.status_code == 200 and "attachment" in zwo.headers["content-disposition"]
    assert http.get("/bike-plan/session/999999.zwo").status_code == 404
    assert http.delete(f"/bike-plan/{created.json()['id']}").json() == {"deleted": created.json()["id"]}


# ---------------- Editor + Regeln (Etappe 2) ----------------
def _sid(day: date) -> int:
    return _find(_overview(), day)["id"]


def test_move_swaps_and_gym_stays_with_the_day(db):
    plan_id = _import()["id"]
    bike_plan.set_gym(plan_id, START + timedelta(days=11), "Gym Oberkörper")   # Fr Woche 2
    hard = _sid(START + timedelta(days=12))                                     # Sa: hart
    bike_plan.update_session(hard, {"day": (START + timedelta(days=9)).isoformat()})  # auf Mi (belegt) → Tausch
    ov = _overview()
    assert _find(ov, START + timedelta(days=9))["title"] == "Sweet Spot 2 × 8"
    assert _find(ov, START + timedelta(days=12))["title"] == "Z2"
    bike_plan.update_session(hard, {"day": (START + timedelta(days=11)).isoformat()})  # auf Fr (frei, Gym)
    fr = _find(_overview(), START + timedelta(days=11))
    assert fr["gym"] == "Gym Oberkörper" and fr["warnings"] == ["Harte Einheit am Gym-Tag (Gym Oberkörper)"]
    with pytest.raises(ValueError, match="außerhalb"):
        bike_plan.update_session(hard, {"day": (START + timedelta(days=30)).isoformat()})


def test_legacy_gym_is_materialized_before_moving(db):
    data = plan_json()
    data["plan"][0]["days"][0]["gym"] = "Gym Oberkörper"     # Mo Woche 1, Gym nur an der Einheit
    plan_id = _import(data)["id"]
    with Session(db) as s:                                  # Plan wie aus der ersten Fassung: ohne gym in den Wochen
        plan = s.get(bike_plan.BikePlan, plan_id)
        plan.weeks_json = json.dumps([{k: v for k, v in w.items() if k != "gym"} for w in json.loads(plan.weeks_json)])
        s.add(plan)
        s.commit()
    assert _find(_overview(), START)["gym"] == "Gym Oberkörper"
    bike_plan.update_session(_sid(START + timedelta(days=1)), {"day": START.isoformat()})  # Di (hart) ↔ Mo
    mo = _find(_overview(), START)
    assert mo["kind"] == "hard" and mo["gym"] == "Gym Oberkörper" and mo["warnings"]


def test_rules_leg_day_back_to_back_and_three_hard(db):
    plan_id = _import()["id"]
    bike_plan.set_gym(plan_id, START, "Gym Beine")                                   # Mo Beine → Di hart
    bike_plan.create_session(plan_id, START + timedelta(days=4), copy_from=_sid(START + timedelta(days=1)))  # Fr hart
    bike_plan.update_session(_sid(START + timedelta(days=2)), {"kind": "hard"})       # Mi hart
    ov = _overview()
    di, mi = _find(ov, START + timedelta(days=1)), _find(ov, START + timedelta(days=2))
    assert "Tag nach dem Beintag — Beine noch nicht erholt" in di["warnings"]
    assert "Zwei harte Tage hintereinander" in mi["warnings"]
    assert ov["weeks"][0]["warnings"] == ["3 harte Einheiten (Regel: höchstens 2 pro Woche)"]


def test_hevy_workout_counts_as_gym_day(db):
    from app.models import Workout
    _import()
    with Session(db) as s:
        s.add(Workout(external_id="h1", title="Milon UK", started_at=datetime.combine(START, datetime.min.time()) + timedelta(hours=18)))
        s.commit()
    ov = _overview()
    assert ov["weeks"][0]["days"][0]["hevy"] == "Milon UK"
    assert "Tag nach dem Beintag — Beine noch nicht erholt" in _find(ov, START + timedelta(days=1))["warnings"]


def test_edit_fields_steps_and_validation(db):
    sid = _import() and _sid(START)
    bike_plan.update_session(sid, {"title": "Tempo", "kind": "hard", "steering": "power_erg", "steps": [
        {"label": "Einrollen", "duration_min": 10, "power_pct": [40, 50]},
        {"label": "Tempo", "duration_min": 20, "power_pct": [76, 87], "cadence": [90, None]}]})
    s = _find(_overview(), START)
    assert (s["title"], s["kind"], s["duration_min"], s["steps"][1]["watts"]) == ("Tempo", "hard", 30, [152, 174])
    for bad, msg in [({"steps": []}, "1–60"), ({"steps": [{"label": "", "duration_min": 5}]}, "Bezeichnung"),
                     ({"steps": [{"label": "x", "power_pct": [90, 80]}]}, "≤"), ({"kind": "sprint"}, "Art"),
                     ({"title": " "}, "Titel"), ({"hr_min": 130, "hr_max": 120, "steering": "heart_rate"}, "Puls")]:
        with pytest.raises(ValueError, match=msg):
            bike_plan.update_session(sid, bad)


def test_create_copy_conflict_delete(db):
    plan_id = _import()["id"]
    sat = START + timedelta(days=5)
    new = bike_plan.create_session(plan_id, sat, copy_from=_sid(START + timedelta(days=1)))
    s = _find(_overview(), sat)
    assert s["id"] == new and s["title"] == "Sweet Spot 2 × 8" and s["week"] == 1
    with pytest.raises(bike_plan.Conflict):
        bike_plan.create_session(plan_id, sat)
    blank = bike_plan.create_session(plan_id, START + timedelta(days=6))
    assert _find(_overview(), START + timedelta(days=6))["steering"] == "heart_rate" and blank
    assert bike_plan.delete_session(new) and not bike_plan.delete_session(new)


def test_briefing_line(db):
    _import()
    line = bike_plan.briefing_line(START + timedelta(days=1))
    assert line.startswith("RAD-PLAN HEUTE (Woche 1, Eingewöhnung): Sweet Spot 2 × 8")
    assert "2× Sweet Spot 8 min bei 176–184 W" in line and "FTP 200 W" in line
    assert "nach Puls 115–125 bpm" in bike_plan.briefing_line(START)
    assert bike_plan.briefing_line(START + timedelta(days=5)).endswith("keine Einheit (Ruhetag).")
    assert bike_plan.briefing_line(START - timedelta(days=1)) is None


def test_editor_api(db):
    app = FastAPI()
    app.include_router(bike_plan_api.router)
    http = TestClient(app)
    http.post("/bike-plan", files={"file": ("p.json", json.dumps(plan_json()).encode())})
    sid = http.get("/bike-plan").json()["weeks"][0]["sessions"][0]["id"]
    assert http.put(f"/bike-plan/session/{sid}", json={"title": "Neu"}).json()["weeks"][0]["sessions"][0]["title"] == "Neu"
    assert http.put(f"/bike-plan/session/{sid}", json={"kind": "sprint"}).status_code == 422
    assert http.put("/bike-plan/session/999999", json={"title": "x"}).status_code == 404
    sat = (START + timedelta(days=5)).isoformat()
    assert http.post("/bike-plan/session", json={"day": sat}).status_code == 200
    assert http.post("/bike-plan/session", json={"day": sat}).status_code == 409
    gym = http.put("/bike-plan/gym", json={"day": sat, "label": "Gym Beine"}).json()
    assert next(d for d in gym["weeks"][0]["days"] if d["date"] == sat)["gym"] == "Gym Beine"
    assert http.delete(f"/bike-plan/session/{sid}").status_code == 200
    assert http.delete(f"/bike-plan/session/{sid}").status_code == 404
