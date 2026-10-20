"""Heldenreise I (#72): Indoor-Fahrten (Zwift/Rolle) geben Rad-EP, Beute, Truhen-Fortschritt und
erfüllen Ausdauer-Aufträge; ihr HC-Spiegel zählt nicht mehr als Alltag. Nur synthetische Fahrten auf
tmp_path-Datenbanken, nie Koordinaten."""
import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import garmin_indoor, hero, hero_events, hero_quests
from app.config import settings
from app.garmin_indoor import GarminIndoorRide
from app.metrics import cycling, health
from app.models import ExerciseSession

TODAY = date(2026, 11, 8)       # Sonntag; Woche ab 2026-11-02 liegt hinter ENDURANCE_FROM
START = date(2026, 11, 2)


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'indoor_hero.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for mod in (hero, cycling, health, garmin_indoor):
        monkeypatch.setattr(mod, "engine", engine)
    for name, fn in (("_achievement_xp", lambda: []), ("_strength_series", lambda: []), ("_protein_days", lambda: {}),
                     ("_protein_target", lambda: None), ("_streak", lambda: 0)):
        monkeypatch.setattr(hero, name, fn)
    monkeypatch.setattr(hero.hero_world, "world", lambda: {"available": False})
    monkeypatch.setattr(settings, "bike_ftp", 200.0)
    monkeypatch.setattr(settings, "run_hr_max", 180.0)
    with Session(engine) as s:
        from app.hero import HeroState
        s.add(HeroState(key="start", value=START.isoformat()))
        s.commit()
    yield engine
    engine.dispose()


def add_ride(engine, aid, start: datetime, minutes=60, power=140.0, hr=130.0, hr_valid=True, km=None,
             elevation=150.0, curve=None, world="Watopia", kind="virtual_ride"):
    with Session(engine) as s:
        s.add(GarminIndoorRide(
            activity_id=aid, activity_type=kind, title=f"Zwift - Route in {world}", world=world, started_at=start,
            duration_seconds=minutes * 60.0, elapsed_duration_seconds=minutes * 60.0,
            distance_km=km if km is not None else minutes * 0.5, elevation_gain_m=elevation,
            avg_power_w=power, norm_power_w=power, work_kj=power * minutes * 60 / 1000 if power else None,
            avg_hr=hr, max_hr=hr + 20 if hr else None, hr_valid=hr_valid,
            power_curve_json=json.dumps(curve if curve is not None else ({"5": power + 100, "60": power + 30, "300": power + 10,
                                                                          "1200": power} if power else {})),
            synced_at=datetime(2026, 11, 8)))
        s.commit()


def add_session(engine, kind, start: datetime, minutes, km=None, hr=140, ext=None):
    with Session(engine) as s:
        s.add(ExerciseSession(exercise_type=kind, started_at=start, ended_at=start + timedelta(minutes=minutes),
                              distance_km=km, avg_hr=hr, max_hr=hr + 20 if hr else None, external_id=ext or f"{kind}-{start}"))
        s.commit()


def runs_frame(rows):
    df = pd.DataFrame(rows)
    df["started_at"] = pd.to_datetime(df["started_at"])
    df["day"] = df["started_at"].dt.date
    df["key"] = df["external_id"]
    return df


def rides_frame(rows):
    base = {"activity_id": "x", "dur_min": 60.0, "zone": 1, "power_zone": 2, "km": 30.0, "elevation_m": 100.0,
            "kj": 500.0, "np": 140.0, "avg_hr": 130.0, "ef": 1.0, "eftp": 200.0, "power_curve": {}, "world": "Watopia",
            "has_power": True}
    df = pd.DataFrame([{**base, **r} for r in rows], columns=[*base, "started_at"])
    df["started_at"] = pd.to_datetime(df["started_at"])
    df["day"] = df["started_at"].dt.date
    df["key"] = "ride:" + df["activity_id"].astype(str)
    return df


