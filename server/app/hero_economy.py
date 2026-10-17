"""Heldenreise: Gold (Kupfer als Basiseinheit), Händlerpreise, Taschen und Briefkasten.

Gold wird live aus den Heldenreise-Ereignissen ab Starttag berechnet; gespeichert werden nur
Verkäufe (hero_item_mods) und — später — Käufe. 1 Gold = 100 Silber = 10.000 Kupfer.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date

SILVER, GOLD = 100, 10_000
START_CAPITAL = 25 * GOLD
EARN = {"km": 10 * SILVER, "kraft": 50 * SILVER, "taeglich": 50 * SILVER, "auftrag": 2 * GOLD, "instanz": 3 * GOLD,
        "boss": 10 * GOLD, "event": 15 * GOLD, "duell": 1 * GOLD, "erkundung": 2 * GOLD}
SELL_BASE = {"grau": 10 * SILVER, "weiss": 50 * SILVER, "gruen": 1 * GOLD, "blau": 3 * GOLD, "lila": 8 * GOLD,
             "orange": 20 * GOLD, "rot": 50 * GOLD}
BACKPACK = 16
MAX_BAGS = 4
BAG_NAMES = {4: "Leinenbeutel", 6: "Wollbeutel", 8: "Runenstoff-Tasche", 10: "Magiestoff-Tasche", 12: "Netherstoff-Tasche"}


def _rng(*parts) -> random.Random:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def sell_price(item: dict) -> int:
    """Händlerpreis in Kupfer: Seltenheit × Stufenfaktor (Stufe 200 = 1,0)."""
    return int(round(SELL_BASE[item["rarity"]] * item["ilvl"] / 200, -2))


def earnings(data: dict, start: date) -> list[tuple[date, int, str]]:
    """Gold-Einnahmen ab Starttag: (Tag, Kupfer, Quelle)."""
    out: list[tuple[date, int, str]] = [(start, START_CAPITAL, "Startkapital")]
    runs, workouts = data["runs"], data["workouts"]
    if not runs.empty:
        for r in runs[runs["day"] >= start].itertuples():
            out.append((r.day, int(round(r.distance_km * EARN["km"], -2)), "Lauf"))
    if not workouts.empty:
        for w in workouts[workouts["day"] >= start].itertuples():
            out.append((w.day, EARN["kraft"], "Krafttraining"))
    for wk in data["quest_weeks"]:
        for q in wk["quests"]:
            if q["done"] and date.fromisoformat(q["done_on"]) >= start:
                out.append((date.fromisoformat(q["done_on"]), EARN["auftrag"], "Auftrag"))
    for d in (data.get("daily") or {}).get("xp", []):
        if d[0] >= start:
            out.append((d[0], EARN["taeglich"], "Tagesaufgabe"))
    for b in data["bosses"]:
        if b["defeated"]:
            out.append((date.fromisoformat(b["defeated_on"]), EARN["boss"], "Boss"))
    for dg in data["dungeons"]:
        if dg["cleared"]:
            out.append((date.fromisoformat(dg["date"]), EARN["instanz"], "Instanz"))
    for e in data["events"]:
        if e["done"]:
            out.append((date.fromisoformat(e["done_on"]), EARN["event"], "Event"))
    for d in data["duels"]:
        if d["won"]:
            out.append((date.fromisoformat(d["date"]), EARN["duell"], "Duell"))
    from .hero_world import RIDE_FACTOR as ride  # Erkundungs-Gold aus Radfunden zählt halb
    for r in data.get("world", {}).get("regions", []):
        if r["discovered"] and date.fromisoformat(r["discovered_on"]) >= start:
            gold = int(r.get("gold", 2) * GOLD * (ride if r.get("via") == "rad" else 1))
            out.append((date.fromisoformat(r["discovered_on"]), gold, "Erkundung zu Rad" if r.get("via") == "rad" else "Erkundung"))
    for p in data.get("world", {}).get("pois", []):
        if p["found"] and p["gold"] and date.fromisoformat(p["found_on"]) >= start:
            gold = int(p["gold"] * GOLD * (ride if p.get("via") == "rad" else 1))
            out.append((date.fromisoformat(p["found_on"]), gold, "Erkundung zu Rad" if p.get("via") == "rad" else "Erkundung"))
    for dg in data.get("world", {}).get("dungeons", []):
        if dg["cleared"] and date.fromisoformat(dg["cleared_on"]) >= start:
            out.append((date.fromisoformat(dg["cleared_on"]), dg["gold"] * GOLD, "Erkundung"))
    return out


def bag_drops(data: dict) -> list[dict]:
    """Taschen als seltene Beute: bezwungene Instanzen 25 %, besiegte Bosse 40 % (geseedet, stabil)."""
    out = []
    sizes = {"normal": [4, 6], "heroisch": [6, 8], "mythisch": [8, 10]}
    for dg in data["dungeons"]:
        rng = _rng("bag", dg["id"])
        if dg["cleared"] and rng.random() < 0.25:
            size = rng.choice(sizes[dg["tier"]])
            out.append({"id": f"bag:{dg['id']}", "name": BAG_NAMES[size], "slots": size, "date": dg["date"],
                        "source": f"Instanz „{dg['name']}“"})
    for b in data["bosses"]:
        rng = _rng("bag", b["month"], b["key"])
        if b["defeated"] and rng.random() < 0.40:
            size = rng.choice([6, 8, 10])
            out.append({"id": f"bag:boss:{b['month']}:{b['key']}", "name": BAG_NAMES[size], "slots": size,
                        "date": b["defeated_on"], "source": f"Boss „{b['name']}“"})
    return out


def capacity(bags: list[dict]) -> tuple[int, list[dict]]:
    """Rucksack + die besten 4 Taschen (automatisch angelegt)."""
    used = sorted(bags, key=lambda b: -b["slots"])[:MAX_BAGS]
    return BACKPACK + sum(b["slots"] for b in used), used


def money(copper: int) -> str:
    g, rest = divmod(abs(copper), GOLD)
    s, c = divmod(rest, SILVER)
    parts = [f"{g}g" if g else "", f"{s}s" if s else "", f"{c}k" if c or not (g or s) else ""]
    return ("−" if copper < 0 else "") + " ".join(p for p in parts if p)


# --- Auktionshaus & Tränke ---------------------------------------------------------------
POTIONS = {
    "ausdauer": ("Trank der Ausdauer", "+10 % Trainings-EP für den Tag", 4 * GOLD, "🧪"),
    "erholung": ("Elixier der Erholung", "+120 Ruhebonus sofort", 3 * GOLD, "⚗️"),
    "glueck": ("Glückstrank", "+10 % Glücksfund-Chance für den Tag", 6 * GOLD, "🍀"),
}
AH_MOUNTS = [("ah_esel", "Störrischer Packesel", "🫏", 40 * GOLD), ("ah_kamel", "Goldener Kamelhengst", "🐫", 120 * GOLD),
             ("ah_pfau", "Prunkvoller Pfau", "🦚", 80 * GOLD)]
BAG_PRICES = {6: 6 * GOLD, 8: 10 * GOLD, 10: 15 * GOLD}


def auction_stock(week: date, level: int, make_item) -> list[dict]:
    """Wochenangebot (geseedet je ISO-Woche): 6 Gegenstände, 1 Tasche, evtl. ein Reittier."""
    rng = _rng("auction", week.isoformat())
    out = []
    for i in range(6):
        rarity = rng.choices(["gruen", "blau", "lila", "orange"], weights=[35, 40, 20, 5])[0]
        item = make_item(_rng("ah-item", week.isoformat(), i), rarity, week, level)
        item = {**item, "id": f"ah:{week.isoformat()}:{i}", "source": "auktion", "reason": "Im Auktionshaus erstanden"}
        out.append({"idx": i, "kind": "item", "item": item, "price": sell_price(item) * 4})
    size = rng.choice([6, 8, 10])
    out.append({"idx": 6, "kind": "bag", "price": BAG_PRICES[size],
                "bag": {"id": f"bag:ah:{week.isoformat()}", "name": BAG_NAMES[size], "slots": size, "source": "Auktionshaus"}})
    if rng.random() < 0.20:
        key, name, glyph, price = rng.choice(AH_MOUNTS)
        out.append({"idx": 7, "kind": "mount", "price": price, "mount": {"key": key, "name": name, "glyph": glyph}})
    return out
