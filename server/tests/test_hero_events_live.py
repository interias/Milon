import json
import math
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, select

from app import hero, hero_events_live as hel, hero_keystone as ks, hero_world
from test_hero_keystone import HOME, H, add_route, client, dungeon, ks_db, live_points, setup_world  # noqa: F401

MIN = 60_000


# --- Würfeln, Sperrfrist, Topf ------------------------------------------------------------------------

def test_roll_lockout_frequency_and_limits():
    start = 1_700_000_000_000
    assert all(hel.roll(f"s{i}", start + m * MIN, start, 2, 0, None) is None for i in range(50) for m in range(10))
    hits = [hel.roll("freq", start + m * MIN, start, 2, 0, None) for m in range(10, 4010)]
    share = sum(h is not None for h in hits) / len(hits)
    assert 0.003 < share < 0.012  # selten: ~0,7 % je Laufminute
    # Höchstzahl je Lauf nach Stufe, Abstand zum letzten Ereignis
    assert (hel.max_events(2), hel.max_events(10), hel.max_events(20)) == (1, 2, 3)
    hot = next(start + m * MIN for m in range(10, 4010) if hel.roll("freq", start + m * MIN, start, 2, 0, None))
    assert hel.roll("freq", hot, start, 2, 1, None) is None
    assert hel.roll("freq", hot, start, 10, 1, None) is not None
    assert hel.roll("freq", hot, start, 10, 1, hot - 5 * MIN) is None
    m0 = hot - hot % MIN  # stabil innerhalb derselben Minute (häufiges Abfragen würfelt nicht neu)
    assert hel.roll("freq", m0 + 1_000, start, 2, 0, None) == hel.roll("freq", m0 + 59_000, start, 2, 0, None)


def test_pot_weighted_by_level_and_tempo_switch_off():
    low, high = hel.pot(2), hel.pot(20)
    assert set(low) == set(high) == {"schatz", "begleiter", "wegelagerer", "totem"}  # Tempo-Ereignisse aus
    assert low["schatz"] > low["totem"] and high["totem"] > high["schatz"]
    assert {"verfolger", "elite", "echo", "wacht"} <= set(hel.pot(20, tempo=True))
    assert not {"verfolger", "elite", "echo", "wacht"} & set(hel.pot(2, tempo=True))
    start = 1_700_000_000_000

    def dist(level):
        c = Counter(k for i in range(400) for m in range(10, 70)
                    if (k := hel.roll(f"w{i}", start + m * MIN, start, level, 0, None)))
        return c

    lo, hi = dist(2), dist(20)
    assert lo["schatz"] + lo["begleiter"] > 2 * (lo["wegelagerer"] + lo["totem"])
    assert hi["wegelagerer"] + hi["totem"] > hi["schatz"] + hi["begleiter"]


def test_spawn_relative_targets_and_unrevealed_ambush():
    pos = (1000.0, 2000.0)
    rng = hel._rng("t")
    ev = hel.spawn("schatz", pos, 90.0, set(), rng, 0)
    assert 250 <= math.dist(pos, ev["target"]) <= 500 and ev["expires_ms"] > 0
    cm = hero_world.CELL_M
    ci, cj = math.floor(pos[0] / cm), math.floor(pos[1] / cm)
    near = {(i, j) for i in range(ci - 4, ci + 5) for j in range(cj - 4, cj + 5)}
    ev = hel.spawn("wegelagerer", pos, 0.0, near, hel._rng("w"), 0)
    i, j = math.floor(ev["target"][0] / cm), math.floor(ev["target"][1] / cm)
    assert (i, j) not in near and 300 <= math.dist(pos, ev["target"]) <= 1000
    every = {(i, j) for i in range(ci - 8, ci + 9) for j in range(cj - 8, cj + 9)}
    assert hel.spawn("wegelagerer", pos, 0.0, every, hel._rng("w"), 0) is None
    assert hel.spawn("verfolger", pos, 0.0, set(), hel._rng("v"), 0) is None  # zweite Stufe: noch keine Mechanik


def test_achieved_reach_and_totem_loop():
    target = (0.0, 0.0)
    line = [(i * 1000, -300 + i * 10.0, 0.0) for i in range(40)]
    assert hel.achieved("schatz", target, 0, line, 0, 10**9) is not None
    assert hel.achieved("schatz", target, 0, line, 0, 5_000) is None  # Fenster vorbei, bevor er ankam
    loop = [(i * 1000, 70 * math.sin(math.radians(a)), 70 * math.cos(math.radians(a))) for i, a in enumerate(range(0, 360, 15))]
    assert hel.achieved("totem", target, 70, loop, 0, 10**9) is not None
    assert hel.achieved("totem", target, 70, loop[:8], 0, 10**9) is None  # nur ein Viertel
    assert hel.achieved("totem", target, 70, line, 0, 10**9) is None       # durchgelaufen ist keine Schleife


# --- Live + Garmin-Bestätigung ------------------------------------------------------------------------

@pytest.fixture
def forced(monkeypatch):
    monkeypatch.setattr(hel, "ROLL_P", 1.0)
    monkeypatch.setattr(hel, "pot", lambda level, tempo=None: {"schatz": 1})


