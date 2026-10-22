"""Trainingsplan „Nächstes Training“: zwei feste Programme (Oberkörper/Unterkörper) mit
doppelter Progression und konstanten Wiederholungen. Wiederholungen werden auf die Ziel-RPE je
Satz umgerechnet (RPE 10 × 12 Wdh. ≈ RPE 8 × 10 Wdh.), damit Sätze bis zum Versagen nicht als
Fortschritt durchgehen.

Regeln (im Grilling mit dem User festgelegt, belegt über „harte Sätze“ 0–3 RIR):
- Gleiche Wdh. in allen Sätzen, RIR sinkt: Satz 1 RPE 8, mittlere RPE 9, letzter `last_rpe`
  (10 = bis zum Versagen erlaubt; RDL 9).
- Ziel = erster Satz der letzten Einheit, umgerechnet auf RPE 8.
- Steigern: alle Sätze am oberen Ende des Bereichs. Halten: alle Sätze am Ziel → Ziel + 1, sonst
  dasselbe Ziel. Zurück: ein Satz unter dem unteren Ende → eine Stufe leichter.
- Plateau: 3 Einheiten (ab PLAN_START) auf demselben Gewicht ohne Wiederholungsgewinn → eine Stufe leichter.
- Pause > 21 Tage → eine Stufe leichter; > 90 Tage oder neu → Start aus dem e1RM der letzten 180 Tage.
Fehlende RPE zählt als eine Stufe über dem Ziel (steigern erst bei Wdh. über dem oberen Ende)."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from ..db import engine

PLAN_START = date(2026, 10, 23)  # Plateau-Regel zählt nur Einheiten im neuen RIR-Schema
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
# Kurzhanteln: Gesamtgewicht beider Hanteln, Hanteln in 2,5-kg-Stufen → 5 kg. MTS, Stirndrücken: 2,5 kg.
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


@dataclass(frozen=True)
class Plan:
    key: str
    title: str                          # Name der Hevy-Routine
    name: str
    per_week: int
    exercises: tuple[PlanExercise, ...]


PLANS: tuple[Plan, ...] = (
    Plan("ok", "Milon OK", "Oberkörper", 2, (
        PlanExercise("row", "Rudern sitzend (Maschine)", ("1DF4A847",),
                     ("Rudern sitzend (Maschine)", "Seated Row (Machine)"), 3, (8, 12), 150, _select(40), warmup=True,
                     muscles=(("Rücken", 1), ("Bizeps", .5), ("Hintere Schulter", .5))),
        PlanExercise("mts", "MTS Incline Press", ("806def2a-0d7f-4b99-a200-893c01b6e00d",),
                     ("MTS Incline Press",), 3, (8, 12), 150, Ladder(2.5), warmup=True,
                     muscles=(("Brust", 1), ("Trizeps", .5))),
        PlanExercise("lateral", "Seitheben (Maschine)", ("D5D0354D",),
                     ("Seitheben (Maschine)", "Lateral Raise (Machine)"), 4, (12, 20), 90, _select(25),
                     muscles=(("Seitliche Schulter", 1),)),
        PlanExercise("pulldown", "Iso-Lateral Front Lat Pulldown", ("ada49467-4881-4b3d-9720-38df35f40c82",),
                     ("Iso-Lateral Front Lat Pulldown",), 3, (8, 12), 150, Ladder(5.0),
                     muscles=(("Rücken", 1), ("Bizeps", .5))),
        PlanExercise("fly", "Butterfly (Maschine)", ("78683336", "9DCE2D64"),
                     ("Fliegende (Maschine)", "Butterfly (Pec Deck)"), 2, (10, 15), 90, _select(82), superset=0,
                     muscles=(("Brust", 1),)),
        PlanExercise("rear_fly", "Reverse Butterfly (Maschine)", ("D8281C62",),
                     ("Reverse Fliegende (Maschine)", "Rear Delt Reverse Fly (Machine)"), 2, (10, 15), 90, _select(40),
                     superset=0, muscles=(("Hintere Schulter", 1),)),
        PlanExercise("hammer", "Hammer Curl sitzend Schrägbank", ("C01F58D1",),
                     ("Hammer Curl sitzend auf der Schrägbank (Kurzhantel)", "Seated Incline Hammer Curl (Dumbbell)"),
                     2, (10, 15), 90, Ladder(5.0), superset=1, muscles=(("Bizeps", 1),)),
        PlanExercise("skull", "Stirndrücken (Langhantel)", ("875F585F",),
                     ("Stirndrücken (Langhantel)", "Skullcrusher (Barbell)"), 2, (10, 15), 90, Ladder(2.5),
                     superset=1, muscles=(("Trizeps", 1),)),
    )),
    Plan("uk", "Milon UK", "Unterkörper", 1, (
        PlanExercise("legpress", "Beinpresse (Maschine)", ("C7973E0E",),
                     ("Beinpresse (Maschine)", "Leg Press (Machine)"), 4, (10, 15), 150, Ladder(5.0, 53), warmup=True,
                     muscles=(("Quadrizeps", 1), ("Gesäß", .5))),
        PlanExercise("rdl", "Romanian Deadlift (Langhantel)", ("2B4B7310",),
                     ("Romanian Deadlift (Barbell)", "Rumänisches Kreuzheben (Langhantel)"), 4, (8, 12), 150, Ladder(5.0),
                     last_rpe=9.0, muscles=(("Beinbeuger", 1), ("Gesäß", 1))),
        PlanExercise("legcurl", "Liegendes Beinbeugen (Maschine)", ("B8127AD1",),
                     ("Liegendes Beinbeugen (Maschine)", "Lying Leg Curl (Machine)"), 4, (10, 15), 90, _select(39),
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
    """RIR sinkt über die Sätze: RPE 8 → 9 … → `last_rpe`."""
    if ex.sets == 1:
        return [ex.last_rpe]
    return [8.0] + [9.0] * (ex.sets - 2) + [ex.last_rpe]


def _main_weight(weights: list[float]) -> float:
    counts = Counter(weights)
    top = max(counts.values())
    return max(w for w, c in counts.items() if c == top)


def _reps_for(e1: float, weight: float, target: float, lo: int, hi: int) -> int:
    """Wdh. bei `weight` und Ziel-RPE aus einem e1RM (Epley rückwärts)."""
    to_failure = 30.0 * (e1 / weight - 1.0)
    return max(lo, min(hi, math.floor(to_failure - (10.0 - target) + 1e-9)))


def _session_sets(df: pd.DataFrame) -> list[dict]:
    """Je Workout die Arbeitssätze dieser Übung: [{date, sets:[(w, r, rpe)]}], chronologisch."""
    work = df[df["set_type"].isin(WORK_TYPES) & (df["weight_kg"] > 0) & (df["reps"] > 0)]
    out = []
    for _, g in work.groupby("workout_id", sort=False):
        out.append({
            "date": g["started_at"].iloc[0].date(),
            "sets": [(float(r.weight_kg), int(r.reps), None if pd.isna(r.rpe) else float(r.rpe))
                     for r in g.itertuples()],
        })
    return sorted(out, key=lambda s: s["date"])


def _adjusted(sets: list[tuple], targets: list[float]) -> list[float]:
    """Wdh. umgerechnet auf die Ziel-RPE je Satz (fehlende RPE = Ziel + 1)."""
    return [r - ((rpe if rpe is not None else t + 1.0) - t) for (_, r, rpe), t in zip(sets, targets)]


def suggest(ex: PlanExercise, sessions: list[dict], today: date) -> dict:
    """Vorschlag für die nächste Einheit einer Übung."""
    lo, hi = ex.reps
    targets = _targets(ex)
    recent = [s for s in sessions if (today - s["date"]).days <= STALE_DAYS]
    weight: float | None
    reps: list[int]
    last = None
    if not recent:
        window = [st for s in sessions if (today - s["date"]).days <= E1RM_DAYS for st in s["sets"]]
        if not window:
            return _result(ex, None, [lo] * ex.sets, targets, "new",
                           "Noch keine Daten – Startgewicht selbst wählen, 2 Wdh. im Tank lassen.", None)
        e1 = max(w * (1 + min(r + (10 - (rpe or 10)), 15) / 30) for w, r, rpe in window)
        mid = (lo + hi) // 2
        weight = ex.ladder.floor(e1 / (1 + (mid + 2) / 30))
        reps = [_reps_for(e1, weight, targets[0], lo, hi)] * ex.sets
        return _result(ex, weight, reps, targets, "start",
                       f"Über {STALE_DAYS} Tage nicht trainiert – Start aus geschätztem 1RM ({_de(round(e1, 1))} kg).",
                       None)

    last = recent[-1]
    w = _main_weight([st[0] for st in last["sets"]])
    at_w = [st for st in last["sets"] if abs(st[0] - w) < 0.01][:ex.sets]
    adj = _adjusted(at_w, targets)
    full = len(adj) == ex.sets
    while len(adj) < ex.sets:  # fehlende Sätze: einen weniger als der vorige
        adj.append((adj[-1] if adj else lo) - 1)
    first_e1 = w * (1 + (adj[0] + 10 - targets[0]) / 30)
    goal = math.floor(adj[0] + 1e-9)
    shown = f"{_de(w)} kg × " + "/".join(str(r) for _, r, _ in at_w)
    if any(rpe is not None for *_, rpe in at_w):
        shown += " @ " + "/".join(_de(rpe) if rpe is not None else "–" for *_, rpe in at_w)

    if full and all(a >= hi for a in adj):
        action, new_w = "increase", ex.ladder.up(w)
        reason = f"Alle Sätze am oberen Ende ({hi}) → +{_de(round(new_w - w, 2))} kg."
    elif any(a < lo for a in adj[:len(at_w)]):
        action, new_w = "decrease", ex.ladder.down(w)
        reason = f"Ein Satz unter {lo} Wdh. (auf Ziel-RPE gerechnet) → eine Stufe leichter."
    elif _plateau(ex, sessions, w, targets):
        action, new_w = "deload", ex.ladder.down(w)
        reason = "3 Einheiten ohne Fortschritt → eine Stufe leichter und neu aufbauen."
    elif full and min(adj) >= goal:
        action, new_w, goal = "hold", w, goal + 1
        reason = "Alle Sätze am Ziel → eine Wdh. mehr."
    else:
        action, new_w = "hold", w
        reason = "Noch nicht alle Sätze am Ziel → gleiches Ziel wiederholen."
    pause = (today - last["date"]).days
    if pause > PAUSE_DAYS and action not in ("decrease", "deload"):
        new_w = ex.ladder.down(w)
        action = "pause"
        reason = f"{pause} Tage Pause → eine Stufe leichter."
    rep = max(lo, min(hi, goal)) if action == "hold" else _reps_for(first_e1, new_w, targets[0], lo, hi)
    reps = [rep] * ex.sets
    last_info = {"date": last["date"].isoformat(), "summary": shown}
    return _result(ex, new_w, reps, targets, action, f"Letztes Mal {shown}. {reason}", last_info)


def _plateau(ex: PlanExercise, sessions: list[dict], w: float, targets: list[float]) -> bool:
    plan = [s for s in sessions if s["date"] >= PLAN_START][-3:]
    if len(plan) < 3:
        return False
    means = []
    for s in plan:
        at_w = [st for st in s["sets"] if abs(st[0] - w) < 0.01][:ex.sets]
        if len(at_w) < ex.sets:
            return False
        means.append(sum(_adjusted(at_w, targets)) / ex.sets)
    return means[-1] <= means[0]


def _result(ex: PlanExercise, weight: float | None, reps: list[int], targets: list[float],
            action: str, reason: str, last: dict | None) -> dict:
    sets = []
    if ex.warmup and weight:
        sets.append({"type": "warmup", "weight_kg": ex.ladder.floor(weight * 0.6), "reps": 12, "rpe": None})
    sets += [{"type": "normal", "weight_kg": weight, "reps": r, "rpe": t} for r, t in zip(reps, targets)]
    rir = "Gleiche Wdh. in allen Sätzen, RIR " + " → ".join(_de(10 - t) for t in targets)
    return {
        "key": ex.key, "name": ex.name, "template_id": ex.templates[0],
        "rep_range": list(ex.reps), "rest_seconds": ex.rest, "superset": ex.superset,
        "weight_kg": weight, "step_up_kg": round(ex.ladder.up(weight) - weight, 2) if weight else None,
        "sets": sets, "action": action, "reason": reason, "rir_note": rir, "last": last,
    }


def _classify(df: pd.DataFrame) -> dict[int, str]:
    """Workout → Plan ('ok'/'uk') nach Anteil der Arbeitssätze; mindestens 2 Planübungen."""
    key_plan = {ex.key: p.key for p in PLANS for ex in p.exercises}
    work = df[df["set_type"].isin(WORK_TYPES)]
    out = {}
    for wid, g in work.groupby("workout_id"):
        plans = Counter(key_plan[k] for k in g["key"])
        best, n = plans.most_common(1)[0]
        if g[g["key"].map(key_plan) == best]["key"].nunique() >= 2:
            out[int(wid)] = best
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


def next_training(today: date | None = None) -> dict:
    """Beide Programme mit Vorschlag je Übung + Wochenstand (Mo–So) und welches als Nächstes dran ist."""
    today = today or datetime.now().date()
    df = _read_sets()
    monday = today - timedelta(days=today.weekday())
    kinds = _classify(df) if not df.empty else {}
    starts = df.groupby("workout_id")["started_at"].first() if not df.empty else pd.Series(dtype="datetime64[ns]")
    plans = []
    for p in PLANS:
        mine = [wid for wid, k in kinds.items() if k == p.key]
        days = sorted(starts[mine].dt.date) if mine else []
        done = sum(1 for d in days if monday <= d <= today)
        exercises = [suggest(ex, _session_sets(df[df["key"] == ex.key]) if not df.empty else [], today)
                     for ex in p.exercises]
        plans.append({
            "key": p.key, "title": p.title, "name": p.name, "per_week": p.per_week, "done": done,
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
