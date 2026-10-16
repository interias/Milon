"""Heldenreise: Titel, Ruf bei Fraktionen und Set-Boni — reine Berechnung aus Kennzahlen."""
from __future__ import annotations

# Ruf-Stufen wie in WoW (Untergrenze, Name).
REP_LEVELS = [(0, "Neutral"), (3000, "Freundlich"), (9000, "Wohlwollend"), (18000, "Respektvoll"), (30000, "Ehrfürchtig")]
FACTIONS = [
    ("laeufergilde", "Läufergilde von Wesel", "Lauf-EP", "laufen"),
    ("eisenbund", "Eisenbund", "Kraft-EP", "kraft"),
    ("tafelrunde", "Tafelrunde der Versorger", "50 Ruf je Tag mit Protein-Ziel", "protein_days"),
    ("orden", "Orden der stillen Nacht", "50 Ruf je Nacht ab 7 h", "sleep_nights"),
]


def reputation(stats: dict) -> list[dict]:
    out = []
    for key, name, source, stat in FACTIONS:
        value = stats[stat] * (50 if stat in ("protein_days", "sleep_nights") else 1)
        idx = max(i for i, (floor, _) in enumerate(REP_LEVELS) if value >= floor)
        floor, standing = REP_LEVELS[idx]
        nxt = REP_LEVELS[idx + 1][0] if idx + 1 < len(REP_LEVELS) else None
        out.append({"key": key, "name": name, "source": source, "value": round(value), "standing": standing,
                    "rank": idx, "floor": floor, "next": nxt,
                    "progress": round((value - floor) / (nxt - floor), 3) if nxt else 1.0})
    return out


# (key, Titel, Bedingung, Kennzahl, Ziel)
TITLES = [
    ("laeufer_vom_rhein", "Läufer vom Rhein", "50 Läufe", "runs", 50),
    ("kilometerfresser", "Kilometerfresser", "500 km gelaufen", "km", 500),
    ("tausendmeiler", "Tausendmeiler", "1.609 km gelaufen", "km", 1609),
    ("fruehaufsteher", "Frühaufsteher", "20 Läufe vor 8 Uhr", "early_runs", 20),
    ("eiserner_wille", "Eiserner Wille", "100 Krafttrainings", "workouts", 100),
    ("unermuedliche_seele", "Unermüdliche Seele", "30 Tage Trainingsserie", "streak", 30),
    ("auftragsmeister", "Auftragsmeister", "10 Wochenaufträge erfüllt", "quests_done", 10),
    ("bossbezwinger", "Bossbezwinger", "einen Monatsboss besiegen", "bosses_down", 1),
    ("schlachtzugsleiter", "Schlachtzugsleiter", "alle 4 Bosse eines Monats besiegen", "full_raids", 1),
    ("dungeonmeister", "Dungeonmeister", "5 Instanzen bezwingen", "dungeons_cleared", 5),
    ("schatzhueter", "Schatzhüter", "10 Gegenstände besitzen", "items", 10),
    ("legendenjaeger", "Legendenjäger", "einen legendären Gegenstand besitzen", "legendaries", 1),
    ("held_von_wesel", "Held von Wesel", "Stufe 40 erreichen", "level", 40),
    ("kartograf", "Kartograf", "5 Gebiete der Weltkarte entdecken", "regions", 5),
    ("weltenwanderer", "Weltenwanderer", "9 Gebiete der Weltkarte entdecken", "regions", 9),
    ("verliesgaenger", "Verliesgänger", "5 Strecken-Verliese bezwingen", "map_dungeons", 5),
    ("heroischer_pfadfinder", "Heroischer Pfadfinder", "3 Verliese heroisch (in einem Lauf) bezwingen", "map_heroic", 3),
    ("seenwaechter", "Seenwächter", "3 Wasser-Verliese bezwingen", "map_wasser", 3),
    ("hueter_der_waelder", "Hüter der Wälder", "3 Wald-Verliese bezwingen", "map_wald", 3),
    ("dorfchronist", "Dorfchronist", "5 Dorf-Verliese bezwingen", "map_dorf", 5),
    ("deichgraf", "Deichgraf", "beide Deich-Verliese bezwingen", "map_deich", 2),
    ("auenlaeufer", "Auenläufer", "3 Auen-Verliese bezwingen", "map_aue", 3),
    ("feldherr", "Feldherr", "3 Feld-Verliese bezwingen", "map_feld", 3),
    ("herr_der_marken", "Herr der Marken", "alle 25 Gebiete der Weltkarte entdecken", "regions", 25),
    ("ehrfuerchtig", "Der Ehrfürchtige", "bei einer Fraktion Ehrfürchtig", "exalted", 1),
]


def titles(stats: dict, chosen: str | None) -> list[dict]:
    return [{"key": k, "name": n, "condition": c, "value": min(stats.get(s, 0), t), "target": t,
             "earned": stats.get(s, 0) >= t, "chosen": k == chosen} for k, n, c, s, t in TITLES]


SET_COLORS = ["#ff7d0a", "#3fc7eb", "#aad372", "#f48cba", "#fff468", "#c41e3a", "#a330c9", "#00ff98"]


def sets(items: list[dict]) -> list[dict]:
    """Sets = gleicher Namenszusatz. Ab 2 angelegten Teilen Aura, ab 4 pulsierende Aura (rein optisch)."""
    groups: dict[str, dict] = {}
    for it in items:
        name = it.get("set")
        if not name:
            continue
        g = groups.setdefault(name, {"name": f"Garnitur {name}", "suffix": name, "owned": 0, "equipped": 0, "slots": set()})
        g["owned"] += 1
        g["slots"].add(it["slot"])
        g["equipped"] += 1 if it.get("equipped") else 0
    out = []
    for g in sorted(groups.values(), key=lambda g: (-g["equipped"], -g["owned"], g["suffix"])):
        out.append({"name": g["name"], "suffix": g["suffix"], "owned": g["owned"], "equipped": g["equipped"],
                    "color": SET_COLORS[sum(map(ord, g["suffix"])) % len(SET_COLORS)],
                    "bonus": "pulsierende Aura" if g["equipped"] >= 4 else "Aura" if g["equipped"] >= 2 else None})
    return out
