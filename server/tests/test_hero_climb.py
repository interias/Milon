"""Heldenreise II (#73): Kletter-Bosse, Traumreiche, Zwift-Reittiere, Kettenfresser.
Nur synthetische Fahrten auf tmp_path-Datenbanken, nie Koordinaten."""
import json
from datetime import date, datetime

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import garmin_indoor, hero, hero_bosses, hero_climb, hero_dreams, hero_extras
from app.config import settings
from app.garmin_indoor import GarminIndoorRide
from app.metrics import achievements, cycling, health

TODAY = date(2026, 11, 8)
START = date(2026, 11, 2)


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'climb.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for mod in (hero, cycling, health, garmin_indoor):
        monkeypatch.setattr(mod, "engine", engine)
    for name, fn in (("_achievement_xp", lambda: []), ("_strength_series", lambda: []), ("_protein_days", lambda: {}),
                     ("_protein_target", lambda: None), ("_streak", lambda: 0)):
        monkeypatch.setattr(hero, name, fn)
    monkeypatch.setattr(hero.hero_world, "world", lambda: {"available": False})
    monkeypatch.setattr(settings, "bike_ftp", 200.0)
    monkeypatch.setattr(settings, "run_hr_max", 180.0)
    monkeypatch.setattr(hero, "local_today", lambda: TODAY)
    with Session(engine) as s:
        s.add(hero.HeroState(key="start", value=START.isoformat()))
        s.commit()
    yield engine
    engine.dispose()


def add_ride(engine, aid, start: datetime, minutes=60, km=30.0, elevation=150.0, world="Watopia", route="Route",
             title=None):
    with Session(engine) as s:
        s.add(GarminIndoorRide(
            activity_id=aid, activity_type="virtual_ride", title=title or f"Zwift - {route} in {world}", world=world, route=route,
            started_at=start, duration_seconds=minutes * 60.0, elapsed_duration_seconds=minutes * 60.0,
            distance_km=km, elevation_gain_m=elevation, avg_power_w=140.0, norm_power_w=140.0, work_kj=500.0,
            avg_hr=130.0, max_hr=150.0, hr_valid=True, power_curve_json=json.dumps({"5": 240, "60": 170, "300": 150, "1200": 140}),
            synced_at=datetime(2026, 11, 8)))
        s.commit()


def frame(rows):
    df = pd.DataFrame(rows)
    df["started_at"] = pd.to_datetime(df["started_at"])
    df["day"] = df["started_at"].dt.date
    return df


# --- Kletter-Bosse -----------------------------------------------------------------------------
def test_peak_thresholds_and_rounds():
    rides = frame([{"started_at": "2026-11-01 08:00", "elevation_m": 5000},          # vor dem Start: zählt nicht
                   {"started_at": "2026-11-03 08:00", "elevation_m": 1000},          # 1.000 < 1.036
                   {"started_at": "2026-11-04 08:00", "elevation_m": 600},           # 1.600: Alpe + Ventoux (genau auf der Schwelle)
                   {"started_at": "2026-11-05 08:00", "elevation_m": 300},           # 1.900: Stelvio
                   {"started_at": "2026-11-06 08:00", "elevation_m": 3000},          # 4.900: Mont Blanc
                   {"started_at": "2026-11-07 08:00", "elevation_m": 1000},          # 5.900: Kilimandscharo
                   {"started_at": "2026-11-08 08:00", "elevation_m": 3000}])         # 8.900: Everest
    c = hero_climb.climb(rides, START)
    on = {p["key"]: p["reached_on"] for p in c["peaks"]}
    assert on == {"alpe": "2026-11-04", "ventoux": "2026-11-04", "stelvio": "2026-11-05", "montblanc": "2026-11-06",
                  "kilimandscharo": "2026-11-07", "everest": "2026-11-08"}
    assert c["total_hm"] == 8900 and c["rounds"] == [] and c["next"]["name"] == "Mount Everest · Runde 2"
    assert c["next_in_hm"] == 8848 * 2 - 8900
    # Wiederholungsrunden: je weitere 8.848 Hm, auch mehrere in einer Fahrt
    more = frame([{"started_at": "2026-11-09 08:00", "elevation_m": 4000}, {"started_at": "2026-11-10 08:00", "elevation_m": 4000},
                  {"started_at": "2026-11-11 08:00", "elevation_m": 4000}, {"started_at": "2026-11-12 08:00", "elevation_m": 4000},
                  {"started_at": "2026-11-13 08:00", "elevation_m": 4000}, {"started_at": "2026-11-14 08:00", "elevation_m": 4000}])
    c2 = hero_climb.climb(pd.concat([rides.iloc[1:], more], ignore_index=True), START)
    assert [r["n"] for r in c2["rounds"]] == [2, 3] and [r["reached_on"] for r in c2["rounds"]] == ["2026-11-11", "2026-11-13"]
    assert c2["total_hm"] == 8900 + 24000 and c2["next"]["name"] == "Mount Everest · Runde 4"
    ev = hero_climb.events(c2)
    assert [e["id"] for e in ev][-2:] == ["runde2", "runde3"] and sum(e["xp"] for e in ev) == 150 + 200 + 250 + 500 + 750 + 1500 + 2 * 500


