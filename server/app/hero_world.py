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
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from .config import settings
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
SIGHT_M = 300.0  # Sichtweite: so weit um die Spur lichtet sich der Nebel
POI_REACH_M = [0.0, 0.0, 0.0]  # gefunden, sobald ein aufgedecktes Feld (Mitte) ≤ 150 m entfernt ist = in Sichtweite
DUNGEON_FILE = Path(__file__).with_name("hero_dungeons.json")
DUNGEON_TYPES = {"wasser": "Wasser", "wald": "Wald", "aue": "Aue", "deich": "Deich & Festung", "feld": "Feld", "dorf": "Dorf"}
COVER_M = 50.0       # Abstand, in dem ein Streckenpunkt als gelaufen gilt
COVER_SHARE = 0.8    # Anteil eines Abschnitts für den Sieg
SEEN_M = CELL_M      # Verlies erscheint, sobald aufgedeckte Zellen die Strecke berühren
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
                            "xp": 5 * level, "provisional": False})
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
                    "loot": dungeon_loot(level, bool(heroic_days)), "segments": seg_out, "provisional": False})
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


LOOP_CLOSE_M = 300.0     # Start und Ende so nah beieinander = geschlossene Runde
LOOP_MAX_KM2 = 40.0      # Schutz gegen GPS-Ausreißer
NEAR_M = 1500.0          # bis hierhin meldet die Karte „du warst schon auf X m dran“


_SIGHT_K = int(SIGHT_M // CELL_M) + 1


def _sight(x: float, y: float) -> list[tuple[int, int]]:
    """Zellen, deren Mitte von (x, y) aus in Sichtweite liegt (inkl. der eigenen Zelle)."""
    ci, cj = math.floor(x / CELL_M), math.floor(y / CELL_M)
    out = [(ci, cj)] if math.hypot(x, y) <= WORLD_RADIUS_M else []
    for i in range(ci - _SIGHT_K, ci + _SIGHT_K + 1):
        for j in range(cj - _SIGHT_K, cj + _SIGHT_K + 1):
            cx, cy = (i + 0.5) * CELL_M, (j + 0.5) * CELL_M
            if (i, j) != (ci, cj) and math.hypot(cx - x, cy - y) <= SIGHT_M and math.hypot(cx, cy) <= WORLD_RADIUS_M:
                out.append((i, j))
    return out


def _loop_cells(meters: list[tuple[float, float]]) -> list[tuple[int, int]]:
    """Zellen im Inneren einer geschlossenen Runde (gerade-ungerade-Regel, Hin-und-zurück bleibt leer)."""
    if len(meters) < 10 or math.hypot(meters[0][0] - meters[-1][0], meters[0][1] - meters[-1][1]) > LOOP_CLOSE_M:
        return []
    poly = meters[::3] + [meters[-1]]
    area = abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]))) / 2
    if area < CELL_M * CELL_M or area > LOOP_MAX_KM2 * 1e6:
        return []
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    edges = list(zip(poly, poly[1:] + poly[:1]))
    out = []
    for i in range(math.floor(min(xs) / CELL_M), math.floor(max(xs) / CELL_M) + 1):
        for j in range(math.floor(min(ys) / CELL_M), math.floor(max(ys) / CELL_M) + 1):
            cx, cy = (i + 0.5) * CELL_M, (j + 0.5) * CELL_M
            if math.hypot(cx, cy) > WORLD_RADIUS_M:
                continue
            inside = False
            for (x1, y1), (x2, y2) in edges:
                if (y1 > cy) != (y2 > cy) and cx < (x2 - x1) * (cy - y1) / (y2 - y1) + x1:
                    inside = not inside
            if inside:
                out.append((i, j))
    return out


