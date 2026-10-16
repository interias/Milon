"""Heldenreise: Weltkarte — echte GPS-Routen decken eine Karte im Nebel auf.

Gitter aus ~150-m-Zellen um den häufigsten Startpunkt („Heimat"). Gebiete = Kern (≤ 1,2 km)
plus drei Ringe (Nahland bis 6 km, Grenzland bis 15 km, Fernland bis 30 km) mit je 8
Himmelsrichtungs-Sektoren. Im Nebel liegen Schreine und Schätze (geseedete Punkte) und
**Verliese als echte Strecken** (`hero_dungeons.json`, aus OSM-Wegen per BRouter gebaut): 2–4
Abschnitte je Verlies, jeder Abschnitt ein Boss, bezwungen ab 80 % Abdeckung durch einen Lauf.
Stufe steigt mit der Entfernung. Die API liefert ausschließlich Meter relativ zur Heimat.
"""
from __future__ import annotations

import json
import math
import random
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlmodel import Session, select

from .db import engine

CELL_M = 150.0
CORE_M = 1200.0
WORLD_RADIUS_M = 30_000.0
CORE = "Zitadelle"
# Sektoren im Uhrzeigersinn ab Nord (je 45°). Ring: (Name, Außenradius, Gebiete, EP, Gold in g)
SECTORS = ["Diersfordter Forst", "Blumenkamp", "Schepersfeld", "Fusternberg", "Lippe-Mündung", "Büdericher Insel", "Rheinauen", "Flüren"]
RINGS = [
    ("Nahland", 6_000.0, SECTORS, 50, 2),
    ("Grenzland", 15_000.0, ["Hamminkeln", "Brünen", "Hünxe", "Voerde", "Rheinberg", "Alpen", "Xanten", "Mehrhoog"], 100, 4),
    ("Fernland", WORLD_RADIUS_M, ["Bocholt", "Borken", "Schermbeck", "Oberhausen", "Moers", "Geldern", "Kalkar", "Rees"], 150, 6),
]
DISCOVER_XP = RINGS[0][3]
# Entdeckungsradius eines Ortes je Ring (Kern = Nahland)
POI_REACH_M = [250.0, 400.0, 600.0]
DUNGEON_FILE = Path(__file__).with_name("hero_dungeons.json")
DUNGEON_TYPES = {"wasser": "Wasser", "wald": "Wald", "aue": "Aue", "deich": "Deich & Festung", "feld": "Feld", "dorf": "Dorf"}
COVER_M = 50.0       # Abstand, in dem ein Streckenpunkt als gelaufen gilt
COVER_SHARE = 0.8    # Anteil eines Abschnitts für den Sieg
SEEN_M = 300.0       # Verlies erscheint, wenn erkundete Zellen so nah an der Strecke liegen
SHRINES = ["Schrein des Windes", "Schrein der Stille", "Schrein der Morgenröte", "Schrein der Quelle", "Schrein der Eiche",
           "Schrein der Ausdauer", "Schrein der Sterne", "Schrein des Flusses", "Schrein der Heide"]
TREASURES = ["Vergrabene Truhe", "Schmugglerversteck", "Verlorener Beutel", "Alte Kiste", "Glitzernder Schatz", "Hort im Wurzelwerk"]
KIND_LABEL = {"schrein": "Schrein", "schatz": "Schatz"}
SHRINE_XP, TREASURE_XP = 100, 25


def _routes() -> list[tuple[date, list[tuple[float, float]]]]:
    from .garmin_routes import GarminRoute
    out = []
    with Session(engine) as session:
        for r in session.exec(select(GarminRoute)).all():
            try:
                segments = json.loads(r.segments_json)
            except ValueError:
                continue
            pts = [(p["lat"], p["lon"]) for seg in segments for p in seg if "lat" in p and "lon" in p]
            if len(pts) >= 2:
                out.append((r.started_at.date(), pts))
    return sorted(out, key=lambda x: x[0])


