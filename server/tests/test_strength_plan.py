from datetime import date, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.metrics import strength_plan as sp
from app.models import Workout, WorkoutSet

TODAY = date(2026, 11, 2)
ROW = next(ex for p in sp.PLANS for ex in p.exercises if ex.key == "row")
SKULL = next(ex for p in sp.PLANS for ex in p.exercises if ex.key == "skull")


def _session(day, sets):
    return {"date": day, "sets": sets}


def test_select_ladder_uses_drop_weights():
    ladder = sp._select(40)
    assert ladder.up(54) == 56.5
    assert ladder.up(59) == 61
    assert ladder.down(54) == 52
    assert ladder.floor(36) == 35.5


def test_increase_when_all_sets_at_top_on_target_rpe():
    s = sp.suggest(ROW, [_session(TODAY - timedelta(days=3), [(54, 12, 8), (54, 12, 8), (54, 12, 9)])], TODAY)
    assert s["action"] == "increase"
    assert s["weight_kg"] == 56.5
    work = [x for x in s["sets"] if x["type"] == "normal"]
    assert [x["rpe"] for x in work] == [8, 8, 9]
    assert all(8 <= x["reps"] <= 12 for x in work)
    assert s["sets"][0]["type"] == "warmup"


def test_failure_reps_are_converted_to_target_rpe():
    # 12 Wdh. bei RPE 10 ≈ 10 Wdh. bei RPE 8 → kein Steigern, halten mit +1.
    s = sp.suggest(ROW, [_session(TODAY - timedelta(days=3), [(54, 12, 10), (54, 12, 10), (54, 12, 10)])], TODAY)
    assert s["action"] == "hold"
    assert [x["reps"] for x in s["sets"] if x["type"] == "normal"] == [11, 11, 12]


def test_missing_rpe_needs_reps_above_top():
    at_top = [_session(TODAY - timedelta(days=3), [(54, 12, None)] * 3)]
    above = [_session(TODAY - timedelta(days=3), [(54, 13, None)] * 3)]
    assert sp.suggest(ROW, at_top, TODAY)["action"] == "hold"
    assert sp.suggest(ROW, above, TODAY)["action"] == "increase"


def test_decrease_when_a_set_falls_below_range():
    s = sp.suggest(ROW, [_session(TODAY - timedelta(days=3), [(61, 10, 8), (61, 9, 8), (61, 6, 9)])], TODAY)
    assert s["action"] == "decrease"
    assert s["weight_kg"] == 59


def test_long_pause_steps_down_and_stale_starts_from_e1rm():
    paused = sp.suggest(ROW, [_session(TODAY - timedelta(days=30), [(54, 10, 8)] * 3)], TODAY)
    assert paused["action"] == "pause" and paused["weight_kg"] == 52
    stale = sp.suggest(ROW, [_session(TODAY - timedelta(days=120), [(61, 10, 10)] * 3)], TODAY)
    assert stale["action"] == "start" and stale["weight_kg"] < 61
    assert sp.suggest(ROW, [], TODAY)["action"] == "new"


def test_plateau_after_three_plan_sessions_without_gain():
    days = [sp.PLAN_START + timedelta(days=d) for d in (0, 4, 8)]
    sessions = [_session(d, [(54, 10, 8), (54, 10, 8), (54, 9, 9)]) for d in days]
    s = sp.suggest(ROW, sessions, days[-1] + timedelta(days=3))
    assert s["action"] == "deload" and s["weight_kg"] == 52


def test_failure_last_targets_rpe_10_without_warmup():
    s = sp.suggest(SKULL, [_session(TODAY - timedelta(days=3), [(25, 14, 8), (25, 14, 10)])], TODAY)
    assert [x["rpe"] for x in s["sets"]] == [8, 10]
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
        # Diese Woche einmal OK (mit Template-IDs): OK und UK haben je eine Einheit offen.
        _workout(s, "a", datetime(2026, 11, 2, 16), [
            ("Rudern sitzend (Maschine)", "1DF4A847", "warmup", 40, 12, None),
            ("Rudern sitzend (Maschine)", "1DF4A847", "normal", 54, 12, 8),
            ("MTS Incline Press", "806def2a-0d7f-4b99-a200-893c01b6e00d", "normal", 60, 10, 8),
        ])
        # Altbestand ohne Template-ID (englischer Name) zählt über den Namen.
        _workout(s, "b", datetime(2026, 10, 28, 16), [
            ("Leg Press (Machine)", None, "normal", 153, 13, 8),
            ("Lying Leg Curl (Machine)", None, "normal", 46, 15, 9),
        ])
        s.commit()
    r = sp.next_training(date(2026, 11, 4))
    ok, uk = r["plans"]
    assert (ok["done"], uk["done"]) == (1, 0)
    assert r["next"] == "ok"  # Gleichstand offener Einheiten → Oberkörper zuerst
    legpress = next(e for e in uk["exercises"] if e["key"] == "legpress")
    assert legpress["last"]["date"] == "2026-10-28"
    assert uk["last_date"] == "2026-10-28"
