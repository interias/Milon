from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import hero
from app.api import hero as hero_api
from app.checkins import CheckIn
from app.models import ExerciseSession, RunBestEffort, StepsDaily, Workout, WorkoutSet

TODAY = date(2026, 10, 16)  # Freitag


@pytest.fixture
def hero_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'hero.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(hero, "engine", engine)
    monkeypatch.setattr(hero, "_achievement_xp", lambda: [])
    monkeypatch.setattr(hero, "_strength_series", lambda: [])
    monkeypatch.setattr(hero, "_protein_days", lambda: {})
    monkeypatch.setattr(hero, "_protein_target", lambda: None)
    monkeypatch.setattr(hero, "_streak", lambda: 0)
    yield engine
    engine.dispose()


def add_run(session, started, km=8.0, minutes=48, hr=140, ext=None):
    session.add(ExerciseSession(exercise_type=33, started_at=started, ended_at=started + timedelta(minutes=minutes),
                                distance_km=km, avg_hr=hr, max_hr=hr + 20, external_id=ext or f"run-{started}"))


def runs_frame(rows):
    df = pd.DataFrame(rows)
    df["started_at"] = pd.to_datetime(df["started_at"])
    df["day"] = df["started_at"].dt.date
    df["key"] = df["external_id"]
    return df


def test_level_curve_titles_and_cap():
    assert hero.level_for(0)["level"] == 1 and hero.level_for(999)["level"] == 1
    lv = hero.level_for(1000)
    assert (lv["level"], lv["floor"], lv["next"]) == (2, 1000, 2025)
    assert hero.level_for(10**9)["level"] == hero.MAX_LEVEL and hero.level_for(10**9)["title"] == "Mythos"


def test_ledger_rested_bonus_and_weekly_diminishing():
    monday = date(2026, 10, 5)
    runs = runs_frame([{"external_id": f"r{i}", "started_at": datetime(2026, 10, 5 + i, 7), "distance_km": 5.0,
                        "dur_min": 30.0, "zone": 1} for i in range(5)])
    empty = pd.DataFrame(columns=["id", "started_at", "sets", "day"])
    book = hero.ledger(runs, empty, {}, {}, set(), [], monday + timedelta(days=6))
    xp = [round(e["xp"]) for e in book["entries"]]
    assert xp == [72, 72, 72, 72, 36]  # 30 min × 1,2 × 2; 5. Lauf der Woche halb
    assert all(e["bonus"] == 0 for e in book["entries"])  # vor dem ersten Lauf kein Ruhetag
    prog = hero.progression(book["entries"], book["daily"])
    assert len(prog) == 1 and prog[0]["laufen"] == 324 and prog[0]["xp"] == 324 and prog[0]["level"] == 1.32
    assert book["pool"] == 2 * hero.REST_PER_DAY  # Sa + So geruht
    # Zwei Krankheitstage laden den Bonus, der nächste Lauf wird verdoppelt.
    later = runs_frame([{"external_id": "a", "started_at": datetime(2026, 10, 12, 7), "distance_km": 5.0,
                         "dur_min": 30.0, "zone": 1},
                        {"external_id": "b", "started_at": datetime(2026, 10, 15, 7), "distance_km": 5.0,
                         "dur_min": 30.0, "zone": 1}])
    book = hero.ledger(later, empty, {}, {}, {date(2026, 10, 13), date(2026, 10, 14)}, [], date(2026, 10, 15))
    assert [round(e["bonus"]) for e in book["entries"]] == [0, 72]


def test_class_and_spec_from_ninety_days():
    d = date(2026, 10, 16)
    runs = runs_frame([{"external_id": f"r{i}", "started_at": datetime(2026, 9, 1) + timedelta(days=3 * i),
                        "distance_km": 6.0, "dur_min": 40.0, "zone": 1} for i in range(10)])
    daily = {r.day: {"laufen": 96.0, "kraft": 0.0, "alltag": 5.0, "erfolge": 0, "ruhebonus": 0} for r in runs.itertuples()}
    c = hero.classify(daily, runs, d)
    assert c["class"] == "jaeger" and c["spec"] == "ausdauer"
    for i in range(8):
        daily[date(2026, 9, 2) + timedelta(days=3 * i)] = {"laufen": 0, "kraft": 400.0, "alltag": 0, "erfolge": 0, "ruhebonus": 0}
    assert hero.classify(daily, runs, d)["class"] == "krieger"
    assert hero.classify({}, runs.iloc[:0], d)["class"] == "moench"


