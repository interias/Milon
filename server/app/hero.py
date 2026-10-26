"""Heldenreise: WoW-artige Gamification aus echten Trainingsdaten.

Alles wird live aus den Daten berechnet (Läufe, Kraft-Workouts, Schritte, Krankheitstage,
Erfolge) — gespeichert werden nur der Starttag (ab dem es Beute gibt) und die Wahl aus der
Wochentruhe. Bausteine:
- XP & Level: Belastung statt Klicks (Laufminuten × Puls-Zone, Kraftsätze, Schritte, Erfolge).
  Ab dem 5. Lauf / 4. Krafttraining einer Woche halbe XP (Schutz gegen Übertraining).
  Ruhebonus wie in WoW: Ruhe- und Krankheitstage laden einen Vorrat, der die Trainings-XP
  verdoppelt, bis er verbraucht ist.
- Klasse (Laufen/Kraft/Alltag-Mischung) + Lauf-Spezialisierung, beides über 90 Tage.
- Attribute: aus Metriken abgeleitete Werte 0–100 mit Δ zu vor 30 Tagen.
- Beute je Lauf ab Starttag: Rarität verdient (Leistung gegen eigenen 90-Tage-Schnitt,
  Bestzeiten), der Gegenstand selbst ist Zufall — fest an den Lauf geseedet, also stabil.
- Wochentruhe (Great Vault): 1/3/4 Läufe öffnen je einen Slot; Krankheitstage senken die
  Schwellen. Abgeschlossene Wochen bleiben wählbar, bis ein Slot gewählt wurde.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from typing import Optional
from sqlmodel import Field, Session, SQLModel, select

from . import hero_bosses, hero_climb, hero_dreams, hero_economy, hero_events, hero_events_live, hero_extras, hero_keystone, hero_quests, hero_social, hero_world
from .checkins import local_today
from .db import engine

log = logging.getLogger(__name__)


class HeroState(SQLModel, table=True):
    __tablename__ = "hero_state"

    key: str = Field(primary_key=True)
    value: str


class HeroClaim(SQLModel, table=True):
    """Gewählter Slot einer Wochentruhe (week = ISO-Montag oder 'veteran')."""
    __tablename__ = "hero_claims"

    week: str = Field(primary_key=True)
    slot: int
    item_json: str
    claimed_at: datetime


class HeroEquip(SQLModel, table=True):
    """Angelegter Gegenstand je Ausrüstungsplatz (item_id wie im Inventar)."""
    __tablename__ = "hero_equipment"

    slot: str = Field(primary_key=True)
    item_id: str
    equipped_at: datetime


class HeroItemMod(SQLModel, table=True):
    """Entzaubert (Staub gutgeschrieben) oder aufgewertet (je +4 Stufen) — je Gegenstand."""
    __tablename__ = "hero_item_mods"

    item_id: str = Field(primary_key=True)
    disenchanted: bool = False
    dust: int = 0
    upgrades: int = 0
    sold: bool = False
    gold: int = 0  # Verkaufserlös in Kupfer


class HeroPurchase(SQLModel, table=True):
    """Kauf im Auktionshaus (Gegenstand, Tasche, Reittier oder Trank) inkl. Inhalt als JSON."""
    __tablename__ = "hero_purchases"

    id: str = Field(primary_key=True)
    week: str = Field(index=True)
    kind: str
    price: int
    payload: str
    bought_at: datetime


class HeroPotionUse(SQLModel, table=True):
    __tablename__ = "hero_potion_uses"

    id: Optional[int] = Field(default=None, primary_key=True)
    day: date = Field(index=True)
    key: str
    used_at: datetime


class HeroLivePoint(SQLModel, table=True):
    """Provisional live position of a running session (watch/phone); deleted once the Garmin track
    covers the session or after 48 h at the latest. Never returned by the API as lat/lon."""
    __tablename__ = "hero_live_points"

    id: Optional[int] = Field(default=None, primary_key=True)
    session: str = Field(index=True)
    ts: int  # epoch milliseconds (UTC)
    lat: float
    lon: float
    acc: float
    received_at: datetime


RARITIES = ["grau", "weiss", "gruen", "blau", "lila", "orange", "rot"]
RARITY_LABEL = {"grau": "Schrott", "weiss": "Gewöhnlich", "gruen": "Ungewöhnlich", "blau": "Selten",
                "lila": "Episch", "orange": "Legendär", "rot": "Artefakt"}

# --- XP ---------------------------------------------------------------------------------
ZONE_FACTOR = [1.0, 1.2, 1.5, 1.8]   # Z1..Z4 (%HFmax wie running._ZONE_DEFS)
NO_HR_FACTOR = 1.1
RUN_XP_PER_MIN = 2.0
SET_XP = 6.0
WORKOUT_XP_CAP = 180
RUNS_FULL_XP = 4          # ab dem 5. Lauf einer ISO-Woche halbe XP
WORKOUTS_FULL_XP = 3      # ab dem 4. Krafttraining halbe XP
REST_PER_DAY = 60
REST_CAP = 240
BUFF_PCT = 0.05          # je aktivem Daten-Buff (Wohlgenährt, Erholt) auf Trainings-EP
FOCUS_PCT = 0.10         # passender Lauf zur gewählten Spezialisierung
LEVEL_BASE = 1000
LEVEL_STEP = 25
MAX_LEVEL = 80

TITLES = [(1, "Frischling"), (10, "Anwärter"), (20, "Streiter"), (30, "Veteran"), (40, "Held"),
          (50, "Champion"), (60, "Meister"), (70, "Legende"), (80, "Mythos")]

CLASSES = {
    "krieger": {"label": "Krieger", "color": "#c69b6d", "desc": "Kraft dominiert dein Training."},
    "paladin": {"label": "Paladin", "color": "#f48cba", "desc": "Kraft und Laufen halten sich die Waage."},
    "jaeger": {"label": "Jäger", "color": "#aad372", "desc": "Laufen dominiert dein Training."},
    "moench": {"label": "Mönch", "color": "#00ff98", "desc": "Alltagsbewegung trägt dich – wenig gezieltes Training."},
}
SPECS = {
    "ausdauer": {"label": "Druide · Ausdauer", "desc": "Überwiegend locker in Zone 1–2."},
    "tempo": {"label": "Schurke · Tempo", "desc": "Viele Läufe in Zone 3–4."},
    "last": {"label": "Todesritter · Last", "desc": "Hohe Wochenlast, du läufst durch die Ermüdung."},
    "strecke": {"label": "Waldläufer · Strecke", "desc": "Lange Läufe prägen dein Training."},
}


def level_for(xp: float) -> dict:
    level, floor, need = 1, 0.0, LEVEL_BASE
    while xp >= floor + need and level < MAX_LEVEL:
        floor += need
        level += 1
        need = LEVEL_BASE + LEVEL_STEP * (level - 1)
    title = next(t for lv, t in reversed(TITLES) if level >= lv)
    return {"level": level, "title": title, "xp": round(xp), "floor": round(floor),
            "next": round(floor + need), "progress": round((xp - floor) / need, 3)}


def _read(sql: str, **kw) -> pd.DataFrame:
    with engine.connect() as con:
        return pd.read_sql(sql, con, **kw)


def _pace(minutes: float) -> str:
    sec = round(minutes * 60)
    return f"{sec // 60}:{sec % 60:02d}"


def _safe(fn, default):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 -- optionale Quelle darf die Seite nie sperren
        log.warning("Heldenreise: %s fehlgeschlagen: %s", getattr(fn, "__name__", fn), exc)
        return default


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _rng(*parts) -> random.Random:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


# --- Daten ------------------------------------------------------------------------------
def _runs() -> pd.DataFrame:
    from .metrics import running
    df = _read("SELECT external_id, started_at, ended_at, distance_km, avg_hr, max_hr "
               "FROM exercise_sessions WHERE exercise_type = 33", parse_dates=["started_at", "ended_at"])
    if df.empty:
        return df
    df["dur_min"] = (df["ended_at"] - df["started_at"]).dt.total_seconds() / 60
    df = df[(df["distance_km"].fillna(0) >= 1) & (df["distance_km"] <= 60)
            & (df["dur_min"] > 5) & (df["dur_min"] < 600)].copy()
    df["pace"] = df["dur_min"] / df["distance_km"]
    df = df[(df["pace"] >= 3) & (df["pace"] <= 12)].copy()
    df["ef"] = (df["distance_km"] * 1000 / df["dur_min"] / df["avg_hr"]).where(df["avg_hr"] > 0)
    hr_max, _ = running._resolved_hr_max(df)
    bounds = np.array([0.70, 0.80, 0.90]) * hr_max
    df["zone"] = df["avg_hr"].apply(lambda h: int(np.searchsorted(bounds, h, side="right")) if pd.notna(h) else None)
    df["day"] = df["started_at"].dt.date
    df["key"] = df["external_id"].fillna(df["started_at"].astype(str))
    return df.sort_values("started_at").reset_index(drop=True)


def _hr_max(runs: pd.DataFrame) -> float:
    from .metrics import running
    return running._resolved_hr_max(runs if "max_hr" in runs else pd.DataFrame())[0]


def _workouts() -> pd.DataFrame:
    df = _read("SELECT w.id, w.started_at, COUNT(ws.id) AS sets FROM workouts w "
               "LEFT JOIN workout_sets ws ON ws.workout_id = w.id AND ws.set_type = 'normal' "
               "WHERE w.started_at IS NOT NULL GROUP BY w.id", parse_dates=["started_at"])
    if not df.empty:
        df["day"] = df["started_at"].dt.date
    return df.sort_values("started_at").reset_index(drop=True) if not df.empty else df


RIDE_ZONE = [0, 1, 2, 2, 3, 3, 3]   # Coggan Z1..Z7 → Lauf-Zone (ZONE_FACTOR): Z3–4 = Tempo, Z5+ = Hart
RIDE_COLUMNS = ["key", "activity_id", "started_at", "day", "dur_min", "zone", "power_zone", "km", "elevation_m",
                "kj", "np", "avg_hr", "ef", "eftp", "power_curve", "world", "has_power"]


def _indoor_rides(hr_max: float = 180.0) -> pd.DataFrame:
    """Indoor-Fahrten (Zwift/Rolle) für die Heldenreise, eine Zeile je Fahrt — nie Koordinaten.
    zone wie bei Läufen (0..3 → ZONE_FACTOR): aus NP/eFTP (Coggan), ohne Watt aus dem Ø-Puls
    (%HFmax wie Läufe, nur bei plausibler Pulsmessung), sonst None. Basis für Rad-EP, Beute,
    Truhe, Aufträge und Disziplin (und für die Kletter-Bosse/Reittiere aus #73)."""
    from .metrics import cycling
    df = cycling.indoor_rides()
    if df.empty:
        return pd.DataFrame(columns=RIDE_COLUMNS)
    df = cycling._with_load(df)
    seconds = df["duration_seconds"].fillna(df["elapsed_duration_seconds"]).astype(float)
    df["dur_min"] = seconds / 60
    df = df[(df["dur_min"] > 5) & (df["dur_min"] < 600)].copy()
    if df.empty:
        return pd.DataFrame(columns=RIDE_COLUMNS)
    df["has_power"] = (df["avg_power_w"].fillna(0) > 0) & df["power_curve"].map(bool)
    df["np"] = df["norm_power_w"].fillna(df["avg_power_w"]).where(df["has_power"])
    ratio = df["np"] / df["eftp"]
    df["power_zone"] = ratio.map(lambda x: int(np.searchsorted(cycling.COGGAN, x, side="right")) + 1
                                 if pd.notna(x) and x > 0 else None)
    bounds = np.array([0.70, 0.80, 0.90]) * hr_max
    hr = df["avg_hr"].where(df["hr_valid"])
    hr_zone = hr.map(lambda h: int(np.searchsorted(bounds, h, side="right")) if pd.notna(h) and h > 0 else None)
    df["zone"] = [RIDE_ZONE[int(p) - 1] if p is not None and pd.notna(p) else (z if z is not None and pd.notna(z) else None)
                  for p, z in zip(df["power_zone"], hr_zone)]
    df["km"] = df["distance_km"].fillna(0.0).astype(float)
    df["elevation_m"] = df["elevation_gain_m"].fillna(0.0).astype(float)
    df["kj"] = df["work_kj"].fillna(df["avg_power_w"] * seconds / 1000).fillna(0.0).astype(float)
    df["ef"] = (df["np"] / hr).where(hr > 0)
    df["key"] = "ride:" + df["activity_id"].astype(str)
    return df.sort_values("started_at")[RIDE_COLUMNS].reset_index(drop=True)


def _other_minutes() -> dict[date, float]:
    from .metrics import health
    df = _read("SELECT started_at, ended_at FROM exercise_sessions WHERE exercise_type IN (4, 53)",
               parse_dates=["started_at", "ended_at"])
    # HC-Spiegel einer Indoor-Fahrt (Garmin Connect → HC) sind keine Alltagsbewegung: die Fahrt gibt Rad-EP.
    df = health._drop_overlapping(df.dropna(subset=["started_at"]), health._indoor_windows())
    from . import walkpad
    with engine.connect() as con:
        # Laufband-Walks zählen als Alltag; ihre HC-Spiegel (Garmin-Upload → HC) nicht zusätzlich.
        pad = pd.DataFrame(walkpad.windows(con), columns=["started_at", "ended_at"])
        pad_minutes = walkpad.minutes_by_day(con)
    df = health._drop_overlapping(df, pad)
    out: dict[date, float] = {}
    for s, e in zip(df["started_at"], df["ended_at"]):
        if pd.notna(s) and pd.notna(e):
            out[s.date()] = out.get(s.date(), 0.0) + max(0.0, min(120.0, (e - s).total_seconds() / 60))
    for d, minutes in pad_minutes.items():
        out[d] = out.get(d, 0.0) + min(240.0, minutes)
    return out


def _steps() -> dict[date, int]:
    from . import walkpad

    df = _read("SELECT day, steps FROM steps_daily", parse_dates=["day"])
    with engine.connect() as con:
        df = walkpad.with_extra_steps(df, con)
    return {d.date(): int(s) for d, s in zip(df["day"], df["steps"]) if pd.notna(s)}


def _checkin_days() -> dict[date, int]:
    try:
        with engine.connect() as con:
            rows = con.exec_driver_sql("SELECT day, energy FROM checkins WHERE energy IS NOT NULL").fetchall()
    except Exception:  # noqa: BLE001 -- Tabelle fehlt
        return {}
    return {date.fromisoformat(str(r[0])[:10]): int(r[1]) for r in rows}


def _sick() -> set[date]:
    try:
        with engine.connect() as con:
            rows = con.exec_driver_sql("SELECT day FROM checkins WHERE sick = 1").fetchall()
    except Exception:  # noqa: BLE001 -- Tabelle fehlt
        return set()
    return {date.fromisoformat(str(r[0])[:10]) for r in rows}


def _best_efforts() -> pd.DataFrame:
    try:
        return _read("SELECT external_id, distance_m, seconds, started_at FROM run_best_efforts",
                     parse_dates=["started_at"])
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=["external_id", "distance_m", "seconds", "started_at"])


