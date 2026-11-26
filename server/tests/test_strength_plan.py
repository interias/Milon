from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.metrics import strength_plan as sp
from app.models import Workout, WorkoutSet

TODAY = date(2026, 11, 2)
# Regel-Tests mit fester Satzzahl, unabhängig von der Plan-Zusammenstellung.
ROW = replace(next(ex for p in sp.PLANS for ex in p.exercises if ex.key == "row"), sets=3)
SKULL = replace(next(ex for p in sp.PLANS for ex in p.exercises if ex.key == "skull"), sets=2, reps=(10, 15))
RDL = next(ex for p in sp.PLANS for ex in p.exercises if ex.key == "rdl")
LATERAL = next(ex for p in sp.PLANS for ex in p.exercises if ex.key == "lateral")


def _session(day, sets):
    return {"date": day, "sets": sets}


def test_select_ladder_uses_drop_weights():
    ladder = sp._select(40)
    assert ladder.up(54) == 56.5
    assert ladder.up(59) == 61
    assert ladder.down(54) == 52
    assert ladder.floor(36) == 35.5


def test_increase_when_all_sets_reach_target_reps():
    s = sp.suggest(ROW, [_session(TODAY - timedelta(days=3), [(54, 12, 10), (54, 12, 10), (54, 12, 10)])], TODAY)
    assert s["action"] == "increase"
    assert s["weight_kg"] == 56.5
    work = [x for x in s["sets"] if x["type"] == "normal"]
    assert [x["rpe"] for x in work] == [8, 8, 9]  # RIR bleibt als Leitplanke
    assert [x["reps"] for x in work] == [12, 12, 12]
    assert s["sets"][0]["type"] == "warmup"
    assert s["rule"]["lines"][0] == "Schwerer: alle 3 Sätze ≥ 12 Wdh. → 59 kg"


def test_rpe_does_not_change_the_decision():
    easy = sp.suggest(ROW, [_session(TODAY - timedelta(days=3), [(54, 12, 6)] * 3)], TODAY)
    blank = sp.suggest(ROW, [_session(TODAY - timedelta(days=3), [(54, 12, None)] * 3)], TODAY)
    assert easy["action"] == blank["action"] == "increase"


def test_hold_until_every_set_reaches_target():
    s = sp.suggest(ROW, [_session(TODAY - timedelta(days=3), [(61, 12, 9), (61, 12, 10), (61, 10, 10)])], TODAY)
    assert s["action"] == "hold" and s["weight_kg"] == 61
    assert [x["reps"] for x in s["sets"] if x["type"] == "normal"] == [12, 12, 12]
    assert "2 von 3 Sätzen ≥ 12 Wdh." in s["reason"]
    assert s["last"]["hit"] == 2


def test_missing_sets_hold():
    s = sp.suggest(ROW, [_session(TODAY - timedelta(days=3), [(61, 12, 9), (61, 12, 10)])], TODAY)
    assert s["action"] == "hold" and "Nur 2 von 3" in s["reason"]


def test_rir_compounds_stop_at_one_isolation_goes_to_zero():
    assert sp._targets(ROW) == [8, 8, 9]
    assert sp._targets(RDL) == [8, 8, 9]
    legpress = next(ex for p in sp.PLANS for ex in p.exercises if ex.key == "legpress")
    assert sp._targets(legpress) == [8, 8, 8, 9]
    assert sp._targets(LATERAL) == [8, 9, 9, 10]
    assert sp._targets(SKULL) == [8, 10]
    compounds = {ex.key for p in sp.PLANS for ex in p.exercises if ex.last_rpe < 10}
    assert compounds == {"row", "mts", "pulldown", "legpress", "rdl", "chinup", "dip"}


def test_lateral_raise_targets_15_and_custom_rule_overrides():
    sessions = [_session(TODAY - timedelta(days=3), [(27.5, 17, 7.5), (27.5, 15, 8.5), (27.5, 15, 9.5), (27.5, 15, 10)])]
    assert sp.suggest(LATERAL, sessions, TODAY)["action"] == "increase"
    custom = sp.suggest(LATERAL, sessions, TODAY, rule=(10, 17))
    assert custom["action"] == "hold" and custom["rule"]["custom"] is True
    assert [x["reps"] for x in custom["sets"]] == [17] * 4


def test_decrease_when_a_set_falls_below_minimum():
    s = sp.suggest(ROW, [_session(TODAY - timedelta(days=3), [(61, 10, 8), (61, 9, 8), (61, 7, 9)])], TODAY)
    assert s["action"] == "decrease"
    assert s["weight_kg"] == 59


def test_long_pause_steps_down_and_stale_starts_from_e1rm():
    paused = sp.suggest(ROW, [_session(TODAY - timedelta(days=30), [(54, 10, 8)] * 3)], TODAY)
    assert paused["action"] == "pause" and paused["weight_kg"] == 52
    stale = sp.suggest(ROW, [_session(TODAY - timedelta(days=120), [(61, 10, 10)] * 3)], TODAY)
    assert stale["action"] == "start" and stale["weight_kg"] < 61
    assert sp.suggest(ROW, [], TODAY)["action"] == "new"