def test_no_rides_no_peaks():
    c = hero_climb.climb(pd.DataFrame(columns=["day", "started_at", "elevation_m"]), START)
    assert c["total_hm"] == 0 and not any(p["reached"] for p in c["peaks"]) and hero_climb.events(c) == []


def test_climb_flows_into_xp_log_loot_and_titles(db):
    add_ride(db, "a", datetime(2026, 11, 3, 8), elevation=1200)         # Alpe du Zwift
    add_ride(db, "b", datetime(2026, 11, 5, 8), elevation=3700)         # → 4.900: Ventoux, Stelvio, Mont Blanc
    o = hero.overview(TODAY)
    assert o["climb"]["total_hm"] == 4900 and o["xp_sources"]["gipfel"] == 150 + 200 + 250 + 500
    assert {"climb:alpe", "climb:montblanc"} <= {it["id"] for it in o["inventory"]}
    assert next(it for it in o["inventory"] if it["id"] == "climb:alpe")["rarity"] == "blau"
    assert any(e["kind"] == "gipfel" and e["name"] == "Mont Blanc" and e["tip"] for e in o["log"])
    titles = {t["key"]: t for t in o["titles"]}
    assert titles["gipfelstuermer"]["earned"] and not titles["dach_der_welt"]["earned"]
    assert not titles["traumwandler"]["earned"]


def test_climb_before_start_day_gives_nothing(db):
    add_ride(db, "old", datetime(2026, 10, 20, 8), elevation=4000)
    assert hero.overview(TODAY)["climb"]["total_hm"] == 0


# --- Traumreiche -------------------------------------------------------------------------------
def test_dreams_count_routes_tolerantly(db):
    add_ride(db, "1", datetime(2026, 11, 3, 8), route="Volcano Circuit", world="Watopia")
    add_ride(db, "2", datetime(2026, 11, 4, 8), route="volcano  circuit", world="watopia")      # gleiche Route, andere Schreibung
    add_ride(db, "3", datetime(2026, 11, 5, 8), route="Prologue", world="Watopia")
    add_ride(db, "4", datetime(2026, 11, 6, 8), route="Classique", world="London")
    add_ride(db, "5", datetime(2026, 11, 7, 8), route=None, world=None, title="Zwift - Your First Workout")
    d = hero_dreams.dreams()
    by = {w["world"]: w for w in d["worlds"]}
    assert set(by) == {"Watopia", "London"} and by["Watopia"]["rides"] == 3 and by["Watopia"]["route_count"] == 2
    assert d["visited_known"] == 2 and not d["all_worlds"] and d["best_routes"] == 2
    tl = hero_dreams.timeline(cycling.indoor_rides())
    assert tl["first"] == {"Watopia": "2026-11-03", "London": "2026-11-06"}
    assert tl["routes"]["Watopia"] == ["2026-11-03", "2026-11-05"]


def test_dream_achievements(db):
    for i, route in enumerate("ABCDE"):
        add_ride(db, f"r{i}", datetime(2026, 11, 2 + i, 8), route=f"Route {route}", world="Watopia", elevation=250)
    add_ride(db, "x", datetime(2026, 11, 8, 8), route="Z", world="London", elevation=250)
    specs = {sp[0]: sp for sp in achievements._specs() if sp[1] == "traumreiche"}
    c = type("C", (), {})()
    assert specs["traum_welt_watopia"][6](c) == (True, "2026-11-02", 1.0, None)
    assert specs["traum_welt_innsbruck"][6](c)[0] is False
    assert specs["traum_routen_5"][6](c)[:2] == (True, "2026-11-06")
    assert specs["traum_routen_10"][6](c)[0] is False
    assert specs["traum_alle"][6](c)[0] is False
    assert specs["traum_hm_1000"][6](c)[:2] == (True, "2026-11-05")      # 4. Fahrt: 4 × 250 = 1.000
    assert specs["traum_hm_5000"][6](c)[0] is False