def test_drop_rarity_rules_and_deterministic_items():
    base = {"external_id": "x", "started_at": pd.Timestamp("2026-10-16 07:00"), "distance_km": 8.0,
            "dur_min": 48.0, "ef": 1.2, "zone": 1}
    prior = runs_frame([{**base, "external_id": f"p{i}", "started_at": pd.Timestamp("2026-10-01") + pd.Timedelta(days=i),
                         "ef": 1.0 + i / 100} for i in range(5)])
    efforts = pd.DataFrame([
        {"external_id": "p0", "distance_m": 5000, "seconds": 1700.0, "started_at": pd.Timestamp("2026-10-01")},
        {"external_id": "x", "distance_m": 5000, "seconds": 1650.0, "started_at": pd.Timestamp("2026-10-16 07:00")}])
    run = pd.Series(base)
    assert hero.drop_rarity(run, prior, efforts)[0] == "orange"
    assert hero.drop_rarity(run, prior, efforts.iloc[:1])[0] == "blau"  # EF über dem 75. Perzentil
    assert hero.drop_rarity(pd.Series({**base, "distance_km": 2.5}), prior, efforts)[0] == "grau"
    assert hero.drop_rarity(pd.Series({**base, "distance_km": 21.2, "dur_min": 130}), prior, efforts)[0] == "rot"
    a = hero.make_item(hero._rng("drop", "x"), "blau", datetime(2026, 10, 16, 7), 1, 40, "beute", "")
    b = hero.make_item(hero._rng("drop", "x"), "blau", datetime(2026, 10, 16, 7), 1, 40, "beute", "")
    assert a == b and a["rarity_label"] == "Selten"


def test_vault_drops_and_claim_flow(hero_db):
    with Session(hero_db) as session:
        session.add(hero.HeroState(key="start", value="2026-10-05"))
        for day in (5, 7, 9):  # Woche 05.–11.10.: 3 Läufe → Slots 1 und 2
            add_run(session, datetime(2026, 10, day, 7))
        add_run(session, datetime(2026, 10, 13, 7))  # aktuelle Woche: 1 Lauf
        for day in (14, 15):
            session.add(CheckIn(day=date(2026, 10, day), sick=True, updated_at=datetime(2026, 10, day)))
        session.add(StepsDaily(day=date(2026, 10, 6), steps=11000))
        w = Workout(started_at=datetime(2026, 10, 8, 18), source="hevy")
        session.add(w)
        session.commit()
        session.add(WorkoutSet(workout_id=w.id, exercise="Squat", set_type="normal", weight_kg=80, reps=5))
        session.commit()
    o = hero.overview(TODAY)
    assert len([i for i in o["inventory"] if i["source"] == "beute"]) == 4
    assert o["hero"]["class"] in hero.CLASSES and o["hero"]["level"] >= 1
    cur = o["vault"]["current"]
    assert cur["sick_days"] == 2 and [s["threshold"] for s in cur["slots"]] == [1, 2, 3]  # Krankheit senkt Schwellen
    past = o["vault"]["claimable"][0]
    assert past["week"] == "2026-10-05" and [s["unlocked"] for s in past["slots"]] == [True, True, False]
    assert o["vault"]["veteran"] is not None

    app = FastAPI()
    app.include_router(hero_api.router)
    client = TestClient(app)
    hero_today = hero.local_today
    try:
        hero.local_today = lambda: TODAY
        assert client.post("/hero/vault/claim", json={"week": "2026-10-05", "slot": 2}).status_code == 422
        assert client.post("/hero/vault/claim", json={"week": "2026-10-12", "slot": 0}).status_code == 422
        item = client.post("/hero/vault/claim", json={"week": "2026-10-05", "slot": 1}).json()["item"]
        assert item == past["slots"][1]["item"]
        assert client.post("/hero/vault/claim", json={"week": "2026-10-05", "slot": 0}).status_code == 409
        assert client.post("/hero/vault/claim", json={"week": "veteran", "slot": 2}).status_code == 200
        after = hero.overview(TODAY)
    finally:
        hero.local_today = hero_today
    assert after["vault"]["claimable"] == [] and after["vault"]["veteran"] is None
    assert {i["source"] for i in after["inventory"]} == {"beute", "truhe", "veteran"}
    assert any(e["kind"] == "truhe" for e in after["log"])


