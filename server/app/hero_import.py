"""Heldenreise: eigene Strecken per GPX — als eigenes Verlies oder als gelaufene Spur.

`import_gpx(content, mode)` nimmt GPX-Bytes (Track oder Route) und einen Modus:
- `dungeon`: Die Strecke wird zum privaten Verlies (2–4 Abschnitte nach Länge, Name/Bosse/Region
  generiert, Stufe wie `hero_world.dungeon_level`). Es erscheint in `hero_world.dungeon_defs()` und
  damit in `world()["dungeons"]` mit `own: true`. Abschnitte zählen nur durch Läufe ab dem Importtag,
  sonst brächte der Import einer schon gelaufenen Strecke rückwirkend EP und Beute.
- `track` (nur mit Zeitstempeln): Die Spur deckt den Nebel auf wie eine Garmin-Route. Überschneidet
  sie sich zeitlich mit einer Garmin-Route, gewinnt Garmin (in `hero_world.world()` ausgewertet). Sie
  zählt nirgends als Lauf (keine Pace, Bestzeiten, Erfolge).

Eigene Strecken liegen nur in der lokalen DB (`hero_own_routes`), sind privat und löschbar. Die
Rückgaben enthalten keine Koordinaten.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.exc import OperationalError
from sqlmodel import Field, Session, SQLModel, select

from .config import settings
from .garmin_routes import MAX_GPX_BYTES, parse_gpx

MODES = ("dungeon", "track")
MIN_LENGTH_M = 2000.0
RESAMPLE_M = 30.0       # Verlies-Punktabstand wie bei den OSM-Verliesen
TRACK_STEP_M = 10.0     # Spur ausdünnen
OWN_TYPE = "eigen"
OWN_TYPE_LABEL = "Eigene Strecke"
BOSSES = ["Wegelagerer", "Pfadwächter", "Meilenfresser", "Kreuzungsgeist", "Grenzsteinhüter", "Wanderschatten",
          "Kilometerkobold", "Steigungstroll"]
NAMES = ["Eigener Pfad von {r}", "Verborgene Fährte bei {r}", "Schleichweg durch {r}", "Geheimer Kurs von {r}",
         "Selbstgezogene Spur bei {r}", "Kartenläufers Weg durch {r}"]


class HeroOwnRoute(SQLModel, table=True):
    """Eigene, per GPX importierte Strecke (privat, nur lokal)."""
    __tablename__ = "hero_own_routes"

    id: str = Field(primary_key=True)
    kind: str                      # "dungeon" | "track"
    name: str
    created_on: str                # lokaler Importtag (ISO), ab dem ein eigenes Verlies bezwungen werden kann
    created_at: datetime
    length_m: float
    start_ms: int | None = None    # Spur: UTC-Zeitraum
    end_ms: int | None = None
    day: str | None = None         # Spur: lokaler Tag des Starts
    data_json: str                 # Verlies: Definition wie hero_dungeons.json; Spur: [[lat, lon], …]


class Duplicate(ValueError):
    """Dieselbe Datei wurde im selben Modus schon importiert."""


def _local_today() -> str:
    return datetime.now(ZoneInfo(settings.timezone)).date().isoformat()


def _resample(meters: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    out, carry = [meters[0]], 0.0
    for (x1, y1), (x2, y2) in zip(meters, meters[1:]):
        d = math.hypot(x2 - x1, y2 - y1)
        pos = step - carry
        while pos <= d:
            t = pos / d
            out.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
            pos += step
        carry = (carry + d) % step if d else carry
    if out[-1] != meters[-1]:
        out.append(meters[-1])
    return out


def _length(meters: list[tuple[float, float]]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(meters, meters[1:]))


def _parse(content: bytes) -> list[dict]:
    if not isinstance(content, bytes) or not content:
        raise ValueError("Die Datei ist leer.")
    if len(content) > MAX_GPX_BYTES:
        raise ValueError("Die Datei ist zu groß (höchstens 10 MiB).")
    try:
        segments = parse_gpx(content)
    except ValueError as exc:
        raise ValueError(f"Keine lesbare GPX-Datei: {exc}") from exc
    return [p for seg in segments for p in seg]


def _dungeon_def(rid: str, digest: str, home, meters, length: float, taken: set[str]) -> dict:
    from . import hero_world
    pts = _resample(meters, RESAMPLE_M)
    nseg = 2 if length < 3500 else 3 if length < 7000 else 4
    per = len(pts) // nseg
    rng = random.Random(digest + ":own")
    bosses = rng.sample(BOSSES, nseg)
    cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    region = hero_world.region_of(cx, cy) or "der Ferne"
    base = rng.choice(NAMES).format(r=region)
    name, n = base, 2
    while name in taken:
        name, n = f"{base} {n}", n + 1
    segs = []
    for i in range(nseg):
        part = pts[i * per: (i + 1) * per + 1] if i < nseg - 1 else pts[i * per:]
        segs.append({"boss": bosses[i],
                     "points": [[round(la, 5), round(lo, 5)] for la, lo in (hero_world._from_m(home, x, y) for x, y in part)]})
    return {"key": rid, "name": name, "type": OWN_TYPE, "own": True,
            "desc": f"Eine selbst geplante Strecke über {length / 1000:.1f} km – {nseg} Abschnitte, nur auf deiner Karte.".replace(".", ",", 1),
            "length_m": round(length), "segments": segs}


def import_gpx(content: bytes, mode: str, *, engine=None, now: datetime | None = None) -> dict:
    """Importiert GPX-Bytes als eigenes Verlies (`dungeon`) oder gelaufene Spur (`track`).

    ValueError = unbrauchbare Datei (Meldung für Menschen), Duplicate = schon importiert."""
    from . import hero_world
    engine = engine or hero_world.engine
    if mode not in MODES:
        raise ValueError("Unbekannter Modus – erlaubt sind „dungeon“ (Verlies) und „track“ (gelaufene Spur).")
    points = _parse(content)
    home = hero_world._home(hero_world._routes())
    if home is None:
        raise ValueError("Die Weltkarte ist noch nicht verfügbar – sie entsteht mit dem ersten Garmin-Lauf mit GPS.")
    meters = [hero_world._to_m(home, p["lat"], p["lon"]) for p in points]
    if any(math.hypot(x, y) > hero_world.WORLD_RADIUS_M for x, y in meters):
        raise ValueError(f"Die Strecke liegt (teilweise) außerhalb der Weltkarte – erlaubt sind "
                         f"{hero_world.WORLD_RADIUS_M / 1000:.0f} km um die Heimat.")
    length = _length(meters)
    if length < MIN_LENGTH_M:
        raise ValueError(f"Die Strecke ist zu kurz ({length / 1000:.1f} km) – mindestens 2 km.".replace(".", ",", 1))

    digest = hashlib.sha256(content).hexdigest()
    rid = f"{'eigen' if mode == 'dungeon' else 'spur'}-{digest[:12]}"
    now = now or datetime.now(timezone.utc)
    row = HeroOwnRoute(id=rid, kind=mode, name="", created_on=_local_today(), created_at=now.replace(tzinfo=None),
                       length_m=round(length), data_json="")
    if mode == "track":
        times = [datetime.fromisoformat(p["time"]).timestamp() for p in points if p.get("time")]
        if len(times) < max(2, len(points) // 2):
            raise ValueError("Die Datei hat keine Zeitstempel – eine gelaufene Spur braucht sie. "
                             "Importiere sie stattdessen als eigenes Verlies.")
        start, end = min(times), max(times)
        if end <= start:
            raise ValueError("Die Zeitstempel der Datei sind unbrauchbar (keine Dauer).")
        if start > (now + timedelta(days=1)).timestamp():
            raise ValueError("Die Spur liegt in der Zukunft – eine gelaufene Spur muss schon gelaufen sein.")
        day = datetime.fromtimestamp(start, ZoneInfo(settings.timezone)).date()
        thin = [points[0]]
        for p, m, prev in zip(points[1:], meters[1:], [meters[0]] + meters[1:-1]):
            if math.hypot(m[0] - prev[0], m[1] - prev[1]) >= TRACK_STEP_M or p is points[-1]:
                thin.append(p)
        row.name = f"Gelaufene Spur vom {day.strftime('%d.%m.%Y')}"
        row.start_ms, row.end_ms, row.day = int(start * 1000), int(end * 1000), day.isoformat()
        row.data_json = json.dumps([[round(p["lat"], 6), round(p["lon"], 6)] for p in thin])
    with Session(engine) as session:
        if session.get(HeroOwnRoute, rid) is not None:
            raise Duplicate("Diese Datei ist schon importiert.")
        if mode == "dungeon":
            taken = {d["name"] for d in hero_world.dungeon_defs()}
            dg = _dungeon_def(rid, digest, home, meters, length, taken)
            row.name, row.data_json = dg["name"], json.dumps(dg, ensure_ascii=False)
        session.add(row)
        session.commit()
    return summary(rid, engine=engine)


def _rows(engine) -> list[HeroOwnRoute]:
    try:
        with Session(engine) as session:
            return list(session.exec(select(HeroOwnRoute).order_by(HeroOwnRoute.created_at)).all())
    except OperationalError:  # Tabelle fehlt (DB ohne init_db, z. B. ältere Test-DB)
        return []


def own_dungeon_defs(engine) -> list[dict]:
    out = []
    for r in _rows(engine):
        if r.kind != "dungeon":
            continue
        try:
            dg = json.loads(r.data_json)
        except ValueError:
            continue
        out.append({**dg, "own": True, "since": r.created_on})
    return out


def own_tracks(engine) -> list[dict]:
    """Gelaufene Spuren: id, Tag, Zeitraum (UTC-ms) und Punkte (lat, lon)."""
    out = []
    for r in _rows(engine):
        if r.kind != "track" or r.day is None:
            continue
        try:
            pts = [(float(a), float(b)) for a, b in json.loads(r.data_json)]
        except (ValueError, TypeError):
            continue
        if len(pts) >= 2:
            out.append({"id": r.id, "day": r.day, "start_ms": r.start_ms, "end_ms": r.end_ms, "points": pts})
    return out


def _view(r: HeroOwnRoute, world: dict) -> dict:
    out = {"id": r.id, "kind": r.kind, "name": r.name, "own": True, "length_km": round(r.length_m / 1000, 1),
           "created_on": r.created_on}
    if r.kind == "track":
        out.update(day=r.day, superseded=r.id in set(world.get("own_superseded", [])))
    else:
        d = next((x for x in world.get("dungeons", []) if x["key"] == r.id), None)
        if d:
            out.update(key=d["key"], level=d["level"], region=d["region"], segments=len(d["segments"]),
                       discovered=d["discovered"], cleared=d["cleared"])
    return out


def list_own(engine=None) -> list[dict]:
    from . import hero_world
    engine = engine or hero_world.engine
    w = hero_world.world()
    return [_view(r, w) for r in _rows(engine)][::-1]


def summary(rid: str, engine=None) -> dict:
    return next(x for x in list_own(engine) if x["id"] == rid)


def delete_own(rid: str, engine=None) -> bool:
    from . import hero_world
    engine = engine or hero_world.engine
    with Session(engine) as session:
        row = session.get(HeroOwnRoute, rid)
        if row is None:
            return False
        session.delete(row)
        session.commit()
    return True