def _closest(cells: dict, points: list[tuple[float, float]]) -> int | None:
    """Kleinster Abstand (m, auf 10 gerundet) einer aufgedeckten Zelle zu den Punkten, None jenseits NEAR_M."""
    k = int(NEAR_M // CELL_M) + 1
    best = None
    for x, y in points:
        ci, cj = math.floor(x / CELL_M), math.floor(y / CELL_M)
        for i in range(ci - k, ci + k + 1):
            for j in range(cj - k, cj + k + 1):
                if (i, j) in cells:
                    d = math.hypot((i + 0.5) * CELL_M - x, (j + 0.5) * CELL_M - y)
                    if best is None or d < best:
                        best = d
    return None if best is None or best > NEAR_M else int(round(best, -1))


def _reveal(meters: list[tuple[float, float]], day: str, cells: dict) -> None:
    """Sichtweite entlang der Spur + Inneres geschlossener Runden aufdecken (Zelle → frühester Tag)."""
    if len(meters) == 1:
        for key in _sight(*meters[0]):
            cells[key] = min(cells.get(key, day), day)
    for (x1, y1), (x2, y2) in zip(meters, meters[1:]):
        steps = max(1, int(math.hypot(x2 - x1, y2 - y1) // (CELL_M / 2)))
        for i in range(steps + 1):
            x, y = x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps
            for key in _sight(x, y):
                cells[key] = min(cells.get(key, day), day)
    for key in _loop_cells(meters):  # geschlossene Runde: Fläche dazwischen ist mit aufgedeckt
        cells[key] = min(cells.get(key, day), day)


def _poi_hits(cells: dict, p: dict) -> list[str]:
    reach = POI_REACH_M[p["ring"]]
    k = int(reach // CELL_M) + 1
    ci, cj = math.floor(p["x"] / CELL_M), math.floor(p["y"] / CELL_M)
    return [cells[(i, j)] for i in range(ci - k, ci + k + 1) for j in range(cj - k, cj + k + 1)
            if (i, j) in cells and math.hypot((i + 0.5) * CELL_M - p["x"], (j + 0.5) * CELL_M - p["y"]) <= reach + CELL_M]


def _build(home, routes) -> tuple[dict, dict]:
    cells: dict[tuple[int, int], str] = {}  # Zelle → Tag der Entdeckung
    lines, routes_m = [], []
    for day, pts in routes:
        meters = [_to_m(home, lat, lon) for lat, lon in pts]
        routes_m.append((day.isoformat(), meters))
        lines.append({"date": day.isoformat(), "points": [[round(x), round(y)] for x, y in meters[::5]]})
        _reveal(meters, day.isoformat(), cells)
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
                 discovered=r["name"] in found, discovered_on=f.get("first"), provisional=False)
    places = []
    for p in pois():
        hits = _poi_hits(cells, p)
        places.append({**p, "reach_m": POI_REACH_M[p["ring"]], "found": bool(hits), "found_on": min(hits) if hits else None,
                       "closest_m": 0 if hits else _closest(cells, [(p["x"], p["y"])]), "provisional": False})
    dgs = dungeons(home, routes_m, cells)
    for d, dg in zip(dgs, dungeon_defs()):
        if d["discovered"]:
            d["closest_m"] = 0
        else:
            pts = [_to_m(home, la, lo) for seg in dg["segments"] for la, lo in seg["points"]]
            d["closest_m"] = _closest(cells, pts[::6])
    for d in dgs:  # ohne Entdeckung bleibt die Strecke im Nebel
        if not d["discovered"]:
            d["segments"] = [{**s, "points": []} for s in d["segments"]]
    value = {"available": True, "cell_m": CELL_M, "radius_m": WORLD_RADIUS_M, "core_m": CORE_M,
             "rings": [{"name": n, "outer_m": o} for n, o, *_ in RINGS],
             "cells": [[i, j] for (i, j) in cells], "routes": lines, "regions": regions, "pois": places, "dungeons": dgs,
             "explored_pct": round(100 * len(cells) / max(1, sum(total.values())), 3),
             "km2": round(len(cells) * CELL_M * CELL_M / 1e6, 2), "live": None}
    return value, cells


def world() -> dict:
    routes = _routes()
    home = _home(routes)
    if home is None:
        return {"available": False}
    key = (home, tuple((d, len(p), p[0], p[-1]) for d, p in routes))
    if _memo.get("key") != key:
        value, cells = _build(home, routes)
        _memo.update(key=key, value=value, home=home, base_cells=cells, cellset=set(cells), tilesets={},
                     live_key=(), live_value=value, tracks=[])
    tracks = _live_tracks()
    lkey = _track_key(tracks)
    if _memo.get("live_key") != lkey:  # Live-Overlay nur neu rechnen, wenn neue Punkte kamen
        live = _overlay(tracks) if tracks else None
        _memo.update(live_key=lkey, live_value=live["value"] if live else _memo["value"], tracks=tracks,
                     cellset=set(_memo["base_cells"]) | set(live["cells"] if live else ()), tilesets={})
    return _memo["live_value"]


_memo: dict = {}


# --- Live-Positionen (vorläufig) -----------------------------------------------------------------
# Uhr/Handy senden während des Laufs Positionen. Sie decken die Karte VORLÄUFIG auf: Funde tragen
# `provisional: true`, die Wahrheitsfelder (found/discovered/cleared) bleiben unverändert, damit kein
# Verbraucher (EP, Gold, Beute, Log, Erfolge) Live-Daten belohnt. Die Garmin-Spur ersetzt sie: deckt
# eine Garmin-Route den Zeitraum einer Session ab, werden deren Punkte gelöscht, spätestens nach 48 h.
LIVE_TTL_MS = 48 * 3600 * 1000
LIVE_MAX_ACC_M = 100.0     # schlechtere GPS-Genauigkeit wird verworfen
LIVE_MAX_SPEED = 15.0      # m/s; schnellere Sprünge zum letzten Punkt = GPS-Ausreißer
LIVE_FUTURE_MS = 5 * 60 * 1000
TARGET_PREFIX = "live_target:"
_live_memo: dict = {}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _norm_ts(ts: float) -> int:
    """Epoch-Sekunden oder -Millisekunden → Millisekunden."""
    return int(ts * 1000) if ts < 1e11 else int(ts)


def _track_key(tracks) -> tuple:
    return tuple((sid, len(pts), pts[-1][0]) for sid, pts in tracks)


def _route_span(route) -> tuple[int, int] | None:
    """UTC-Zeitraum (ms) einer Garmin-Route: Punktzeiten, sonst Start + Dauer."""
    times = []
    try:
        for seg in json.loads(route.segments_json):
            for p in seg:
                if p.get("time"):
                    times.append(datetime.fromisoformat(p["time"]).timestamp())
    except (ValueError, TypeError, AttributeError):
        times = []
    if times:
        return int(min(times) * 1000), int(max(times) * 1000)
    try:
        start = (datetime.fromisoformat(route.started_at_utc) if route.started_at_utc
                 else route.started_at.replace(tzinfo=ZoneInfo(settings.timezone)))
    except (ValueError, TypeError):
        return None
    dur = route.elapsed_duration_seconds or route.duration_seconds or 0
    return int(start.timestamp() * 1000), int((start.timestamp() + dur) * 1000)


def purge_live(now_ms: int | None = None) -> list[str]:
    """Löscht Sessions, die eine Garmin-Route abdeckt oder deren letzter Punkt > 48 h alt ist (+ ihre Ziele)."""
    from sqlalchemy import delete, func

    from .garmin_routes import GarminRoute
    from .hero import HeroLivePoint, HeroState
    now_ms = now_ms if now_ms is not None else _now_ms()
    with Session(engine) as s:
        spans = s.exec(select(HeroLivePoint.session, func.min(HeroLivePoint.ts), func.max(HeroLivePoint.ts))
                       .group_by(HeroLivePoint.session)).all()
        drop = {sid for sid, _, hi in spans if hi < now_ms - LIVE_TTL_MS}
        rest = [(sid, lo, hi) for sid, lo, hi in spans if sid not in drop]
        if rest:
            since = datetime.fromtimestamp(min(lo for _, lo, _ in rest) / 1000, ZoneInfo(settings.timezone))
            since = since.replace(tzinfo=None) - timedelta(days=2)
            route_spans = [sp for r in s.exec(select(GarminRoute).where(GarminRoute.started_at >= since)).all()
                           if (sp := _route_span(r))]
            drop |= {sid for sid, lo, hi in rest if any(a <= hi and b >= lo for a, b in route_spans)}
        alive = {sid for sid, _, _ in spans} - drop
        for row in s.exec(select(HeroState).where(HeroState.key.startswith(TARGET_PREFIX, autoescape=True))).all():
            sid = row.key[len(TARGET_PREFIX):]
            try:
                set_at = json.loads(row.value).get("set_at", 0)
            except ValueError:
                set_at = 0
            if sid in drop or (sid not in alive and set_at < now_ms - LIVE_TTL_MS):
                s.delete(row)
        if drop:
            s.exec(delete(HeroLivePoint).where(HeroLivePoint.session.in_(drop)))
        s.commit()
    return sorted(drop)


def _live_tracks() -> list[tuple[str, list[tuple[int, float, float]]]]:
    """Offene Sessions als (session, [(ts, lat, lon)]) — nur wenn die Live-Schnittstelle an ist."""
    if not settings.hero_live_token:
        return []
    from .hero import HeroLivePoint
    try:
        purge_live()
        with Session(engine) as s:
            rows = s.exec(select(HeroLivePoint.session, HeroLivePoint.ts, HeroLivePoint.lat, HeroLivePoint.lon)
                          .order_by(HeroLivePoint.session, HeroLivePoint.ts)).all()
    except OperationalError:  # Tabelle fehlt (DB ohne init_db)
        return []
    out: dict[str, list] = {}
    for sid, ts, lat, lon in rows:
        out.setdefault(sid, []).append((ts, lat, lon))
    return list(out.items())


def ingest_live(session_id: str, points: list[dict], now_ms: int | None = None) -> dict:
    """Nimmt einen Stapel Positionen an; verwirft ungenaue (> 100 m), veraltete und Sprünge > 15 m/s."""
    from .hero import HeroLivePoint
    now_ms = now_ms if now_ms is not None else _now_ms()
    accepted = rejected = 0
    with Session(engine) as s:
        last = s.exec(select(HeroLivePoint).where(HeroLivePoint.session == session_id)
                      .order_by(HeroLivePoint.ts.desc()).limit(1)).first()
        prev = (last.ts, last.lat, last.lon) if last else None
        received = datetime.now(timezone.utc).replace(tzinfo=None)
        for ts, p in sorted(((_norm_ts(q["ts"]), q) for q in points), key=lambda tq: tq[0]):
            ok = p["acc"] <= LIVE_MAX_ACC_M and now_ms - LIVE_TTL_MS <= ts <= now_ms + LIVE_FUTURE_MS
            if ok and prev:
                dt = (ts - prev[0]) / 1000
                dx, dy = _to_m((prev[1], prev[2]), p["lat"], p["lon"])
                ok = dt > 0 and math.hypot(dx, dy) / dt <= LIVE_MAX_SPEED
            if not ok:
                rejected += 1
                continue
            s.add(HeroLivePoint(session=session_id, ts=ts, lat=p["lat"], lon=p["lon"], acc=p["acc"], received_at=received))
            prev = (ts, p["lat"], p["lon"])
            accepted += 1
        s.commit()
    return {"session": session_id, "accepted": accepted, "rejected": rejected}


def _overlay(tracks) -> dict:
    """Weltkarte + vorläufige Aufdeckung aus Live-Spuren (gemerkt je Basis- und Live-Stand)."""
    mkey = (_memo["key"], _track_key(tracks))
    if mkey in _live_memo:
        return _live_memo[mkey]
    home, base_cells, base = _memo["home"], _memo["base_cells"], _memo["value"]
    tz = ZoneInfo(settings.timezone)
    live: dict[tuple[int, int], str] = {}
    routes_m, lines = [], []
    for sid, pts in tracks:
        day = datetime.fromtimestamp(pts[0][0] / 1000, tz).date().isoformat()
        meters = [_to_m(home, lat, lon) for _, lat, lon in pts]
        routes_m.append((day, meters))
        lines.append({"session": sid, "date": day, "points": [[round(x), round(y)] for x, y in meters]})
        _reveal(meters, day, live)
    new = {c: d for c, d in live.items() if c not in base_cells}
    finds = []
    per_region: dict[str, int] = {}
    for i, j in new:
        name = region_of((i + 0.5) * CELL_M, (j + 0.5) * CELL_M)
        if name:
            per_region[name] = per_region.get(name, 0) + 1
    regions = []
    for r in base["regions"]:
        n = per_region.get(r["name"], 0)
        if n:
            r = {**r, "live_cells": n, "provisional": not r["discovered"]}
            if r["provisional"]:
                finds.append({"kind": "gebiet", "id": f"region:{r['name']}", "name": r["name"], "xp": r["xp"]})
        regions.append(r)
    places = []
    for p in base["pois"]:
        if not p["found"] and _poi_hits(live, p):
            p = {**p, "provisional": True, "closest_m": 0}
            finds.append({"kind": p["kind"], "id": p["id"], "name": p["name"], "xp": p["xp"]})
        places.append(p)
    dgs = []
    for d, ld in zip(base["dungeons"], dungeons(home, routes_m, live)):
        if not ld["discovered"]:
            dgs.append(d)
            continue
        segs = []
        for si, (sg, ls) in enumerate(zip(d["segments"], ld["segments"])):
            sg = {**sg, "live_coverage": ls["coverage"]}
            if not d["discovered"]:  # vorläufig entdeckt: Strecke zeigen
                sg["points"] = ls["points"]
            if ls["cleared"] and not sg["cleared"]:
                sg["provisional"] = True
                finds.append({"kind": "abschnitt", "id": f"{d['id']}:{si}", "name": f"{sg['boss']} ({d['name']})", "xp": sg["xp"]})
            segs.append(sg)
        d = {**d, "segments": segs}
        if not d["discovered"]:
            d.update(provisional=True, closest_m=0)
            finds.append({"kind": "verlies_entdeckt", "id": d["id"], "name": d["name"], "xp": 0})
        if not d["cleared"] and all(sg["cleared"] or sg["provisional"] for sg in segs):
            d["provisional_cleared"] = True
            finds.append({"kind": "verlies", "id": d["id"], "name": d["name"], "xp": d["xp"]})
        dgs.append(d)
    for f in finds:
        f["provisional"] = True
    value = {**base, "regions": regions, "pois": places, "dungeons": dgs,
             "live": {"sessions": [sid for sid, _ in tracks], "cells": [[i, j] for i, j in new], "routes": lines,
                      "km2": round(len(new) * CELL_M * CELL_M / 1e6, 2)}}
    out = {"value": value, "cells": new, "finds": finds}
    if len(_live_memo) >= 4:
        _live_memo.clear()
    _live_memo[mkey] = out
    return out


def _bearing(x: float, y: float, tx: float, ty: float) -> tuple[int, int]:
    """(Richtung in Grad ab Nord im Uhrzeigersinn, Entfernung in m)."""
    return round((math.degrees(math.atan2(tx - x, ty - y)) + 360) % 360) % 360, round(math.hypot(tx - x, ty - y))


def _get_target(session_id: str) -> dict | None:
    from .hero import HeroState
    with Session(engine) as s:
        row = s.get(HeroState, TARGET_PREFIX + session_id)
    try:
        return json.loads(row.value) if row else None
    except ValueError:
        return None


def set_live_target(session_id: str | None, kind: str | None, ref: str | None) -> str:
    """Setzt (oder löscht mit kind=None) das Ziel einer Session; ohne Session die zuletzt aktive.
    ValueError = keine offene Session, KeyError = unbekanntes Ziel."""
    from .hero import HeroState
    if session_id is None:
        tracks = _live_tracks()
        if not tracks:
            raise ValueError("Keine laufende Session.")
        session_id = max(tracks, key=lambda t: t[1][-1][0])[0]
    if kind is not None:
        ids = ({p["id"] for p in pois()} if kind == "poi"
               else {f"dungeon:{d['key']}" for d in dungeon_defs()} if kind == "dungeon" else set())
        if ref not in ids:
            raise KeyError(ref)
    with Session(engine) as s:
        row = s.get(HeroState, TARGET_PREFIX + session_id)
        if kind is None:
            if row:
                s.delete(row)
        else:
            value = json.dumps({"kind": kind, "id": ref, "set_at": _now_ms()})
            row = row or HeroState(key=TARGET_PREFIX + session_id, value=value)
            row.value = value
            s.add(row)
        s.commit()
    return session_id


def _target_point(item: dict, kind: str, pos) -> tuple[float, float]:
    """Zielpunkt: Ort selbst; Verlies = nächster Punkt eines offenen, sichtbaren Abschnitts, sonst Mitte."""
    if kind == "dungeon":
        pts = [p for sg in item["segments"] if not (sg["cleared"] or sg["provisional"]) for p in sg["points"]]
        if pts and pos:
            return min(pts, key=lambda p: math.hypot(p[0] - pos[0], p[1] - pos[1]))
    return item["x"], item["y"]


def live_state(session_id: str) -> dict:
    """Kompakter Stand für Uhr/Handy — nur Meter, Grad und Namen, keine Koordinaten."""
    out = {"session": session_id, "available": False, "active": False, "points": 0, "first_ts": None, "last_ts": None,
           "revealed": {"cells": 0, "km2": 0.0}, "finds": [], "target": None, "dungeon": None}
    if not world().get("available"):
        return out
    out["available"] = True
    track = [t for t in _memo.get("tracks", []) if t[0] == session_id]
    view, pos = _memo["value"], None
    if track:
        ov = _overlay(track)
        pts = track[0][1]
        view, pos = ov["value"], _to_m(_memo["home"], pts[-1][1], pts[-1][2])
        out.update(active=True, points=len(pts), first_ts=pts[0][0], last_ts=pts[-1][0], finds=ov["finds"],
                   revealed={"cells": len(ov["cells"]), "km2": round(len(ov["cells"]) * CELL_M * CELL_M / 1e6, 2)})
    by_id = {p["id"]: ("poi", p) for p in view["pois"]} | {d["id"]: ("dungeon", d) for d in view["dungeons"]}
    chosen = _get_target(session_id)
    if chosen and chosen.get("id") in by_id:
        kind, item = by_id[chosen["id"]]
    elif pos:
        open_ = [("poi", p) for p in view["pois"] if not (p["found"] or p["provisional"])]
        open_ += [("dungeon", d) for d in view["dungeons"] if not (d["cleared"] or d.get("provisional_cleared"))]
        if not open_:
            return out
        kind, item = min(open_, key=lambda ki: math.hypot(*(a - b for a, b in zip(_target_point(ki[1], ki[0], pos), pos))))
        chosen = None
    else:
        return out
    target = {"kind": kind, "id": item["id"], "name": item["name"], "chosen": chosen is not None,
              "label": item["kind_label"] if kind == "poi" else "Verlies", "level": item["level"],
              "bearing_deg": None, "distance_m": None}
    if pos:
        target["bearing_deg"], target["distance_m"] = _bearing(*pos, *_target_point(item, kind, pos))
    out["target"] = target
    if kind == "dungeon":
        out["dungeon"] = {"id": item["id"], "name": item["name"], "discovered": item["discovered"],
                          "cleared": item["cleared"], "provisional": item["provisional"],
                          "provisional_cleared": bool(item.get("provisional_cleared")),
                          "segments": [{"boss": sg["boss"], "coverage": max(sg["coverage"], sg.get("live_coverage", 0.0)),
                                        "cleared": sg["cleared"], "provisional": sg["provisional"]}
                                       for sg in item["segments"]]}
    return out


# --- Kartenkacheln im aufgedeckten Bereich ------------------------------------------------------
# OSM-Standardkacheln, serverseitig geholt und dauerhaft unter data/hero_tiles gecacht. Die API
# spricht nur relative Kachel-Schlüssel („z_dx_dy“ zur Heimatkachel) — keine absoluten Koordinaten.
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_UA = "Milon/1.0 (personal fitness dashboard; single user)"
TILE_DIR = Path(__file__).resolve().parents[2] / "data" / "hero_tiles"
TILE_Z = (11, 17)
TILE_MAX = 160
_tile_gate = threading.BoundedSemaphore(2)  # OSM-Richtlinie: höchstens 2 parallele Verbindungen
# Stichproben je Zelle (in Zellbreiten, inkl. Maskenrand) – dicht genug für die kleinsten Kacheln (z17 ≈ 190 m)
_TILE_PROBE = [(-0.5 + a * 0.5, -0.5 + b * 0.5) for a in range(5) for b in range(5)]


def _from_m(home, x: float, y: float) -> tuple[float, float]:
    return home[0] + y / 110_540, home[1] + x / (111_320 * math.cos(math.radians(home[0])))


def _tile_of(lat: float, lon: float, z: int) -> tuple[float, float]:
    n = 2 ** z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def _tile_bounds(tx: int, ty: int, z: int) -> tuple[float, float, float, float]:
    """(lat_nord, lon_west, lat_süd, lon_ost) einer Kachel."""
    n = 2 ** z
    lat = lambda y: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))  # noqa: E731
    return lat(ty), tx / n * 360 - 180, lat(ty + 1), (tx + 1) / n * 360 - 180


def _explored() -> tuple | None:
    if "home" not in _memo:
        if not world().get("available"):
            return None
    return _memo["home"], _memo["cellset"]


def _tileset(z: int) -> set[tuple[int, int]]:
    """Kacheln, die aufgedeckte Zellen berühren (inkl. weichem Maskenrand)."""
    home, cells = _explored()
    cache = _memo.setdefault("tilesets", {})
    if z not in cache:
        out = set()
        for i, j in cells:
            for dx, dy in _TILE_PROBE:  # inkl. weichem Maskenrand
                lat, lon = _from_m(home, (i + dx) * CELL_M, (j + dy) * CELL_M)
                tx, ty = _tile_of(lat, lon, z)
                out.add((int(tx), int(ty)))
        cache[z] = out
    return cache[z]


def tiles(x0: float, y0: float, x1: float, y1: float, px: int) -> dict:
    """Kacheln für einen Kartenausschnitt (Meter relativ zur Heimat, y nach Norden)."""
    ex = _explored()
    if ex is None:
        return {"z": None, "tiles": []}
    home = ex[0]
    mpp = max(1e-3, (x1 - x0) / max(1, px))
    z = round(math.log2(40_075_016 * math.cos(math.radians(home[0])) / (256 * mpp)))
    z = max(TILE_Z[0], min(TILE_Z[1], z))
    while True:
        (ax, ay), (bx, by) = _tile_of(*_from_m(home, x0, y1), z), _tile_of(*_from_m(home, x1, y0), z)
        found = [(tx, ty) for tx, ty in _tileset(z) if int(ax) <= tx <= int(bx) and int(ay) <= ty <= int(by)]
        if len(found) <= TILE_MAX or z == TILE_Z[0]:
            break
        z -= 1
    hx, hy = (int(v) for v in _tile_of(home[0], home[1], z))
    out = []
    for tx, ty in found[:TILE_MAX]:
        north, west, south, east = _tile_bounds(tx, ty, z)
        xw, yn = _to_m(home, north, west)
        xe, ys = _to_m(home, south, east)
        out.append({"key": f"{z}_{tx - hx}_{ty - hy}", "x": round(xw, 1), "y": round(-yn, 1),
                    "w": round(xe - xw, 1), "h": round(yn - ys, 1)})
    return {"z": z, "tiles": out}


def tile_png(key: str) -> bytes | None:
    """PNG einer Kachel im aufgedeckten Bereich (sonst None); holt sie einmalig von OSM."""
    try:
        z, dx, dy = (int(v) for v in key.split("_"))
    except ValueError:
        return None
    ex = _explored()
    if ex is None or not TILE_Z[0] <= z <= TILE_Z[1]:
        return None
    hx, hy = (int(v) for v in _tile_of(ex[0][0], ex[0][1], z))
    tx, ty = hx + dx, hy + dy
    if (tx, ty) not in _tileset(z):
        return None
    path = TILE_DIR / str(z) / str(tx) / f"{ty}.png"
    if path.exists():
        return path.read_bytes()
    with _tile_gate:
        req = urllib.request.Request(TILE_URL.format(z=z, x=tx, y=ty), headers={"User-Agent": TILE_UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data
