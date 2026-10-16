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
from sqlmodel import Field, Session, SQLModel, select

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


def _workouts() -> pd.DataFrame:
    df = _read("SELECT w.id, w.started_at, COUNT(ws.id) AS sets FROM workouts w "
               "LEFT JOIN workout_sets ws ON ws.workout_id = w.id AND ws.set_type = 'normal' "
               "WHERE w.started_at IS NOT NULL GROUP BY w.id", parse_dates=["started_at"])
    if not df.empty:
        df["day"] = df["started_at"].dt.date
    return df.sort_values("started_at").reset_index(drop=True) if not df.empty else df


def _other_minutes() -> dict[date, float]:
    df = _read("SELECT started_at, ended_at FROM exercise_sessions WHERE exercise_type IN (4, 53)",
               parse_dates=["started_at", "ended_at"])
    out: dict[date, float] = {}
    for s, e in zip(df["started_at"], df["ended_at"]):
        if pd.notna(s) and pd.notna(e):
            out[s.date()] = out.get(s.date(), 0.0) + max(0.0, min(120.0, (e - s).total_seconds() / 60))
    return out


def _steps() -> dict[date, int]:
    df = _read("SELECT day, steps FROM steps_daily", parse_dates=["day"])
    return {d.date(): int(s) for d, s in zip(df["day"], df["steps"]) if pd.notna(s)}


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


# --- XP-Buch ----------------------------------------------------------------------------
def run_xp(row) -> float:
    factor = ZONE_FACTOR[min(3, int(row.zone))] if row.zone is not None and pd.notna(row.zone) else NO_HR_FACTOR
    return row.dur_min * factor * RUN_XP_PER_MIN