def test_equip_unequip_and_best(hero_db, monkeypatch):
    monkeypatch.setattr(hero, "local_today", lambda: TODAY)
    with Session(hero_db) as session:
        session.add(hero.HeroState(key="start", value="2026-10-01"))
        for day in range(1, 15):
            add_run(session, datetime(2026, 10, day, 7), km=5 + day % 4)
        session.commit()
    items = hero.overview(TODAY)["inventory"]
    assert items and not any(it["equipped"] for it in items)
    app = FastAPI()
    app.include_router(hero_api.router)
    client = TestClient(app)
    first = items[-1]
    assert client.post("/hero/equip", json={"item_id": first["id"]}).status_code == 200
    o = hero.overview(TODAY)
    assert o["equipment"][first["slot"]]["id"] == first["id"] and o["ilvl_avg"] == first["ilvl"]
    assert client.post("/hero/equip", json={"item_id": "drop:unbekannt"}).status_code == 404
    best = client.post("/hero/equip-best").json()["equipped"]
    o = hero.overview(TODAY)
    for slot, item_id in best.items():
        top = max((it for it in o["inventory"] if it["slot"] == slot), key=lambda it: it["ilvl"])
        assert item_id == top["id"] and o["equipment"][slot]["equipped"]
    assert client.post("/hero/unequip", json={"slot": first["slot"]}).status_code == 200
    assert first["slot"] not in hero.overview(TODAY)["equipment"]
    assert client.post("/hero/unequip", json={"slot": "flügel"}).status_code == 404


def test_day_buffs_and_focus_bonus():
    buffs = hero.day_buffs({date(2026, 10, 5): 150.0, date(2026, 10, 6): 80.0}, 140.0,
                           {date(2026, 10, 6): 450.0, date(2026, 10, 7): 300.0})
    assert buffs == {date(2026, 10, 6): {"wohlgenaehrt", "erholt"}}  # Protein vom Vortag, Nacht ≥ 7 h
    runs = runs_frame([{"external_id": "a", "started_at": datetime(2026, 10, 6, 7), "distance_km": 5.0, "dur_min": 30.0, "zone": 1},
                       {"external_id": "b", "started_at": datetime(2026, 10, 8, 7), "distance_km": 5.0, "dur_min": 30.0, "zone": 1}])
    empty = pd.DataFrame(columns=["id", "started_at", "sets", "day"])
    mods = hero.Mods(buffs, [{"from": "2026-10-07", "value": "ausdauer"}])
    book = hero.ledger(runs, empty, {}, {}, set(), [], date(2026, 10, 8), mods)
    a, b = book["entries"]
    assert round(a["xp"], 1) == round(72 * 1.10, 1)  # zwei Daten-Buffs, Fokus erst ab 07.10.
    assert round(b["xp"], 1) == round(72 * 1.10, 1) and b["bonus"] > 0  # Fokus +10 %, dazu Ruhebonus
    assert round(book["totals"]["buffs"], 1) == 7.2 and round(book["totals"]["fokus"], 1) == 7.2


def test_choose_spec_and_buffs(hero_db, monkeypatch):
    monkeypatch.setattr(hero, "local_today", lambda: TODAY)
    with Session(hero_db) as session:
        for day in range(1, 15):
            add_run(session, datetime(2026, 10, day, 7))
        session.add(CheckIn(day=TODAY, sick=True, updated_at=datetime(2026, 10, 16)))
        session.commit()
    app = FastAPI()
    app.include_router(hero_api.router)
    client = TestClient(app)
    assert client.post("/hero/spec", json={"spec": "zauberei"}).status_code == 422
    assert client.post("/hero/spec", json={"spec": "tempo"}).status_code == 200
    o = hero.overview(TODAY)
    assert o["hero"]["spec"] == "tempo" and o["hero"]["spec_chosen"] == "tempo"
    keys = {b["key"] for b in o["buffs"]}
    assert {"krank", "fokus"} <= keys
    client.post("/hero/spec", json={"spec": None})
    o = hero.overview(TODAY)
    assert o["hero"]["spec_chosen"] is None and o["hero"]["spec"] == o["hero"]["spec_auto"]