def test_isolation_two_sets_without_warmup():
    s = sp.suggest(SKULL, [_session(TODAY - timedelta(days=3), [(25, 14, 8), (25, 14, 10)])], TODAY)
    assert [x["rpe"] for x in s["sets"]] == [8, 10]
    assert [x["reps"] for x in s["sets"]] == [15, 15]
    assert all(x["type"] == "normal" for x in s["sets"])


@pytest.fixture
def plan_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'plan.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(sp, "engine", engine)
    return engine


def _workout(s, ext, when, rows):
    w = Workout(external_id=ext, title="x", started_at=when, source="hevy")
    s.add(w)
    s.flush()
    for i, (name, tid, typ, kg, reps, rpe) in enumerate(rows):
        s.add(WorkoutSet(workout_id=w.id, exercise=name, exercise_template_id=tid, set_index=i,
                         set_type=typ, weight_kg=kg, reps=reps, rpe=rpe))


def test_next_training_week_count_and_name_fallback(plan_db):
    with Session(plan_db) as s:
        # Diese Woche einmal Oberkörper (mit Template-IDs): 1 von 2 OK, UK und Arme offen.
        _workout(s, "a", datetime(2026, 11, 2, 16), [
            ("Rudern sitzend (Maschine)", "1DF4A847", "warmup", 40, 12, None),
            ("Rudern sitzend (Maschine)", "1DF4A847", "normal", 54, 12, 8),
            ("MTS Incline Press", "806def2a-0d7f-4b99-a200-893c01b6e00d", "normal", 60, 10, 8),
        ])
        # Altbestand ohne Template-ID (englischer Name) zählt über den Namen.
        _workout(s, "b", datetime(2026, 10, 28, 16), [
            ("Leg Press (Machine)", None, "normal", 153, 13, 8),
            ("Seated Leg Curl (Machine)", None, "normal", 46, 15, 9),
        ])
        s.commit()
    r = sp.next_training(date(2026, 11, 4))
    ok, uk, arme_a, arme_b = r["plans"]
    assert (ok["per_week"], ok["done"], uk["done"], arme_a["done"]) == (2, 1, 0, 0)
    assert arme_a["program"] == arme_b["program"] == "arme" and uk["program"] == "uk"
    assert r["next"] == "ok"  # Gleichstand offener Einheiten → erstes Programm (Oberkörper)
    legpress = next(e for e in uk["exercises"] if e["key"] == "legpress")
    assert legpress["last"]["date"] == "2026-10-28"
    assert uk["last_date"] == "2026-10-28"


def test_weekly_volume_counts_hard_sets_fractionally(plan_db):
    with Session(plan_db) as s:
        _workout(s, "a", datetime(2026, 11, 2, 16), [
            ("Rudern sitzend (Maschine)", "1DF4A847", "warmup", 40, 12, None),
            ("Rudern sitzend (Maschine)", "1DF4A847", "normal", 54, 12, 8),
            ("Rudern sitzend (Maschine)", "1DF4A847", "normal", 54, 12, 6),  # zu leicht: kein harter Satz
            ("Rudern sitzend (Maschine)", "1DF4A847", "normal", 54, 12, None),  # ohne RPE zählt
        ])
        _workout(s, "b", datetime(2026, 10, 20, 16), [
            ("Seitheben (Maschine)", "D5D0354D", "normal", 32, 12, 9),
        ])
        s.commit()
    v = {m["muscle"]: m for m in sp.weekly_volume(date(2026, 11, 4))["muscles"]}
    assert v["Rücken"]["this_week"] == 2 and v["Bizeps"]["this_week"] == 1
    assert v["Seitliche Schulter"]["avg_4w"] == 0.2  # 1 Satz in den 4 Wochen davor
    assert v["Seitliche Schulter"]["planned"] == 8 and v["Gesäß"]["planned"] == 5


def test_classify_tells_gym_and_home_apart(plan_db):
    with Session(plan_db) as s:
        _workout(s, "a", datetime(2026, 11, 2, 16), [
            ("Rudern sitzend (Maschine)", "1DF4A847", "normal", 54, 12, 8),
            ("Butterfly (Pec Deck)", "9DCE2D64", "normal", 82, 12, 9),
        ])
        _workout(s, "b", datetime(2026, 11, 4, 16), [
            ("MTS Incline Press", "806def2a-0d7f-4b99-a200-893c01b6e00d", "normal", 60, 10, 8),
            ("Face Pull", "BE640BA0", "normal", 30, 15, 9),
        ])
        _workout(s, "c", datetime(2026, 11, 5, 16), [
            ("Beinpresse (Maschine)", "C7973E0E", "normal", 153, 12, 8),
            ("Beinbeugen sitzend", "11A123F3", "normal", 61, 12, 9),
        ])
        s.commit()
        _workout(s, "d", datetime(2026, 11, 3, 18), [
            ("Chin Up", "29083183", "normal", None, 8, 8),
            ("Seated Incline Curl (Dumbbell)", "8BAB2735", "normal", 15, 12, 9),
        ])
        _workout(s, "e", datetime(2026, 11, 6, 18), [
            ("Skullcrusher (Barbell)", "875F585F", "normal", 30, 10, 9),
            ("Triceps Dip", "28BB4A95", "normal", None, 10, 8),
        ])
        s.commit()
    kinds = sp._classify(sp._read_sets())
    assert sorted(kinds.values()) == ["arme_a", "arme_b", "ok", "ok", "uk"]