def test_all_worlds_title_and_achievement(db):
    for i, w in enumerate(hero_dreams.KNOWN_WORLDS):
        add_ride(db, f"w{i}", datetime(2026, 11, 2, 6 + i % 10, i), world=w, route=f"R{i}")
    c = type("C", (), {})()
    spec = next(sp for sp in achievements._specs() if sp[0] == "traum_alle")
    assert spec[6](c)[0] is True
    assert {t["key"]: t for t in hero.overview(TODAY)["titles"]}["traumwandler"]["earned"]


def test_variety_badge_ignores_dream_category():
    ach = [{"category": "x", "earned": True}, {"category": "traumreiche", "earned": False}]
    assert achievements._meta_variety(ach)[0] is True


# --- Reittiere ---------------------------------------------------------------------------------
def test_zwift_km_feed_fully_and_unlock(db):
    hero._state_set("mount", "deichgaul")
    for i in range(9):                                                      # 9 × 120 = 1.080 Zwift-km
        add_ride(db, f"m{i}", datetime(2026, 11, 2 + i % 6, 6 + i), km=120.0, minutes=180, route=f"R{i}")
    o = hero.overview(date(2026, 11, 9))
    m = {x["key"]: x for x in o["mounts"]}
    assert m["deichgaul"]["ride_km"] == 1080 and m["deichgaul"]["level"] == 10          # voller Satz, Stufe gedeckelt
    assert m["deichgaul"]["unlocked"] and m["auenhengst"]["unlocked"]                   # Zwift zählt zu den Rad-km
    assert m["watopia_wyvern"]["unlocked"] and m["watopia_wyvern"]["unit"] == "Zwift-km" and m["watopia_wyvern"]["value"] == 1000
    assert m["watopia_wyvern"]["unlocked_on"] is not None


def test_wyvern_needs_zwift_not_gps_km():
    day = date(2026, 11, 3)
    runs = pd.DataFrame(columns=["day", "distance_km", "started_at"])
    wo = pd.DataFrame(columns=["day", "sets", "started_at"])
    gps = [(day, 250.0)] * 5
    m = {x["key"]: x for x in hero_extras.mounts(runs, wo, None, gps)}
    assert m["auenhengst"]["unlocked"] and not m["watopia_wyvern"]["unlocked"]
    m = {x["key"]: x for x in hero_extras.mounts(runs, wo, None, [], None, [(day, 600.0), (date(2026, 11, 4), 400.0)])}
    assert m["watopia_wyvern"]["unlocked_on"] == "2026-11-04" and m["deichgaul"]["unlocked"]


def test_no_zwift_leaves_existing_mounts_unchanged():
    runs = pd.DataFrame(columns=["day", "distance_km", "started_at"])
    wo = pd.DataFrame(columns=["day", "sets", "started_at"])
    keys = [m["key"] for m in hero_extras.mounts(runs, wo, None)]
    assert keys[:-1] == ["deichschaf", "rheinpony", "schlachtross", "nebelwolf", "greif", "sturmhirsch", "drachling", "phoenix",
                         "kriegsbaer", "mammut", "deichgaul", "auenhengst"] and keys[-1] == "watopia_wyvern"


# --- Kettenfresser -----------------------------------------------------------------------------
def _base(ride_min=None):
    empty = pd.DataFrame(columns=["day", "distance_km", "started_at", "key", "pace", "sets"])
    efforts = pd.DataFrame(columns=["external_id", "distance_m", "seconds", "started_at"])
    data = {"runs": empty, "workouts": empty, "efforts": efforts, "sick": set()}
    if ride_min is not None:
        data["ride_min"] = ride_min
    return data


def test_chain_eater_absent_without_recent_ride():
    keys = [b["key"] for b in hero_bosses.month_bosses(date(2026, 10, 1), _base(), TODAY)]
    assert keys == ["waechter", "wyrm", "fresser", "koloss"]
    old = [(date(2026, 6, 1), 120.0)]                                       # > 90 Tage vor Monatsende
    assert "kettenfresser" not in [b["key"] for b in hero_bosses.month_bosses(date(2026, 10, 1), _base(old), TODAY)]


def test_chain_eater_first_month_fixed_four_hours_and_win_day():
    rides = [(date(2026, 10, 3), 90.0), (date(2026, 10, 10), 100.0), (date(2026, 10, 20), 60.0)]
    boss = next(b for b in hero_bosses.month_bosses(date(2026, 10, 1), _base(rides), TODAY) if b["key"] == "kettenfresser")
    assert boss["goal"] == "4 h auf dem Rad im Monat" and boss["xp"] == hero_bosses.BOSS_XP and boss["loot"] == "lila"
    assert boss["defeated"] and boss["defeated_on"] == "2026-10-20" and boss["status"] == "4 h 10 min gefahren"
    assert boss["hp"] == 0.0