# --- EP --------------------------------------------------------------------------------------
def test_ride_xp_from_power_zone_else_hr_zone(db):
    add_ride(db, "z2", datetime(2026, 11, 3, 18), minutes=60, power=140)                  # NP/eFTP 0,70 → Coggan Z2 → 1,2
    add_ride(db, "z6", datetime(2026, 11, 4, 18), minutes=30, power=250)                  # 1,25 → Z6 → Hart 1,8
    add_ride(db, "hr", datetime(2026, 11, 5, 18), minutes=40, power=None, hr=150)        # ohne Watt: 150/180 → Z3 → 1,5
    add_ride(db, "none", datetime(2026, 11, 6, 18), minutes=50, power=None, hr=150, hr_valid=False)  # nichts → 1,1
    rides = hero._indoor_rides(180.0)
    assert [None if pd.isna(z) else int(z) for z in rides["power_zone"]] == [2, 6, None, None]
    data = hero._load(TODAY)
    xp = {e["ref"]: e["xp"] for e in data["entries"] if e["kind"] == "rad"}
    assert xp == pytest.approx({"ride:z2": 60 * 2 * 1.2, "ride:z6": 30 * 2 * 1.8, "ride:hr": 40 * 2 * 1.5,
                                "ride:none": 50 * 2 * 1.1})
    assert data["book"]["totals"]["rad"] == pytest.approx(sum(xp.values()))
    assert data["book"]["totals"]["laufen"] == 0
    assert any(p["rad"] > 0 for p in hero.progression(data["entries"], data["book"]["daily"]))


def test_shared_weekly_counter_and_rest_bonus():
    day = lambda i, h=7: f"2026-11-0{2 + i} {h:02d}:00"
    runs = runs_frame([{"external_id": f"r{i}", "started_at": day(i), "distance_km": 8.0, "dur_min": 50.0, "zone": 1}
                       for i in range(4)])
    rides = rides_frame([{"activity_id": "late", "started_at": day(3, 18), "dur_min": 50.0, "zone": 1},
                         {"activity_id": "early", "started_at": day(3, 5), "dur_min": 50.0, "zone": 1}])
    book = hero.ledger(runs, runs.iloc[0:0].assign(sets=[]), {}, {}, set(), [], date(2026, 11, 5), rides=rides)
    order = [(e["ref"], e["xp"]) for e in book["entries"] if e["kind"] in ("lauf", "rad")]
    full = 50 * 2 * 1.2
    # Tag 4: Fahrt 5 Uhr ist die 4. Ausdauereinheit (voll), Lauf 7 Uhr die 5., Fahrt 18 Uhr die 6. (beide halb).
    assert order == [("r0", full), ("r1", full), ("r2", full), ("ride:early", full), ("r3", full / 2), ("ride:late", full / 2)]
    # Ruhebonus wirkt auf Fahrten wie auf Läufe: zwei Ruhetage (120 EP) vor der ersten Fahrt verdoppeln sie.
    only = rides_frame([{"activity_id": "a", "started_at": "2026-11-04 18:00", "dur_min": 50.0, "zone": 1}])
    steps = {date(2026, 11, 2): 0}
    book = hero.ledger(runs.iloc[0:0], runs.iloc[0:0].assign(sets=[]), steps, {}, set(), [], date(2026, 11, 4), rides=only)
    ride = next(e for e in book["entries"] if e["kind"] == "rad")
    assert ride["bonus"] == pytest.approx(min(120.0, full))


def test_buffs_potions_and_focus_apply_to_rides():
    d = date(2026, 11, 4)
    rides = rides_frame([{"activity_id": "a", "started_at": "2026-11-04 18:00", "dur_min": 50.0, "zone": 1, "km": 40.0}])
    empty = rides.iloc[0:0]
    mods = hero.Mods(buffs={d: {"erholt"}}, potions={d: {"ausdauer"}}, spec_hist=[{"from": "2026-11-01", "value": "ausdauer"}])
    e = next(e for e in hero.ledger(empty, empty.assign(sets=[]), {}, {}, set(), [], d, mods, rides=rides)["entries"]
             if e["kind"] == "rad")
    assert e["xp"] == pytest.approx(120 * (1 + 0.05 + 0.10 + 0.10))  # Erholt + Ausdauertrank + Fokus Ausdauer
    ride = next(rides.itertuples())
    assert hero.matches_spec("ausdauer", ride, 1) and not hero.matches_spec("tempo", ride, 1)
    assert not hero.matches_spec("strecke", ride, 1)  # virtuelle km zählen nie für „Strecke“