def _achievement_xp() -> list[tuple[date | None, int, str]]:
    from .metrics import achievements
    out = []
    for a in achievements.evaluate()["achievements"]:
        if a["earned"]:  # ohne Datum (z. B. Meta-Erfolge) → am ersten Tag des XP-Buchs
            d = date.fromisoformat(str(a["earned_date"])[:10]) if a.get("earned_date") else None
            out.append((d, int(a["points"]), a["name"]))
    return out


def start_date(today: date) -> date:
    """Tag, ab dem Beute fällt — beim ersten Aufruf festgeschrieben."""
    with Session(engine) as session:
        row = session.get(HeroState, "start")
        if row is None:
            row = HeroState(key="start", value=today.isoformat())
            session.add(row)
            session.commit()
        return date.fromisoformat(row.value)


# Talentreihen wie in WoW: alle 10 Stufen eine Reihe, je eine von drei Optionen. Wirkung ab dem
# Tag der Wahl (datierte Historie je Reihe), jederzeit umwählbar.
TALENT_ROWS = [
    (10, "Rhythmus", [
        ("morgen", "Morgenläufer", "+10 % EP für Läufe vor 9 Uhr", "sun"),
        ("abend", "Feierabendläufer", "+10 % EP für Läufe ab 17 Uhr", "sunset"),
        ("wochenende", "Wochenendkrieger", "+10 % EP für Läufe am Wochenende", "calendar")]),
    (20, "Eisen", [
        ("eisenwille", "Eisenwille", "+10 % EP für Krafttraining", "dumbbell"),
        ("ausgleich", "Ausgleich", "+15 % Kraft-EP an Tagen ohne Lauf", "scale"),
        ("doppelschlag", "Doppelschlag", "+10 % EP für Lauf und Kraft am selben Tag", "swords")]),
    (30, "Erholung", [
        ("tiefschlaf", "Tiefschlaf", "Erholt gibt +10 % statt +5 %", "moon"),
        ("langer_atem", "Langer Atem", "Ruhebonus-Vorrat bis 360 statt 240 EP", "bed"),
        ("feinschmecker", "Feinschmecker", "Wohlgenährt gibt +10 % statt +5 %", "food")]),
    (40, "Aufträge", [
        ("pfadfinder", "Pfadfinder", "+1 Lauf-Auftrag pro Woche", "map"),
        ("schmied", "Schmied", "+1 Kraft-Auftrag pro Woche", "anvil"),
        ("hueter", "Hüter", "+1 Pflege-Auftrag pro Woche", "leaf")]),
    (50, "Glück", [
        ("schatzsucher", "Schatzsucher", "Glücksfund-Chance 15 % statt 8 %", "gem"),
        ("truhenmeister", "Truhenmeister", "Truhen-Slots: 30 % statt 15 % Chance auf +1 Seltenheit", "chest"),
        ("bossjaeger", "Bossjäger", "+50 % EP für besiegte Bosse", "skull")]),
]
TALENT_LOCKED = [60, 70, 80]
QUEST_EXTRA = {"pfadfinder": "lauf", "schmied": "kraft", "hueter": "pflege"}


def _state_get(key: str) -> str | None:
    with Session(engine) as session:
        row = session.get(HeroState, key)
        return row.value if row else None


def _state_set(key: str, value: str) -> None:
    with Session(engine) as session:
        row = session.get(HeroState, key) or HeroState(key=key, value=value)
        row.value = value
        session.add(row)
        session.commit()


def _history(key: str) -> list[dict]:
    """Datierte Wahl-Historie [{from, value}] — Wirkungen gelten ab dem Tag der Wahl."""
    try:
        return json.loads(_state_get(key) or "[]")
    except ValueError:
        return []


def _active(hist: list[dict], d: date):
    value = None
    for h in hist:
        if h["from"] <= d.isoformat():
            value = h["value"]
    return value


def _choose(key: str, value, today: date) -> list[dict]:
    hist = [h for h in _history(key) if h["from"] != today.isoformat()]
    hist.append({"from": today.isoformat(), "value": value})
    _state_set(key, json.dumps(hist))
    return hist


def _protein_days() -> dict[date, float]:
    from .metrics import nutrition
    df = nutrition._daily()
    return {} if df.empty else {d.date(): float(p) for d, p in zip(df["day"], df["protein_g"]) if pd.notna(p)}


def _protein_target() -> float | None:
    from .metrics import nutrition
    return nutrition.protein_target()


def _sleep_minutes() -> dict[date, float]:
    df = _read("SELECT day, asleep_minutes FROM sleep_sessions WHERE main_sleep = 1", parse_dates=["day"])
    return {d.date(): float(m) for d, m in zip(df["day"], df["asleep_minutes"]) if pd.notna(m)}


def day_buffs(protein: dict[date, float], target: float | None, sleep: dict[date, float]) -> dict[date, set[str]]:
    """Daten-Buffs je Tag: Wohlgenährt = Protein-Ziel am Vortag (≥ 90 %), Erholt = Nacht ≥ 7 h."""
    out: dict[date, set[str]] = {}
    if target:
        for d, g in protein.items():
            if g >= 0.9 * target:
                out.setdefault(d + timedelta(days=1), set()).add("wohlgenaehrt")
    for d, m in sleep.items():
        if m >= 420:
            out.setdefault(d, set()).add("erholt")
    return out


def matches_spec(spec: str | None, run, week_index: int) -> bool:
    """Passt eine Einheit zur Spezialisierung? Fahrten (Zeilen aus _indoor_rides) zählen über ihre Zone
    und den gemeinsamen Ausdauer-Wochenzähler, nie für „Strecke“ (virtuelle km)."""
    zone = run.zone if run.zone is not None and pd.notna(run.zone) else None
    return {"ausdauer": zone is not None and zone <= 1, "tempo": zone is not None and zone >= 2,
            "strecke": (getattr(run, "distance_km", None) or 0) >= 10, "last": week_index >= 3}.get(spec or "", False)


XP_KEYS = ["laufen", "kraft", "alltag", "erfolge", "ruhebonus", "buffs", "fokus", "talente", "auftraege", "bosse", "instanzen", "taeglich", "event", "duelle", "erkundung", "events", "rad", "gipfel"]
EXTRA_KEY = {"auftrag": ("auftraege", "Auftrag"), "boss": ("bosse", "Boss besiegt:"), "instanz": ("instanzen", "Instanz"),
             "taeglich": ("taeglich", "Tagesaufgabe"), "event": ("event", "Event"), "duell": ("duelle", "Duell gewonnen:"), "erkundung": ("erkundung", "Gebiet entdeckt:"),
             "verlies": ("erkundung", "Verlies bezwungen:"), "abschnitt": ("erkundung", "Abschnitt bezwungen:"), "schrein": ("erkundung", "Schrein entdeckt:"), "schatz": ("erkundung", "Schatz gefunden:"),
             "spontan": ("events", "Ereignis bestanden:"), "gipfel": ("gipfel", "Gipfel bezwungen:")}


class Mods:
    """Zeitabhängige Wirkungen auf Trainings-EP: Daten-Buffs und gewählte Spezialisierung."""

    def __init__(self, buffs: dict[date, set[str]] | None = None, spec_hist: list[dict] | None = None,
                 talents: dict[int, list[dict]] | None = None, potions: dict[date, set[str]] | None = None):
        self.buffs = buffs or {}
        self.spec_hist = spec_hist or []
        self.talents = talents or {}
        self.potions = potions or {}

    def refill(self, d: date) -> float:
        return 120.0 if "erholung" in self.potions.get(d, set()) else 0.0

    def talent(self, row: int, d: date) -> str | None:
        return _active(self.talents.get(row, []), d)

    def training(self, d: date) -> float:
        have = self.buffs.get(d, set())
        pct = 0.0
        if "wohlgenaehrt" in have:
            pct += 2 * BUFF_PCT if self.talent(30, d) == "feinschmecker" else BUFF_PCT
        if "erholt" in have:
            pct += 2 * BUFF_PCT if self.talent(30, d) == "tiefschlaf" else BUFF_PCT
        if "ausdauer" in self.potions.get(d, set()):
            pct += 0.10
        return pct

    def run_talent(self, d: date, run, lifted: bool) -> float:
        t, hour = self.talent(10, d), run.started_at.hour
        pct = 0.10 if (t == "morgen" and hour < 9) or (t == "abend" and hour >= 17) \
            or (t == "wochenende" and d.weekday() >= 5) else 0.0
        return pct + (0.10 if lifted and self.talent(20, d) == "doppelschlag" else 0.0)

    def workout_talent(self, d: date, ran: bool) -> float:
        t = self.talent(20, d)
        return {"eisenwille": 0.10, "ausgleich": 0.0 if ran else 0.15, "doppelschlag": 0.10 if ran else 0.0}.get(t or "", 0.0)

    def rest_cap(self, d: date) -> float:
        return 360.0 if self.talent(30, d) == "langer_atem" else REST_CAP

    def luck(self, d: date) -> float:
        base = 0.15 if self.talent(50, d) == "schatzsucher" else 0.08
        return base + (0.10 if "glueck" in self.potions.get(d, set()) else 0.0)

    def vault_bonus(self, d: date) -> float:
        return 0.30 if self.talent(50, d) == "truhenmeister" else 0.15

    def quest_extra(self, d: date) -> str | None:
        return QUEST_EXTRA.get(self.talent(40, d) or "")

    def focus(self, d: date, run, week_index: int) -> float:
        return FOCUS_PCT if matches_spec(_active(self.spec_hist, d), run, week_index) else 0.0


# --- XP-Buch ----------------------------------------------------------------------------
def run_xp(row) -> float:
    factor = ZONE_FACTOR[min(3, int(row.zone))] if row.zone is not None and pd.notna(row.zone) else NO_HR_FACTOR
    return row.dur_min * factor * RUN_XP_PER_MIN