def test_chain_eater_target_from_three_months_and_sick_days():
    prior = [(date(2026, 7, 5), 600.0), (date(2026, 8, 5), 600.0), (date(2026, 9, 5), 600.0)]    # Ø 600 min/Monat
    month = date(2026, 10, 1)
    boss = next(b for b in hero_bosses.month_bosses(month, _base(prior + [(date(2026, 10, 2), 60.0)]), TODAY)
                if b["key"] == "kettenfresser")
    assert boss["goal"] == "11 h auf dem Rad im Monat" and not boss["defeated"] and 0 < boss["hp"] < 1       # 600 × 1,1 = 660 min
    # unter dem Mindestwert gilt 4 h
    low = [(date(2026, 9, 5), 30.0)]
    boss = next(b for b in hero_bosses.month_bosses(month, _base(low + [(date(2026, 10, 2), 10.0)]), TODAY) if b["key"] == "kettenfresser")
    assert boss["goal"] == "4 h auf dem Rad im Monat"
    # Krankheitstage senken das Ziel anteilig (15 von 31 Tagen krank → 16/31 von 240 min = 124 min)
    sick = _base([(date(2026, 10, 2), 10.0)])
    sick["sick"] = {date(2026, 10, d) for d in range(1, 16)}
    boss = next(b for b in hero_bosses.month_bosses(month, sick, TODAY) if b["key"] == "kettenfresser")
    assert boss["goal"] == "2 h 04 min auf dem Rad im Monat"


def test_chain_eater_in_load_uses_indoor_and_gps_minutes(db):
    from app.garmin_routes import GarminRide
    add_ride(db, "a", datetime(2026, 11, 3, 8), minutes=120)
    with Session(db) as s:
        s.add(GarminRide(activity_id="g", title="Rad", started_at=datetime(2026, 11, 4, 8), distance_km=40.0,
                         duration_seconds=125 * 60.0, point_count=2, segments_json="[]", synced_at=datetime(2026, 11, 4)))
        s.commit()
    boss = next(b for b in hero._load(TODAY)["bosses"] if b["key"] == "kettenfresser")
    assert boss["defeated"] and boss["defeated_on"] == "2026-11-04"           # 120 + 125 ≥ 240 min
    o = hero.overview(TODAY)
    assert any(b["key"] == "kettenfresser" for b in o["bosses"]) and o["xp_sources"]["bosse"] >= hero_bosses.BOSS_XP
    assert any(it["id"] == "boss:2026-11-01:kettenfresser" for it in o["inventory"])


def test_runs_only_history_has_no_new_content(db):
    from datetime import timedelta
    from app.models import ExerciseSession
    with Session(db) as s:
        start = datetime(2026, 11, 3, 7)
        s.add(ExerciseSession(exercise_type=33, started_at=start, ended_at=start + timedelta(minutes=48), distance_km=8.0,
                              avg_hr=140, max_hr=160, external_id="run-a"))
        s.commit()
    data = hero._load(TODAY)
    assert [b["key"] for b in data["bosses"]] == ["waechter", "wyrm", "fresser", "koloss"]
    assert data["book"]["totals"]["gipfel"] == 0 and data["climb"]["total_hm"] == 0 and data["dreams"]["worlds"] == []
    assert not any(d["id"].startswith("climb:") for d in data["drops"])


def test_chain_eater_does_not_undo_a_won_raid(db):
    """Ein Monat mit 4 besiegten klassischen Bossen bleibt ein Schlachtzug, auch wenn der Kettenfresser dazukommt."""
    def boss(key, defeated):
        return {"month": "2026-10-01", "key": key, "defeated": defeated}
    runs = pd.DataFrame(columns=["day", "distance_km", "started_at"])
    classic = [boss(k, True) for k in ("waechter", "wyrm", "fresser", "koloss")]
    data = {"runs": runs, "workouts": [], "quest_weeks": [], "dungeons": [], "protein": {}, "protein_target": None,
            "sleep": {}, "bosses": [*classic, boss("kettenfresser", False)]}
    stats = hero._hero_stats(data, [], 1, {})
    assert stats["full_raids"] == 1 and stats["bosses_down"] == 4
    data["bosses"] = [boss("waechter", False), *classic[1:], boss("kettenfresser", True)]
    assert hero._hero_stats(data, [], 1, {})["full_raids"] == 0
