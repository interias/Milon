"""Heldenreise: Abenteuerlauf mit Stein — Mythisch+ je Strecken-Verlies.

Der Nutzer aktiviert vor dem Lauf einen Stein für ein entdecktes Verlies (Stufe frei wählbar bis zur
höchsten je erreichten Steinstufe dieses Verlieses, Start +2). Zeitlimit = Median-Pace der lockeren Läufe
(Z1–Z2, Ø-HF < 80 % HFmax) der letzten 90 Tage × Streckenlänge × (1 + Puffer); der Puffer sinkt mit der
Stufe. Das Ergebnis entscheidet allein die Garmin-Spur nach der Aktivierung: alle Abschnitte (gleiche
Abdeckungsregel wie die Weltkarte) in der Zeit → +1, deutlich schneller → +2, zu langsam → −1 (nie unter
+2). Abbruch, unvollständige Strecke oder keine Spur kosten nichts. Live gilt alles als vorläufig.

Affixe sind nur Beute-Boni, nie Strafen: selbst gewählte (Bedingung aus der Spur), ein Wochen-Affix
(geseedet je ISO-Woche) und Wetter-Affixe (Regen, Wind ≥ 20 km/h, Dunkelheit) aus der Vorhersage.
Die Belohnung selbst (Truhe, Wertung, Titel) ist nicht Teil dieses Moduls; es liefert `loot_bonus`.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Field, Session, SQLModel, select

from . import hero_world
from .config import settings

START_LEVEL = 2
MAX_LEVEL = 30
BUFFER_HI, BUFFER_LO = 0.20, 0.05      # Puffer bei +2 bzw. ab +10
FAST_SHARE = 0.80                      # ≤ 80 % des Zeitlimits = deutlich schneller
EASY_HR_SHARE = 0.80                   # locker = Ø-HF unter Zone 3 (Z1–Z2 der Laufzonen)
EASY_DAYS = 90
DEFAULT_PACE = 7.0                     # min/km, nur ohne jede Laufhistorie
EXPIRE_MS = 24 * 3600 * 1000           # ohne Garmin-Spur verfällt ein Stein kostenlos
ROUTE_WINDOW_MS = 12 * 3600 * 1000     # Garmin-Lauf muss in diesem Fenster nach der Aktivierung starten
STAND_SPEED, STAND_MAX_S = 0.5, 60     # Pausenlos: kein Stillstand > 60 s

# Wählbare Affixe = selbst gewählte Zusatzbedingungen; erfüllt → +1 Beute-Bonus, verfehlt → kein Malus.
AFFIXES = {
    "zeitdruck": {"name": "Zeitdruck", "desc": "Verlies in höchstens 90 % des Zeitlimits"},
    "pausenlos": {"name": "Pausenlos", "desc": "im Verlies nie länger als 60 s stehen bleiben"},
    "negativ": {"name": "Negativer Split", "desc": "zweite Hälfte der Strecke spürbar (≥ 2 %) schneller als die erste"},
    "fruehaufsteher": {"name": "Frühaufsteher", "desc": "Verlies vor 8 Uhr betreten"},
}
WEATHER_AFFIXES = {
    "regen": {"name": "Regen", "desc": "Regen während des Laufs"},
    "sturm": {"name": "Sturm", "desc": "Wind ab 20 km/h"},
    "dunkelheit": {"name": "Dunkelheit", "desc": "Lauf ganz oder teilweise im Dunkeln"},
}
EASY_DEBUFFS = {"uebermuedet": "Übermüdet", "erschoepft": "Erschöpft", "krank": "Krank"}


class HeroKeystone(SQLModel, table=True):
    __tablename__ = "hero_keystones"

    id: int | None = Field(default=None, primary_key=True)
    session: str = Field(index=True)
    dungeon: str = Field(index=True)          # Verlies-Schlüssel (ohne „dungeon:“)
    level: int
    affixes_json: str = "[]"                  # selbst gewählt
    week_affix: str
    weather_json: str = "[]"                  # automatisch, nur Bonus
    activated_ms: int
    time_limit_s: int
    status: str = "active"                    # active | timed | fast | slow | incomplete | aborted | expired
    delta: int = 0                            # Stufenänderung durch das Ergebnis
    result_json: str = "{}"                   # elapsed_s, Abschnitte, erfüllte Affixe, loot_bonus, Lauf
    resolved_ms: int | None = None


# --- Bausteine (rein, testbar) -------------------------------------------------------------------

def buffer_for(level: int) -> float:
    """Zeitpuffer: +2 ≈ 20 %, linear fallend bis +10 ≈ 5 %, darüber 5 %."""
    return max(BUFFER_LO, BUFFER_HI - (BUFFER_HI - BUFFER_LO) * (level - START_LEVEL) / 8)


def easy_pace(runs: list[dict], today: date, hr_max: float) -> dict:
    """Median-Pace (min/km) der lockeren Läufe der letzten 90 Tage.

    Locker = Ø-HF < 80 % HFmax (Z1 Locker + Z2 Grundlage aus `running._ZONE_DEFS`). Ohne ≥ 3 solche
    Läufe: langsamere Hälfte aller Läufe des Zeitraums; ohne Läufe: 7:00/km."""
    since = today - timedelta(days=EASY_DAYS)
    recent = [r for r in runs if since <= r["started_at"].date() <= today and r.get("pace")]
    easy = [r["pace"] for r in recent if r.get("avg_hr") and r["avg_hr"] < EASY_HR_SHARE * hr_max]
    source = "zonen"
    if len(easy) < 3:
        paces = sorted(r["pace"] for r in recent)
        easy, source = paces[len(paces) // 2:], "langsame_haelfte"
    if not easy:
        return {"pace": DEFAULT_PACE, "runs": 0, "source": "standard"}
    easy = sorted(easy)
    mid = len(easy) // 2
    med = easy[mid] if len(easy) % 2 else (easy[mid - 1] + easy[mid]) / 2
    return {"pace": round(med, 3), "runs": len(easy), "source": source}


def time_limit_s(pace_min_km: float, length_m: float, level: int) -> int:
    return round(pace_min_km * 60 * length_m / 1000 * (1 + buffer_for(level)))


def week_affix(day: date) -> str:
    """Wochen-Affix: geseedet je ISO-Woche, stabil innerhalb der Woche."""
    year, week, _ = day.isocalendar()
    keys = sorted(AFFIXES)
    return keys[int(hashlib.sha256(f"keystone-week:{year}-W{week:02d}".encode()).hexdigest(), 16) % len(keys)]


def weather_affixes(hours: list[dict], start: datetime, minutes: float) -> list[str]:
    """Wetter-Affixe aus Stundenwerten (Open-Meteo-Form) im Laufzeitfenster; leer = kein Bonus."""
    lo = start.replace(minute=0, second=0, microsecond=0)
    hi = start + timedelta(minutes=minutes)
    window = []
    for h in hours:
        try:
            t = datetime.fromisoformat(h["time"])
        except (KeyError, TypeError, ValueError):
            continue
        if lo <= t <= hi:
            window.append(h)
    out = []
    if any((h.get("rain_mm") or 0) >= 0.2 or (h.get("rain_prob") or 0) >= 70 for h in window):
        out.append("regen")
    if any((h.get("wind_kmh") or 0) >= 20 for h in window):
        out.append("sturm")
    if any(h.get("is_day") is False for h in window):
        out.append("dunkelheit")
    return out


def history(rows: list[HeroKeystone]) -> dict[str, dict]:
    """Je Verlies: aktuelle Steinstufe (nach Ergebnissen) und höchste je erreichte Stufe (Start +2)."""
    out: dict[str, dict] = {}
    for k in sorted(rows, key=lambda r: r.activated_ms):
        h = out.setdefault(k.dungeon, {"key_level": START_LEVEL, "max_level": START_LEVEL, "runs": 0, "timed": 0})
        if k.status in ("timed", "fast", "slow"):
            h["key_level"] = max(START_LEVEL, min(MAX_LEVEL, k.level + k.delta))
            h["max_level"] = max(h["max_level"], h["key_level"])
            h["runs"] += 1
            h["timed"] += k.status != "slow"
    return out


def judge(elapsed_s: float, limit_s: float, all_segments: bool) -> tuple[str, int]:
    """Ergebnis der Garmin-Spur → (Status, Stufenänderung)."""
    if not all_segments:
        return "incomplete", 0
    if elapsed_s <= FAST_SHARE * limit_s:
        return "fast", 2
    if elapsed_s <= limit_s:
        return "timed", 1
    return "slow", -1


def _section(track: list[tuple[int, float, float]], grid) -> list[tuple[int, float, float]]:
    """Teil der Spur (ts_ms, x, y) zwischen erstem und letztem Punkt nahe der Verlies-Strecke."""
    near = [i for i, (_, x, y) in enumerate(track) if _near(x, y, grid)]
    return track[near[0]:near[-1] + 1] if near else []


def _near(x: float, y: float, grid) -> bool:
    cm = hero_world.COVER_M
    ci, cj = math.floor(x / cm), math.floor(y / cm)
    return any(math.hypot(x - a, y - b) <= cm
               for i in (ci - 1, ci, ci + 1) for j in (cj - 1, cj, cj + 1) for a, b in grid.get((i, j), ()))


def evaluate(track: list[tuple[int, float, float]], segments: list[list[tuple[float, float]]], limit_s: int,
             affixes: list[str], tz: ZoneInfo) -> dict:
    """Wertet eine Spur (ts_ms, x, y — nur Punkte nach der Aktivierung) gegen die Verlies-Strecke aus."""
    route_grid = hero_world._route_hash([(x, y) for _, x, y in track]) if len(track) >= 2 else {}
    coverage = [round(hero_world._coverage(seg, route_grid), 2) if route_grid else 0.0 for seg in segments]
    cleared = [c >= hero_world.COVER_SHARE for c in coverage]
    dungeon_grid = hero_world._route_hash([p for seg in segments for p in seg])
    sec = _section(track, dungeon_grid)
    elapsed = (sec[-1][0] - sec[0][0]) / 1000 if len(sec) >= 2 else None
    done = {}
    if elapsed is not None:
        stand, worst = 0.0, 0.0
        dist = [0.0]
        for (t1, x1, y1), (t2, x2, y2) in zip(sec, sec[1:]):
            d, dt = math.hypot(x2 - x1, y2 - y1), (t2 - t1) / 1000
            dist.append(dist[-1] + d)
            stand = stand + dt if dt > 0 and d / dt < STAND_SPEED else 0.0
            worst = max(worst, stand)
        half = next(i for i, d in enumerate(dist) if d >= dist[-1] / 2)
        first, second = sec[half][0] - sec[0][0], sec[-1][0] - sec[half][0]
        start_local = datetime.fromtimestamp(sec[0][0] / 1000, tz)
        checks = {"zeitdruck": elapsed <= 0.9 * limit_s, "pausenlos": worst <= STAND_MAX_S,
                  "negativ": dist[-1] > 0 and second < 0.98 * first, "fruehaufsteher": start_local.hour < 8}
        done = {a: bool(checks.get(a)) for a in affixes}
    return {"coverage": coverage, "cleared": cleared, "all_segments": all(cleared) and bool(cleared),
            "elapsed_s": round(elapsed) if elapsed is not None else None,
            "section_start_ms": sec[0][0] if sec else None, "affixes_done": done}


# --- Daten ----------------------------------------------------------------------------------------

def _run_history() -> tuple[list[dict], float]:
    from .metrics import running
    df = running._runs()
    if df.empty:
        return [], 180.0
    hr_max, _ = running._resolved_hr_max(df)
    return ([{"started_at": t.to_pydatetime(), "pace": float(p), "avg_hr": None if h != h else float(h)}
             for t, p, h in zip(df["started_at"], df["pace"], df["avg_hr"])], hr_max)


def _weather_hours(day_offset: int) -> list[dict]:
    from . import weather
    w = weather.today(0, day_offset)
    return w.get("hours", []) if w.get("configured") else []


def briefing_recommendation(today: date) -> str | None:
    """Tempo-Empfehlung des Morgenbriefings („locker" …). Das Morgenbriefing gibt es noch nicht → None."""
    return None


def today_debuffs(today: date) -> list[str]:
    """Debuffs der Buff-Leiste (gleiche Schwellen wie `hero.buffs_today`): Übermüdet, Erschöpft, Krank."""
    from . import hero
    out = []
    try:
        night = hero._sleep_minutes().get(today)
    except Exception:  # noqa: BLE001 -- Tabelle fehlt
        night = None
    if night is not None and night < 360:
        out.append("uebermuedet")
    ci = hero._checkin(today)
    if ci.get("sick") or today in hero._sick():
        out.append("krank")
    elif ci.get("energy") is not None and ci["energy"] <= 2:
        out.append("erschoepft")
    return out


def suggest(key_level: int, today: date) -> dict:
    """Stufen-Vorschlag — nur ein Vorschlag, die Wahl bleibt frei."""
    rec = briefing_recommendation(today)
    if rec == "locker":
        return {"level": START_LEVEL, "source": "morgenbriefing", "reason": "Morgenbriefing empfiehlt heute locker"}
    debuffs = today_debuffs(today) if rec is None else []
    if debuffs:
        names = ", ".join(EASY_DEBUFFS[d] for d in debuffs)
        return {"level": START_LEVEL, "source": "debuffs", "reason": f"{names} – heute lieber eine niedrige Stufe"}
    return {"level": key_level, "source": "stand", "reason": "Aktuelle Steinstufe dieses Verlieses"}


def _rows(s: Session) -> list[HeroKeystone]:
    return list(s.exec(select(HeroKeystone)).all())


def _dungeon(key: str) -> tuple[dict, list[list[tuple[float, float]]]] | None:
    """Entdecktes Verlies (Garmin-Wahrheit) + Abschnittspunkte in Metern; None = unbekannt/im Nebel."""
    w = hero_world.world()
    if not w.get("available"):
        return None
    d = next((x for x in w["dungeons"] if x["key"] == key), None)
    dg = next((x for x in hero_world.dungeon_defs() if x["key"] == key), None)
    if d is None or dg is None or not d["discovered"]:
        return None
    home = hero_world._memo["home"]
    return dg, [[hero_world._to_m(home, la, lo) for la, lo in seg["points"]] for seg in dg["segments"]]


def _route_track(route, home, after_ms: int) -> list[tuple[int, float, float]]:
    out = []
    try:
        for seg in json.loads(route.segments_json):
            for p in seg:
                if p.get("time") and "lat" in p and "lon" in p:
                    ts = int(datetime.fromisoformat(p["time"]).timestamp() * 1000)
                    if ts >= after_ms:
                        out.append((ts, *hero_world._to_m(home, p["lat"], p["lon"])))
    except (ValueError, TypeError, AttributeError):
        return []
    return sorted(out)


def resolve_pending(now_ms: int | None = None) -> int:
    """Wertet aktive Steine gegen neue Garmin-Läufe aus; ohne Spur nach 24 h verfällt der Stein kostenlos."""
    from .garmin_routes import GarminRoute
    now_ms = now_ms if now_ms is not None else hero_world._now_ms()
    tz = ZoneInfo(settings.timezone)
    changed = 0
    with Session(hero_world.engine) as s:
        active = list(s.exec(select(HeroKeystone).where(HeroKeystone.status == "active")).all())
        if not active:
            return 0
        if not hero_world.world().get("available"):
            return 0
        home = hero_world._memo["home"]
        since = datetime.fromtimestamp(min(k.activated_ms for k in active) / 1000, tz).replace(tzinfo=None) - timedelta(days=1)
        routes = [(r, sp) for r in s.exec(select(GarminRoute).where(GarminRoute.started_at >= since)).all()
                  if (sp := hero_world._route_span(r))]
        for k in active:
            cands = sorted(((sp, r) for r, sp in routes
                            if sp[1] >= k.activated_ms and sp[0] <= k.activated_ms + ROUTE_WINDOW_MS), key=lambda x: x[0])
            dg = next((x for x in hero_world.dungeon_defs() if x["key"] == k.dungeon), None)
            if cands and dg:
                route = cands[0][1]
                segs = [[hero_world._to_m(home, la, lo) for la, lo in seg["points"]] for seg in dg["segments"]]
                affixes = sorted(set(json.loads(k.affixes_json)) | {k.week_affix})
                ev = evaluate(_route_track(route, home, k.activated_ms), segs, k.time_limit_s, affixes, tz)
                k.status, k.delta = judge(ev["elapsed_s"] or 0, k.time_limit_s, ev["all_segments"])
                k.result_json = json.dumps({**ev, "activity_id": route.activity_id,
                                            "loot_bonus": _loot_bonus(k, ev) if k.status != "incomplete" else 0})
            elif now_ms - k.activated_ms > EXPIRE_MS:
                k.status, k.delta = "expired", 0
            else:
                continue
            k.resolved_ms = now_ms
            s.add(k)
            changed += 1
        s.commit()
    return changed


def _loot_bonus(k: HeroKeystone, ev: dict) -> int:
    """Beute-Bonus (Stufen) für #63: +1 je erfülltem gewähltem Affix bzw. Wochen-Affix, +1 je Wetter-Affix."""
    keys = set(json.loads(k.affixes_json)) | {k.week_affix}
    return sum(bool(ev["affixes_done"].get(a)) for a in keys) + len(json.loads(k.weather_json))


# --- API-Funktionen -------------------------------------------------------------------------------

def preview(dungeon_key: str, today: date | None = None) -> dict:
    """Aktivierungs-Vorschau: erlaubte Stufen, Vorschlag, Zeitlimit je Stufe, Affixe. KeyError = nicht entdeckt."""
    found = _dungeon(dungeon_key)
    if found is None:
        raise KeyError(dungeon_key)
    dg, _ = found
    today = today or datetime.now(ZoneInfo(settings.timezone)).date()
    resolve_pending()
    with Session(hero_world.engine) as s:
        h = history(_rows(s)).get(dungeon_key, {"key_level": START_LEVEL, "max_level": START_LEVEL, "runs": 0, "timed": 0})
    runs, hr_max = _run_history()
    pace = easy_pace(runs, today, hr_max)
    levels = list(range(START_LEVEL, h["max_level"] + 1))
    return {"dungeon": dungeon_key, "name": dg["name"], "length_km": round(dg["length_m"] / 1000, 2),
            "key_level": h["key_level"], "max_level": h["max_level"], "levels": levels,
            "suggested_level": suggest(min(h["key_level"], h["max_level"]), today),
            "easy_pace": pace,
            "time_limits": {str(lv): time_limit_s(pace["pace"], dg["length_m"], lv) for lv in levels},
            "week_affix": {"key": week_affix(today), **AFFIXES[week_affix(today)]},
            "affixes": [{"key": a, **v} for a, v in AFFIXES.items()]}


def activate(session_id: str, dungeon_key: str, level: int, affixes: list[str], now_ms: int | None = None) -> dict:
    """Aktiviert einen Stein. KeyError = Verlies unbekannt/nicht entdeckt, ValueError = Stufe/Affix ungültig."""
    now_ms = now_ms if now_ms is not None else hero_world._now_ms()
    tz = ZoneInfo(settings.timezone)
    start = datetime.fromtimestamp(now_ms / 1000, tz)
    pv = preview(dungeon_key, start.date())
    if level not in pv["levels"]:
        raise ValueError(f"Stufe +{level} nicht erlaubt (+{START_LEVEL} bis +{pv['max_level']}).")
    bad = [a for a in affixes if a not in AFFIXES]
    if bad:
        raise ValueError(f"Unbekannter Affix: {', '.join(bad)}")
    limit = pv["time_limits"][str(level)]
    try:
        hours = _weather_hours((start.date() - datetime.now(tz).date()).days)
        weather = weather_affixes(hours, start.replace(tzinfo=None), limit / 60 + 30)
    except Exception:  # noqa: BLE001 -- Wetter fehlt: kein Bonus, nie ein Nachteil
        weather = []
    with Session(hero_world.engine) as s:
        for old in s.exec(select(HeroKeystone).where(HeroKeystone.session == session_id, HeroKeystone.status == "active")):
            old.status, old.resolved_ms = "aborted", now_ms
            s.add(old)
        k = HeroKeystone(session=session_id, dungeon=dungeon_key, level=level, affixes_json=json.dumps(sorted(set(affixes))),
                         week_affix=week_affix(start.date()), weather_json=json.dumps(weather), activated_ms=now_ms,
                         time_limit_s=limit)
        s.add(k)
        s.commit()
    hero_world.set_live_target(session_id, "dungeon", f"dungeon:{dungeon_key}")
    return {"session": session_id, "dungeon": dungeon_key, "level": level, "time_limit_s": limit,
            "affixes": sorted(set(affixes)), "week_affix": week_affix(start.date()), "weather_affixes": weather,
            "suggested_level": pv["suggested_level"], "provisional": True}


def abort(session_id: str, now_ms: int | None = None) -> bool:
    """Bricht den aktiven Stein einer Session ab — kostet nichts."""
    now_ms = now_ms if now_ms is not None else hero_world._now_ms()
    with Session(hero_world.engine) as s:
        rows = list(s.exec(select(HeroKeystone).where(HeroKeystone.session == session_id, HeroKeystone.status == "active")))
        for k in rows:
            k.status, k.resolved_ms = "aborted", now_ms
            s.add(k)
        s.commit()
    return bool(rows)


def _affix_view(keys: list[str], table: dict, kind: str) -> list[dict]:
    return [{"key": a, "kind": kind, **table[a]} for a in keys if a in table]


def live(session_id: str, track: list[tuple[int, float, float]] | None, now_ms: int | None = None) -> dict | None:
    """Aktiver Stein einer Session für `live/state` (vorläufig); track = Live-Punkte (ts, x, y) in Metern."""
    now_ms = now_ms if now_ms is not None else hero_world._now_ms()
    try:
        resolve_pending(now_ms)
        with Session(hero_world.engine) as s:
            k = s.exec(select(HeroKeystone).where(HeroKeystone.session == session_id, HeroKeystone.status == "active")
                       .order_by(HeroKeystone.activated_ms.desc())).first()
    except Exception:  # noqa: BLE001 -- Tabelle fehlt (DB ohne init_db): ohne Stein wie bisher
        return None
    if k is None:
        return None
    dg = next((x for x in hero_world.dungeon_defs() if x["key"] == k.dungeon), None)
    if dg is None:
        return None
    home = hero_world._memo["home"]
    segs = [[hero_world._to_m(home, la, lo) for la, lo in seg["points"]] for seg in dg["segments"]]
    chosen = json.loads(k.affixes_json)
    ev = evaluate([p for p in (track or []) if p[0] >= k.activated_ms], segs, k.time_limit_s, chosen,
                  ZoneInfo(settings.timezone))
    started = ev["section_start_ms"]
    used = (now_ms - started) / 1000 if started else 0.0
    return {"id": k.id, "dungeon": f"dungeon:{k.dungeon}", "name": dg["name"], "level": k.level,
            "affixes": _affix_view(chosen, AFFIXES, "gewaehlt") + _affix_view([k.week_affix], AFFIXES, "woche")
            + _affix_view(json.loads(k.weather_json), WEATHER_AFFIXES, "wetter"),
            "time_limit_s": k.time_limit_s, "clock_started": started is not None,
            "remaining_s": round(k.time_limit_s - used),
            "segments": [{"boss": seg["boss"], "coverage": c, "cleared": ok}
                         for seg, c, ok in zip(dg["segments"], ev["coverage"], ev["cleared"])],
            "segments_cleared": sum(ev["cleared"]), "segments_total": len(segs), "provisional": True}


def results(dungeon_key: str | None = None) -> list[dict]:
    """Ausgewertete Steine (neueste zuerst) — Grundlage für Belohnung/Wertung (#63)."""
    resolve_pending()
    with Session(hero_world.engine) as s:
        rows = [k for k in _rows(s) if k.status != "active" and (dungeon_key is None or k.dungeon == dungeon_key)]
    return [{"id": k.id, "session": k.session, "dungeon": k.dungeon, "level": k.level, "status": k.status, "delta": k.delta,
             "affixes": json.loads(k.affixes_json), "week_affix": k.week_affix, "weather_affixes": json.loads(k.weather_json),
             "time_limit_s": k.time_limit_s, "activated_ms": k.activated_ms, "resolved_ms": k.resolved_ms,
             "result": json.loads(k.result_json)} for k in sorted(rows, key=lambda r: -r.activated_ms)]