def test_plans_match_the_weekly_split():
    by_key = {p.key: p for p in sp.PLANS}
    assert set(by_key) == {"ok", "uk", "arme_a", "arme_b"}
    ok = {ex.key: ex.sets for ex in by_key["ok"].exercises}
    assert ok == {"row": 4, "mts": 4, "pulldown": 4, "fly": 3, "lateral": 4, "face_pull": 4}
    assert by_key["ok"].per_week == 2
    assert [ex.key for ex in by_key["arme_a"].exercises] == ["chinup", "incline_curl", "oh_ext"]
    assert [ex.key for ex in by_key["arme_b"].exercises] == ["skull", "dip", "ez_curl"]
    assert next(ex for ex in by_key["uk"].exercises if ex.key == "legcurl").templates == ("11A123F3",)
    v = {m["muscle"]: m["planned"] for m in sp.weekly_volume(date(2026, 11, 4))["muscles"]}
    assert 10 <= v["Bizeps"] <= 20 and 10 <= v["Trizeps"] <= 20


CHIN = next(ex for p in sp.PLANS for ex in p.exercises if ex.key == "chinup")


def test_bodyweight_progresses_by_reps_only():
    hit = sp.suggest(CHIN, [_session(TODAY - timedelta(days=3), [(0, 10, 9), (0, 10, 9), (0, 10, 9)])], TODAY)
    assert hit["action"] == "increase" and hit["weight_kg"] is None and hit["bodyweight"]
    assert all(x["weight_kg"] is None for x in hit["sets"]) and len(hit["sets"]) == 3
    hold = sp.suggest(CHIN, [_session(TODAY - timedelta(days=3), [(0, 8, 9), (0, 6, 9), (0, 4, 10)])], TODAY)
    assert hold["action"] == "hold" and hold["last"]["reps"] == [8, 6, 4]
    assert sp.suggest(CHIN, [], TODAY)["action"] == "new"


def test_bodyweight_sets_without_weight_are_read(plan_db):
    with Session(plan_db) as s:
        _workout(s, "a", datetime(2026, 11, 3, 18), [
            ("Chin Up", "29083183", "normal", None, 8, 8),
            ("Chin Up", "29083183", "normal", None, 7, 9),
            ("Seated Incline Curl (Dumbbell)", "8BAB2735", "normal", 15, 12, 9),
        ])
        s.commit()
    plan = next(p for p in sp.next_training(date(2026, 11, 4))["plans"] if p["key"] == "arme_a")
    chin = next(e for e in plan["exercises"] if e["key"] == "chinup")
    assert chin["last"]["reps"] == [8, 7] and plan["done"] == 1


def test_rules_are_stored_used_and_reset(plan_db):
    with Session(plan_db) as s:
        _workout(s, "a", datetime(2026, 11, 2, 16), [
            ("Seitheben (Maschine)", "D5D0354D", "normal", 27.5, 15, 9),
            ("Seitheben (Maschine)", "D5D0354D", "normal", 27.5, 15, 9),
            ("Seitheben (Maschine)", "D5D0354D", "normal", 27.5, 15, 9),
            ("Seitheben (Maschine)", "D5D0354D", "normal", 27.5, 15, 10),
            ("Rudern sitzend (Maschine)", "1DF4A847", "normal", 54, 12, 8),
        ])
        s.commit()
    lateral = lambda: next(e for e in sp.next_training(date(2026, 11, 4))["plans"][0]["exercises"] if e["key"] == "lateral")
    assert lateral()["action"] == "increase"
    rule = sp.set_rule("lateral", 12, 18)
    assert rule["custom"] and rule["target_reps"] == 18
    assert lateral()["action"] == "hold"
    assert sp.reset_rule("lateral")["target_reps"] == 15
    assert lateral()["action"] == "increase"
    with pytest.raises(ValueError):
        sp.set_rule("lateral", 16, 15)
    with pytest.raises(KeyError):
        sp.set_rule("nope", 8, 12)
    assert {r["key"] for r in sp.rule_list()} >= {"row", "mts", "lateral", "face_pull", "legcurl"}


def test_rule_api(plan_db):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.put("/metrics/strength/rules/row", json={"min_reps": 6, "target_reps": 10}).json()["target_reps"] == 10
    assert c.put("/metrics/strength/rules/row", json={"min_reps": 12, "target_reps": 10}).status_code == 422
    assert c.put("/metrics/strength/rules/nope", json={"min_reps": 6, "target_reps": 10}).status_code == 404
    assert next(r for r in c.get("/metrics/strength/rules").json() if r["key"] == "row")["custom"] is True
    assert c.delete("/metrics/strength/rules/row").json()["custom"] is False
