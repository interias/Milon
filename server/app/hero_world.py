"""Heldenreise: Weltkarte — echte GPS-Routen decken eine Karte im Nebel auf.

Gitter aus ~150-m-Zellen um den häufigsten Startpunkt („Heimat"). Gebiete = Kern (≤ 1,2 km)
plus 8 Himmelsrichtungs-Sektoren mit Namen aus Wesel. Die API liefert ausschließlich Meter
relativ zur Heimat — keine absoluten Koordinaten.
"""
from __future__ import annotations

import json
import math
from datetime import date

from sqlmodel import Session, select

from .db import engine

CELL_M = 150.0
WORLD_RADIUS_M = 6000.0
CORE_M = 1200.0
DISCOVER_XP = 50
# Sektoren im Uhrzeigersinn ab Nord (je 45°).
SECTORS = ["Diersfordter Forst", "Blumenkamp", "Schepersfeld", "Fusternberg", "Lippe-Mündung", "Büdericher Insel", "Rheinauen", "Flüren"]
CORE = "Zitadelle"


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


def region_of(x: float, y: float) -> str:
    if math.hypot(x, y) <= CORE_M:
        return CORE
    angle = (math.degrees(math.atan2(x, y)) + 360 + 22.5) % 360  # 0° = Nord, im Uhrzeigersinn
    return SECTORS[int(angle // 45)]


def world() -> dict:
    routes = _routes()
    home = _home(routes)
    if home is None:
        return {"available": False}
    cells: dict[tuple[int, int], str] = {}  # Zelle → Tag der Entdeckung
    lines = []
    for day, pts in routes:
        meters = [_to_m(home, lat, lon) for lat, lon in pts]
        lines.append({"date": day.isoformat(), "points": [[round(x), round(y)] for x, y in meters[::5]]})
        for (x1, y1), (x2, y2) in zip(meters, meters[1:]):
            steps = max(1, int(math.hypot(x2 - x1, y2 - y1) // (CELL_M / 2)))
            for i in range(steps + 1):
                x, y = x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps
                if math.hypot(x, y) <= WORLD_RADIUS_M:
                    cells.setdefault((math.floor(x / CELL_M), math.floor(y / CELL_M)), day.isoformat())
    # Gesamtzellen je Gebiet innerhalb des Weltradius
    n = int(WORLD_RADIUS_M // CELL_M) + 1
    total: dict[str, int] = {}
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            cx, cy = (i + 0.5) * CELL_M, (j + 0.5) * CELL_M
            if math.hypot(cx, cy) <= WORLD_RADIUS_M:
                total[region_of(cx, cy)] = total.get(region_of(cx, cy), 0) + 1
    found: dict[str, dict] = {}
    for (i, j), day in cells.items():
        name = region_of((i + 0.5) * CELL_M, (j + 0.5) * CELL_M)
        f = found.setdefault(name, {"cells": 0, "first": day})
        f["cells"] += 1
        f["first"] = min(f["first"], day)
    regions = [{"name": name, "cells": found.get(name, {}).get("cells", 0), "total": total.get(name, 1),
                "pct": round(100 * found.get(name, {}).get("cells", 0) / total.get(name, 1), 1),
                "discovered": name in found, "discovered_on": found.get(name, {}).get("first")}
               for name in [CORE, *SECTORS]]
    return {"available": True, "cell_m": CELL_M, "radius_m": WORLD_RADIUS_M, "core_m": CORE_M,
            "cells": [[i, j] for (i, j) in cells], "routes": lines, "regions": regions,
            "explored_pct": round(100 * len(cells) / max(1, sum(total.values())), 2),
            "km2": round(len(cells) * CELL_M * CELL_M / 1e6, 2)}