def step_xp(steps: int) -> int:
    return min(45, max(0, (steps - 5000) // 1000) * 3)


def ledger(runs, workouts, steps, other, sick, ach, today: date, mods: Mods | None = None,
           extra: list[tuple[date, float, str, str]] | None = None, rides: pd.DataFrame | None = None) -> dict:
    """Chronologisches XP-Buch mit Ruhebonus und Wochen-Abschwächung.
    Läufe und Indoor-Fahrten teilen sich einen Ausdauer-Wochenzähler (ab der 5. Einheit halbe EP)."""
    entries: list[dict] = []
    by_day_runs: dict[date, list] = {}
    for r in runs.itertuples():
        by_day_runs.setdefault(r.day, []).append(r)
    by_day_rides: dict[date, list] = {}
    for r in (rides.itertuples() if rides is not None else []):
        by_day_rides.setdefault(r.day, []).append(r)
    by_day_wo: dict[date, list] = {}
    for w in workouts.itertuples():
        by_day_wo.setdefault(w.day, []).append(w)
    days = [*by_day_runs, *by_day_rides, *by_day_wo, *steps, *other, *(d for d, _, _ in ach if d)]
    if not days:
        return {"entries": [], "pool": 0, "totals": {}, "daily": {}}
    first = min(days)
    extra_by_day: dict[date, list] = {}
    for d, xp, name, kind, *note in extra or []:  # optional 5. Feld: Zusatz im Log, z. B. „zu Rad“
        extra_by_day.setdefault(d, []).append((xp, name, kind, note[0] if note else None))
    ach_by_day: dict[date, list] = {}
    for d, pts, name in ach:
        ach_by_day.setdefault(min(d, today) if d else first, []).append((pts, name))
    mods = mods or Mods()
    pool = 0.0
    week_runs: dict[date, int] = {}
    week_wo: dict[date, int] = {}
    totals = {k: 0.0 for k in XP_KEYS}
    daily: dict[date, dict] = {}
    d = first
    while d <= today:
        wk = _monday(d)
        trained = False
        day_xp = {k: 0.0 for k in XP_KEYS}
        buff_pct = mods.training(d)
        pool = min(mods.rest_cap(d), pool + mods.refill(d))
        ran, lifted = bool(by_day_runs.get(d)), bool(by_day_wo.get(d))
        sessions = [("lauf", r) for r in by_day_runs.get(d, [])]
        if by_day_rides.get(d):  # reine Lauftage behalten ihre Reihenfolge
            sessions = sorted(sessions + [("rad", r) for r in by_day_rides[d]], key=lambda s: s[1].started_at)
        for kind, r in sessions:
            week_runs[wk] = week_runs.get(wk, 0) + 1
            # Fahrt = Lauf-Formel: 2 EP/min × Zonenfaktor (Zone aus Leistung, sonst Puls)
            xp = run_xp(r) * (1.0 if week_runs[wk] <= RUNS_FULL_XP else 0.5)
            bonus = min(pool, xp)
            pool -= bonus
            tal = xp * mods.run_talent(d, r, lifted) if kind == "lauf" else 0.0  # Talente nennen ausdrücklich Läufe
            buff, focus = xp * buff_pct, xp * mods.focus(d, r, week_runs[wk])
            trained = True
            label = f"Lauf {r.distance_km:.1f} km" if kind == "lauf" else f"Radfahrt {r.dur_min:.0f} min"
            entries.append({"date": d, "kind": kind, "xp": xp + buff + focus + tal, "bonus": bonus, "ref": r.key,
                            "label": label})
            day_xp["laufen" if kind == "lauf" else "rad"] += xp
            day_xp["ruhebonus"] += bonus
            day_xp["buffs"] += buff
            day_xp["fokus"] += focus
            day_xp["talente"] += tal
        for w in by_day_wo.get(d, []):
            week_wo[wk] = week_wo.get(wk, 0) + 1
            xp = min(WORKOUT_XP_CAP, w.sets * SET_XP) * (1.0 if week_wo[wk] <= WORKOUTS_FULL_XP else 0.5)
            bonus = min(pool, xp)
            pool -= bonus
            buff, tal = xp * buff_pct, xp * mods.workout_talent(d, ran)
            trained = True
            entries.append({"date": d, "kind": "kraft", "xp": xp + buff + tal, "bonus": bonus, "ref": str(w.id),
                            "label": f"Krafttraining {w.sets} Sätze"})
            day_xp["kraft"] += xp
            day_xp["ruhebonus"] += bonus
            day_xp["buffs"] += buff
            day_xp["talente"] += tal
        everyday = step_xp(steps.get(d, 0)) + min(30.0, other.get(d, 0.0) * 0.5)
        if everyday:
            entries.append({"date": d, "kind": "alltag", "xp": everyday, "bonus": 0.0, "ref": None,
                            "label": "Alltagsbewegung"})
            day_xp["alltag"] += everyday
        for pts, name in ach_by_day.get(d, []):
            entries.append({"date": d, "kind": "erfolg", "xp": float(pts), "bonus": 0.0, "ref": None,
                            "label": f"Erfolg „{name}“", "name": name})
            day_xp["erfolge"] += pts
        for xp, name, kind, note in extra_by_day.get(d, []):
            key, prefix = EXTRA_KEY[kind]
            entries.append({"date": d, "kind": kind, "xp": float(xp), "bonus": 0.0, "ref": None,
                            "label": f"{prefix} „{name}“" + (f" ({note})" if note else ""), "name": name})
            day_xp[key] += xp
        if d in sick or not trained:
            pool = min(mods.rest_cap(d), pool + REST_PER_DAY)
        for k, v in day_xp.items():
            totals[k] += v
        daily[d] = day_xp
        d += timedelta(days=1)
    return {"entries": entries, "pool": pool, "totals": totals, "daily": daily}


def progression(entries: list[dict], daily: dict[date, dict]) -> list[dict]:
    """Wochenweise: EP je Quelle, kumulierte EP und Stufe (mit Bruchteil) am Wochenende."""
    weeks: dict[date, dict] = {}
    for d, v in daily.items():
        w = weeks.setdefault(_monday(d), {k: 0.0 for k in v})
        for k in w:
            w[k] += v[k]
    out, total = [], 0.0
    for wk in sorted(weeks):
        total += sum(weeks[wk].values())
        lv = level_for(total)
        out.append({"week": wk.isoformat(), **{k: round(v) for k, v in weeks[wk].items()},
                    "xp": round(total), "level": round(lv["level"] + lv["progress"], 2)})
    return out


def _level_events(entries: list[dict]) -> list[dict]:
    events, xp, level = [], 0.0, 1
    for e in entries:
        xp += e["xp"] + e["bonus"]
        lv = level_for(xp)
        if lv["level"] > level:
            level = lv["level"]
            events.append({"date": e["date"], "kind": "level", "text": f"Level {level} erreicht – {lv['title']}",
                           "name": lv["title"], "level": level})
    return events


# --- Klasse & Spezialisierung -----------------------------------------------------------
def classify(daily: dict[date, dict], runs: pd.DataFrame, d: date, rides: pd.DataFrame | None = None) -> dict:
    """Klasse aus 90 Tagen; Rad-EP zählen zur Ausdauer-Seite (Jäger-Anteil) wie Lauf-EP."""
    start = d - timedelta(days=89)
    win = [v for k, v in daily.items() if start <= k <= d]
    run_xp_ = sum(v["laufen"] for v in win)
    ride_xp = sum(v.get("rad", 0.0) for v in win)
    str_xp = sum(v["kraft"] for v in win)
    daily_xp = sum(v["alltag"] for v in win)
    sub = runs[(runs["day"] >= start) & (runs["day"] <= d)] if not runs.empty else runs
    n_rides = int(((rides["day"] >= start) & (rides["day"] <= d)).sum()) if rides is not None and not rides.empty else 0
    endurance = run_xp_ + ride_xp
    training = endurance + str_xp
    sessions = len(sub) + n_rides + sum(1 for v in win if v["kraft"] > 0)
    if training <= 0 or sessions < 6 or daily_xp > training:
        cls = "moench"
    else:
        share = endurance / training
        cls = "jaeger" if share >= 0.65 else "krieger" if share <= 0.35 else "paladin"
    total = training + daily_xp or 1.0
    shares = {"laufen": round(run_xp_ / total, 3), "rad": round(ride_xp / total, 3), "kraft": round(str_xp / total, 3),
              "alltag": round(daily_xp / total, 3)}
    spec, scores = None, {}
    if len(sub) >= 4:
        zoned = sub[sub["zone"].notna()]
        n = len(zoned) or 1
        weeks = max(1.0, (min(d, sub["day"].max()) - start).days / 7) if len(sub) else 13
        scores = {
            "ausdauer": float((zoned["zone"] <= 1).sum() / n) if len(zoned) else 0.0,
            "tempo": float((zoned["zone"] >= 2).sum() / n) if len(zoned) else 0.0,
            "last": float(min(1.0, max(0.0, (sub["dur_min"].sum() / weeks - 150) / 150))),
            "strecke": float((sub["distance_km"] >= 10).mean()),
        }
        spec = max(scores, key=scores.get)
    return {"class": cls, "spec": spec, "shares": shares,
            "spec_scores": {k: round(v, 2) for k, v in scores.items()}}


def _class_events(daily, runs, first: date, today: date, rides: pd.DataFrame | None = None) -> list[dict]:
    events, prev = [], None
    d = _monday(first) + timedelta(days=6)
    while d <= today + timedelta(days=6):
        at = min(d, today)
        c = classify(daily, runs, at, rides)
        cur = (c["class"], c["spec"])
        if prev is not None and cur != prev:
            label = CLASSES[c["class"]]["label"] + (f" ({SPECS[c['spec']]['label']})" if c["spec"] else "")
            events.append({"date": at, "kind": "klasse", "text": f"Klassenwechsel: jetzt {label}", "name": label})
        prev = cur
        d += timedelta(days=7)
    return events


# --- Attribute --------------------------------------------------------------------------
def _clamp(x: float) -> int:
    return int(round(min(100.0, max(0.0, x))))


def attributes(runs, workouts, steps, sick, today: date, rides: pd.DataFrame | None = None) -> list[dict]:
    vo2 = _safe(lambda: _read("SELECT measured_at, vo2 FROM vo2max", parse_dates=["measured_at"]),
                pd.DataFrame(columns=["measured_at", "vo2"]))
    be = _best_efforts()
    be5 = be[be["distance_m"] == 5000] if not be.empty else be
    sleep = _safe(lambda: _read("SELECT day, asleep_minutes FROM sleep_sessions WHERE main_sleep = 1",
                                parse_dates=["day"]), pd.DataFrame(columns=["day", "asleep_minutes"]))
    idx = _safe(_strength_series, [])
    train_days = set(runs["day"]) if not runs.empty else set()
    train_days |= set(workouts["day"]) if not workouts.empty else set()
    train_days |= set(rides["day"]) if rides is not None and not rides.empty else set()  # Fahrten = Trainingstage

    def ausdauer(d):
        s = vo2[vo2["measured_at"].dt.date <= d]["vo2"] if not vo2.empty else []
        if len(s) == 0:
            return None, "keine VO₂max"
        v = float(s.iloc[-1])
        return _clamp((v - 30) / 30 * 100), f"VO₂max {v:.0f}"

    def tempo(d):
        s = be5[(be5["started_at"].dt.date <= d) & (be5["started_at"].dt.date > d - timedelta(days=180))]
        if s.empty:
            return None, "kein 5-km-Wert (180 T)"
        t = float(s["seconds"].min())
        return _clamp((2400 - t) / (2400 - 1020) * 100), f"5 km {int(t // 60)}:{int(round(t % 60)):02d}"

    def staerke(d):
        pts = [p for p in idx if p[0] <= d]
        if not pts:
            return None, "kein Kraftindex"
        v = pts[-1][1]
        return _clamp((v - 70) / 80 * 100), f"Index {v:.0f}"

    def disziplin(d):
        span = [d - timedelta(days=i) for i in range(28)]
        healthy = [x for x in span if x not in sick]
        if not healthy:
            return 100, "28 T krank (pausiert)"
        n = sum(1 for x in healthy if x in train_days)
        return _clamp(n / (16 * len(healthy) / 28) * 100), f"{n} Trainingstage / 28 T"

    def erholung(d):
        s = sleep[(sleep["day"].dt.date <= d) & (sleep["day"].dt.date > d - timedelta(days=14))]["asleep_minutes"].dropna() \
            if not sleep.empty else []
        if len(s) < 3:
            return None, "zu wenig Schlafdaten"
        m = float(s.mean())
        return _clamp((m - 360) / 120 * 100), f"Ø {m / 60:.1f} h Schlaf".replace(".", ",")

    def beweglichkeit(d):
        vals = [steps[d - timedelta(days=i)] for i in range(30) if d - timedelta(days=i) in steps]
        if len(vals) < 5:
            return None, "zu wenig Schrittdaten"
        m = sum(vals) / len(vals)
        return _clamp((m - 4000) / 8000 * 100), f"Ø {m:,.0f} Schritte".replace(",", ".")

    spec = [("ausdauer", "Ausdauer", "VO₂max", ausdauer), ("tempo", "Tempo", "5-km-Bestzeit (180 T)", tempo),
            ("staerke", "Stärke", "Gesamtstärke-Index", staerke),
            ("disziplin", "Disziplin", "Trainingstage, Krankheit pausiert", disziplin),
            ("erholung", "Erholung", "Schlaf 14 T", erholung), ("beweglichkeit", "Beweglichkeit", "Schritte 30 T", beweglichkeit)]
    out = []
    for key, label, source, fn in spec:
        now, text = _safe(lambda fn=fn: fn(today), (None, "nicht verfügbar"))
        before, _ = _safe(lambda fn=fn: fn(today - timedelta(days=30)), (None, ""))
        out.append({"key": key, "label": label, "source": source, "score": now, "value": text,
                    "delta": (now - before) if now is not None and before is not None else None})
    return out


def _strength_series() -> list[tuple[date, float]]:
    from .metrics import strength
    res = strength.strength_index("12m") or {}
    out = []
    for p in res.get("series") or []:
        v = p.get("smoothed") if p.get("smoothed") is not None else p.get("raw")
        if v is not None:
            out.append((date.fromisoformat(str(p["week"])[:10]), float(v)))
    return out


# --- Beute ------------------------------------------------------------------------------
SLOTS = {
    "kopf": ("Kopf", ["Stirnband", "Laufkappe", "Haube"]),
    "schultern": ("Schultern", ["Schulterstücke", "Schulterwickel"]),
    "brust": ("Brust", ["Laufweste", "Wams", "Funktionsshirt", "Harnisch"]),
    "haende": ("Hände", ["Handschuhe", "Fäustlinge", "Handwickel"]),
    "handgelenk": ("Handgelenk", ["Armschienen", "Schweißbänder"]),
    "beine": ("Beine", ["Laufhose", "Beinkleider", "Gamaschen"]),
    "fuesse": ("Füße", ["Treter", "Laufschuhe", "Sohlen", "Spikes"]),
    "hals": ("Hals", ["Amulett", "Anhänger"]),
    "ring": ("Finger", ["Ring", "Siegelring"]),
    "schmuck": ("Schmuckstück", ["Stoppuhr", "Kompass", "Talisman", "Pulsstein"]),
}
_TIME_SUFFIX = [(6, "der Nacht"), (8, "des Morgengrauens"), (11, "des Vormittags"), (14, "der Mittagssonne"),
                (18, "des Nachmittags"), (21, "der Abendröte"), (24, "der Nacht")]
_ZONE_SUFFIX = ["des ruhigen Atems", "der Ausdauer", "des Tempos", "der Glut"]
_SEASON_SUFFIX = {"Winter": "des Frostpfads", "Frühling": "des Erwachens", "Sommer": "der Sommerhitze",
                  "Herbst": "des Herbstwinds"}
_EPIC_SUFFIX = ["des Windläufers", "der gebrochenen Bestzeit", "des unermüdlichen Herzens",
                "der letzten Meile", "des Sturmläufers"]
_FLAVOR = {
    "grau": "Kurz und knapp – immerhin bist du losgelaufen.",
    "weiss": "Solides Handwerk aus einem soliden Lauf.",
    "gruen": "Ein Hauch mehr als dein Durchschnitt hat es geschmiedet.",
    "blau": "Seltener Fund: Du warst effizienter als sonst.",
    "lila": "Episch – an diesem Tag ist eine Bestmarke gefallen.",
    "orange": "Legendär: geschmiedet aus einer neuen Bestzeit.",
    "rot": "Ein Artefakt. Darüber wird man in den Tavernen singen.",
}

_CHEST_FLAVOR = {
    "truhe": "Aus der Wochentruhe gehoben – der Lohn einer treuen Laufwoche.",
    "veteran": "Ein Erbstück deiner bisherigen Reise, lange vor dem ersten Drop verdient.",
    "auftrag": "Belohnung des Auftragsbretts – für eine Woche, in der alles erledigt wurde.",
    "boss": "Aus dem Hort eines besiegten Monatsbosses.",
    "instanz": "Aus der Schatzkammer einer bezwungenen Instanz.",
    "taeglich": "Fleißbelohnung für sieben erledigte Tagesaufgaben am Stück.",
    "event": "Festtagsbeute – nur in diesem einen Monat zu erringen.",
    "auktion": "Im Auktionshaus von Wesel erstanden – Gold gegen Glanz.",
    "gipfel": "Vom Gipfel mitgebracht – Höhenmeter für Höhenmeter in Zwift erklommen.",
    "verlies": "Aus einem Verlies im Nebel geborgen – je weiter der Weg, desto reicher der Hort.",
}


def flavor(rarity: str, source: str) -> str:
    return _CHEST_FLAVOR.get(source) or _FLAVOR[rarity]


def _season(m: int) -> str:
    return "Winter" if m in (12, 1, 2) else "Frühling" if m in (3, 4, 5) else "Sommer" if m in (6, 7, 8) else "Herbst"


def make_item(rng: random.Random, rarity: str, when: datetime, zone, level: int, source: str, reason: str) -> dict:
    slot = rng.choice(list(SLOTS))
    slot_label, bases = SLOTS[slot]
    hour = when.hour
    candidates = [next(s for h, s in _TIME_SUFFIX if hour < h), _SEASON_SUFFIX[_season(when.month)]]
    if zone is not None and pd.notna(zone):
        candidates.append(_ZONE_SUFFIX[min(3, int(zone))])
    if RARITIES.index(rarity) >= RARITIES.index("lila"):
        candidates = _EPIC_SUFFIX
    base, suffix = rng.choice(bases), rng.choice(candidates)
    return _item(rng, base, suffix, slot, rarity, level, flavor(rarity, source), source, reason, when)


def _item(rng: random.Random, base: str, suffix: str, slot: str, rarity: str, level: int, flavor_text: str,
          source: str, reason: str, when: datetime) -> dict:
    ilvl = 100 + 2 * level + 8 * RARITIES.index(rarity) + rng.randint(0, 3)
    return {"name": f"{base} {suffix}", "set": suffix, "slot": slot, "slot_label": SLOTS[slot][0], "rarity": rarity,
            "rarity_label": RARITY_LABEL[rarity], "ilvl": ilvl, "flavor": flavor_text,
            "source": source, "reason": reason, "date": when.date().isoformat()}


# Beute je Indoor-Fahrt: eigene Grundnamen (Rad statt Lauf), Namenszusatz aus der virtuellen Welt.
RIDE_BASES = {
    "kopf": ["Radhelm", "Radkappe", "Aerohelm"], "schultern": ["Windschultern", "Schulterkappen"],
    "brust": ["Radtrikot", "Zeitfahrwams", "Windweste"], "haende": ["Radhandschuhe", "Lenkerfäustlinge"],
    "handgelenk": ["Armlinge", "Schaltmanschetten"], "beine": ["Trägerhose", "Beinlinge"],
    "fuesse": ["Klickschuhe", "Überschuhe", "Pedalplatten"], "hals": ["Kettenamulett", "Ritzelanhänger"],
    "ring": ["Kettenring", "Speichenring"], "schmuck": ["Wattstein", "Trittfrequenzmesser", "Glockenspiel"],
}
_RIDE_EPIC_SUFFIX = ["des Sprinters", "der brennenden Kurbel", "des Gipfelstürmers", "des tausendsten Watts",
                     "des Windschattens"]
_RIDE_ZONE_SUFFIX = ["der leichten Kurbel", "der Grundlage", "der Schwelle", "des Wattsturms"]
RIDE_PR_SLOTS = {5: ["schmuck", "ring"], 60: ["schmuck", "ring"], 300: ["haende", "handgelenk"], 1200: ["brust"]}
RIDE_PR_LABEL = {5: "5 s", 60: "1 min", 300: "5 min", 1200: "20 min"}
_RIDE_FLAVOR = {
    "grau": "Kurz auf der Rolle – immerhin hast du getreten.",
    "gruen": "Mehr Zeit oder mehr Arbeit als sonst hat es geschmiedet.",
    "blau": "Seltener Fund: eine lange oder besonders effiziente Fahrt.",
    "lila": "Episch – an diesem Tag ist ein Leistungs-Bestwert gefallen.",
    "orange": "Legendär: geschmiedet aus neuer Schwellenleistung.",
    "rot": "Ein Artefakt. Hundert Kilometer oder ein ganzer Everest auf der Rolle.",
}


def make_ride_item(rng: random.Random, rarity: str, ride, level: int, reason: str, slots: list[str] | None) -> dict:
    slot = rng.choice(slots or list(SLOTS))
    when = ride.started_at.to_pydatetime() if hasattr(ride.started_at, "to_pydatetime") else ride.started_at
    zone = ride.zone if ride.zone is not None and pd.notna(ride.zone) else None
    if RARITIES.index(rarity) >= RARITIES.index("lila"):
        candidates = _RIDE_EPIC_SUFFIX
    elif isinstance(ride.world, str) and ride.world:
        candidates = [f"von {ride.world}"]
    else:
        candidates = [_SEASON_SUFFIX[_season(when.month)]] + ([_RIDE_ZONE_SUFFIX[min(3, int(zone))]] if zone is not None else [])
    base, suffix = rng.choice(RIDE_BASES[slot]), rng.choice(candidates)
    return _item(rng, base, suffix, slot, rarity, level, _RIDE_FLAVOR.get(rarity, _FLAVOR[rarity]), "beute", reason, when)


def _eftp_rise(rides: pd.DataFrame, i: int) -> bool:
    """Hebt die Fahrt i Milons automatische eFTP (90 T) gegenüber dem Stand direkt davor?"""
    from .config import settings
    from .metrics import cycling
    if settings.bike_ftp and settings.bike_ftp > 0:
        return False
    ride = rides.iloc[i]
    before = rides.iloc[:i]
    before = before[before["has_power"]]
    if not ride["has_power"] or before.empty:
        return False
    old, _ = cycling._auto_eftp(before, ride["day"], None)
    new, _ = cycling._auto_eftp(pd.concat([before, rides.iloc[i:i + 1]]), ride["day"], None)
    return bool(old and new and new > old + 0.5)


def ride_rarity(ride, prior: pd.DataFrame, eftp_rise: bool = False) -> tuple[str, str, list[str] | None]:
    """Verdiente Rarität einer Fahrt gegen die eigenen Fahrten davor (Bestwerte) bzw. der 90 Tage davor.
    Liefert zusätzlich die Ausrüstungsplätze, aus denen ein Bestwert-Gegenstand stammt."""
    if ride.km >= 100 or ride.elevation_m >= 8848:
        return "rot", "100 km oder 8.848 Hm in einer Fahrt", None
    if ride.dur_min < 20:
        return "grau", "kurze Fahrt", None
    prs = []
    for sec in RIDE_PR_SLOTS:
        watts = (ride.power_curve or {}).get(sec)
        earlier = [c[sec] for c in prior["power_curve"] if c and c.get(sec)] if not prior.empty else []
        if watts and earlier and watts > max(earlier):
            prs.append(sec)
    if 1200 in prs:
        return "orange", "neuer 20-min-Bestwert", RIDE_PR_SLOTS[1200]
    if eftp_rise:
        return "orange", "eFTP gestiegen", RIDE_PR_SLOTS[1200]
    if prs:
        sec = max(prs)
        return "lila", f"neuer Bestwert über {RIDE_PR_LABEL[sec]}", RIDE_PR_SLOTS[sec]
    window = prior[prior["started_at"] >= ride.started_at - pd.Timedelta(days=90)] if not prior.empty else prior
    if len(window) >= 3 and ride.dur_min > window["dur_min"].max():
        return "blau", "längste Fahrt seit 90 Tagen", None
    efs = window["ef"].dropna() if not window.empty else pd.Series(dtype=float)
    if pd.notna(ride.ef) and len(efs) >= 3 and ride.ef >= efs.quantile(0.75):
        return "blau", "effizienter als 3 von 4 Fahrten", None
    if len(window) >= 3 and (ride.dur_min > window["dur_min"].mean() or ride.kj > window["kj"].mean()):
        return "gruen", "mehr Zeit oder Arbeit als dein Schnitt", None
    return "weiss", "solide Fahrt", None


def ride_drops(rides: pd.DataFrame, entries: list[dict], start: date, mods: Mods | None = None) -> list[dict]:
    """Beute je Indoor-Fahrt ab Starttag — Rarität verdient, Gegenstand fest an die Fahrt geseedet."""
    out = []
    for i, r in enumerate(rides.itertuples()):
        if r.day < start:
            continue
        rarity, reason, slots = ride_rarity(r, rides.iloc[:i], _safe(lambda i=i: _eftp_rise(rides, i), False))
        rng = _rng("ride", r.key)
        lucky = rarity not in ("orange", "rot") and rng.random() < (mods or Mods()).luck(r.day)
        if lucky:
            rarity = RARITIES[RARITIES.index(rarity) + 1]
            reason += " · Glücksfund"
        item = make_ride_item(rng, rarity, r, _level_at(entries, r.day), reason, slots)
        out.append({**item, "id": f"drop:{r.key}", "lucky": lucky, "ride_min": int(round(float(r.dur_min)))})
    return out


def drop_rarity(run, prior: pd.DataFrame, efforts: pd.DataFrame) -> tuple[str, str]:
    """Verdiente Rarität eines Laufs gegen die eigenen Läufe der 90 Tage davor."""
    if run.distance_km >= 21.0975:
        return "rot", "Halbmarathon oder mehr"
    if run.distance_km < 3 or run.dur_min < 20:
        return "grau", "kurzer Lauf"
    mine = efforts[efforts["external_id"] == run.external_id] if not efforts.empty else efforts
    earlier = efforts[efforts["started_at"] < run.started_at] if not efforts.empty else efforts
    prs = []
    for e in mine.itertuples():
        prev = earlier[earlier["distance_m"] == e.distance_m]["seconds"]
        if len(prev) and e.seconds < prev.min():
            prs.append(int(e.distance_m))
    if any(dm in (5000, 10000) for dm in prs):
        return "orange", f"neue Bestzeit über {max(dm for dm in prs if dm in (5000, 10000)) // 1000} km"
    if prs:
        return "lila", f"neue Bestzeit über {prs[0] / 1000:g} km"
    window = prior[prior["started_at"] >= run.started_at - pd.Timedelta(days=90)]
    if not window.empty and run.distance_km > window["distance_km"].max() and len(window) >= 3:
        return "blau", "längster Lauf seit 90 Tagen"
    efs = window["ef"].dropna()
    if pd.notna(run.ef) and len(efs) >= 3:
        if run.ef >= efs.quantile(0.75):
            return "blau", "effizienter als 3 von 4 Läufen"
        if run.ef >= efs.median():
            return "gruen", "effizienter als dein Schnitt"
    if len(window) >= 3 and run.distance_km >= 1.2 * window["distance_km"].median():
        return "gruen", "länger als dein Schnitt"
    return "weiss", "solider Lauf"


def _level_at(entries: list[dict], d: date) -> int:
    return level_for(sum(e["xp"] + e["bonus"] for e in entries if e["date"] <= d))["level"]


def drops(runs: pd.DataFrame, entries: list[dict], start: date, mods: Mods | None = None) -> list[dict]:
    efforts = _best_efforts()
    out = []
    for i, r in enumerate(runs.itertuples()):
        if r.day < start:
            continue
        rarity, reason = drop_rarity(r, runs.iloc[:i], efforts)
        rng = _rng("drop", r.key)
        lucky = rarity not in ("orange", "rot") and rng.random() < (mods or Mods()).luck(r.day)
        if lucky:
            rarity = RARITIES[RARITIES.index(rarity) + 1]
            reason += " · Glücksfund"
        item = make_item(rng, rarity, r.started_at.to_pydatetime(), r.zone, _level_at(entries, r.day), "beute", reason)
        out.append({**item, "id": f"drop:{r.key}", "lucky": lucky, "run_km": round(float(r.distance_km), 1)})
    return out


# --- Wochentruhe ------------------------------------------------------------------------
VAULT_THRESHOLDS = [1, 3, 4]
RIDE_VAULT_MIN = 30   # Fahrt zählt ab 30 min für die Truhen-Schwellen


def _claims() -> dict[str, HeroClaim]:
    with Session(engine) as session:
        return {c.week: c for c in session.exec(select(HeroClaim)).all()}


STONE_RARITY = [(12, "orange"), (8, "lila"), (5, "blau"), (2, "gruen")]   # Steinstufe → Mindestqualität der Truhe


def stone_rarity(level: int) -> str | None:
    return next((r for lv, r in STONE_RARITY if level >= lv), None)


def vault_week(week: date, runs: pd.DataFrame, items: list[dict], sick: set[date], entries, today: date,
               mods: Mods | None = None, stones: list[dict] | None = None, rides: pd.DataFrame | None = None) -> dict:
    end = week + timedelta(days=6)
    n = int(((runs["day"] >= week) & (runs["day"] <= end)).sum()) if not runs.empty else 0
    # Fahrten ab 30 min zählen wie Läufe für die Slot-Schwellen; ihre Beute (Quelle „beute“) für die Qualität.
    n_rides = int(((rides["day"] >= week) & (rides["day"] <= end) & (rides["dur_min"] >= RIDE_VAULT_MIN)).sum()) \
        if rides is not None and not rides.empty else 0
    n += n_rides
    sick_n = sum(1 for i in range(7) if week + timedelta(days=i) in sick)
    relief = sick_n // 2
    thresholds = [max(1, t - relief) for t in VAULT_THRESHOLDS]
    week_items = [it for it in items if it["source"] == "beute" and week.isoformat() <= it["date"] <= end.isoformat()]
    base = max((RARITIES.index(it["rarity"]) for it in week_items), default=RARITIES.index("weiss"))
    # Mythisch: der höchste in der Zeit geschaffte Stein der Woche bestimmt die Qualität von Slot 1 (ohne Steine unverändert).
    stone = hero_keystone.week_best(stones, week) if stones else 0
    stone_base = max(base, RARITIES.index(stone_rarity(stone) or "grau")) if stone else base
    base = min(base, RARITIES.index("orange"))
    level = _level_at(entries, min(end, today))
    slots = []
    for i, t in enumerate(thresholds):
        # Mehr Läufe = mehr Auswahl (wie die Great Vault), Qualität = beste Leistung der Woche.
        rng = _rng("vault", week.isoformat(), i)
        bump = 1 if rng.random() < (mods or Mods()).vault_bonus(min(end, today)) else 0
        rarity = RARITIES[min(RARITIES.index("orange"), (stone_base if i == 0 else base) + bump)]
        item = make_item(rng, rarity, datetime.combine(end, datetime.min.time()).replace(hour=8), None, level,
                         "truhe", f"Wochentruhe · Slot {i + 1}")
        item["ilvl"] += 3 * i + (stone if i == 0 else 0)
        slots.append({"slot": i, "threshold": t, "unlocked": n >= t, "item": {**item, "id": f"truhe:{week}:{i}"}})
    return {"week": week.isoformat(), "runs": n, "rides": n_rides, "sick_days": sick_n, "slots": slots,
            "complete": end < today, "stone_level": stone or None}


def veteran_chest(level: int, today: date) -> dict:
    when = datetime.combine(today, datetime.min.time()).replace(hour=8)
    slots = []
    for i, rarity in enumerate(["blau", "lila", "orange"]):
        item = make_item(_rng("veteran", i), rarity, when, None, level, "veteran", "Veteranentruhe für deine bisherige Reise")
        slots.append({"slot": i, "threshold": 0, "unlocked": True, "item": {**item, "id": f"veteran:{i}"}})
    return {"week": "veteran", "runs": 0, "rides": 0, "sick_days": 0, "slots": slots, "complete": True}


def vault(runs, items, sick, entries, start: date, today: date, level: int, mods: Mods | None = None,
          stones: list[dict] | None = None, rides: pd.DataFrame | None = None) -> dict:
    claims = _claims()
    def with_claim(v):
        c = claims.get(v["week"])
        return {**v, "claimed_slot": c.slot if c else None}
    current = with_claim(vault_week(_monday(today), runs, items, sick, entries, today, mods, stones, rides))
    claimable = []
    w = _monday(start)
    while w < _monday(today):
        v = with_claim(vault_week(w, runs, items, sick, entries, today, mods, stones, rides))
        if v["claimed_slot"] is None and any(s["unlocked"] for s in v["slots"]):
            claimable.append(v)
        w += timedelta(days=7)
    veteran = with_claim(veteran_chest(level, start))
    return {"current": current, "claimable": claimable[::-1],
            "veteran": veteran if veteran["claimed_slot"] is None else None}


def claim(week: str, slot: int, today: date | None = None) -> dict:
    """Wählt einen freigeschalteten Slot. ValueError = ungültig, KeyError = schon gewählt."""
    today = today or local_today()
    data = _load(today)
    if week in _claims():
        raise KeyError(week)
    if week == "veteran":
        chest = veteran_chest(data["level"], data["start"])
    else:
        monday = date.fromisoformat(week)
        if monday.weekday() != 0 or monday < _monday(data["start"]) or monday >= _monday(today):
            raise ValueError("Diese Woche ist noch nicht abgeschlossen oder liegt vor dem Start.")
        chest = vault_week(monday, data["runs"], data["drops"], data["sick"], data["entries"], today, data["mods"],
                           data.get("stones"), data.get("indoor"))
    picked = next((s for s in chest["slots"] if s["slot"] == slot), None)
    if picked is None or not picked["unlocked"]:
        raise ValueError("Slot nicht freigeschaltet.")
    item = picked["item"]
    with Session(engine) as session:
        session.add(HeroClaim(week=week, slot=slot, item_json=json.dumps(item, ensure_ascii=False),
                              claimed_at=datetime.now()))
        session.commit()
    return item


# --- Ausrüstung ------------------------------------------------------------------------
DUST = {"grau": 1, "weiss": 2, "gruen": 5, "blau": 10, "lila": 25, "orange": 60, "rot": 150}
UPGRADE_ILVL = 4
MAX_UPGRADES = 3


def _set_suffix(item: dict) -> str | None:
    if item.get("set"):
        return item["set"]
    base = next((b for b in SLOTS.get(item["slot"], ("", []))[1] if item["name"].startswith(b + " ")), None)
    return item["name"][len(base) + 1:] if base else None


def _item_mods() -> dict[str, HeroItemMod]:
    with Session(engine) as session:
        return {m.item_id: m for m in session.exec(select(HeroItemMod)).all()}


def upgrade_cost(upgrades: int) -> int:
    return 10 * (upgrades + 1)


def dust_balance(mods: dict[str, HeroItemMod]) -> int:
    spent = sum(10 * m.upgrades * (m.upgrades + 1) // 2 for m in mods.values())
    return sum(m.dust for m in mods.values() if m.disenchanted) - spent


def _inventory(drops_: list[dict], claims: dict[str, HeroClaim]) -> list[dict]:
    claimed = [{**(it := json.loads(c.item_json)), "flavor": flavor(it["rarity"], it["source"]),
                "claimed_at": c.claimed_at.isoformat()} for c in claims.values()]
    claimed += [json.loads(p.payload) for p in _purchases() if p.kind == "item"]
    mods = _item_mods()
    out = []
    for it in drops_ + claimed:
        m = mods.get(it["id"])
        if m and (m.disenchanted or m.sold):
            continue
        ups = m.upgrades if m else 0
        out.append({**it, "set": _set_suffix(it), "upgrades": ups, "ilvl": it["ilvl"] + UPGRADE_ILVL * ups,
                    "upgrade_cost": upgrade_cost(ups) if ups < MAX_UPGRADES else None, "dust": DUST[it["rarity"]],
                    "price": hero_economy.sell_price({**it, "ilvl": it["ilvl"] + UPGRADE_ILVL * ups})})
    return sorted(out, key=lambda it: (it["date"], it["ilvl"]), reverse=True)


def _find_item(item_id: str) -> dict:
    items = _inventory(_load(local_today())["drops"], _claims())
    item = next((it for it in items if it["id"] == item_id), None)
    if item is None:
        raise KeyError(item_id)
    return item


def disenchant(item_id: str) -> int:
    """Zerlegt einen nicht angelegten Gegenstand in Arkanstaub. KeyError/ValueError bei Ungültigem."""
    item = _find_item(item_id)
    if _equipment().get(item["slot"]) == item_id:
        raise ValueError("Angelegte Gegenstände können nicht entzaubert werden.")
    with Session(engine) as session:
        row = session.get(HeroItemMod, item_id) or HeroItemMod(item_id=item_id)
        row.disenchanted, row.dust = True, DUST[item["rarity"]]
        session.add(row)
        session.commit()
    return DUST[item["rarity"]]


def sell(item_id: str) -> int:
    """Verkauft einen nicht angelegten Gegenstand an den Händler; liefert den Erlös in Kupfer."""
    item = _find_item(item_id)
    if _equipment().get(item["slot"]) == item_id:
        raise ValueError("Angelegte Gegenstände können nicht verkauft werden.")
    with Session(engine) as session:
        row = session.get(HeroItemMod, item_id) or HeroItemMod(item_id=item_id)
        row.sold, row.gold = True, item["price"]
        session.add(row)
        session.commit()
    return item["price"]


def gold_view(data: dict, today: date) -> dict:
    earned = hero_economy.earnings(data, data["start"])
    sold = sum(m.gold for m in _item_mods().values() if m.sold)
    spent = _safe(_gold_spent, 0)
    week = today - timedelta(days=today.weekday())
    by_source: dict[str, int] = {}
    for _, c, src in earned:
        by_source[src] = by_source.get(src, 0) + c
    return {"balance": sum(c for _, c, _ in earned) + sold - spent, "earned": sum(c for _, c, _ in earned),
            "sold": sold, "spent": spent, "week": sum(c for d, c, _ in earned if d >= week),
            "sources": by_source, "rates": hero_economy.EARN}


def _gold_spent() -> int:
    return sum(p.price for p in _purchases())


def _purchases() -> list[HeroPurchase]:
    with Session(engine) as session:
        return list(session.exec(select(HeroPurchase)).all())


def _potion_days() -> dict[date, set[str]]:
    out: dict[date, set[str]] = {}
    with Session(engine) as session:
        for u in session.exec(select(HeroPotionUse)).all():
            out.setdefault(u.day, set()).add(u.key)
    return out


def auction_view(level: int, today: date) -> dict:
    week = today - timedelta(days=today.weekday())
    bought = {p.id for p in _purchases()}
    stock = hero_economy.auction_stock(
        week, level, lambda rng, rarity, wk, lvl: make_item(rng, rarity, datetime.combine(wk, datetime.min.time()).replace(hour=9),
                                                          None, lvl, "auktion", "Im Auktionshaus erstanden"))
    for s_ in stock:
        s_["sold"] = f"ah:{week.isoformat()}:{s_['idx']}" in bought
    return {"week": week.isoformat(), "ends": (week + timedelta(days=7)).isoformat(), "listings": stock}


def potions_view(today: date) -> list[dict]:
    bought: dict[str, int] = {}
    for p in _purchases():
        if p.kind == "potion":
            key = json.loads(p.payload)["key"]
            bought[key] = bought.get(key, 0) + 1
    used: dict[str, int] = {}
    today_used: set[str] = set()
    for d, keys in _potion_days().items():
        for k in keys:
            used[k] = used.get(k, 0) + 1
            if d == today:
                today_used.add(k)
    return [{"key": k, "name": n, "effect": e, "price": price, "glyph": g, "count": bought.get(k, 0) - used.get(k, 0),
             "active_today": k in today_used} for k, (n, e, price, g) in hero_economy.POTIONS.items()]


def buy(kind: str, ref: str, today: date | None = None) -> dict:
    """Kauft ein Angebot (kind='listing', ref=idx) oder einen Trank (kind='potion', ref=key)."""
    today = today or local_today()
    data = _load(today)
    balance = gold_view(data, today)["balance"]
    week = today - timedelta(days=today.weekday())
    if kind == "potion":
        if ref not in hero_economy.POTIONS:
            raise KeyError(ref)
        price = hero_economy.POTIONS[ref][2]
        pid, payload, pkind = f"potion:{datetime.now().isoformat()}", {"key": ref}, "potion"
    else:
        listing = next((x for x in auction_view(data["level"], today)["listings"] if str(x["idx"]) == str(ref)), None)
        if listing is None:
            raise KeyError(ref)
        if listing["sold"]:
            raise ValueError("Schon verkauft – nächste Woche gibt es Nachschub.")
        price, pid, pkind = listing["price"], f"ah:{week.isoformat()}:{listing['idx']}", listing["kind"]
        payload = listing.get("item") or listing.get("bag") or listing.get("mount")
        if pkind == "bag":
            payload = {**payload, "date": today.isoformat()}
    if balance < price:
        raise ValueError(f"Zu wenig Gold – es fehlen {hero_economy.money(price - balance)}.")
    with Session(engine) as session:
        session.add(HeroPurchase(id=pid, week=week.isoformat(), kind=pkind, price=price,
                                 payload=json.dumps(payload, ensure_ascii=False), bought_at=datetime.now()))
        session.commit()
    return {"kind": pkind, "price": price, "payload": payload}


def drink(key: str, today: date | None = None) -> None:
    today = today or local_today()
    pot = next((p for p in potions_view(today) if p["key"] == key), None)
    if pot is None:
        raise KeyError(key)
    if pot["active_today"]:
        raise ValueError("Diesen Trank hast du heute schon getrunken.")
    if pot["count"] < 1:
        raise ValueError("Kein Trank mehr im Gepäck.")
    with Session(engine) as session:
        session.add(HeroPotionUse(day=today, key=key, used_at=datetime.now()))
        session.commit()


def upgrade(item_id: str) -> dict:
    item = _find_item(item_id)
    mods = _item_mods()
    ups = mods[item_id].upgrades if item_id in mods else 0
    if ups >= MAX_UPGRADES:
        raise ValueError("Bereits voll aufgewertet.")
    if dust_balance(mods) < upgrade_cost(ups):
        raise ValueError(f"Zu wenig Arkanstaub – {upgrade_cost(ups)} nötig.")
    with Session(engine) as session:
        row = session.get(HeroItemMod, item_id) or HeroItemMod(item_id=item_id)
        row.upgrades = ups + 1
        session.add(row)
        session.commit()
    return {**item, "upgrades": ups + 1, "ilvl": item["ilvl"] + UPGRADE_ILVL}


def _ride_days() -> list[tuple[date, float]]:
    """GPS-Radfahrten aus Garmin (Tag, km) — nur sie füttern Reittiere (HC-Pendelfahrten ohne Spur zählen nicht)."""
    df = _read("SELECT started_at, distance_km FROM garmin_rides")
    out = []
    for ts, km in zip(pd.to_datetime(df["started_at"]), df["distance_km"]):
        if pd.notna(km) and 0 < float(km) <= 300:
            out.append((ts.date(), float(km)))
    return out


def _zwift_days(indoor: pd.DataFrame) -> list[tuple[date, float]]:
    """Virtuelle Zwift-km je Fahrt (Tag, km) — füttern Reittiere zum vollen Satz; nie Koordinaten."""
    if indoor is None or indoor.empty:
        return []
    return [(r.day, float(r.km)) for r in indoor.itertuples() if pd.notna(r.km) and 0 < float(r.km) <= 300]


def _ride_minutes(indoor: pd.DataFrame) -> list[tuple[date, float]]:
    """Rad-Zeit je Fahrt (Tag, Minuten): Indoor-Fahrten plus GPS-Fahrten — Basis des Monatsbosses Kettenfresser."""
    out = [] if indoor is None or indoor.empty else [(r.day, float(r.dur_min)) for r in indoor.itertuples()]
    df = _safe(lambda: _read("SELECT started_at, duration_seconds FROM garmin_rides"), None)
    if df is not None:
        for ts, sec in zip(pd.to_datetime(df["started_at"]), df["duration_seconds"]):
            if pd.notna(sec) and 5 * 60 < float(sec) < 600 * 60:
                out.append((ts.date(), float(sec) / 60))
    return out


def _mount_history(start: date) -> list[dict]:
    """Datierte Reittier-Wahl [{from, value}]; ein älterer, undatierter Wert gilt ab Starttag."""
    hist = _history("mount_history")
    if not hist:
        legacy = _state_get("mount")
        if legacy:
            hist = [{"from": start.isoformat(), "value": legacy}]
    return hist


def _all_mounts(data: dict, chosen: str | None) -> list[dict]:
    fed: dict[str, float] = data.get("fed") or {}
    mounts = hero_extras.mounts(data["runs"], data["workouts"], chosen, data.get("rides"), fed, data.get("zwift_days"))
    for p in _purchases():
        if p.kind == "mount":
            m = json.loads(p.payload)
            km = round(fed.get(m["key"], 0.0), 1)
            mounts.append({**m, "kind": "auktion", "need": 0, "value": 0, "unlocked": True, "unit": "Auktionshaus",
                           "unlocked_on": p.bought_at.date().isoformat(), "chosen": m["key"] == chosen,
                           "ride_km": km, "level": hero_extras.mount_level(km)})
    return mounts


def choose_mount(key: str | None) -> None:
    today = local_today()
    if key is not None:
        data = _load(today)
        m = next((m for m in _all_mounts(data, None) if m["key"] == key), None)
        if m is None:
            raise KeyError(key)
        if not m["unlocked"]:
            raise ValueError("Reittier noch nicht freigeschaltet.")
    # Die Historie wird zuerst aus dem bisherigen Wert aufgebaut, damit frühere Fahrten ihrem Tier bleiben.
    if not _history("mount_history"):
        _state_set("mount_history", json.dumps(_mount_history(start_date(today))))
    _choose("mount_history", key or "", today)
    _state_set("mount", key or "")


def choose_title(key: str | None, today: date | None = None) -> None:
    if key is not None:
        t = next((t for t in overview(today)["titles"] if t["key"] == key), None)
        if t is None:
            raise KeyError(key)
        if not t["earned"]:
            raise ValueError("Titel noch nicht freigeschaltet.")
    _state_set("title", key or "")


def _hero_stats(data: dict, inventory: list[dict], level: int, totals: dict) -> dict:
    runs, target = data["runs"], data["protein_target"]
    months: dict[str, int] = {}
    raid: dict[str, list[bool]] = {}
    for b in data["bosses"]:
        months[b["month"]] = months.get(b["month"], 0) + (1 if b["defeated"] else 0)
        if b["key"] != "kettenfresser":   # Zusatzboss: ein schon gewonnener Schlachtzug geht durch ihn nie verloren
            raid.setdefault(b["month"], []).append(b["defeated"])
    stats = {
        "runs": int(len(runs)), "km": float(runs["distance_km"].sum()) if not runs.empty else 0.0,
        "early_runs": int((runs["started_at"].dt.hour < 8).sum()) if not runs.empty else 0,
        "workouts": int(len(data["workouts"])), "streak": _safe(_streak, 0),
        "quests_done": sum(q["done"] for wk in data["quest_weeks"] for q in wk["quests"]),
        "bosses_down": sum(months.values()), "full_raids": sum(1 for v in raid.values() if all(v)),
        "dungeons_cleared": sum(1 for d in data["dungeons"] if d["cleared"]),
        "items": len(inventory), "legendaries": sum(1 for it in inventory if it["rarity"] in ("orange", "rot")),
        "level": level, "laufen": totals.get("laufen", 0.0), "kraft": totals.get("kraft", 0.0),
        "protein_days": sum(1 for g in data["protein"].values() if target and g >= 0.9 * target),
        "sleep_nights": sum(1 for m in data["sleep"].values() if m >= 420),
    }
    stats["regions"] = sum(1 for r in data.get("world", {}).get("regions", []) if r["discovered"])
    stats["peaks"] = sum(1 for p in (data.get("climb") or {}).get("peaks", []) if p["reached"])
    stats["dream_worlds"] = (data.get("dreams") or {}).get("visited_known", 0)
    dgs = [d for d in data.get("world", {}).get("dungeons", []) if not d.get("own")]   # Option B: eigene zählen nicht
    mythic = _safe(lambda: hero_keystone.rating(data.get("stones")), None) or {}
    stats["key_best"], stats["key_total"] = mythic.get("best_level", 0), mythic.get("total", 0)
    stats["key_dungeons"] = mythic.get("dungeons_timed", 0)
    stats["map_dungeons"] = sum(1 for d in dgs if d["cleared"])
    stats["map_heroic"] = sum(1 for d in dgs if d["heroic"])
    for kind in hero_world.DUNGEON_TYPES:
        stats[f"map_{kind}"] = sum(1 for d in dgs if d["cleared"] and d["type"] == kind)
    stats["exalted"] = sum(1 for f in hero_social.reputation(stats) if f["standing"] == "Ehrfürchtig")
    return stats


def _equipment() -> dict[str, str]:
    with Session(engine) as session:
        return {e.slot: e.item_id for e in session.exec(select(HeroEquip)).all()}


def _set_slot(session: Session, slot: str, item_id: str | None) -> None:
    row = session.get(HeroEquip, slot)
    if item_id is None:
        if row is not None:
            session.delete(row)
    elif row is None:
        session.add(HeroEquip(slot=slot, item_id=item_id, equipped_at=datetime.now()))
    else:
        row.item_id, row.equipped_at = item_id, datetime.now()
        session.add(row)


def equip(item_id: str, today: date | None = None) -> dict:
    """Legt einen Gegenstand aus dem Inventar an (ersetzt den Platz). KeyError = unbekannt."""
    items = _inventory(_load(today or local_today())["drops"], _claims())
    item = next((it for it in items if it["id"] == item_id), None)
    if item is None:
        raise KeyError(item_id)
    with Session(engine) as session:
        _set_slot(session, item["slot"], item_id)
        session.commit()
    return item


def unequip(slot: str) -> None:
    if slot not in SLOTS:
        raise KeyError(slot)
    with Session(engine) as session:
        _set_slot(session, slot, None)
        session.commit()


def equip_best(today: date | None = None) -> dict[str, str]:
    """Legt je Platz den Gegenstand mit der höchsten Stufe an."""
    best: dict[str, dict] = {}
    for it in _inventory(_load(today or local_today())["drops"], _claims()):
        if it["slot"] not in best or it["ilvl"] > best[it["slot"]]["ilvl"]:
            best[it["slot"]] = it
    with Session(engine) as session:
        for slot, it in best.items():
            _set_slot(session, slot, it["id"])
        session.commit()
    return {slot: it["id"] for slot, it in best.items()}


# --- Aufträge & Talente --------------------------------------------------------------
def quest_loot(weeks: list[dict], entries: list[dict]) -> list[dict]:
    out = []
    for wk in weeks:
        if not wk["complete"]:
            continue
        rng = _rng("questloot", wk["week"])
        rarity = rng.choices(["gruen", "blau", "lila"], weights=[60, 35, 5])[0]
        done = date.fromisoformat(wk["complete_on"])
        item = make_item(rng, rarity, datetime.combine(done, datetime.min.time()).replace(hour=18), None,
                         _level_at(entries, done), "auftrag", "Alle Wochenaufträge erfüllt")
        out.append({**item, "id": f"quest:{wk['week']}"})
    return out


def boss_loot(bosses: list[dict], dungeons: list[dict], entries: list[dict]) -> list[dict]:
    out = []
    for b in bosses:
        if not b["defeated"]:
            continue
        rng = _rng("bossloot", b["month"], b["key"])
        rarity = "orange" if b["loot"] == "orange" and rng.random() < 0.5 else "lila"
        won = date.fromisoformat(b["defeated_on"])
        item = make_item(rng, rarity, datetime.combine(won, datetime.min.time()).replace(hour=20), None,
                         _level_at(entries, won), "boss", f"Monatsboss „{b['name']}“ besiegt")
        out.append({**item, "id": f"boss:{b['month']}:{b['key']}"})
    for dg in dungeons:
        if not dg["cleared"]:
            continue
        rng = _rng("dungeonloot", dg["id"])
        day = date.fromisoformat(dg["date"])
        item = make_item(rng, dg["loot"], datetime.combine(day, datetime.min.time()).replace(hour=12), None,
                         _level_at(entries, day), "instanz", f"{dg['tier_label']}e Instanz „{dg['name']}“ bezwungen")
        out.append({**item, "id": dg["id"]})
    return out


def climb_loot(events: list[dict], entries: list[dict]) -> list[dict]:
    out = []
    for e in events:
        rng = _rng("climbloot", e["id"])
        day = date.fromisoformat(e["date"])
        item = make_item(rng, e["loot"], datetime.combine(day, datetime.min.time()).replace(hour=17), None,
                         _level_at(entries, day), "gipfel", f"Gipfel „{e['name']}“ bezwungen")
        out.append({**item, "id": f"climb:{e['id']}"})
    return out


def event_loot(daily: dict | None, events: list[dict], entries: list[dict]) -> list[dict]:
    out = []
    for d in (daily or {}).get("loot_days", []):
        rng = _rng("dailyloot", d.isoformat())
        item = make_item(rng, "blau", datetime.combine(d, datetime.min.time()).replace(hour=21), None,
                         _level_at(entries, d), "taeglich", "7 Tagesaufgaben in Folge")
        out.append({**item, "id": f"daily:{d.isoformat()}"})
    for e in events:
        if not e["done"]:
            continue
        d = date.fromisoformat(e["done_on"])
        item = make_item(_rng("eventloot", e["month"]), "lila", datetime.combine(d, datetime.min.time()).replace(hour=19), None,
                         _level_at(entries, d), "event", f"Event „{e['name']}“ abgeschlossen")
        out.append({**item, "name": e["item"], "set": None, "id": f"event:{e['month']}"})
    return out


def map_loot(world: dict, start: date) -> list[dict]:
    """Beute aus Verliesen der Weltkarte (ab Starttag); Gegenstandsstufe folgt der Stufe des Verlieses."""
    out = []
    for dg in world.get("dungeons", []):
        if not dg["cleared"] or date.fromisoformat(dg["cleared_on"]) < start:
            continue
        d = date.fromisoformat(dg["cleared_on"])
        mode = "heroisch" if dg["heroic"] else "normal"
        item = make_item(_rng("maploot", dg["id"], mode), dg["loot"], datetime.combine(d, datetime.min.time()).replace(hour=13), None,
                         dg["level"], "verlies", f"{'Heroisches ' if dg['heroic'] else ''}Verlies „{dg['name']}“ (Stufe {dg['level']}) bezwungen")
        out.append({**item, "id": f"map:{dg['key']}"})
    return out


def live_event_loot(events: list[dict], entries: list[dict]) -> list[dict]:
    """Beute aus spontanen Ereignissen des Abenteuerlaufs (erst nach Garmin-Bestätigung)."""
    out = []
    for e in events:
        d = date.fromisoformat(e["date"])
        item = make_item(_rng("liveevent", e["id"]), e["loot"], datetime.fromtimestamp(e["reached_ms"] / 1000), None,
                         _level_at(entries, d), "events", f"Ereignis „{e['name']}“ (Stein +{e['level']}) bestanden")
        out.append({**item, "id": f"liveevent:{e['id']}"})
    return out


def trainer(data: dict, overview_parts: dict, today: date, pool: float, cap: float) -> dict:
    runs = data["runs"]
    yesterday = today - timedelta(days=1)
    y_runs = runs[runs["day"] == yesterday] if not runs.empty else runs
    long_y = float(y_runs["distance_km"].max()) if not y_runs.empty and y_runs["distance_km"].max() >= 15 else None
    weak = next((b for b in overview_parts["bosses"] if not b["defeated"] and b["hp"] < 0.25), None)
    cur = overview_parts["vault"]["current"]
    locked = [s["threshold"] for s in cur["slots"] if not s["unlocked"]]
    missing = (locked[0] - cur["runs"]) if locked else None
    quests = overview_parts["quests"]
    open_q = next((q["title"] for q in quests["quests"] if not q["done"]), None) if quests else None
    ev = overview_parts["event"]
    ctx = {"class_label": overview_parts["class_label"], "sick": today in data["sick"] or bool(_checkin(today).get("sick")),
           "long_run_yesterday": long_y, "tired": data["sleep"].get(today, 999) < 360, "weak_boss": weak,
           "vault_runs_missing": missing if missing is not None and missing <= 2 else None, "open_quest": open_q,
           "rested_full": pool >= cap, "event_left": (ev["goal"] - ev["tokens"]) if ev and not ev["done"] else None,
           "event_name": ev["name"] if ev else None, "event_token": ev["token"] if ev else None}
    return {"name": hero_events.TRAINER, "role": hero_events.TRAINER_ROLE, "quote": hero_events.trainer_quote(ctx, today)}


def talents_view(mods: Mods, level: int, today: date) -> list[dict]:
    rows = []
    for lvl, name, options in TALENT_ROWS:
        rows.append({"level": lvl, "name": name, "unlocked": level >= lvl, "chosen": mods.talent(lvl, today),
                     "options": [{"key": k, "name": n, "effect": e, "icon": i} for k, n, e, i in options]})
    rows += [{"level": lvl, "name": "Noch verborgen", "unlocked": False, "chosen": None, "options": []} for lvl in TALENT_LOCKED]
    return rows


def choose_talent(row: int, choice: str | None, today: date | None = None) -> None:
    """Wählt ein Talent einer freigeschalteten Reihe (None = abwählen); wirkt ab heute."""
    today = today or local_today()
    spec = next((r for r in TALENT_ROWS if r[0] == row), None)
    if spec is None or (choice is not None and choice not in {k for k, *_ in spec[2]}):
        raise KeyError(f"{row}:{choice}")
    if choice is not None and _load(today)["level"] < row:
        raise ValueError(f"Talentreihe {row} ist erst ab Stufe {row} frei.")
    _choose(f"talent_{row}", choice, today)


# --- Buffs & Debuffs (heute) ---------------------------------------------------------
FOCUS_TEXT = {
    "ausdauer": "+10 % EP für Läufe in Zone 1–2",
    "tempo": "+10 % EP für Läufe in Zone 3–4",
    "strecke": "+10 % EP für Läufe ab 10 km",
    "last": "+10 % EP ab dem 3. Lauf einer Woche",
}


def _checkin(today: date) -> dict:
    try:
        with engine.connect() as con:
            row = con.exec_driver_sql("SELECT energy, sick FROM checkins WHERE day = ?", (today.isoformat(),)).fetchone()
    except Exception:  # noqa: BLE001
        return {}
    return {"energy": row[0], "sick": bool(row[1])} if row else {}


def _streak() -> int:
    from .metrics import activity
    return int(activity.consistency(365).get("streak") or 0)


def buffs_today(data: dict, today: date, rested: float, chosen: str | None) -> list[dict]:
    out = []

    def add(key, name, kind, icon, effect, source):
        out.append({"key": key, "name": name, "kind": kind, "icon": icon, "effect": effect, "source": source})

    target = data["protein_target"]
    yesterday = data["protein"].get(today - timedelta(days=1))
    if "wohlgenaehrt" in data["buffs"].get(today, set()):
        add("wohlgenaehrt", "Wohlgenährt", "buff", "food", "+5 % Trainings-EP heute",
            f"Gestern {yesterday:.0f} g Protein (Ziel {target:.0f} g)" if yesterday and target else "Protein-Ziel gestern erreicht")
    night = data["sleep"].get(today)
    if night is not None and night >= 420:
        add("erholt", "Erholt", "buff", "moon", "+5 % Trainings-EP heute", f"{night / 60:.1f} h geschlafen".replace(".", ","))
    elif night is not None and night < 360:
        add("uebermuedet", "Übermüdet", "debuff", "eye", "Kein Malus – nur ein Hinweis, heute locker zu bleiben",
            f"nur {night / 60:.1f} h geschlafen".replace(".", ","))
    if rested > 0:
        add("ausgeruht", "Ausgeruht", "buff", "bed", f"Verdoppelt die nächsten {rested:.0f} Trainings-EP", "Ruhe- und Krankheitstage")
    ci = _checkin(today)
    if ci.get("sick") or today in data["sick"]:
        add("krank", "Krank", "debuff", "thermo", "Serie, Truhe und Aufträge pausieren; Ruhebonus lädt", "Check-in: krank")
    elif ci.get("energy") is not None and ci["energy"] >= 4:
        add("energie", "Energiegeladen", "buff", "zap", "Gute Voraussetzung für einen harten Lauf", f"Check-in: Energie {ci['energy']}/5")
    elif ci.get("energy") is not None and ci["energy"] <= 2:
        add("erschoepft", "Erschöpft", "debuff", "battery", "Kein Malus – heute lieber Erholung", f"Check-in: Energie {ci['energy']}/5")
    streak = _safe(_streak, 0)
    if streak >= 7:
        add("feuereifer", "Feuereifer", "buff", "flame", "Nur Ehre – halte die Serie am Leben", f"{streak} Tage Trainingsserie")
    for key in sorted(data["mods"].potions.get(today, set())):
        name, effect, _, glyph = hero_economy.POTIONS[key]
        add(f"trank_{key}", name, "buff", "potion", effect, "Heute getrunken")
    if chosen:
        add("fokus", f"Fokus: {SPECS[chosen]['label']}", "buff", "target", FOCUS_TEXT[chosen], "Gewählte Spezialisierung")
    return out


# --- Begleiter -------------------------------------------------------------------------
PETS = {"jaeger": ("fuchs", "Funke"), "krieger": ("baer", "Brumm"), "paladin": ("loewe", "Leo"), "moench": ("eule", "Kauz")}
PET_STAGES = [(0, "Junges"), (7, "Halbstark"), (30, "Ausgewachsen")]


def companion(cls: str, data: dict, today: date, now: datetime | None = None) -> dict:
    """Begleiter passend zur Klasse; Wachstum nach Trainingsserie, Stimmung aus den Tagesdaten."""
    species, name = PETS[cls]
    streak = _safe(_streak, 0)
    stage = max(i for i, (floor, _) in enumerate(PET_STAGES) if streak >= floor)
    hour = (now or datetime.now()).hour
    runs, workouts = data["runs"], data["workouts"]
    ran = (not runs.empty) and bool((runs["day"] == today).any())
    lifted = (not workouts.empty) and bool((workouts["day"] == today).any())
    loot_today = any(it["date"] == today.isoformat() and RARITIES.index(it["rarity"]) >= RARITIES.index("lila") for it in data["drops"])
    if today in data["sick"] or _checkin(today).get("sick"):
        mood, text = "krank", f"{name} liegt eingerollt neben dir und wärmt dich. Gute Besserung!"
    elif loot_today:
        mood, text = "stolz", f"{name} bewacht stolz deine neue epische Beute."
    elif ran or lifted:
        mood, text = "froh", f"{name} tobt vor Freude – heute schon {'gelaufen' if ran else 'trainiert'}!"
    elif hour < 6 or hour >= 22:
        mood, text = "schlaeft", f"{name} schläft tief und fest. Psst."
    else:
        mood, text = "wartet", f"{name} sitzt an der Tür und schaut auf deine Laufschuhe."
    return {"species": species, "name": name, "stage": stage, "stage_label": PET_STAGES[stage][1],
            "streak": streak, "next_stage": PET_STAGES[stage + 1][0] if stage + 1 < len(PET_STAGES) else None,
            "mood": mood, "text": text}


def choose_spec(spec: str | None, today: date | None = None) -> None:
    """Wählt die Spezialisierung (None = automatisch nach Neigung); wirkt ab heute."""
    if spec is not None and spec not in SPECS:
        raise KeyError(spec)
    _choose("spec_history", spec, today or local_today())


# --- Gesamtbild -------------------------------------------------------------------------
def _load(today: date) -> dict:
    runs = _safe(_runs, pd.DataFrame())
    if runs.empty:
        runs = pd.DataFrame(columns=["external_id", "started_at", "day", "distance_km", "dur_min", "ef", "zone", "key"])
    indoor = _safe(lambda: _indoor_rides(_safe(lambda: _hr_max(runs), 180.0)), pd.DataFrame(columns=RIDE_COLUMNS))
    workouts = _safe(_workouts, pd.DataFrame(columns=["id", "started_at", "sets", "day"]))
    steps = _safe(_steps, {})
    other = _safe(_other_minutes, {})
    sick = _sick()
    ach = _safe(_achievement_xp, [])
    protein = _safe(_protein_days, {})
    target = _safe(_protein_target, None)
    sleep = _safe(_sleep_minutes, {})
    buffs = day_buffs(protein, target, sleep)
    spec_hist = _history("spec_history")
    talents = {lvl: _history(f"talent_{lvl}") for lvl, _, _ in TALENT_ROWS}
    mods = Mods(buffs, spec_hist, talents, _safe(_potion_days, {}))
    start = start_date(today)
    base = {"runs": runs, "workouts": workouts, "steps": steps, "sick": sick, "protein": protein,
            "protein_target": target, "sleep": sleep, "indoor": indoor,
            "ride_min": _safe(lambda: _ride_minutes(indoor), [])}
    weeks = []
    w = _monday(start)
    while w <= _monday(today):
        weeks.append(_safe(lambda w=w: hero_quests.week_quests(
            w, _active(spec_hist, w), mods.quest_extra(min(w + timedelta(days=6), today)), base, today), None))
        w += timedelta(days=7)
    weeks = [x for x in weeks if x]
    extra = [(date.fromisoformat(q["done_on"]), q["xp"], q["title"], "auftrag") for wk in weeks for q in wk["quests"] if q["done"]]
    base["efforts"] = _safe(_best_efforts, pd.DataFrame(columns=["external_id", "distance_m", "seconds", "started_at"]))
    bosses = []
    m = start.replace(day=1)
    while m <= today:
        bosses += _safe(lambda m=m: hero_bosses.month_bosses(m, base, today), [])
        m = (m + timedelta(days=32)).replace(day=1)
    for b in bosses:
        if b["defeated"]:
            won = date.fromisoformat(b["defeated_on"])
            factor = 1.5 if mods.talent(50, won) == "bossjaeger" else 1.0
            extra.append((won, b["xp"] * factor, b["name"], "boss"))
    base["other"], base["checkins"] = other, _safe(_checkin_days, {})
    daily = _safe(lambda: hero_events.dailies(start, today, base), None)
    if daily:
        extra += [(d, xp, title, "taeglich") for d, xp, title in daily["xp"]]
    events = []
    m = start.replace(day=1)
    while m <= today:
        events.append(_safe(lambda m=m: hero_events.season_event(m, base, today), None))
        m = (m + timedelta(days=32)).replace(day=1)
    events = [e for e in events if e]
    extra += [(date.fromisoformat(e["done_on"]), e["xp"], e["name"], "event") for e in events if e["done"]]
    duels = _safe(lambda: hero_extras.run_duels(runs, start), [])
    extra += [(date.fromisoformat(d["date"]), d["xp"], f"Doppelgänger vom {d['twin_date'][8:10]}.{d['twin_date'][5:7]}.", "duell")
              for d in duels if d["won"]]
    world = _safe(hero_world.world, {"available": False})
    for f, kind in [(r, "erkundung") for r in world.get("regions", []) if r["discovered"]] + \
                   [(p, p["kind"]) for p in world.get("pois", []) if p["found"]]:
        on = f["discovered_on"] if kind == "erkundung" else f["found_on"]
        if f.get("via") == "rad":  # zu Rad gefunden: halbe Erkundungs-EP, Quelle im Log
            extra.append((date.fromisoformat(on), f["xp"] * hero_world.RIDE_FACTOR, f["name"], kind, "zu Rad"))
        else:
            extra.append((date.fromisoformat(on), f["xp"], f["name"], kind))
    for dg in world.get("dungeons", []):
        extra += [(date.fromisoformat(sg["cleared_on"]), sg["xp"], f"{sg['boss']} ({dg['name']})", "abschnitt")
                  for sg in dg["segments"] if sg["cleared"]]
        if dg["cleared"]:
            extra.append((date.fromisoformat(dg["cleared_on"]), dg["xp"] * (1.5 if dg["heroic"] else 1), dg["name"], "verlies"))
    dungeons = _safe(lambda: hero_bosses.dungeons(runs, start), [])
    extra += [(date.fromisoformat(dg["date"]), dg["xp"], dg["name"], "instanz") for dg in dungeons if dg["xp"]]
    live_events = [e for e in _safe(hero_events_live.confirmed, []) if date.fromisoformat(e["date"]) >= start]
    extra += [(date.fromisoformat(e["date"]), e["xp"], e["name"], "spontan") for e in live_events]
    climb = _safe(lambda: hero_climb.climb(indoor, start), {"total_hm": 0, "peaks": [], "rounds": [], "next": None, "next_in_hm": 0, "rides": 0})
    climb_events = _safe(lambda: hero_climb.events(climb), [])
    extra += [(date.fromisoformat(e["date"]), e["xp"], e["name"], "gipfel") for e in climb_events]
    dreams = _safe(hero_dreams.dreams, {})
    book = ledger(runs, workouts, steps, other, sick, ach, today, mods, extra, indoor)
    rides = [(d, km) for d, km in _safe(_ride_days, []) if d >= start]
    mount_hist = _mount_history(start)
    zwift_days = [(d, km) for d, km in _zwift_days(indoor) if d >= start]
    mount_feed = hero_extras.ride_feed([*rides, *zwift_days], lambda d: _active(mount_hist, d) or None)
    fed: dict[str, float] = {}
    for f in mount_feed:
        fed[f["mount"]] = fed.get(f["mount"], 0.0) + f["km"]
    tips: dict[tuple[str, str], list[str]] = {}
    cat = {"lauf": "Laufen", "ausdauer": "Ausdauer", "kraft": "Kraft", "pflege": "Pflege"}
    for wk in weeks:
        for q in wk["quests"]:
            tips[("auftrag", q["title"])] = [f"Wochenauftrag · {cat.get(q['category'], q['category'])}",
                                             f"{q['goal']}: {q['target']:g} {q['unit']}", f"Belohnung: {q['xp']} EP"]
    for b in bosses:
        tips[("boss", b["name"])] = [f"Monatsboss · {b['kind']}", f"Ziel: {b['goal']}", f"Belohnung: {b['xp']} EP + epische Beute"]
    for dg in dungeons:
        tips[("instanz", dg["name"])] = [f"{dg['tier_label']}e Instanz · {dg['km']:.1f} km".replace(".", ","),
                                         "Bosse: " + ", ".join(b["name"] for b in dg["bosses"] if b["defeated"])]
    for e in climb_events:
        tips[("gipfel", e["name"])] = [f"Kletter-Boss · {e['hm']:,} Hm Zwift".replace(",", "."), "Kumulierte Zwift-Höhenmeter seit Beginn",
                                       f"Belohnung: {e['xp']} EP + {RARITY_LABEL[e['loot']].lower()} Beute"]
    for e in events:
        tips[("event", e["name"])] = ["Saison-Event", e["rule"], f"Belohnung: {e['xp']} EP + {e['item']}"]
    for r in world.get("regions", []):
        tips[("erkundung", r["name"])] = ["Gebiet der Weltkarte", f"{r['pct']:g} % erkundet ({r['cells']} von {r['total']} Feldern)".replace(".", ",")] \
            + (["Zu Rad entdeckt: halbe Belohnung"] if r.get("via") == "rad" else [])
    for p in world.get("pois", []):
        rows = [f"{p['kind_label']} · Stufe {p['level']} · {p['region']}", f"{p['km']:g} km von der Heimat".replace(".", ",")]
        if p["loot"]:
            rows.append(f"Belohnung: {p['xp']} EP, {p['gold']} Gold + {RARITY_LABEL[p['loot']].lower()} Beute")
        else:
            rows.append(f"Belohnung: {p['xp']} EP" + (f", {p['gold']} Gold" if p["gold"] else ""))
        if p.get("via") == "rad":
            rows.append("Zu Rad gefunden: halbe Belohnung")
        tips[(p["kind"], p["name"])] = rows
    for dg in world.get("dungeons", []):
        head = f"{'Heroisches ' if dg['heroic'] else ''}Verlies · {dg['type_label']} · Stufe {dg['level']}"
        tips[("verlies", dg["name"])] = [head, f"{dg['length_km']:g} km Strecke, {len(dg['segments'])} Abschnitte".replace(".", ","),
                                         dg["desc"], f"Belohnung: {dg['xp']} EP, {dg['gold']} Gold + {RARITY_LABEL[dg['loot']].lower()} Beute"]
        for sg in dg["segments"]:
            tips[("abschnitt", f"{sg['boss']} ({dg['name']})")] = [f"Abschnittsboss · {dg['name']}", f"Stufe {dg['level']} · {sg['xp']} EP",
                                                                   f"Abgedeckt: {round(sg['coverage'] * 100)} % (ab 80 % bezwungen)"]
    for e in live_events:
        tips[("spontan", e["name"])] = [f"Spontanes Ereignis · Stein +{e['level']}", "Von der Garmin-Spur bestätigt",
                                        f"Belohnung: {e['xp']} EP + {RARITY_LABEL[e['loot']].lower()} Beute"]
    for d in duels:
        label = f"Doppelgänger vom {d['twin_date'][8:10]}.{d['twin_date'][5:7]}."
        tips[("duell", label)] = ["Duell gegen dein früheres Ich",
                                  f"Du: {d['km']:.1f} km in {_pace(d['pace'])}/km".replace(".", ",", 1),
                                  f"Schatten: {d['twin_km']:.1f} km in {_pace(d['twin_pace'])}/km".replace(".", ",", 1)]
    total = sum(e["xp"] + e["bonus"] for e in book["entries"])
    level = level_for(total)["level"]
    loot = _safe(lambda: drops(runs, book["entries"], start, mods), [])
    loot += _safe(lambda: ride_drops(indoor, book["entries"], start, mods), [])
    loot += _safe(lambda: quest_loot(weeks, book["entries"]), [])
    loot += _safe(lambda: boss_loot(bosses, dungeons, book["entries"]), [])
    loot += _safe(lambda: event_loot(daily, events, book["entries"]), [])
    loot += _safe(lambda: climb_loot(climb_events, book["entries"]), [])
    loot += _safe(lambda: map_loot(world, start), [])
    loot += _safe(lambda: live_event_loot(live_events, book["entries"]), [])
    return {"runs": runs, "indoor": indoor, "workouts": workouts, "steps": steps, "sick": sick, "book": book,
            "protein": protein, "protein_target": target, "sleep": sleep, "buffs": buffs, "spec_hist": spec_hist,
            "rides": rides, "zwift_days": zwift_days, "climb": climb, "dreams": dreams, "mount_hist": mount_hist, "mount_feed": mount_feed, "fed": fed,
            "mods": mods, "talents": talents, "quest_weeks": weeks, "bosses": bosses, "dungeons": dungeons, "daily": daily, "events": events, "duels": duels, "tips": tips, "world": world,
            "entries": book["entries"], "start": start, "level": level, "drops": loot, "total": total,
            "stones": _safe(hero_keystone.results, [])}


def overview(today: date | None = None) -> dict:
    today = today or local_today()
    data = _load(today)
    book, runs, entries = data["book"], data["runs"], data["entries"]
    lv = level_for(data["total"])
    cls = classify(book["daily"], runs, today, data["indoor"])
    chosen = _active(data["spec_hist"], today)
    spec = chosen or cls["spec"]
    week_start = _monday(today)
    claims = _claims()
    worn = _equipment()
    inventory = [{**it, "equipped": worn.get(it["slot"]) == it["id"]} for it in _inventory(data["drops"], claims)]
    bags = _safe(lambda: hero_economy.bag_drops(data), [])
    bags += [json.loads(p.payload) for p in _safe(_purchases, []) if p.kind == "bag"]
    cap, used_bags = hero_economy.capacity(bags)
    loose = sorted((it for it in inventory if not it["equipped"]), key=lambda it: (it["date"], it["id"]))
    mail_ids = {it["id"] for it in loose[cap:]}
    inventory = [{**it, "mail": it["id"] in mail_ids} for it in inventory]
    equipment = {it["slot"]: it for it in inventory if it["equipped"]}
    stats = _hero_stats(data, inventory, lv["level"], book["totals"])
    chosen_title = _state_get("title") or None
    title_list = hero_social.titles(stats, chosen_title)
    title_name = next((t["name"] for t in title_list if t["chosen"] and t["earned"]), None)

    log_events = _level_events(entries)
    first = min(book["daily"]) if book["daily"] else today
    log_events += _safe(lambda: _class_events(book["daily"], runs, first, today, data["indoor"]), [])
    log_events += [{"date": e["date"], "kind": e["kind"], "text": e["label"] + f" (+{e['xp']:.0f} XP)",
                    "name": e["name"], "xp": round(e["xp"]), "tip": data["tips"].get((e["kind"], e["name"]))}
                   for e in entries if e["kind"] in ("auftrag", "boss", "instanz", "event", "duell", "erkundung", "verlies", "abschnitt", "schrein", "schatz", "spontan", "gipfel")]
    log_events += [{"date": e["date"], "kind": "erfolg", "text": e["label"] + f" (+{e['xp']:.0f} XP)",
                    "name": e["name"], "xp": round(e["xp"])}
                   for e in entries if e["kind"] == "erfolg"]
    log_events += [{"date": date.fromisoformat(it["date"]), "kind": "beute",
                    "text": f"Beute: {it['name']} ({it['rarity_label']})", "rarity": it["rarity"], "name": it["name"],
                    "item_id": it["id"]}
                   for it in data["drops"]]
    log_events += [{"date": c.claimed_at.date(), "kind": "truhe",
                    "text": f"Truhe gewählt: {json.loads(c.item_json)['name']}",
                    "rarity": json.loads(c.item_json)["rarity"], "name": json.loads(c.item_json)["name"],
                    "item_id": json.loads(c.item_json)["id"]}
                   for c in claims.values()]
    for b in bags:
        log_events.append({"date": date.fromisoformat(b["date"][:10]), "kind": "tasche", "text": f"Tasche erhalten: {b['name']}",
                           "name": b["name"], "tip": [f"Tasche · {b['slots']} Plätze", f"Gefunden: {b['source']}"]})
    for m in _safe(lambda: hero_extras.mounts(runs, data["workouts"], None, data.get("rides"), data.get("fed"), data.get("zwift_days")), []):
        if m["unlocked"]:
            log_events.append({"date": date.fromisoformat(m["unlocked_on"]), "kind": "reittier",
                               "text": f"Reittier erhalten: {m['name']}", "name": m["name"],
                               "tip": [f"Reittier {m['glyph']}", f"Freigeschaltet bei {m['need']:,} {m['unit']}".replace(",", ".")]})
    mount_by_key = {m["key"]: m for m in _safe(lambda: _all_mounts(data, None), [])}
    for f in data.get("mount_feed", []):
        m = mount_by_key.get(f["mount"])
        if m:
            km = f"{f['km']:g}".replace(".", ",")
            log_events.append({"date": date.fromisoformat(f["date"]), "kind": "fahrt", "km": f["km"],
                               "text": f"[{m['name']}] trabte {km} km", "name": m["name"],
                               "tip": [f"Reittier {m['glyph']} · Stufe {m['level']}", f"Radfahrt: {km} km",
                                       f"Gefüttert insgesamt: {str(m['ride_km']).replace('.', ',')} km"]})
    log_events.sort(key=lambda e: e["date"], reverse=True)

    week_xp = sum(e["xp"] + e["bonus"] for e in entries if e["date"] >= week_start)
    result = {
        "today": today.isoformat(),
        "start": data["start"].isoformat(),
        "hero": {
            **lv,
            "class": cls["class"], "class_label": CLASSES[cls["class"]]["label"],
            "class_color": CLASSES[cls["class"]]["color"], "class_desc": CLASSES[cls["class"]]["desc"],
            "spec": spec, "spec_label": SPECS[spec]["label"] if spec else None,
            "spec_desc": SPECS[spec]["desc"] if spec else "Mindestens 4 Läufe in 90 Tagen nötig.",
            "spec_auto": cls["spec"], "spec_chosen": chosen,
            "spec_scores": cls["spec_scores"], "shares": cls["shares"],
            "rested": round(book["pool"]), "rested_cap": REST_CAP, "week_xp": round(week_xp),
            "title_chosen": title_name,
        },
        "xp_sources": {k: round(v) for k, v in book["totals"].items()},
        "progression": progression(entries, book["daily"]),
        "buffs": buffs_today(data, today, book["pool"], chosen),
        "companion": companion(cls["class"], data, today),
        "specs": [{"key": k, **v, "focus": FOCUS_TEXT[k], "score": cls["spec_scores"].get(k)} for k, v in SPECS.items()],
        "attributes": attributes(runs, data["workouts"], data["steps"], data["sick"], today, data["indoor"]),
        "vault": vault(runs, data["drops"], data["sick"], entries, data["start"], today, data["level"], data["mods"],
                       data.get("stones"), data["indoor"]),
        "mythic": _safe(lambda: hero_keystone.rating(data.get("stones")), None),
        "talents": talents_view(data["mods"], lv["level"], today),
        "quests": data["quest_weeks"][-1] if data["quest_weeks"] else None,
        "bosses": [b for b in data["bosses"] if b["month"] == today.replace(day=1).isoformat()],
        "dungeons": data["dungeons"][::-1][:10],
        "climb": data["climb"],
        "dreams": data["dreams"],
        "daily": {k: v for k, v in data["daily"].items() if k in ("today", "streak", "last7")} if data["daily"] else None,
        "event": next((e for e in data["events"] if e["month"] == today.replace(day=1).isoformat()), None),
        "duels": {"last": data["duels"][-1] if data["duels"] else None,
                  "won": sum(1 for d in data["duels"] if d["won"]), "total": len(data["duels"]),
                  "shadows": [hero_extras.shadow(runs, today, 91, "vor 3 Monaten"),
                              hero_extras.shadow(runs, today, 365, "vor einem Jahr")]},
        "mounts": _safe(lambda: _all_mounts(data, _active(data["mount_hist"], today) or None), []),
        "auction": _safe(lambda: auction_view(lv["level"], today), None),
        "world": data["world"],
        "potions": _safe(lambda: potions_view(today), []),
        "inventory": inventory,
        "equipment": equipment,
        "dust": dust_balance(_item_mods()),
        "gold": gold_view(data, today),
        "bags": {"capacity": cap, "backpack": hero_economy.BACKPACK, "max_bags": hero_economy.MAX_BAGS,
                 "used": used_bags, "spare": [b for b in bags if b not in used_bags]},
        "sets": hero_social.sets(inventory),
        "titles": title_list,
        "reputation": hero_social.reputation(stats),
        "ilvl_avg": round(sum(it["ilvl"] for it in equipment.values()) / len(equipment)) if equipment else None,
        "log": [{**e, "date": e["date"].isoformat()} for e in log_events[:40]],
        "rules": {"runs_full_xp": RUNS_FULL_XP, "workouts_full_xp": WORKOUTS_FULL_XP,
                  "rest_per_day": REST_PER_DAY, "vault_thresholds": VAULT_THRESHOLDS,
                  "ride_vault_min": RIDE_VAULT_MIN},
    }
    return _with_trainer(result, data, today)


def _with_trainer(result: dict, data: dict, today: date) -> dict:
    parts = {"bosses": result["bosses"], "vault": result["vault"], "quests": result["quests"], "event": result["event"],
             "class_label": result["hero"]["class_label"]}
    result["trainer"] = _safe(lambda: trainer(data, parts, today, data["book"]["pool"], data["mods"].rest_cap(today)),
                              {"name": hero_events.TRAINER, "role": hero_events.TRAINER_ROLE, "quote": hero_events.FALLBACK[0]})
    return result


def coach_summary(today: date | None = None) -> dict:
    """Kurzfassung für Coach/MCP — nur Stand, keine Listen."""
    o = overview(today)
    h, cur = o["hero"], o["vault"]["current"]
    open_slots = [s["threshold"] for s in cur["slots"] if not s["unlocked"]]
    return {"klasse": h["class_label"], "spezialisierung": h["spec_label"], "level": h["level"],
            "titel": h["title"], "xp_bis_level": h["next"] - h["xp"], "ruhebonus": h["rested"],
            "truhe_laeufe_diese_woche": cur["runs"],
            "truhe_naechster_slot_bei": open_slots[0] if open_slots else None,
            "attribute": {a["label"]: a["score"] for a in o["attributes"]}}