REGRESSION_TOTALS = {"laufen": 581.1, "auftraege": 300.0, "bosse": 800.0, "instanzen": 200.0, "taeglich": 50.0}
REGRESSION_DROPS = [
    ("drop:run-0", "weiss", "Armschienen des Morgengrauens", "handgelenk", 110),
    ("drop:run-1", "weiss", "Laufhose des Tempos", "beine", 110),
    ("drop:run-2", "weiss", "Amulett der Abendröte", "hals", 115),
    ("drop:run-3", "weiss", "Laufschuhe des Herbstwinds", "fuesse", 115),
    ("drop:run-4", "blau", "Spikes der Ausdauer", "fuesse", 129),
    ("drop:run-5", "weiss", "Schulterwickel des Tempos", "schultern", 115),
    ("boss:2026-10-01:wyrm", "lila", "Stoppuhr der letzten Meile", "schmuck", 138),
    ("boss:2026-10-01:fresser", "lila", "Stirnband der gebrochenen Bestzeit", "kopf", 136),
    ("dungeon:run-2", "blau", "Schulterstücke der Mittagssonne", "schultern", 128),
    ("dungeon:run-4", "blau", "Beinkleider des Herbstwinds", "beine", 131),
]


def test_runs_only_history_unchanged(db):
    """Regressionswerte, erzeugt mit dem Stand vor #72 (Epic-Kopf 55bf0ed): reine Lauf-Historie, sechs Läufe in
    einer Woche vor ENDURANCE_FROM (5. und 6. Lauf halbe EP) → gleiche EP, Aufträge und Beute wie bisher."""
    hero._state_set("start", "2026-10-12")
    for i, (h, km, minutes, hr) in enumerate([(7, 8.0, 48, 140), (7, 5.0, 31, 150), (18, 10.5, 66, 135),
                                             (7, 3.2, 21, 160), (7, 12.0, 80, 138), (9, 6.0, 37, 155)]):
        add_session(db, 33, datetime(2026, 10, 12 + i, h), minutes, km=km, hr=hr, ext=f"run-{i}")
    data = hero._load(date(2026, 10, 18))
    totals = {k: round(v, 3) for k, v in data["book"]["totals"].items() if v}
    assert totals == REGRESSION_TOTALS
    assert [(it["id"], it["rarity"], it["name"], it["slot"], it["ilvl"]) for it in data["drops"]] == REGRESSION_DROPS


# --- Alltag / HC-Spiegel -----------------------------------------------------------------------
def test_hc_mirror_of_indoor_ride_is_not_everyday(db):
    add_ride(db, "z", datetime(2026, 11, 3, 18), minutes=60)
    add_session(db, 4, datetime(2026, 11, 3, 18, 1), 58, km=29.0, hr=None, ext="hc-zwift-mirror")
    add_session(db, 4, datetime(2026, 11, 4, 8), 30, km=7.0, hr=None, ext="hc-commute")
    assert hero._other_minutes() == {date(2026, 11, 4): 30.0}
    data = hero._load(TODAY)
    kinds = {(e["date"], e["kind"]) for e in data["entries"]}
    assert (date(2026, 11, 3), "rad") in kinds and (date(2026, 11, 3), "alltag") not in kinds
    assert (date(2026, 11, 4), "alltag") in kinds
    # Tagesaufgabe „In Bewegung“ bleibt am Fahrttag erfüllt — die Fahrt ist Training.
    base = {"runs": data["runs"], "workouts": data["workouts"], "other": hero._other_minutes(), "indoor": data["indoor"]}
    assert hero_events.daily_done("bewegung", date(2026, 11, 3), base)


