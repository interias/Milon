from datetime import date, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.metrics import strength_plan as sp
from app.models import Workout, WorkoutSet

TODAY = date(2026, 11, 2)
ROW = next(ex for p in sp.PLANS for ex in p.exercises if ex.key == "row")
SKULL = next(ex for p in sp.PLANS for ex in p.exercises if ex.key == "skull")
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
    assert [x["rpe"] for x in work] == [8, 9, 10]  # RIR bleibt als Leitplanke
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


def test_rir_falls_across_sets_with_rdl_and_four_set_exceptions():
    assert sp._targets(ROW) == [8, 9, 10]
    assert sp._targets(LATERAL) == [8, 9, 9, 10]
    assert sp._targets(RDL) == [8, 9, 9, 9]


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


def test_superset_isolation_two_sets_without_warmup():
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
        # Diese Woche einmal OK A (mit Template-IDs, ohne eigene Übung → erste Variante): OK B und UK offen.
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
    ok, ok_b, uk = r["plans"]
    assert (ok["done"], ok_b["done"], uk["done"]) == (1, 0, 0)
    assert ok_b["program"] == "ok" and uk["program"] == "uk"
    assert r["next"] == "ok_b"  # Gleichstand offener Einheiten → Oberkörper B vor Unterkörper
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
    assert v["Seitliche Schulter"]["planned"] == 8 and v["Gesäß"]["planned"] == 6


def test_classify_tells_upper_body_variants_apart(plan_db):
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
    kinds = sp._classify(sp._read_sets())
    assert sorted(kinds.values()) == ["ok", "ok_b", "uk"]


def test_upper_body_b_has_five_mts_sets_and_face_pulls():
    b = next(p for p in sp.PLANS if p.key == "ok_b")
    keys = [ex.key for ex in b.exercises]
    assert "fly" not in keys and "rear_fly" not in keys and "face_pull" in keys
    assert next(ex for ex in b.exercises if ex.key == "mts").sets == 5
    uk = next(p for p in sp.PLANS if p.key == "uk")
    assert next(ex for ex in uk.exercises if ex.key == "legcurl").templates == ("11A123F3",)


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