def test_week_quests_progress_halving_and_pick():
    from app import hero_quests
    week = date(2026, 10, 12)
    assert hero_quests.pick(week, "tempo", None) == hero_quests.pick(week, "tempo", None)
    assert len(hero_quests.pick(week, None, "kraft")) == 4
    runs = runs_frame([{"external_id": f"r{i}", "started_at": datetime(2026, 10, 12 + i, 7), "distance_km": 11.0,
                        "dur_min": 66.0, "zone": 1} for i in range(3)])
    data = {"runs": runs, "workouts": pd.DataFrame(columns=["id", "started_at", "sets", "day"]), "steps": {},
            "sick": set(), "protein": {}, "protein_target": None, "sleep": {}}
    monkey = hero_quests.pick
    try:
        hero_quests.pick = lambda w, s, e: ["lang1", "km20", "laeufe3"]
        wk = hero_quests.week_quests(week, None, None, data, date(2026, 10, 16))
        assert [q["done_on"] for q in wk["quests"]] == ["2026-10-12", "2026-10-13", "2026-10-14"] and wk["complete"]
        sick = {**data, "sick": {date(2026, 10, d) for d in (15, 16, 17)}}
        wk = hero_quests.week_quests(week, None, None, {**sick, "runs": runs.iloc[:1]}, date(2026, 10, 16))
        assert wk["halved"] and [q["target"] for q in wk["quests"]] == [1, 10, 2]
    finally:
        hero_quests.pick = monkey


def test_talent_effects_and_api(hero_db, monkeypatch):
    mods = hero.Mods(talents={10: [{"from": "2026-10-01", "value": "morgen"}], 30: [{"from": "2026-10-01", "value": "langer_atem"}]})
    early = pd.Series({"started_at": pd.Timestamp("2026-10-06 07:00")})
    late = pd.Series({"started_at": pd.Timestamp("2026-10-06 19:00")})
    assert mods.run_talent(date(2026, 10, 6), early, False) == 0.10 and mods.run_talent(date(2026, 10, 6), late, False) == 0.0
    assert mods.rest_cap(date(2026, 10, 6)) == 360 and mods.rest_cap(date(2026, 9, 30)) == hero.REST_CAP
    monkeypatch.setattr(hero, "local_today", lambda: TODAY)
    app = FastAPI()
    app.include_router(hero_api.router)
    client = TestClient(app)
    assert client.post("/hero/talent", json={"row": 10, "choice": "flugmodus"}).status_code == 422
    assert client.post("/hero/talent", json={"row": 10, "choice": "morgen"}).status_code == 409  # Stufe 1
    monkeypatch.setattr(hero, "_load", lambda today: {"level": 12})
    assert client.post("/hero/talent", json={"row": 10, "choice": "morgen"}).status_code == 200
    assert hero._active(hero._history("talent_10"), TODAY) == "morgen"


