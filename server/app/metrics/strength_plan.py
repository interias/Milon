"""Trainingsplan „Nächstes Training“: feste Programme (Oberkörper A/B, Unterkörper) mit
doppelter Progression nach geschafften Wiederholungen.

Regeln (vom User 2026-11-08 festgelegt, je Übung einstellbar über `StrengthRule`):
- Je Übung Ziel-Wdh. und Mindest-Wdh. (Standard = `PlanExercise.reps`).
- Schwerer: alle geplanten Sätze der letzten Einheit (Hauptgewicht) ≥ Ziel-Wdh. → eine Stufe hoch.
- Leichter: ein Satz unter der Mindest-Wdh. → eine Stufe runter. Sonst gleiches Gewicht.
- Pause > 21 Tage → eine Stufe leichter; > 90 Tage oder neu → Start aus dem e1RM der letzten 180 Tage.
- RIR sinkt über die Sätze (Satz 1 RPE 8, mittlere `mid_rpe`, letzter `last_rpe`) — nur Leitplanke
  beim Training, zählt nicht für die Entscheidung. Isolation an Maschinen 2 → 1 → 0, schwere
  Grundübungen (`_COMPOUND`) 2 → 2 → 1 (User-Entscheid 2026-11-10: 0 RIR bringt kaum mehr
  Hypertrophie als 1–2 RIR, kostet aber Erholung — Robinson 2024, Refalo 2024)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
from sqlmodel import Field, Session, SQLModel, select

from ..db import engine
from .strength import e1rm
from ..data_cache import cached

PAUSE_DAYS = 21
STALE_DAYS = 90
E1RM_DAYS = 180
WORK_TYPES = ("normal", "failure")


@dataclass(frozen=True)
class Ladder:
    """Einstellbare Gewichte eines Geräts: Hauptstufen (Stack/Platten) ab `anchor` im Abstand
    `step`, je Hauptstufe kombinierbar mit Zwischengewichten `addons`."""
    step: float
    anchor: float = 0.0
    addons: tuple[float, ...] = (0.0,)
    max_kg: float = 400.0

    def values(self) -> list[float]:
        base = self.anchor % self.step
        out: set[float] = set()
        k = 0
        while base + k * self.step <= self.max_kg:
            for a in self.addons:
                v = round(base + k * self.step + a, 2)
                if 0 < v <= self.max_kg:
                    out.add(v)
            k += 1
        return sorted(out)

    def up(self, w: float) -> float:
        return next((v for v in self.values() if v > w + 0.01), w)

    def down(self, w: float) -> float:
        lower = [v for v in self.values() if v < w - 0.01]
        return lower[-1] if lower else w

    def floor(self, x: float) -> float:
        lower = [v for v in self.values() if v <= x + 0.01]
        return lower[-1] if lower else self.values()[0]


# Hammer Strength Select (Rudern, Seitheben, Pec Fly/Rear Delt, Beinbeugen, Beinstrecker): 7-kg-Stack + 2 Fallgewichte à 2,5 kg.
# Beinpresse 45°: 53-kg-Schlitten + Plattenpaare (2 × 2,5 kg). RDL: 20-kg-Stange + Plattenpaare (5 kg).
# Kurzhanteln: Gesamtgewicht beider Hanteln, Hanteln in 2,5-kg-Stufen → 5 kg. Stirndrücken: 2,5 kg.
# MTS: zwei getrennte Stacks in 2,5-kg-Stufen, geloggt wird die Summe → 5 kg.
# Face Pull (Seilzug): Stack-Stufen unbekannt → 2,5 kg angenommen.
def _select(anchor: float) -> Ladder:
    return Ladder(7.0, anchor, (0.0, 2.5, 5.0))


@dataclass(frozen=True)
class PlanExercise:
    key: str
    name: str
    templates: tuple[str, ...]          # Hevy-IDs; die erste geht in die Routine
    names: tuple[str, ...]              # DE/EN-Namen für Sätze ohne Template-ID (Altbestand)
    sets: int
    reps: tuple[int, int]
    rest: int                           # Sekunden; im Supersatz nach dem Paar
    ladder: Ladder
    warmup: bool = False
    superset: int | None = None
    last_rpe: float = 10.0              # Ziel-RPE des letzten Satzes
    muscles: tuple[tuple[str, float], ...] = ()  # harte Sätze je Muskel; mitbeteiligt = 0,5
    mid_rpe: float = 9.0                # Ziel-RPE der mittleren Sätze


# Schwere Grundübungen: nie bis zum Versagen (RIR 2 → 2 → 1).
_COMPOUND = {"mid_rpe": 8.0, "last_rpe": 9.0}


@dataclass(frozen=True)
class Plan:
    key: str
    title: str                          # Name der Hevy-Routine
    name: str
    per_week: int
    exercises: tuple[PlanExercise, ...]
    family: str = ""                    # Varianten desselben Programms (Kraft-Tag „ok“/„uk“); leer = key

    @property
    def program(self) -> str:
        return self.family or self.key


_ROW = PlanExercise("row", "Rudern sitzend (Maschine)", ("1DF4A847",),
                    ("Rudern sitzend (Maschine)", "Seated Row (Machine)"), 3, (8, 12), 150, _select(40), warmup=True, **_COMPOUND,
                    muscles=(("Rücken", 1), ("Bizeps", .5), ("Hintere Schulter", .5)))
_LATERAL = PlanExercise("lateral", "Seitheben (Maschine)", ("D5D0354D",),
                        ("Seitheben (Maschine)", "Lateral Raise (Machine)"), 4, (12, 15), 90, _select(25),
                        muscles=(("Seitliche Schulter", 1),))
_PULLDOWN = PlanExercise("pulldown", "Iso-Lateral Front Lat Pulldown", ("ada49467-4881-4b3d-9720-38df35f40c82",),
                         ("Iso-Lateral Front Lat Pulldown",), 3, (8, 12), 150, Ladder(5.0), **_COMPOUND,
                         muscles=(("Rücken", 1), ("Bizeps", .5)))
_HAMMER = PlanExercise("hammer", "Hammer Curl sitzend Schrägbank", ("C01F58D1",),
                       ("Hammer Curl sitzend auf der Schrägbank (Kurzhantel)", "Seated Incline Hammer Curl (Dumbbell)"),
                       2, (10, 15), 90, Ladder(5.0), superset=1, muscles=(("Bizeps", 1),))
_SKULL = PlanExercise("skull", "Stirndrücken (Langhantel)", ("875F585F",),
                      ("Stirndrücken (Langhantel)", "Skullcrusher (Barbell)"), 2, (10, 15), 90, Ladder(2.5),
                      superset=1, muscles=(("Trizeps", 1),))


def _mts(sets: int) -> PlanExercise:
    return PlanExercise("mts", "MTS Incline Press", ("806def2a-0d7f-4b99-a200-893c01b6e00d",),
                        ("MTS Incline Press",), sets, (8, 12), 150, Ladder(5.0), warmup=True, **_COMPOUND,
                        muscles=(("Brust", 1), ("Trizeps", .5)))


PLANS: tuple[Plan, ...] = (
    Plan("ok", "Milon OK", "Oberkörper A", 1, (
        _ROW, _mts(3), _LATERAL, _PULLDOWN,
        PlanExercise("fly", "Butterfly (Maschine)", ("78683336", "9DCE2D64"),
                     ("Fliegende (Maschine)", "Butterfly (Pec Deck)"), 2, (10, 15), 90, _select(82), superset=0,
                     muscles=(("Brust", 1),)),
        PlanExercise("rear_fly", "Reverse Butterfly (Maschine)", ("D8281C62",),
                     ("Reverse Fliegende (Maschine)", "Rear Delt Reverse Fly (Machine)"), 2, (10, 15), 90, _select(40),
                     superset=0, muscles=(("Hintere Schulter", 1),)),
        _HAMMER, _SKULL,
    )),
    # Variante ohne Butterfly: Brustvolumen über 5 Sätze MTS, hintere Schulter per Face Pull am Seilzug.
    Plan("ok_b", "Milon OK B", "Oberkörper B", 1, (
        _ROW, _mts(5), _LATERAL, _PULLDOWN,
        PlanExercise("face_pull", "Face Pull (Seilzug)", ("BE640BA0",), ("Face Pull",), 3, (12, 20), 90,
                     Ladder(2.5), muscles=(("Hintere Schulter", 1),)),
        _HAMMER, _SKULL,
    ), family="ok"),
    Plan("uk", "Milon UK", "Unterkörper", 1, (
        PlanExercise("legpress", "Beinpresse (Maschine)", ("C7973E0E",),
                     ("Beinpresse (Maschine)", "Leg Press (Machine)"), 4, (10, 15), 150, Ladder(5.0, 53), warmup=True, **_COMPOUND,
                     muscles=(("Quadrizeps", 1), ("Gesäß", .5))),
        PlanExercise("rdl", "Romanian Deadlift (Langhantel)", ("2B4B7310",),
                     ("Romanian Deadlift (Barbell)", "Rumänisches Kreuzheben (Langhantel)"), 3, (6, 10), 150, Ladder(5.0),
                     **_COMPOUND, muscles=(("Beinbeuger", 1), ("Gesäß", 1))),
        PlanExercise("legcurl", "Beinbeugen sitzend (Maschine)", ("11A123F3",),
                     ("Beinbeugen sitzend", "Seated Leg Curl (Machine)"), 4, (10, 15), 90, _select(40),
                     superset=0, muscles=(("Beinbeuger", 1),)),
        PlanExercise("legext", "Beinstrecker (Maschine)", ("75A4F6C4",),
                     ("Beinstrecker (Maschine)", "Leg Extension (Machine)"), 4, (10, 15), 90, _select(61),
                     superset=0, muscles=(("Quadrizeps", 1),)),
    )),
)
MUSCLES = ("Brust", "Rücken", "Seitliche Schulter", "Hintere Schulter", "Bizeps", "Trizeps",
           "Quadrizeps", "Beinbeuger", "Gesäß")
VOLUME_BAND = (10, 20)  # harte Sätze je Muskel und Woche (Schoenfeld 2017, Pelland 2025)
HARD_RPE = 7.0          # ≤ 3 RIR zählt als harter Satz; fehlende RPE zählt mit
REP_LIMIT = 50


class StrengthRule(SQLModel, table=True):
    """Eigene Progressionsregel je Planübung (Plan-Übungsschlüssel); fehlt sie, gilt `PlanExercise.reps`."""
    __tablename__ = "strength_rules"

    key: str = Field(primary_key=True)
    min_reps: int
    target_reps: int


def _exercises() -> dict[str, PlanExercise]:
    """Planübungen je Schlüssel; Varianten teilen Übungen (z. B. MTS) — die erste Definition zählt für die Wdh."""
    out: dict[str, PlanExercise] = {}
    for p in PLANS:
        for ex in p.exercises:
            out.setdefault(ex.key, ex)
    return out


def rules() -> dict[str, tuple[int, int]]:
    """Gespeicherte Regeln: Schlüssel → (Mindest-Wdh., Ziel-Wdh.)."""
    with Session(engine) as db:
        return {r.key: (r.min_reps, r.target_reps) for r in db.exec(select(StrengthRule)).all()}


def rule_list() -> list[dict]:
    """Alle Planübungen mit aktueller Regel und den Namen, unter denen Hevy sie führt (für den Übungskatalog)."""
    own = rules()
    out = []
    for key, ex in _exercises().items():
        lo, hi = own.get(key, ex.reps)
        out.append({"key": key, "name": ex.name, "names": list(ex.names), "sets": ex.sets,
                    "min_reps": lo, "target_reps": hi, "default": list(ex.reps), "custom": key in own})
    return out


def set_rule(key: str, min_reps: int, target_reps: int) -> dict:
    """Regel speichern; KeyError bei unbekannter Übung, ValueError bei unplausiblen Wdh."""
    if key not in _exercises():
        raise KeyError(key)
    if not 1 <= min_reps <= target_reps <= REP_LIMIT:
        raise ValueError(f"Wiederholungen: 1 ≤ Mindest-Wdh. ≤ Ziel-Wdh. ≤ {REP_LIMIT}.")
    with Session(engine) as db:
        row = db.get(StrengthRule, key) or StrengthRule(key=key, min_reps=min_reps, target_reps=target_reps)
        row.min_reps, row.target_reps = min_reps, target_reps
        db.add(row)
        db.commit()
    return next(r for r in rule_list() if r["key"] == key)


def reset_rule(key: str) -> dict:
    if key not in _exercises():
        raise KeyError(key)
    with Session(engine) as db:
        row = db.get(StrengthRule, key)
        if row:
            db.delete(row)
            db.commit()
    return next(r for r in rule_list() if r["key"] == key)


def _read_sets() -> pd.DataFrame:
    """Alle Hevy-Sätze der Planübungen (Arbeit + Aufwärmen) mit Plan-Übungsschlüssel."""
    templates = {t: ex.key for p in PLANS for ex in p.exercises for t in ex.templates}
    names = {n: ex.key for p in PLANS for ex in p.exercises for n in ex.names}
    with engine.connect() as con:
        df = pd.read_sql(
            "SELECT ws.workout_id, ws.exercise, ws.exercise_template_id, ws.set_index, ws.set_type, "
            "ws.weight_kg, ws.reps, ws.rpe, w.started_at "
            "FROM workout_sets ws JOIN workouts w ON w.id = ws.workout_id "
            "WHERE w.started_at IS NOT NULL", con, parse_dates=["started_at"])
    if df.empty:
        return df.assign(key=pd.Series(dtype=str))
    df["key"] = df["exercise_template_id"].map(templates)
    no_id = df["exercise_template_id"].isna()
    df.loc[no_id, "key"] = df.loc[no_id, "exercise"].map(names)
    return df.dropna(subset=["key"]).sort_values(["started_at", "workout_id", "set_index"])


def _de(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _targets(ex: PlanExercise) -> list[float]:
    """RIR sinkt über die Sätze: RPE 8 → `mid_rpe` … → `last_rpe`."""
    if ex.sets == 1:
        return [ex.last_rpe]
    return [8.0] + [ex.mid_rpe] * (ex.sets - 2) + [ex.last_rpe]


def _main_weight(weights: list[float]) -> float:
    counts = Counter(weights)
    top = max(counts.values())
    return max(w for w, c in counts.items() if c == top)


def _session_sets(df: pd.DataFrame) -> list[dict]:
    """Je Workout die Arbeitssätze dieser Übung: [{date, sets:[(w, r, rpe)]}], chronologisch."""
    work = df[df["set_type"].isin(WORK_TYPES) & (df["weight_kg"] > 0) & (df["reps"] > 0)]
    sessions: dict = {}  # workout_id → Session, in Reihenfolge des ersten Auftretens (wie groupby sort=False)
    for wid, started, w, r, rpe in zip(work["workout_id"].tolist(), work["started_at"].tolist(),
                                       work["weight_kg"].tolist(), work["reps"].tolist(), work["rpe"].tolist()):
        s = sessions.get(wid)
        if s is None:
            s = sessions[wid] = {"date": started.date(), "sets": []}
        s["sets"].append((float(w), int(r), None if pd.isna(rpe) else float(rpe)))
    return sorted(sessions.values(), key=lambda s: s["date"])


def _sets_word(n: int) -> str:
    return "Satz" if n == 1 else "Sätze"


def suggest(ex: PlanExercise, sessions: list[dict], today: date,
            rule: tuple[int, int] | None = None) -> dict:
    """Vorschlag für die nächste Einheit einer Übung; `rule` = (Mindest-Wdh., Ziel-Wdh.)."""
    lo, hi = rule or ex.reps
    targets = _targets(ex)
    recent = [s for s in sessions if (today - s["date"]).days <= STALE_DAYS]
    if not recent:
        window = [st for s in sessions if (today - s["date"]).days <= E1RM_DAYS for st in s["sets"]]
        if not window:
            return _result(ex, None, lo, hi, targets, "new",
                           "Noch keine Daten – Startgewicht selbst wählen.", None)
        e1 = max(e1rm(w, r, rpe) for w, r, rpe in window)
        weight = ex.ladder.floor(e1 / (1 + (hi + 2) / 30))  # Ziel-Wdh. mit ~2 Wdh. Reserve
        return _result(ex, weight, lo, hi, targets, "start",
                       f"Über {STALE_DAYS} Tage nicht trainiert – Start aus geschätztem 1RM ({_de(round(e1, 1))} kg).",
                       None)

    last = recent[-1]
    w = _main_weight([st[0] for st in last["sets"]])
    at_w = [st for st in last["sets"] if abs(st[0] - w) < 0.01][:ex.sets]
    done = [r for _, r, _ in at_w]
    shown = f"{_de(w)} kg × " + "/".join(str(r) for r in done)
    if any(rpe is not None for *_, rpe in at_w):
        shown += " @ " + "/".join(_de(rpe) if rpe is not None else "–" for *_, rpe in at_w)
    hit = sum(r >= hi for r in done)

    if len(done) == ex.sets and hit == ex.sets:
        action, new_w = "increase", ex.ladder.up(w)
        reason = f"Alle {ex.sets} Sätze ≥ {hi} Wdh. → +{_de(round(new_w - w, 2))} kg."
    elif any(r < lo for r in done):
        action, new_w = "decrease", ex.ladder.down(w)
        reason = f"Ein Satz unter {lo} Wdh. → eine Stufe leichter."
    else:
        action, new_w = "hold", w
        reason = (f"{hit} von {ex.sets} Sätzen ≥ {hi} Wdh. → gleiches Gewicht."
                  if len(done) == ex.sets else
                  f"Nur {len(done)} von {ex.sets} Sätzen mit {_de(w)} kg erfasst → gleiches Gewicht.")
    pause = (today - last["date"]).days
    if pause > PAUSE_DAYS and action != "decrease":
        new_w = ex.ladder.down(w)
        action = "pause"
        reason = f"{pause} Tage Pause → eine Stufe leichter."
    last_info = {"date": last["date"].isoformat(), "summary": shown, "reps": done, "hit": hit}
    return _result(ex, new_w, lo, hi, targets, action, f"Letztes Mal {shown}. {reason}", last_info)


def _rule_lines(ex: PlanExercise, weight: float | None, lo: int, hi: int, targets: list[float]) -> list[str]:
    up = f" → {_de(ex.ladder.up(weight))} kg" if weight else " → eine Stufe schwerer"
    down = f" → {_de(ex.ladder.down(weight))} kg" if weight else " → eine Stufe leichter"
    return [
        f"Schwerer: alle {ex.sets} {_sets_word(ex.sets)} ≥ {hi} Wdh.{up}",
        f"Leichter: ein Satz unter {lo} Wdh.{down}",
        "Sonst: gleiches Gewicht, Wiederholungen sammeln",
        f"Pause über {PAUSE_DAYS} Tage: eine Stufe leichter",
        "RIR " + " → ".join(_de(10 - t) for t in targets) + ": Leitplanke beim Training, zählt nicht für die Regel",
    ]


def _result(ex: PlanExercise, weight: float | None, lo: int, hi: int, targets: list[float],
            action: str, reason: str, last: dict | None) -> dict:
    sets = []
    if ex.warmup and weight:
        sets.append({"type": "warmup", "weight_kg": ex.ladder.floor(weight * 0.6), "reps": 12, "rpe": None})
    sets += [{"type": "normal", "weight_kg": weight, "reps": hi, "rpe": t} for t in targets]
    rir = (f"Ziel {ex.sets} × {hi} Wdh., dann schwerer; unter {lo} leichter. RIR "
           + " → ".join(_de(10 - t) for t in targets) + " als Leitplanke")
    return {
        "key": ex.key, "name": ex.name, "template_id": ex.templates[0],
        "rep_range": [lo, hi], "rest_seconds": ex.rest, "superset": ex.superset,
        "weight_kg": weight, "step_up_kg": round(ex.ladder.up(weight) - weight, 2) if weight else None,
        "sets": sets, "action": action, "reason": reason, "rir_note": rir, "last": last,
        "rule": {"min_reps": lo, "target_reps": hi, "default": list(ex.reps), "custom": (lo, hi) != ex.reps,
                 "lines": _rule_lines(ex, weight, lo, hi, targets)},
    }


def _classify(df: pd.DataFrame) -> dict[int, str]:
    """Workout → Plan-Key nach Anteil der Arbeitssätze; mindestens 2 Übungen des Programms.
    Varianten eines Programms (ok/ok_b) trennen die Übungen, die nur eine Variante hat; ohne
    solche gilt die erste Variante."""
    key_program = {ex.key: p.program for p in PLANS for ex in p.exercises}
    work = df[df["set_type"].isin(WORK_TYPES)]
    by_workout: dict = {}
    for wid, key in zip(work["workout_id"].tolist(), work["key"].tolist()):
        by_workout.setdefault(wid, []).append(key)
    variants_of = {prog: [p for p in PLANS if p.program == prog] for prog in {p.program for p in PLANS}}
    own_of = {prog: {p.key: {ex.key for ex in p.exercises} - set().union(*({e.key for e in v.exercises}
                                                                            for v in variants if v is not p))
                     for p in variants}
              for prog, variants in variants_of.items()}
    out = {}
    for wid in sorted(by_workout):  # wie groupby: nach workout_id
        workout_keys = by_workout[wid]
        programs = Counter(key_program[k] for k in workout_keys)
        best, n = programs.most_common(1)[0]
        keys = {k for k in workout_keys if key_program[k] == best}
        if len(keys) < 2:
            continue
        own = own_of[best]
        out[int(wid)] = max(variants_of[best], key=lambda p: len(own[p.key] & keys)).key
    return out


def _duration_min(plan: Plan) -> int:
    seconds, done = 0, set()
    for ex in plan.exercises:
        if ex.superset is None:
            seconds += ex.sets * (45 + ex.rest) + (105 if ex.warmup else 0) + 120
        elif ex.superset not in done:
            done.add(ex.superset)
            pair = [e for e in plan.exercises if e.superset == ex.superset]
            seconds += max(e.sets for e in pair) * (45 * len(pair) + ex.rest) + 120
    return round(seconds / 60)


@cached
def next_training(today: date | None = None) -> dict:
    """Alle Programme mit Vorschlag je Übung + Wochenstand (Mo–So) und welches als Nächstes dran ist."""
    today = today or datetime.now().date()
    df = _read_sets()
    monday = today - timedelta(days=today.weekday())
    kinds = _classify(df) if not df.empty else {}
    starts = df.groupby("workout_id")["started_at"].first() if not df.empty else pd.Series(dtype="datetime64[ns]")
    own = rules()
    by_key = {k: _session_sets(g) for k, g in df.groupby("key", sort=False)} if not df.empty else {}
    plans = []
    for p in PLANS:
        mine = [wid for wid, k in kinds.items() if k == p.key]
        days = sorted(starts[mine].dt.date) if mine else []
        done = sum(1 for d in days if monday <= d <= today)
        exercises = [suggest(ex, by_key.get(ex.key, []), today, own.get(ex.key)) for ex in p.exercises]
        plans.append({
            "key": p.key, "program": p.program, "title": p.title, "name": p.name, "per_week": p.per_week, "done": done,
            "last_date": days[-1].isoformat() if days else None,
            "duration_min": _duration_min(p), "exercises": exercises,
        })
    open_plans = [p for p in plans if p["per_week"] - p["done"] > 0]
    nxt = max(open_plans, key=lambda p: p["per_week"] - p["done"])["key"] if open_plans else None
    return {"date": today.isoformat(), "week_start": monday.isoformat(), "next": nxt, "plans": plans}


def weekly_volume(today: date | None = None) -> dict:
    """Harte Sätze je Muskel: diese Woche (Mo–heute) vs. Ø der 4 vollen Wochen davor + Soll laut Plan.
    Zählt nur die Planübungen; mitbeteiligte Muskeln halb (fraktionale Zählung nach Pelland)."""
    today = today or datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(weeks=4)
    factors = {ex.key: ex.muscles for p in PLANS for ex in p.exercises}
    planned = dict.fromkeys(MUSCLES, 0.0)
    for p in PLANS:
        for ex in p.exercises:
            for muscle, f in ex.muscles:
                planned[muscle] += ex.sets * p.per_week * f
    this, prev = dict.fromkeys(MUSCLES, 0.0), dict.fromkeys(MUSCLES, 0.0)
    df = _read_sets()
    if not df.empty:
        day = df["started_at"].dt.date
        hard = df[df["set_type"].isin(WORK_TYPES) & (df["rpe"].isna() | (df["rpe"] >= HARD_RPE))
                  & (day >= start) & (day <= today)]
        for r in hard.itertuples():
            bucket = this if r.started_at.date() >= monday else prev
            for muscle, f in factors[r.key]:
                bucket[muscle] += f
    return {
        "week_start": monday.isoformat(), "band": list(VOLUME_BAND),
        "muscles": [{"muscle": m, "this_week": round(this[m], 1), "avg_4w": round(prev[m] / 4, 1),
                     "planned": round(planned[m], 1)} for m in MUSCLES],
    }