def start_run(engine, session="run-1", run_min=20):
    now = int(time.time() * 1000)
    ks.activate(session, "festungsring", 2, [], now_ms=now - (run_min + 5) * MIN)
    seg = [hero_world._to_m(HOME, la, lo) for la, lo in dungeon()["segments"][0]["points"]]
    pts = [p for p in live_points(seg, now - run_min * MIN) if p["ts"] <= now]
    assert client().post("/hero/live", json={"session": session, "points": pts}, headers=H).json()["rejected"] == 0
    return seg


def state(session="run-1"):
    return client().get("/hero/live/state", params={"session": session}, headers=H).json()


def test_no_event_without_keystone_or_within_lockout(ks_db, forced):
    setup_world(ks_db)
    assert state()["event"] is None  # ohne Stein wie bisher
    start_run(ks_db, run_min=5)
    assert state()["event"] is None  # Sperrfrist: erste 10 Minuten
    assert Session(ks_db).exec(select(hel.HeroLiveEvent)).first() is None


def test_event_appears_is_confirmed_by_garmin_and_pays_out(ks_db, forced):
    setup_world(ks_db)
    seg = start_run(ks_db)
    ev = state()["event"]
    assert ev["kind"] == "schatz" and ev["status"] == "active" and ev["provisional"] and ev["text"]
    assert 200 <= ev["distance_m"] <= 550 and 0 <= ev["bearing_deg"] < 360 and ev["remaining_s"] > 0
    raw = json.dumps(state())
    assert all(k not in raw for k in ('"lat"', '"lon"', "target_x", "target_y", '"x"', '"y"'))
    assert state()["event"]["id"] == ev["id"]  # höchstens ein Ereignis je Lauf auf Stufe +2
    assert len(Session(ks_db).exec(select(hel.HeroLiveEvent)).all()) == 1

    row = Session(ks_db).get(hel.HeroLiveEvent, ev["id"])
    start = datetime.fromtimestamp(row.rolled_ms / 1000, timezone.utc) + timedelta(seconds=10)
    add_route(ks_db, [seg[-1], (row.target_x, row.target_y)], start, "garmin-event", total_s=120)
    assert hel.resolve_pending(row.expires_ms + 1) == 1
    done = Session(ks_db).get(hel.HeroLiveEvent, ev["id"])
    assert done.status == "confirmed"
    got = hel.confirmed()
    assert got[0]["xp"] == hel.xp_for("schatz", 2) and got[0]["activity_id"] == "garmin-event"
    item = hero.live_event_loot(got, [])[0]
    assert item["id"] == f"liveevent:{ev['id']}" and item["source"] == "events" and item["rarity"] == hel.loot_for(2)
    assert hero.EXTRA_KEY["spontan"][0] == "events" and "events" in hero.XP_KEYS


def test_event_rejected_by_garmin_and_decline_costs_nothing(ks_db, forced):
    setup_world(ks_db)
    start_run(ks_db, session="run-2")
    assert state("run-2")["event"]["status"] == "active"
    assert client().post("/hero/live/event/decline", json={"session": "run-2"}, headers=H).json()["declined"]
    ev2 = state("run-2")["event"]
    assert ev2["status"] == "declined" and ev2["reward"] is None and not ev2["provisional"]

    seg = start_run(ks_db)
    ev = state()["event"]
    row = Session(ks_db).get(hel.HeroLiveEvent, ev["id"])
    start = datetime.fromtimestamp(row.rolled_ms / 1000, timezone.utc) + timedelta(seconds=10)
    away = (2 * seg[-1][0] - row.target_x, 2 * seg[-1][1] - row.target_y)  # Gegenrichtung
    add_route(ks_db, [seg[-1], away], start, "garmin-away", total_s=120)
    hel.resolve_pending(row.expires_ms + 1)
    assert Session(ks_db).get(hel.HeroLiveEvent, ev["id"]).status == "rejected"
    assert Session(ks_db).get(hel.HeroLiveEvent, ev2["id"]).status == "declined"
    assert hel.confirmed() == []


def test_rides_never_confirm(ks_db, forced):
    from app.garmin_routes import GarminRide
    setup_world(ks_db)
    seg = start_run(ks_db)
    row = Session(ks_db).get(hel.HeroLiveEvent, state()["event"]["id"])
    t0 = datetime.fromtimestamp(row.rolled_ms / 1000, timezone.utc)
    pts = [{"lat": la, "lon": lo, "time": (t0 + timedelta(seconds=30 * i)).isoformat()}
           for i, (la, lo) in enumerate(hero_world._from_m(HOME, *p) for p in (seg[-1], (row.target_x, row.target_y)))]
    with Session(ks_db) as s:
        s.add(GarminRide(activity_id="ride", title="Rad", started_at=t0.replace(tzinfo=None), point_count=2,
                         segments_json=json.dumps([pts]), synced_at=datetime.now()))
        s.commit()
    assert hel.resolve_pending(row.expires_ms + 1) == 0
    assert hel.resolve_pending(row.expires_ms + hel.EXPIRE_MS + 1) == 1
    assert Session(ks_db).get(hel.HeroLiveEvent, row.id).status == "expired"


def test_no_event_for_session_without_own_keystone(ks_db, forced):
    setup_world(ks_db)
    seg = start_run(ks_db)  # andere Session mit Stein
    now = int(time.time() * 1000)
    pts = [p for p in live_points(seg, now - 20 * MIN) if p["ts"] <= now]
    client().post("/hero/live", json={"session": "solo", "points": pts}, headers=H)
    assert state("solo")["event"] is None  # Opt-in: nur mit eigenem Stein
