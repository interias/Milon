"""Zwift worlds: map bounds, ride tracks as map positions, cached map images.

Bounds and image URLs come from the MIT-licensed package zwift-data 2.1.2 (© 2021 Andi Pätzold,
github.com/andipaetzold/zwift-data). A world's map image spans exactly its bounds, linear in lat/lon.

A track is stored as positions on the map image (x, y in 0..1 from the top-left corner), never as
latitude/longitude. Positions are only kept for rides whose points lie inside one known world, so a
ride with real GPS can never leave a real place in the database. The images belong to Zwift: they are
fetched once from Zwift's CDN into data/zwift_maps/ (gitignored) and never shipped with the repo."""
from __future__ import annotations

import io
import math
import threading
import urllib.request
from pathlib import Path

from .config import DATA_DIR

MAP_DIR = DATA_DIR / "zwift_maps"
MAP_MAX_EDGE = 4096          # the originals are up to 8192 px wide
MIN_SHARE = 0.6              # share of a ride's points inside one world, else no track
MIN_STEP = 0.0004            # thinning: next point at least this far from the last kept one (≈ 3 px on 8192)
MAX_JUMP = 0.05              # larger jumps between samples start a new segment (teleport, world edge)

# (slug, name, (lat, lon) top-left corner, (lat, lon) bottom-right corner, image file on Zwift's CDN)
WORLDS = [
    ("watopia", "Watopia", (-11.62597, 166.87747), (-11.74087, 167.03255), "MiniMap_Watopia_2.png"),
    ("richmond", "Richmond", (37.5774, -77.48954), (37.5014, -77.394), "MiniMap_Richmond.png"),
    ("london", "London", (51.5362, -0.1776), (51.4601, -0.0555), "MiniMap_London.png"),
    ("new-york", "New York", (40.817257, -74.022655), (40.587913, -73.922165), "MiniMap_NewYork_2.png"),
    ("innsbruck", "Innsbruck", (47.2947, 11.3501), (47.2055, 11.4822), "MiniMap_Innsbruck.png"),
    ("bologna", "Bologna", (44.5308037, 11.26261748), (44.45463821, 11.36991729102076), "MiniMap_Bologna.png"),
    ("yorkshire", "Yorkshire", (54.0254, -1.632), (53.9491, -1.5022), "MiniMap_Yorkshire.png"),
    ("crit-city", "Crit City", (-10.3657, 165.7824), (-10.4038, 165.8207), "MiniMap_CritCity.png"),
    ("makuri-islands", "Makuri Islands", (-10.73746, 165.76591), (-10.85234, 165.88222), "MiniMap_Japan.png"),
    ("france", "France", (-21.64155, 166.1384), (-21.7564, 166.26125), "MiniMap_France.png"),
    ("paris", "Paris", (48.9058, 2.2561), (48.82945, 2.3722), "MiniMap_Champs.png"),
    ("scotland", "Scotland", (55.67595, -5.2802), (55.61845, -5.17798), "MiniMap_Scotland.png"),
]
BY_SLUG = {w[0]: w for w in WORLDS}
BY_NAME = {w[1]: w for w in WORLDS}
IMAGE_URL = "https://cdn.zwift.com/static/images/maps/{}"
_fetch_gate = threading.Lock()


def _position(world, lat: float, lon: float) -> tuple[float, float] | None:
    _, _, (lat1, lon1), (lat2, lon2), _ = world
    x, y = (lon - lon1) / (lon2 - lon1), (lat - lat1) / (lat2 - lat1)
    return (x, y) if 0 <= x <= 1 and 0 <= y <= 1 else None


def aspect(slug: str) -> float:
    """Width/height of a world's map (bounds in metres; matches the image, e.g. Watopia 4:3)."""
    _, _, (lat1, lon1), (lat2, lon2), _ = BY_SLUG[slug]
    return abs(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2)) / abs(lat2 - lat1)


def track(points: list[tuple[float, float]]) -> dict:
    """(lat, lon) samples in time order → {"world": slug, "segments": [[[x, y], …], …]} or {} when the
    ride does not clearly lie in one known world. Only map positions leave this function."""
    best, inside = None, []
    for world in WORLDS:
        hits = [p for p in (_position(world, lat, lon) for lat, lon in points) if p is not None]
        if len(hits) > len(inside):
            best, inside = world, hits
    if best is None or len(inside) < 2 or len(inside) < MIN_SHARE * len(points):
        return {}
    segments: list[list[list[float]]] = []
    last = None
    for x, y in inside:
        if last is not None:
            step = math.hypot(x - last[0], y - last[1])
            if step < MIN_STEP:
                continue
            if step > MAX_JUMP:
                last = None
        if last is None:
            segments.append([])
        segments[-1].append([round(x, 5), round(y, 5)])
        last = (x, y)
    segments = [s for s in segments if len(s) >= 2]
    return {"world": best[0], "segments": segments} if segments else {}


def map_image(slug: str) -> bytes | None:
    """JPEG of a world's map (longest edge MAP_MAX_EDGE), fetched once and cached; None = unknown world."""
    world = BY_SLUG.get(slug)
    if world is None:
        return None
    path = MAP_DIR / f"{slug}.jpg"
    if path.exists():
        return path.read_bytes()
    with _fetch_gate:
        if path.exists():
            return path.read_bytes()
        from PIL import Image

        req = urllib.request.Request(IMAGE_URL.format(world[4]), headers={"User-Agent": "Milon/1.0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read()
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        image.thumbnail((MAP_MAX_EDGE, MAP_MAX_EDGE))
        out = io.BytesIO()
        image.save(out, "JPEG", quality=85, optimize=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(f"{path}.tmp")
        tmp.write_bytes(out.getvalue())
        tmp.replace(path)
        return out.getvalue()
