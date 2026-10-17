from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app import hero, hero_keystone as ks, hero_social
from app.metrics import achievements as ach

WEEK = date(2026, 10, 5)  # Montag


def ms(d: date, hour=8) -> int:
    return int(datetime(d.year, d.month, d.day, hour, tzinfo=ZoneInfo("Europe/Berlin")).timestamp() * 1000)


def stone(day: date, level: int, status="timed", dungeon="festungsring"):
    return {"id": 1, "dungeon": dungeon, "level": level, "status": status, "activated_ms": ms(day)}


def vault(stones=None, n_runs=3):
    runs = pd.DataFrame({"day": [WEEK + pd.Timedelta(days=i).to_pytimedelta() for i in range(n_runs)]})
    return hero.vault_week(WEEK, runs, [], set(), [], date(2026, 10, 16), None, stones)


def test_week_best_takes_highest_timed_stone_of_the_week():
    done = [stone(date(2026, 10, 6), 4), stone(date(2026, 10, 8), 9, "fast"), stone(date(2026, 10, 9), 15, "slow"),
            stone(date(2026, 10, 9), 12, "incomplete"), stone(date(2026, 10, 12), 20)]
    assert ks.week_best(done, WEEK) == 9
    assert ks.week_best([], WEEK) == 0


def test_vault_stone_lifts_only_slot_one_and_is_unchanged_without():
    plain = vault()
    assert plain["stone_level"] is None
    assert vault([]) == plain                      # opt-in: ohne Steine nichts anders
    low, high = vault([stone(date(2026, 10, 7), 3)]), vault([stone(date(2026, 10, 7), 10)])
    rar = lambda v: hero.RARITIES.index(v["slots"][0]["item"]["rarity"])
    assert high["stone_level"] == 10 and low["stone_level"] == 3
    assert rar(high) >= hero.RARITIES.index("lila") and rar(high) > rar(low) >= rar(plain)
    assert high["slots"][0]["item"]["ilvl"] > plain["slots"][0]["item"]["ilvl"] or rar(high) != rar(plain)
    # Nur Slot 1 wird vom Stein bestimmt, die anderen Slots bleiben unverändert.
    assert [s["item"] for s in high["slots"][1:]] == [s["item"] for s in plain["slots"][1:]]
    # Ein zu langsamer Stein oder einer aus anderer Woche hebt nichts.
    assert vault([stone(date(2026, 10, 7), 20, "slow"), stone(date(2026, 10, 14), 20)]) == plain


def test_rating_best_level_per_dungeon_and_total(monkeypatch):
    done = [stone(date(2026, 10, 1), 4), stone(date(2026, 10, 3), 8, "fast"), stone(date(2026, 10, 4), 12, "slow"),
            stone(date(2026, 10, 5), 6, dungeon="auesee")]
    r = ks.rating(done)
    best = {d["dungeon"]: d for d in r["dungeons"]}
    assert best["festungsring"]["best_level"] == 8 and best["festungsring"]["timed_runs"] == 2
    assert best["festungsring"]["best_date"] == "2026-10-03"
    assert r["total"] == 14 and r["best_level"] == 8 and r["dungeons_timed"] == 2


def test_rating_excludes_own_dungeons_from_total(monkeypatch):
    monkeypatch.setattr(ks.hero_world, "dungeon_defs", lambda: [{"key": "eigen-abc", "name": "Meine Runde", "own": True}])
    r = ks.rating([stone(date(2026, 10, 1), 14, dungeon="eigen-abc"), stone(date(2026, 10, 2), 5)])
    assert any(d["own"] and d["best_level"] == 14 for d in r["dungeons"])   # sichtbar
    assert r["total"] == 5 and r["best_level"] == 5 and r["dungeons_timed"] == 1


def hero_stats(world, stones):
    data = {"runs": pd.DataFrame(), "workouts": [], "quest_weeks": [], "bosses": [], "dungeons": [], "protein": {},
            "protein_target": None, "sleep": {}, "world": world, "stones": stones}
    return hero._hero_stats(data, [], 5, {})


def dg(key, own, cleared=True, heroic=True, typ="wasser"):
    return {"key": key, "own": own, "cleared": cleared, "heroic": heroic, "type": "eigen" if own else typ,
            "level": 60, "cleared_on": "2026-10-01", "heroic_on": "2026-10-01", "segments": []}


def test_title_unlock_from_stone_level(monkeypatch):
    monkeypatch.setattr(hero, "_streak", lambda: 0)
    monkeypatch.setattr(ks.hero_world, "dungeon_defs", lambda: [])
    low = {t["key"]: t for t in hero_social.titles(hero_stats({}, [stone(date(2026, 10, 1), 9)]), None)}
    high = {t["key"]: t for t in hero_social.titles(hero_stats({}, [stone(date(2026, 10, 1), 10)]), None)}
    assert not low["schluesselmeister"]["earned"] and low["steinlaeufer"]["earned"]
    assert high["schluesselmeister"]["earned"]


def test_option_b_own_dungeons_do_not_count(monkeypatch):
    monkeypatch.setattr(hero, "_streak", lambda: 0)
    monkeypatch.setattr(ks.hero_world, "dungeon_defs", lambda: [{"key": "eigen-x", "name": "E", "own": True}])
    own = {"dungeons": [dg("eigen-x", True)], "regions": []}
    osm = {"dungeons": [dg("auesee", False)], "regions": []}
    s_own, s_osm = hero_stats(own, []), hero_stats(osm, [])
    assert (s_own["map_dungeons"], s_own["map_heroic"], s_own["map_wasser"]) == (0, 0, 0)
    assert (s_osm["map_dungeons"], s_osm["map_heroic"], s_osm["map_wasser"]) == (1, 1, 1)
    # Erfolge der Kategorie Weltkarte
    for target, kw in ((1, {}), (1, {"heroic": True}), (1, {"min_level": 50})):
        assert not ach._wk_dungeons(own, target, **kw)[0]
        assert ach._wk_dungeons(osm, target, **kw)[0]
    # Stein-Läufe in eigenen Verliesen zählen weder für Titel noch Erfolge.
    stats = hero_stats(own, [stone(date(2026, 10, 1), 12, dungeon="eigen-x")])
    assert stats["key_best"] == 0 and stats["key_dungeons"] == 0
    monkeypatch.setattr(ks, "results", lambda dungeon_key=None: [stone(date(2026, 10, 1), 12, dungeon="eigen-x")])
    assert not ach._wk_stone(10)[0]
    monkeypatch.setattr(ks, "results", lambda dungeon_key=None: [stone(date(2026, 10, 1), 12)])
    assert ach._wk_stone(10)[0] and not ach._wk_stone(20)[0]