def test_month_bosses_and_dungeons():
    from app import hero_bosses
    rows = [{"external_id": "old", "started_at": datetime(2026, 9, 10, 7), "distance_km": 12.0, "dur_min": 72.0, "zone": 1},
            {"external_id": "old2", "started_at": datetime(2026, 9, 20, 7), "distance_km": 10.0, "dur_min": 62.0, "zone": 1},
            {"external_id": "fast", "started_at": datetime(2026, 10, 5, 7), "distance_km": 13.5, "dur_min": 76.0, "zone": 1}]
    runs = runs_frame(rows)
    runs["pace"] = runs["dur_min"] / runs["distance_km"]
    efforts = pd.DataFrame([
        {"external_id": "old", "distance_m": 5000, "seconds": 1800.0, "started_at": pd.Timestamp("2026-09-10 07:00")},
        {"external_id": "fast", "distance_m": 5000, "seconds": 1760.0, "started_at": pd.Timestamp("2026-10-05 07:00")}])
    data = {"runs": runs, "workouts": pd.DataFrame(columns=["id", "started_at", "sets", "day"]), "efforts": efforts,
            "sick": set()}
    bosses = {b["key"]: b for b in hero_bosses.month_bosses(date(2026, 10, 1), data, TODAY)}
    assert bosses["waechter"]["defeated_on"] == "2026-10-05"  # 29:20 < 30:00 × 0,98
    assert bosses["wyrm"]["defeated_on"] == "2026-10-05"  # 13,5 km ≥ 12 + 1
    assert not bosses["fresser"]["defeated"] and 0 < bosses["fresser"]["hp"] < 1
    sick = {**data, "sick": {date(2026, 10, d) for d in range(1, 17)}}
    assert hero_bosses.month_bosses(date(2026, 10, 1), sick, TODAY)[2]["goal"] == "19 km im Monat"  # 40 × 15/31
    dg = hero_bosses.dungeons(runs, date(2026, 10, 1))
    assert len(dg) == 1 and dg[0]["tier"] == "normal" and dg[0]["cleared"]
    assert [b["name"] for b in dg[0]["bosses"]] == ["Torwächter", "Hallenfürst", "Der Unermüdliche", "Schatten des Tempos"]


def test_reputation_titles_and_sets():
    from app import hero_social
    stats = {"laufen": 9500, "kraft": 31000, "protein_days": 10, "sleep_nights": 0}
    rep = {f["key"]: f for f in hero_social.reputation(stats)}
    assert rep["laeufergilde"]["standing"] == "Wohlwollend" and rep["eisenbund"]["standing"] == "Ehrfürchtig"
    assert rep["tafelrunde"]["value"] == 500 and rep["orden"]["progress"] == 0.0
    titles = {t["key"]: t for t in hero_social.titles({"km": 520, "level": 12}, "kilometerfresser")}
    assert titles["kilometerfresser"]["earned"] and titles["kilometerfresser"]["chosen"]
    assert not titles["held_von_wesel"]["earned"] and titles["held_von_wesel"]["value"] == 12
    items = [{"set": "des Morgengrauens", "slot": s, "equipped": True} for s in ("kopf", "brust")] + \
            [{"set": "der Nacht", "slot": "ring", "equipped": False}]
    sets = hero_social.sets(items)
    assert sets[0]["suffix"] == "des Morgengrauens" and sets[0]["bonus"] == "Aura" and sets[1]["bonus"] is None


def test_disenchant_upgrade_and_title(hero_db, monkeypatch):
    monkeypatch.setattr(hero, "local_today", lambda: TODAY)
    with Session(hero_db) as session:
        session.add(hero.HeroState(key="start", value="2026-10-01"))
        for day in range(1, 15):
            add_run(session, datetime(2026, 10, day, 7), km=5 + day % 4)
        session.commit()
    app = FastAPI()
    app.include_router(hero_api.router)
    client = TestClient(app)
    items = sorted(hero.overview(TODAY)["inventory"], key=lambda it: it["ilvl"])
    worn, junk, keep = items[0], items[1], items[-1]
    client.post("/hero/equip", json={"item_id": worn["id"]})
    assert client.post("/hero/disenchant", json={"item_id": worn["id"]}).status_code == 409  # angelegt
    assert client.post("/hero/upgrade", json={"item_id": keep["id"]}).status_code == 409  # kein Staub
    gained = sum(client.post("/hero/disenchant", json={"item_id": it["id"]}).json()["dust"]
                 for it in items[1:-1] if it["slot"] != worn["slot"] or it["id"] != worn["id"])
    o = hero.overview(TODAY)
    assert o["dust"] == gained and junk["id"] not in {it["id"] for it in o["inventory"]}
    if gained >= 10:
        up = client.post("/hero/upgrade", json={"item_id": keep["id"]}).json()["item"]
        assert up["ilvl"] == keep["ilvl"] + hero.UPGRADE_ILVL and hero.overview(TODAY)["dust"] == gained - 10
    assert client.post("/hero/title", json={"key": "held_von_wesel"}).status_code == 409
    assert client.post("/hero/title", json={"key": "gibtsnicht"}).status_code == 422
    assert client.post("/hero/title", json={"key": None}).status_code == 200