# --- Klasse & Disziplin ---------------------------------------------------------------------------
def test_ride_xp_counts_to_hunter_side_and_discipline(db):
    for i in range(8):
        add_ride(db, f"r{i}", datetime(2026, 11, 2, 6) + timedelta(days=i % 7, hours=12 * (i // 7)), minutes=45)
    data = hero._load(TODAY)
    cls = hero.classify(data["book"]["daily"], data["runs"], TODAY, data["indoor"])
    assert cls["class"] == "jaeger" and cls["shares"]["rad"] > 0.9 and cls["shares"]["laufen"] == 0
    assert hero.classify(data["book"]["daily"], data["runs"], TODAY)["class"] == "moench"  # ohne Fahrten zu wenig Einheiten
    disc = next(a for a in hero.attributes(data["runs"], data["workouts"], {}, set(), TODAY, data["indoor"])
                if a["key"] == "disziplin")
    assert disc["value"] == "7 Trainingstage / 28 T"


# --- Beute -------------------------------------------------------------------------------------------
def _prior(n=3, **kw):
    return rides_frame([{"activity_id": f"p{i}", "started_at": f"2026-10-{10 + i} 18:00", "dur_min": 60.0, "kj": 500.0,
                         "ef": 1.0 + i * 0.1, "power_curve": {5: 500.0, 60: 300.0, 300: 220.0, 1200: 190.0}, **kw}
                        for i in range(n)])


def _ride(**kw):
    row = {"activity_id": "new", "started_at": "2026-11-03 18:00", "dur_min": 55.0, "kj": 400.0, "ef": 0.9,
           "power_curve": {5: 400.0, 60: 250.0, 300: 200.0, 1200: 180.0}, **kw}
    return next(rides_frame([row]).itertuples())


@pytest.mark.parametrize("ride, eftp_rise, rarity, slots", [
    (dict(km=100.0), False, "rot", None),
    (dict(elevation_m=8848.0, dur_min=300.0), False, "rot", None),
    (dict(dur_min=19.0, power_curve={5: 900.0}), False, "grau", None),
    (dict(power_curve={5: 400.0, 60: 250.0, 300: 200.0, 1200: 191.0}), False, "orange", ["brust"]),
    (dict(), True, "orange", ["brust"]),
    (dict(power_curve={5: 501.0, 1200: 100.0}), False, "lila", ["schmuck", "ring"]),
    (dict(power_curve={5: 501.0, 60: 301.0, 300: 221.0}), False, "lila", ["haende", "handgelenk"]),
    (dict(dur_min=61.0), False, "blau", None),
    (dict(ef=1.2), False, "blau", None),
    (dict(kj=501.0), False, "gruen", None),
    (dict(), False, "weiss", None),
])
def test_ride_rarity_rules(ride, eftp_rise, rarity, slots):
    got, _, got_slots = hero.ride_rarity(_ride(**ride), _prior(), eftp_rise)
    assert (got, got_slots) == (rarity, slots)


def test_ride_rarity_needs_history():
    first = _ride(power_curve={5: 2000.0, 1200: 400.0})
    assert hero.ride_rarity(first, _prior(0), False)[0] == "weiss"           # erste Fahrt: kein Bestwert ohne Vergleich
    assert hero.ride_rarity(_ride(dur_min=61.0), _prior(2), False)[0] == "weiss"  # Schnitt/Längste erst ab 3 Fahrten


def test_eftp_rise_from_cp_fit(monkeypatch):
    monkeypatch.setattr(settings, "bike_ftp", 0.0)
    rides = rides_frame([{"activity_id": "a", "started_at": "2026-11-01 18:00", "power_curve": {180: 260.0, 600: 220.0}},
                         {"activity_id": "b", "started_at": "2026-11-03 18:00", "power_curve": {180: 290.0, 600: 245.0}},
                         {"activity_id": "c", "started_at": "2026-11-05 18:00", "power_curve": {180: 250.0, 600: 200.0}}])
    assert [hero._eftp_rise(rides, i) for i in range(3)] == [False, True, False]
    monkeypatch.setattr(settings, "bike_ftp", 230.0)  # feste FTP aus den Einstellungen steigt nie
    assert not hero._eftp_rise(rides, 1)


def test_ride_drops_are_seeded_and_named_after_world(db):
    add_ride(db, "old", datetime(2026, 10, 20, 18), minutes=60)                               # vor Starttag: keine Beute
    add_ride(db, "sprint", datetime(2026, 11, 3, 18), minutes=45, curve={"5": 900.0, "60": 160.0})
    add_ride(db, "plain", datetime(2026, 11, 4, 18), minutes=45, world=None, kind="indoor_cycling")
    first = [it for it in hero._load(TODAY)["drops"] if it["id"].startswith("drop:ride:")]
    again = [it for it in hero._load(TODAY)["drops"] if it["id"].startswith("drop:ride:")]
    assert first == again and [it["id"] for it in first] == ["drop:ride:sprint", "drop:ride:plain"]
    sprint, plain = first
    assert sprint["rarity"] in ("lila", "orange") and sprint["slot"] in ("schmuck", "ring")
    assert sprint["source"] == "beute" and sprint["ride_min"] == 45
    assert "von Watopia" not in plain["name"] and plain["name"].split()[0] in hero.RIDE_BASES[plain["slot"]]


# --- Truhe -----------------------------------------------------------------------------------------
def test_vault_threshold_counts_rides_from_30_min():
    week = date(2026, 11, 2)
    runs = runs_frame([{"external_id": "r", "started_at": "2026-11-02 07:00", "distance_km": 8.0, "dur_min": 48.0, "zone": 1}])
    rides = rides_frame([{"activity_id": "a", "started_at": "2026-11-03 18:00", "dur_min": 45.0},
                         {"activity_id": "b", "started_at": "2026-11-04 18:00", "dur_min": 30.0},
                         {"activity_id": "c", "started_at": "2026-11-05 18:00", "dur_min": 29.0}])
    item = {"source": "beute", "date": "2026-11-03", "rarity": "lila"}
    v = hero.vault_week(week, runs, [item], set(), [], TODAY, rides=rides)
    assert (v["runs"], v["rides"]) == (3, 2) and [s["unlocked"] for s in v["slots"]] == [True, True, False]
    assert all(hero.RARITIES.index(s["item"]["rarity"]) >= hero.RARITIES.index("lila") for s in v["slots"])
    assert hero.vault_week(week, runs, [], set(), [], TODAY)["runs"] == 1  # ohne Fahrten wie bisher


# --- Aufträge ---------------------------------------------------------------------------------------
def test_endurance_quests_met_by_ride_but_run_quests_are_not():
    rides = rides_frame([{"activity_id": "a", "started_at": "2026-11-03 18:00", "dur_min": 95.0, "zone": 1},
                         {"activity_id": "b", "started_at": "2026-11-04 18:00", "dur_min": 35.0, "zone": 3}])
    empty_runs = runs_frame([{"external_id": "x", "started_at": "2020-01-01 07:00", "distance_km": 5.0, "dur_min": 30.0, "zone": 1}])
    data = {"runs": empty_runs, "workouts": pd.DataFrame(columns=["day", "sets"]), "indoor": rides, "sick": set(),
            "protein": {}, "sleep": {}, "steps": {}}
    week = date(2026, 11, 2)
    quests = {}
    for picked in (["grundlage90", "kraft2", "schlaf3"], ["tempo30", "kraft2", "schlaf3"], ["ausdauer150", "kraft2", "schlaf3"],
                   ["laeufe3", "kraft2", "schlaf3"], ["km20", "kraft2", "schlaf3"], ["locker2", "kraft2", "schlaf3"]):
        hero_quests.pick, orig = (lambda w, s, e, p=picked: p), hero_quests.pick
        try:
            q = hero_quests.week_quests(week, None, None, data, TODAY)["quests"][0]
        finally:
            hero_quests.pick = orig
        quests[q["id"]] = (q["done"], q["progress"], q["category"])
    assert quests["grundlage90"] == (True, 90, "ausdauer") and quests["tempo30"] == (True, 30, "ausdauer")
    assert quests["ausdauer150"] == (False, 130, "ausdauer")
    assert {quests[k][:2] for k in ("laeufe3", "km20", "locker2")} == {(False, 0)}


def test_endurance_quests_only_from_gate_week():
    gate = hero_quests.ENDURANCE_FROM
    before = [gate - timedelta(weeks=i) for i in range(1, 80)]
    for spec in (None, "ausdauer", "tempo", "last", "strecke"):
        assert not any(set(hero_quests.pick(w, spec, "lauf")) & set(hero_quests.ENDURANCE) for w in before)
    after = [gate + timedelta(weeks=i) for i in range(52)]
    assert any(hero_quests.pick(w, None, None)[0] in hero_quests.ENDURANCE for w in after)


def test_overview_with_rides(db, monkeypatch):
    monkeypatch.setattr(hero, "local_today", lambda: TODAY)
    add_session(db, 33, datetime(2026, 11, 2, 7), 48, km=8.0, ext="run-a")
    add_ride(db, "z", datetime(2026, 11, 3, 18), minutes=60)
    o = hero.overview(TODAY)
    assert o["xp_sources"]["rad"] == round(60 * 2 * 1.2) and o["hero"]["shares"]["rad"] > 0
    assert o["vault"]["current"]["runs"] == 2 and o["vault"]["current"]["rides"] == 1
    assert any(e.get("item_id") == "drop:ride:z" for e in o["log"])
    assert any(it["id"] == "drop:ride:z" for it in o["inventory"])
