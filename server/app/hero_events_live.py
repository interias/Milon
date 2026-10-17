"""Heldenreise: spontane Ereignisse während eines Abenteuerlaufs (Live-Session mit aktivem Stein).

Mechanik (bewusst ohne Vorankündigung): Bei jedem `live/state` würfelt der Server für die laufende Minute
(geseedet je Session + Minute, also stabil bei häufigem Abfragen). Nie in den ersten 10 Minuten des Laufs,
nie während ein Ereignis läuft, mit Abstand zum letzten und höchstens `max_events(Stufe)` je Lauf. Die Art
zieht ein nach Steinstufe gewichteter Topf; Tempo-Ereignisse sind vorbereitet, aber per Schalter aus.

Ziele entstehen relativ zur aktuellen Position (Meter zur Heimat, nur serverseitig gespeichert); die API
nennt nur Richtung, Entfernung und Restzeit. Live gilt alles als vorläufig: Bestätigt (EP + Beute, Quelle
`events`) wird erst durch die Garmin-Spur im Zeitfenster des Ereignisses; Radspuren nie. Ablehnen,
Verpassen oder fehlende Spur kosten nichts.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Field, Session, SQLModel, select

from . import hero_world
from .config import settings
from .hero_keystone import HeroKeystone

LOCK_MS = 10 * 60_000          # nie in den ersten 10 Minuten des Laufs
GAP_MS = 10 * 60_000           # Abstand nach dem Ende des letzten Ereignisses
ROLL_P = 0.007                 # je Laufminute nach Sperrfrist: ~30 % je 60-min-Lauf (etwa jeder 3.–4. Steinlauf)
REACH_M = 40.0                 # Ziel gilt als erreicht in diesem Abstand
EXPIRE_MS = 24 * 3600 * 1000   # ohne Garmin-Spur verfällt ein Ereignis kostenlos
TOTEM_SECTORS, TOTEM_NEED = 8, 7
TEMPO_EVENTS = False           # zweite Stufe (Tempo-Ereignisse) — vorbereitet, noch aus

# Topf: Gewicht je Stufen-Band (Stufe < 8 | < 15 | ab 15); Tempo-Ereignisse nur mit Schalter.
POT = {
    "schatz": {"tempo": False, "weights": (4, 3, 2)},
    "begleiter": {"tempo": False, "weights": (4, 2, 1)},
    "wegelagerer": {"tempo": False, "weights": (1, 3, 3)},
    "totem": {"tempo": False, "weights": (1, 2, 3)},
    "verfolger": {"tempo": True, "weights": (0, 2, 3)},
    "elite": {"tempo": True, "weights": (0, 1, 3)},
    "echo": {"tempo": True, "weights": (0, 2, 2)},
    "wacht": {"tempo": True, "weights": (0, 1, 2)},
}
BASE_XP = {"schatz": 60, "begleiter": 50, "wegelagerer": 80, "totem": 70}
NAMES = {"schatz": "Flüchtiger Schatz", "begleiter": "Spur des Begleiters", "wegelagerer": "Wegelagerer", "totem": "Totem"}
FINAL = ("confirmed", "rejected", "expired", "declined")
COMPASS = ["Norden", "Nordosten", "Osten", "Südosten", "Süden", "Südwesten", "Westen", "Nordwesten"]


class HeroLiveEvent(SQLModel, table=True):
    __tablename__ = "hero_live_events"

    id: int | None = Field(default=None, primary_key=True)
    session: str = Field(index=True)
    keystone_id: int
    level: int
    kind: str
    text: str
    rolled_ms: int
    expires_ms: int
    target_x: float                # Meter zur Heimat — nur serverseitig, nie in der Antwort
    target_y: float
    radius_m: float = 0.0          # Totem: Schleifenradius
    status: str = "active"         # active | reached | missed | declined | confirmed | rejected | expired
    reached_ms: int | None = None
    result_json: str = "{}"        # xp, loot, activity_id, reached_ms (nach Garmin-Bestätigung)
    resolved_ms: int | None = None


def _rng(*parts) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16], 16))


# --- Bausteine (rein, testbar) -------------------------------------------------------------------

def tier(level: int) -> int:
    return 0 if level < 8 else 1 if level < 15 else 2


def max_events(level: int) -> int:
    return 1 + tier(level)


def pot(level: int, tempo: bool | None = None) -> dict[str, int]:
    tempo = TEMPO_EVENTS if tempo is None else tempo
    return {k: v["weights"][tier(level)] for k, v in POT.items()
            if v["weights"][tier(level)] > 0 and (tempo or not v["tempo"])}


def roll(session_id: str, now_ms: int, run_start_ms: int, level: int, done: int, last_end_ms: int | None,
         tempo: bool | None = None) -> str | None:
    """Würfelt für die laufende Minute; None = kein Ereignis (Sperrfrist, Höchstzahl, Abstand oder Pech)."""
    if now_ms - run_start_ms < LOCK_MS or done >= max_events(level):
        return None
    if last_end_ms is not None and now_ms - last_end_ms < GAP_MS:
        return None
    rng = _rng("liveevent", session_id, now_ms // 60_000)
    if rng.random() >= ROLL_P:
        return None
    weights = pot(level, tempo)
    return rng.choices(list(weights), list(weights.values()))[0]


def xp_for(kind: str, level: int) -> int:
    return round(BASE_XP.get(kind, 50) * (1 + 0.1 * (level - 2)))


def loot_for(level: int) -> str:
    return "gruen" if level < 5 else "blau" if level < 10 else "lila" if level < 15 else "orange"


def _heading(track: list[tuple[int, float, float]]) -> float | None:
    """Laufrichtung (Grad ab Nord) aus den letzten ~60 s der Spur."""
    if len(track) < 2:
        return None
    last = track[-1]
    ref = next((p for p in reversed(track) if last[0] - p[0] >= 60_000), track[0])
    dx, dy = last[1] - ref[1], last[2] - ref[2]
    return None if math.hypot(dx, dy) < 20 else math.degrees(math.atan2(dx, dy)) % 360


def _offset(pos, bearing: float, dist: float) -> tuple[float, float]:
    r = math.radians(bearing)
    return pos[0] + dist * math.sin(r), pos[1] + dist * math.cos(r)


def _compass(bearing: float) -> str:
    return COMPASS[round(bearing / 45) % 8]


def spawn(kind: str, pos: tuple[float, float], heading: float | None, cells: set, rng: random.Random,
          now_ms: int) -> dict | None:
    """Ziel relativ zur Position; None = kein passendes Ziel (z. B. nichts Unaufgedecktes in Reichweite)."""
    h = heading if heading is not None else rng.uniform(0, 360)
    radius = 0.0
    if kind == "schatz":
        dist, b = rng.uniform(250, 500), (h + rng.uniform(-100, 100)) % 360
        target, window = _offset(pos, b, dist), dist / 2.0 * 1000 + 180_000
        text = f"Ein Glitzern im Gras, etwa {round(dist, -1):.0f} m Richtung {_compass(b)}. Es verblasst bald."
    elif kind == "begleiter":
        dist, b = rng.uniform(300, 600), (h + rng.uniform(-60, 60)) % 360
        target, window = _offset(pos, b, dist), 15 * 60_000
        text = f"Dein Begleiter hat eine Fährte gewittert und zieht nach {_compass(b)}. Folge ihm ein Stück."
    elif kind == "totem":
        dist, b = rng.uniform(150, 300), (h + rng.uniform(-45, 45)) % 360
        target, window, radius = _offset(pos, b, dist), 15 * 60_000, round(rng.uniform(60, 100))
        text = f"Ein altes Totem ragt im {_compass(b)} auf. Umrunde es einmal in kleiner Schleife."
    elif kind == "wegelagerer":
        cm = hero_world.CELL_M
        ci, cj = math.floor(pos[0] / cm), math.floor(pos[1] / cm)
        cands = []
        for i in range(ci - 7, ci + 8):
            for j in range(cj - 7, cj + 8):
                cx, cy = (i + 0.5) * cm, (j + 0.5) * cm
                d = math.hypot(cx - pos[0], cy - pos[1])
                if (i, j) not in cells and 300 <= d <= 1000 and math.hypot(cx, cy) <= hero_world.WORLD_RADIUS_M:
                    off = abs((math.degrees(math.atan2(cx - pos[0], cy - pos[1])) - h + 180) % 360 - 180)
                    cands.append((off + rng.uniform(0, 40), (cx, cy)))
        if not cands:
            return None
        target, window = min(cands)[1], 20 * 60_000
        b = math.degrees(math.atan2(target[0] - pos[0], target[1] - pos[1])) % 360
        text = f"Ein Wegelagerer lauert im Nebel Richtung {_compass(b)}. Stell ihn, bevor er verschwindet."
    else:  # Tempo-Ereignisse: Mechanik folgt mit der zweiten Stufe
        return None
    return {"kind": kind, "text": text, "target": target, "radius_m": radius, "expires_ms": now_ms + int(window)}


def achieved(kind: str, target: tuple[float, float], radius_m: float, track: list[tuple[int, float, float]],
             start_ms: int, end_ms: int) -> int | None:
    """Zeitpunkt (ms), an dem die Spur im Fenster das Ereignis erfüllt; None = nicht erfüllt."""
    pts = [p for p in track if start_ms <= p[0] <= end_ms]
    if kind == "totem":
        seen: set[int] = set()
        for ts, x, y in pts:
            d = math.hypot(x - target[0], y - target[1])
            if d <= radius_m + REACH_M:
                seen.add(int((math.degrees(math.atan2(x - target[0], y - target[1])) % 360) // (360 / TOTEM_SECTORS)))
                if len(seen) >= TOTEM_NEED:
                    return ts
        return None
    return next((ts for ts, x, y in pts if math.hypot(x - target[0], y - target[1]) <= REACH_M), None)


def _progress(e: HeroLiveEvent, track: list[tuple[int, float, float]]) -> float | None:
    if e.kind != "totem":
        return None
    seen = {int((math.degrees(math.atan2(x - e.target_x, y - e.target_y)) % 360) // (360 / TOTEM_SECTORS))
            for ts, x, y in track if e.rolled_ms <= ts <= e.expires_ms
            and math.hypot(x - e.target_x, y - e.target_y) <= e.radius_m + REACH_M}
    return round(min(1.0, len(seen) / TOTEM_NEED), 2)


# --- Garmin-Bestätigung ---------------------------------------------------------------------------

def resolve_pending(now_ms: int | None = None) -> int:
    """Bestätigt/verwirft vorläufige Ereignisse anhand der Garmin-Laufspur (Radspuren nie)."""
    from .garmin_routes import GarminRoute
    from .hero_keystone import _route_track
    now_ms = now_ms if now_ms is not None else hero_world._now_ms()
    tz = ZoneInfo(settings.timezone)
    changed = 0
    with Session(hero_world.engine) as s:
        open_ = [e for e in s.exec(select(HeroLiveEvent).where(HeroLiveEvent.status.in_(("active", "reached", "missed"))))
                 if now_ms > e.expires_ms or e.status == "reached"]
        if not open_ or not hero_world.world().get("available"):
            return 0
        home = hero_world._memo["home"]
        since = datetime.fromtimestamp(min(e.rolled_ms for e in open_) / 1000, tz).replace(tzinfo=None) - timedelta(days=1)
        routes = [(sp, r) for r in s.exec(select(GarminRoute).where(GarminRoute.started_at >= since)).all()
                  if (sp := hero_world._route_span(r))]
        for e in open_:
            cover = sorted(((sp, r) for sp, r in routes if sp[0] <= e.expires_ms and sp[1] >= e.rolled_ms), key=lambda x: x[0])
            if cover:
                route = cover[0][1]
                hit = achieved(e.kind, (e.target_x, e.target_y), e.radius_m, _route_track(route, home, e.rolled_ms),
                               e.rolled_ms, e.expires_ms)
                if hit is None:
                    e.status = "rejected"
                    e.result_json = json.dumps({"activity_id": route.activity_id})
                else:
                    e.status = "confirmed"
                    e.result_json = json.dumps({"activity_id": route.activity_id, "reached_ms": hit,
                                                "date": datetime.fromtimestamp(hit / 1000, tz).date().isoformat(),
                                                "xp": xp_for(e.kind, e.level), "loot": loot_for(e.level)})
            elif now_ms - e.expires_ms > EXPIRE_MS:
                e.status = "expired"
            else:
                continue
            e.resolved_ms = now_ms
            s.add(e)
            changed += 1
        s.commit()
    return changed


# --- API-Funktionen -------------------------------------------------------------------------------

def _view(e: HeroLiveEvent, pos, track, now_ms: int) -> dict:
    out = {"id": e.id, "kind": e.kind, "name": NAMES.get(e.kind, e.kind), "text": e.text, "status": e.status,
           "provisional": e.status not in FINAL, "level": e.level, "bearing_deg": None, "distance_m": None,
           "remaining_s": None, "radius_m": e.radius_m or None, "progress": _progress(e, track),
           "reward": {"xp": xp_for(e.kind, e.level), "loot": loot_for(e.level)}}
    if e.status == "active":
        out["remaining_s"] = max(0, round((e.expires_ms - now_ms) / 1000))
        if pos:
            out["bearing_deg"], out["distance_m"] = hero_world._bearing(*pos, e.target_x, e.target_y)
    if e.status == "rejected" or e.status == "expired" or e.status == "declined":
        out["reward"] = None
    return out


def live(session_id: str, track: list[tuple[int, float, float]] | None, keystone: dict | None,
         now_ms: int | None = None) -> dict | None:
    """Ereignis einer Session für `live/state`: würfelt bei aktivem Stein, aktualisiert vorläufig aus den
    Live-Punkten und liefert das jüngste Ereignis (aktiv oder Ergebnis). None = keins."""
    now_ms = now_ms if now_ms is not None else hero_world._now_ms()
    track = track or []
    try:
        resolve_pending(now_ms)
        with Session(hero_world.engine) as s:
            rows = list(s.exec(select(HeroLiveEvent).where(HeroLiveEvent.session == session_id)
                               .order_by(HeroLiveEvent.rolled_ms)).all())
            for e in rows:
                if e.status != "active":
                    continue
                hit = achieved(e.kind, (e.target_x, e.target_y), e.radius_m, track, e.rolled_ms, e.expires_ms)
                if hit is not None:
                    e.status, e.reached_ms = "reached", hit
                elif now_ms > e.expires_ms:
                    e.status = "missed"
                else:
                    continue
                s.add(e)
            stone = s.get(HeroKeystone, keystone["id"]) if keystone else None
            if stone and stone.status == "active" and track and not any(e.status == "active" for e in rows):
                run = [p for p in track if p[0] >= stone.activated_ms]
                mine = [e for e in rows if e.keystone_id == stone.id]
                last_end = max((min(t for t in (e.reached_ms, e.resolved_ms, e.expires_ms) if t) for e in mine), default=None)
                kind = roll(session_id, now_ms, run[0][0], stone.level, len(mine), last_end) if run else None
                ev = spawn(kind, run[-1][1:], _heading(run), hero_world._memo.get("cellset", set()),
                           _rng("liveevent-spawn", session_id, now_ms // 60_000), now_ms) if kind else None
                if ev:
                    row = HeroLiveEvent(session=session_id, keystone_id=stone.id, level=stone.level,
                                        kind=ev["kind"], text=ev["text"], rolled_ms=now_ms, expires_ms=ev["expires_ms"],
                                        target_x=ev["target"][0], target_y=ev["target"][1], radius_m=ev["radius_m"])
                    s.add(row)
                    rows.append(row)
            s.commit()
            for e in rows:
                s.refresh(e)
    except Exception:  # noqa: BLE001 -- Tabelle fehlt (DB ohne init_db): ohne Ereignisse wie bisher
        return None
    if not rows:
        return None
    pos = track[-1][1:] if track else None
    return _view(rows[-1], pos, track, now_ms)


def decline(session_id: str, now_ms: int | None = None) -> bool:
    """Lehnt das aktive Ereignis einer Session ab — kostet nichts."""
    now_ms = now_ms if now_ms is not None else hero_world._now_ms()
    with Session(hero_world.engine) as s:
        rows = list(s.exec(select(HeroLiveEvent).where(HeroLiveEvent.session == session_id, HeroLiveEvent.status == "active")))
        for e in rows:
            e.status, e.resolved_ms = "declined", now_ms
            s.add(e)
        s.commit()
    return bool(rows)


def confirmed() -> list[dict]:
    """Von Garmin bestätigte Ereignisse (für Ledger und Beute in `hero._load`)."""
    resolve_pending()
    with Session(hero_world.engine) as s:
        rows = list(s.exec(select(HeroLiveEvent).where(HeroLiveEvent.status == "confirmed")).all())
    return [{"id": e.id, "kind": e.kind, "name": NAMES.get(e.kind, e.kind), "level": e.level, **json.loads(e.result_json)}
            for e in sorted(rows, key=lambda r: r.rolled_ms)]