def step_xp(steps: int) -> int:
    return min(45, max(0, (steps - 5000) // 1000) * 3)


def ledger(runs, workouts, steps, other, sick, ach, today: date) -> dict:
    """Chronologisches XP-Buch mit Ruhebonus und Wochen-Abschwächung."""
    entries: list[dict] = []
    by_day_runs: dict[date, list] = {}
    for r in runs.itertuples():
        by_day_runs.setdefault(r.day, []).append(r)
    by_day_wo: dict[date, list] = {}
    for w in workouts.itertuples():
        by_day_wo.setdefault(w.day, []).append(w)
    days = [*by_day_runs, *by_day_wo, *steps, *other, *(d for d, _, _ in ach if d)]
    if not days:
        return {"entries": [], "pool": 0, "totals": {}, "daily": {}}
    first = min(days)
    ach_by_day: dict[date, list] = {}
    for d, pts, name in ach:
        ach_by_day.setdefault(min(d, today) if d else first, []).append((pts, name))
    pool = 0.0
    week_runs: dict[date, int] = {}
    week_wo: dict[date, int] = {}
    totals = {"laufen": 0.0, "kraft": 0.0, "alltag": 0.0, "erfolge": 0.0, "ruhebonus": 0.0}
    daily: dict[date, dict] = {}
    d = first
    while d <= today:
        wk = _monday(d)
        trained = False
        day_xp = {"laufen": 0.0, "kraft": 0.0, "alltag": 0.0, "erfolge": 0.0, "ruhebonus": 0.0}
        for r in by_day_runs.get(d, []):
            week_runs[wk] = week_runs.get(wk, 0) + 1
            xp = run_xp(r) * (1.0 if week_runs[wk] <= RUNS_FULL_XP else 0.5)
            bonus = min(pool, xp)
            pool -= bonus
            trained = True
            entries.append({"date": d, "kind": "lauf", "xp": xp, "bonus": bonus, "ref": r.key,
                            "label": f"Lauf {r.distance_km:.1f} km"})
            day_xp["laufen"] += xp
            day_xp["ruhebonus"] += bonus
        for w in by_day_wo.get(d, []):
            week_wo[wk] = week_wo.get(wk, 0) + 1
            xp = min(WORKOUT_XP_CAP, w.sets * SET_XP) * (1.0 if week_wo[wk] <= WORKOUTS_FULL_XP else 0.5)
            bonus = min(pool, xp)
            pool -= bonus
            trained = True
            entries.append({"date": d, "kind": "kraft", "xp": xp, "bonus": bonus, "ref": str(w.id),
                            "label": f"Krafttraining {w.sets} Sätze"})
            day_xp["kraft"] += xp
            day_xp["ruhebonus"] += bonus
        everyday = step_xp(steps.get(d, 0)) + min(30.0, other.get(d, 0.0) * 0.5)
        if everyday:
            entries.append({"date": d, "kind": "alltag", "xp": everyday, "bonus": 0.0, "ref": None,
                            "label": "Alltagsbewegung"})
            day_xp["alltag"] += everyday
        for pts, name in ach_by_day.get(d, []):
            entries.append({"date": d, "kind": "erfolg", "xp": float(pts), "bonus": 0.0, "ref": None,
                            "label": f"Erfolg „{name}“", "name": name})
            day_xp["erfolge"] += pts
        if d in sick or not trained:
            pool = min(REST_CAP, pool + REST_PER_DAY)
        for k, v in day_xp.items():
            totals[k] += v
        daily[d] = day_xp
        d += timedelta(days=1)
    return {"entries": entries, "pool": pool, "totals": totals, "daily": daily}


def progression(entries: list[dict], daily: dict[date, dict]) -> list[dict]:
    """Wochenweise: EP je Quelle, kumulierte EP und Stufe (mit Bruchteil) am Wochenende."""
    weeks: dict[date, dict] = {}
    for d, v in daily.items():
        w = weeks.setdefault(_monday(d), {"laufen": 0.0, "kraft": 0.0, "alltag": 0.0, "erfolge": 0.0, "ruhebonus": 0.0})
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
def classify(daily: dict[date, dict], runs: pd.DataFrame, d: date) -> dict:
    start = d - timedelta(days=89)
    win = [v for k, v in daily.items() if start <= k <= d]
    run_xp_ = sum(v["laufen"] for v in win)
    str_xp = sum(v["kraft"] for v in win)
    daily_xp = sum(v["alltag"] for v in win)
    sub = runs[(runs["day"] >= start) & (runs["day"] <= d)] if not runs.empty else runs
    training = run_xp_ + str_xp
    sessions = len(sub) + sum(1 for v in win if v["kraft"] > 0)
    if training <= 0 or sessions < 6 or daily_xp > training:
        cls = "moench"
    else:
        share = run_xp_ / training
        cls = "jaeger" if share >= 0.65 else "krieger" if share <= 0.35 else "paladin"
    total = training + daily_xp or 1.0
    shares = {"laufen": round(run_xp_ / total, 3), "kraft": round(str_xp / total, 3),
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


def _class_events(daily, runs, first: date, today: date) -> list[dict]:
    events, prev = [], None
    d = _monday(first) + timedelta(days=6)
    while d <= today + timedelta(days=6):
        at = min(d, today)
        c = classify(daily, runs, at)
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


def attributes(runs, workouts, steps, sick, today: date) -> list[dict]:
    vo2 = _safe(lambda: _read("SELECT measured_at, vo2 FROM vo2max", parse_dates=["measured_at"]),
                pd.DataFrame(columns=["measured_at", "vo2"]))
    be = _best_efforts()
    be5 = be[be["distance_m"] == 5000] if not be.empty else be
    sleep = _safe(lambda: _read("SELECT day, asleep_minutes FROM sleep_sessions WHERE main_sleep = 1",
                                parse_dates=["day"]), pd.DataFrame(columns=["day", "asleep_minutes"]))
    idx = _safe(_strength_series, [])
    train_days = set(runs["day"]) if not runs.empty else set()
    train_days |= set(workouts["day"]) if not workouts.empty else set()

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
    name = f"{rng.choice(bases)} {rng.choice(candidates)}"
    ilvl = 100 + 2 * level + 8 * RARITIES.index(rarity) + rng.randint(0, 3)
    return {"name": name, "slot": slot, "slot_label": slot_label, "rarity": rarity,
            "rarity_label": RARITY_LABEL[rarity], "ilvl": ilvl, "flavor": flavor(rarity, source),
            "source": source, "reason": reason, "date": when.date().isoformat()}


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


def drops(runs: pd.DataFrame, entries: list[dict], start: date) -> list[dict]:
    efforts = _best_efforts()
    out = []
    for i, r in enumerate(runs.itertuples()):
        if r.day < start:
            continue
        rarity, reason = drop_rarity(r, runs.iloc[:i], efforts)
        rng = _rng("drop", r.key)
        lucky = rarity not in ("orange", "rot") and rng.random() < 0.08
        if lucky:
            rarity = RARITIES[RARITIES.index(rarity) + 1]
            reason += " · Glücksfund"
        item = make_item(rng, rarity, r.started_at.to_pydatetime(), r.zone, _level_at(entries, r.day), "beute", reason)
        out.append({**item, "id": f"drop:{r.key}", "lucky": lucky, "run_km": round(float(r.distance_km), 1)})
    return out


# --- Wochentruhe ------------------------------------------------------------------------
VAULT_THRESHOLDS = [1, 3, 4]


def _claims() -> dict[str, HeroClaim]:
    with Session(engine) as session:
        return {c.week: c for c in session.exec(select(HeroClaim)).all()}


def vault_week(week: date, runs: pd.DataFrame, items: list[dict], sick: set[date], entries, today: date) -> dict:
    end = week + timedelta(days=6)
    n = int(((runs["day"] >= week) & (runs["day"] <= end)).sum()) if not runs.empty else 0
    sick_n = sum(1 for i in range(7) if week + timedelta(days=i) in sick)
    relief = sick_n // 2
    thresholds = [max(1, t - relief) for t in VAULT_THRESHOLDS]
    week_items = [it for it in items if week.isoformat() <= it["date"] <= end.isoformat()]
    base = max((RARITIES.index(it["rarity"]) for it in week_items), default=RARITIES.index("weiss"))
    base = min(base, RARITIES.index("orange"))
    level = _level_at(entries, min(end, today))
    slots = []
    for i, t in enumerate(thresholds):
        # Mehr Läufe = mehr Auswahl (wie die Great Vault), Qualität = beste Leistung der Woche.
        rng = _rng("vault", week.isoformat(), i)
        bump = 1 if rng.random() < 0.15 else 0
        rarity = RARITIES[min(RARITIES.index("orange"), base + bump)]
        item = make_item(rng, rarity, datetime.combine(end, datetime.min.time()).replace(hour=8), None, level,
                         "truhe", f"Wochentruhe · Slot {i + 1}")
        item["ilvl"] += 3 * i
        slots.append({"slot": i, "threshold": t, "unlocked": n >= t, "item": {**item, "id": f"truhe:{week}:{i}"}})
    return {"week": week.isoformat(), "runs": n, "sick_days": sick_n, "slots": slots,
            "complete": end < today}


def veteran_chest(level: int, today: date) -> dict:
    when = datetime.combine(today, datetime.min.time()).replace(hour=8)
    slots = []
    for i, rarity in enumerate(["blau", "lila", "orange"]):
        item = make_item(_rng("veteran", i), rarity, when, None, level, "veteran", "Veteranentruhe für deine bisherige Reise")
        slots.append({"slot": i, "threshold": 0, "unlocked": True, "item": {**item, "id": f"veteran:{i}"}})
    return {"week": "veteran", "runs": 0, "sick_days": 0, "slots": slots, "complete": True}


def vault(runs, items, sick, entries, start: date, today: date, level: int) -> dict:
    claims = _claims()
    def with_claim(v):
        c = claims.get(v["week"])
        return {**v, "claimed_slot": c.slot if c else None}
    current = with_claim(vault_week(_monday(today), runs, items, sick, entries, today))
    claimable = []
    w = _monday(start)
    while w < _monday(today):
        v = with_claim(vault_week(w, runs, items, sick, entries, today))
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
        chest = vault_week(monday, data["runs"], data["drops"], data["sick"], data["entries"], today)
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
def _inventory(drops_: list[dict], claims: dict[str, HeroClaim]) -> list[dict]:
    claimed = [{**(it := json.loads(c.item_json)), "flavor": flavor(it["rarity"], it["source"]),
                "claimed_at": c.claimed_at.isoformat()} for c in claims.values()]
    return sorted(drops_ + claimed, key=lambda it: (it["date"], it["ilvl"]), reverse=True)


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


# --- Gesamtbild -------------------------------------------------------------------------
def _load(today: date) -> dict:
    runs = _safe(_runs, pd.DataFrame())
    if runs.empty:
        runs = pd.DataFrame(columns=["external_id", "started_at", "day", "distance_km", "dur_min", "ef", "zone", "key"])
    workouts = _safe(_workouts, pd.DataFrame(columns=["id", "started_at", "sets", "day"]))
    steps = _safe(_steps, {})
    other = _safe(_other_minutes, {})
    sick = _sick()
    ach = _safe(_achievement_xp, [])
    book = ledger(runs, workouts, steps, other, sick, ach, today)
    start = start_date(today)
    total = sum(e["xp"] + e["bonus"] for e in book["entries"])
    level = level_for(total)["level"]
    loot = _safe(lambda: drops(runs, book["entries"], start), [])
    return {"runs": runs, "workouts": workouts, "steps": steps, "sick": sick, "book": book,
            "entries": book["entries"], "start": start, "level": level, "drops": loot, "total": total}


def overview(today: date | None = None) -> dict:
    today = today or local_today()
    data = _load(today)
    book, runs, entries = data["book"], data["runs"], data["entries"]
    lv = level_for(data["total"])
    cls = classify(book["daily"], runs, today)
    week_start = _monday(today)
    claims = _claims()
    worn = _equipment()
    inventory = [{**it, "equipped": worn.get(it["slot"]) == it["id"]} for it in _inventory(data["drops"], claims)]
    equipment = {it["slot"]: it for it in inventory if it["equipped"]}

    log_events = _level_events(entries)
    first = min(book["daily"]) if book["daily"] else today
    log_events += _safe(lambda: _class_events(book["daily"], runs, first, today), [])
    log_events += [{"date": e["date"], "kind": "erfolg", "text": e["label"] + f" (+{e['xp']:.0f} XP)",
                    "name": e["name"], "xp": round(e["xp"])}
                   for e in entries if e["kind"] == "erfolg"]
    log_events += [{"date": date.fromisoformat(it["date"]), "kind": "beute",
                    "text": f"Beute: {it['name']} ({it['rarity_label']})", "rarity": it["rarity"], "name": it["name"]}
                   for it in data["drops"]]
    log_events += [{"date": c.claimed_at.date(), "kind": "truhe",
                    "text": f"Truhe gewählt: {json.loads(c.item_json)['name']}",
                    "rarity": json.loads(c.item_json)["rarity"], "name": json.loads(c.item_json)["name"]}
                   for c in claims.values()]
    log_events.sort(key=lambda e: e["date"], reverse=True)

    week_xp = sum(e["xp"] + e["bonus"] for e in entries if e["date"] >= week_start)
    return {
        "today": today.isoformat(),
        "start": data["start"].isoformat(),
        "hero": {
            **lv,
            "class": cls["class"], "class_label": CLASSES[cls["class"]]["label"],
            "class_color": CLASSES[cls["class"]]["color"], "class_desc": CLASSES[cls["class"]]["desc"],
            "spec": cls["spec"], "spec_label": SPECS[cls["spec"]]["label"] if cls["spec"] else None,
            "spec_desc": SPECS[cls["spec"]]["desc"] if cls["spec"] else "Mindestens 4 Läufe in 90 Tagen nötig.",
            "spec_scores": cls["spec_scores"], "shares": cls["shares"],
            "rested": round(book["pool"]), "rested_cap": REST_CAP, "week_xp": round(week_xp),
        },
        "xp_sources": {k: round(v) for k, v in book["totals"].items()},
        "progression": progression(entries, book["daily"]),
        "attributes": attributes(runs, data["workouts"], data["steps"], data["sick"], today),
        "vault": vault(runs, data["drops"], data["sick"], entries, data["start"], today, data["level"]),
        "inventory": inventory,
        "equipment": equipment,
        "ilvl_avg": round(sum(it["ilvl"] for it in equipment.values()) / len(equipment)) if equipment else None,
        "log": [{**e, "date": e["date"].isoformat()} for e in log_events[:40]],
        "rules": {"runs_full_xp": RUNS_FULL_XP, "workouts_full_xp": WORKOUTS_FULL_XP,
                  "rest_per_day": REST_PER_DAY, "vault_thresholds": VAULT_THRESHOLDS},
    }


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