def _home(routes) -> tuple[float, float] | None:
    """Häufigster Startpunkt (auf ~300 m gerundet), gemittelt."""
    if not routes:
        return None
    buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for _, pts in routes:
        lat, lon = pts[0]
        buckets.setdefault((round(lat * 333), round(lon * 213)), []).append((lat, lon))
    best = max(buckets.values(), key=len)
    return sum(p[0] for p in best) / len(best), sum(p[1] for p in best) / len(best)


def _to_m(home, lat, lon) -> tuple[float, float]:
    x = (lon - home[1]) * 111_320 * math.cos(math.radians(home[0]))
    y = (lat - home[0]) * 110_540
    return x, y


def ring_of(x: float, y: float) -> int:
    """-1 = Kern, 0..2 = Ring, 3 = außerhalb der Welt."""
    r = math.hypot(x, y)
    if r <= CORE_M:
        return -1
    return next((i for i, ring in enumerate(RINGS) if r <= ring[1]), len(RINGS))


def region_of(x: float, y: float) -> str | None:
    ring = ring_of(x, y)
    if ring < 0:
        return CORE
    if ring >= len(RINGS):
        return None
    angle = (math.degrees(math.atan2(x, y)) + 360 + 22.5) % 360  # 0° = Nord, im Uhrzeigersinn
    return RINGS[ring][2][int(angle // 45)]


def poi_level(dist_m: float) -> int:
    """Stufe eines Ortes: je weiter weg, desto höher (1 km ≈ 10, 15 km ≈ 41, 30 km ≈ 74)."""
    return max(10, min(80, round(8 + 2.2 * dist_m / 1000)))


def dungeon_loot(level: int, heroic: bool = False) -> str:
    tiers = ["blau", "lila", "orange"]
    idx = 0 if level < 25 else 1 if level < 45 else 2
    return tiers[min(2, idx + (1 if heroic else 0))]


@lru_cache(maxsize=1)
def dungeon_defs() -> list[dict]:
    try:
        return json.loads(DUNGEON_FILE.read_text(encoding="utf-8"))["dungeons"]
    except (OSError, ValueError, KeyError):
        return []


def _route_hash(meters: list[tuple[float, float]]) -> dict[tuple[int, int], list[tuple[float, float]]]:
    """Routenpunkte (auf ≤ 20 m verdichtet) in 50-m-Zellen."""
    grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for (x1, y1), (x2, y2) in zip(meters, meters[1:]):
        steps = max(1, int(math.hypot(x2 - x1, y2 - y1) // 20))
        for i in range(steps + 1):
            x, y = x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps
            grid.setdefault((math.floor(x / COVER_M), math.floor(y / COVER_M)), []).append((x, y))
    return grid


def _coverage(points: list[tuple[float, float]], grid) -> float:
    hit = 0
    for x, y in points:
        ci, cj = math.floor(x / COVER_M), math.floor(y / COVER_M)
        if any(math.hypot(x - a, y - b) <= COVER_M
               for i in (ci - 1, ci, ci + 1) for j in (cj - 1, cj, cj + 1) for a, b in grid.get((i, j), ())):
            hit += 1
    return hit / max(1, len(points))


def dungeons(home, routes_m: list[tuple[str, list[tuple[float, float]]]], cells: dict) -> list[dict]:
    """Strecken-Verliese: Entdeckung über erkundete Zellen, Abschnitte über Abdeckung je Lauf."""
    grids = []
    for day, meters in routes_m:
        xs, ys = [p[0] for p in meters], [p[1] for p in meters]
        grids.append((day, (min(xs) - COVER_M, min(ys) - COVER_M, max(xs) + COVER_M, max(ys) + COVER_M), _route_hash(meters)))
    out = []
    for dg in dungeon_defs():
        segs = [[_to_m(home, la, lo) for la, lo in seg["points"]] for seg in dg["segments"]]
        allp = [p for seg in segs for p in seg]
        cx, cy = sum(p[0] for p in allp) / len(allp), sum(p[1] for p in allp) / len(allp)
        dist = math.hypot(cx, cy)
        level = min(80, poi_level(dist) + min(8, round(dg["length_m"] / 2000)))
        k = int(SEEN_M // CELL_M)
        seen = [cells[(i, j)] for x, y in allp[::3] for i in range(math.floor(x / CELL_M) - k, math.floor(x / CELL_M) + k + 1)
                for j in range(math.floor(y / CELL_M) - k, math.floor(y / CELL_M) + k + 1) if (i, j) in cells]
        seg_out, per_route = [], {}
        for si, (seg, pts) in enumerate(zip(dg["segments"], segs)):
            sx, sy = [p[0] for p in pts], [p[1] for p in pts]
            best, won = 0.0, None
            for ri, (day, (x0, y0, x1, y1), grid) in enumerate(grids):
                if max(sx) < x0 or min(sx) > x1 or max(sy) < y0 or min(sy) > y1:
                    continue
                cov = _coverage(pts, grid)
                best = max(best, cov)
                if cov >= COVER_SHARE:
                    won = min(won or day, day)
                    per_route.setdefault(ri, (day, set()))[1].add(si)
            seg_out.append({"boss": seg["boss"], "points": [[round(x), round(y)] for x, y in pts[::2]],
                            "coverage": round(best, 2), "cleared": won is not None, "cleared_on": won,
                            "xp": 5 * level})
        cleared = all(s["cleared"] for s in seg_out)
        heroic_days = sorted(day for day, idx in per_route.values() if len(idx) == len(seg_out))
        out.append({"id": f"dungeon:{dg['key']}", "key": dg["key"], "name": dg["name"], "type": dg["type"],
                    "type_label": DUNGEON_TYPES.get(dg["type"], dg["type"]), "desc": dg["desc"],
                    "x": round(cx), "y": round(cy), "km": round(dist / 1000, 1), "length_km": round(dg["length_m"] / 1000, 1),
                    "region": region_of(cx, cy), "level": level, "xp": 10 * level, "gold": 2 + level // 10,
                    "discovered": bool(seen) or any(s["coverage"] > 0 for s in seg_out),
                    "discovered_on": min(seen) if seen else None,
                    "cleared": cleared, "cleared_on": max(s["cleared_on"] for s in seg_out) if cleared else None,
                    "heroic": bool(heroic_days), "heroic_on": heroic_days[0] if heroic_days else None,
                    "loot": dungeon_loot(level, bool(heroic_days)), "segments": seg_out})
    return out


@lru_cache(maxsize=1)
def _region_totals() -> dict[str, int]:
    n = int(WORLD_RADIUS_M // CELL_M) + 1
    total: dict[str, int] = {}
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            name = region_of((i + 0.5) * CELL_M, (j + 0.5) * CELL_M)
            if name:
                total[name] = total.get(name, 0) + 1
    return total


@lru_cache(maxsize=1)
def pois() -> list[dict]:
    """Feste Orte im Nebel, geseedet (Polarkoordinaten relativ zur Heimat)."""
    rng = random.Random("milon-world-v1")
    out: list[dict] = []

    def place(region: str, kind: str, name: str, ring: int, a0: float, a1: float, r0: float, r1: float):
        a = math.radians(rng.uniform(a0, a1))
        r = math.sqrt(rng.uniform(r0 * r0, r1 * r1))  # flächengleich verteilt
        x, y = math.sin(a) * r, math.cos(a) * r
        lvl = poi_level(r)
        out.append({"id": f"{kind}:{len(out)}", "kind": kind, "kind_label": KIND_LABEL[kind], "name": name, "region": region,
                    "ring": max(0, ring), "x": round(x), "y": round(y), "km": round(r / 1000, 1), "level": lvl})

    for kind, name in (("schrein", SHRINES[0]), ("schatz", TREASURES[0])):
        place(CORE, kind, f"{name} ({CORE})", -1, 0, 360, 200, CORE_M - 150)
    inner = CORE_M
    for ring, (_, outer, sectors, _, _) in enumerate(RINGS):
        for s, region in enumerate(sectors):
            a0, a1 = s * 45 - 22.5 + 4, s * 45 + 22.5 - 4
            r0, r1 = inner + 300, outer - 300
            place(region, "schrein", f"{rng.choice(SHRINES)} ({region})", ring, a0, a1, r0, r1)
            for t in rng.sample(TREASURES, 2):
                place(region, "schatz", f"{t} ({region})", ring, a0, a1, r0, r1)
        inner = outer
    for p in out:
        lvl = p["level"]
        if p["kind"] == "schrein":
            p.update(xp=SHRINE_XP, gold=0, loot=None)
        else:
            p.update(xp=TREASURE_XP, gold=1 + round(p["km"] * 0.3), loot=None)
    return out


def world() -> dict:
    routes = _routes()
    home = _home(routes)
    if home is None:
        return {"available": False}
    key = (home, tuple((d, len(p), p[0], p[-1]) for d, p in routes))
    if _memo.get("key") == key:
        return _memo["value"]
    cells: dict[tuple[int, int], str] = {}  # Zelle → Tag der Entdeckung
    lines, routes_m = [], []
    for day, pts in routes:
        meters = [_to_m(home, lat, lon) for lat, lon in pts]
        routes_m.append((day.isoformat(), meters))
        lines.append({"date": day.isoformat(), "points": [[round(x), round(y)] for x, y in meters[::5]]})
        for (x1, y1), (x2, y2) in zip(meters, meters[1:]):
            steps = max(1, int(math.hypot(x2 - x1, y2 - y1) // (CELL_M / 2)))
            for i in range(steps + 1):
                x, y = x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps
                if math.hypot(x, y) <= WORLD_RADIUS_M:
                    key = (math.floor(x / CELL_M), math.floor(y / CELL_M))
                    cells[key] = min(cells.get(key, day.isoformat()), day.isoformat())
    total = _region_totals()
    found: dict[str, dict] = {}
    for (i, j), day in cells.items():
        name = region_of((i + 0.5) * CELL_M, (j + 0.5) * CELL_M)
        if not name:
            continue
        f = found.setdefault(name, {"cells": 0, "first": day})
        f["cells"] += 1
        f["first"] = min(f["first"], day)
    regions = [{"name": CORE, "ring": 0, "ring_label": RINGS[0][0], "xp": DISCOVER_XP, "gold": RINGS[0][4]}]
    regions += [{"name": name, "ring": i, "ring_label": ring[0], "xp": ring[3], "gold": ring[4]}
                for i, ring in enumerate(RINGS) for name in ring[2]]
    for r in regions:
        f = found.get(r["name"], {})
        r.update(cells=f.get("cells", 0), total=total.get(r["name"], 1),
                 pct=round(100 * f.get("cells", 0) / total.get(r["name"], 1), 1),
                 discovered=r["name"] in found, discovered_on=f.get("first"))
    places = []
    for p in pois():
        reach = POI_REACH_M[p["ring"]]
        k = int(reach // CELL_M) + 1
        ci, cj = math.floor(p["x"] / CELL_M), math.floor(p["y"] / CELL_M)
        hits = [cells[(i, j)] for i in range(ci - k, ci + k + 1) for j in range(cj - k, cj + k + 1)
                if (i, j) in cells and math.hypot((i + 0.5) * CELL_M - p["x"], (j + 0.5) * CELL_M - p["y"]) <= reach + CELL_M / 2]
        places.append({**p, "reach_m": reach, "found": bool(hits), "found_on": min(hits) if hits else None})
    dgs = dungeons(home, routes_m, cells)
    for d in dgs:  # ohne Entdeckung bleibt die Strecke im Nebel
        if not d["discovered"]:
            d["segments"] = [{**s, "points": []} for s in d["segments"]]
    value = {"available": True, "cell_m": CELL_M, "radius_m": WORLD_RADIUS_M, "core_m": CORE_M,
            "rings": [{"name": n, "outer_m": o} for n, o, *_ in RINGS],
            "cells": [[i, j] for (i, j) in cells], "routes": lines, "regions": regions, "pois": places, "dungeons": dgs,
            "explored_pct": round(100 * len(cells) / max(1, sum(total.values())), 3),
            "km2": round(len(cells) * CELL_M * CELL_M / 1e6, 2)}
    _memo.update(key=key, value=value)
    return value


_memo: dict = {}
