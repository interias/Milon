"""Heldenreise: Wochenaufträge — aus Rohdaten berechnet, je ISO-Woche geseedet (stabil).

Pro Woche ein Lauf-, ein Kraft- und ein Pflege-Auftrag (Talent der Stufe 40 ergänzt einen
vierten). Die Lauf-Aufträge sind nach der Spezialisierung gewichtet. Ab ENDURANCE_FROM liegen im
Lauf-Topf zusätzlich Ausdauer-Aufträge (Minuten bzw. Zonen-Minuten, Lauf ODER Indoor-Fahrt) — erst
ab dann, damit die geseedete Auswahl früherer Wochen unverändert bleibt. Ab 3 Krankheitstagen
halbieren sich die Ziele. Jeder Auftrag gibt EP am Tag der Erfüllung; alle erfüllt → Beute.
"""
from __future__ import annotations

import hashlib
import math
import random
from datetime import date, timedelta

import pandas as pd

QUEST_XP = 150

# (id, Kategorie, Titel, Ziel-Beschreibung, Ziel, Einheit)
QUESTS = {
    "locker2": ("lauf", "Ruhiger Atem", "Lockere Läufe in Zone 1–2", 2, "Läufe"),
    "tempo1": ("lauf", "Feuer in den Beinen", "Tempolauf in Zone 3–4", 1, "Lauf"),
    "lang1": ("lauf", "Die lange Straße", "Lauf ab 10 km", 1, "Lauf"),
    "laeufe3": ("lauf", "Dreifacher Schritt", "Läufe diese Woche", 3, "Läufe"),
    "km20": ("lauf", "Kilometerfresser", "Kilometer gelaufen", 20, "km"),
    "morgen1": ("lauf", "Vor dem Hahnenschrei", "Lauf vor 9 Uhr", 1, "Lauf"),
    "kraft2": ("kraft", "Eisen ruft", "Krafttrainings", 2, "Trainings"),
    "saetze30": ("kraft", "Hammer und Amboss", "Arbeitssätze", 30, "Sätze"),
    "protein5": ("pflege", "Gut versorgt", "Tage mit Protein-Ziel", 5, "Tage"),
    "schlaf3": ("pflege", "Traumwandler", "Nächte ab 7 h Schlaf", 3, "Nächte"),
    "schritte60": ("pflege", "Wanderer", "Schritte", 60000, "Schritte"),
    "ruhetag1": ("pflege", "Ruhe ist Training", "Ruhetag ohne Lauf und Kraft", 1, "Tag"),
    "ausdauer150": ("ausdauer", "Unermüdlich", "Ausdauer-Minuten, Lauf oder Rad", 150, "min"),
    "grundlage90": ("ausdauer", "Ruhige Kurbel", "Minuten in Zone 1–2, Lauf oder Rad", 90, "min"),
    "tempo30": ("ausdauer", "Glühende Pedale", "Minuten in Zone 3–4, Lauf oder Rad", 30, "min"),
}
ENDURANCE_FROM = date(2026, 10, 26)  # erste Woche mit Ausdauer-Aufträgen (#72)
ENDURANCE = [k for k, v in QUESTS.items() if v[0] == "ausdauer"]
SPEC_ENDURANCE = {"ausdauer": ["grundlage90"], "tempo": ["tempo30"], "last": ["ausdauer150"]}
SPEC_LAUF = {"ausdauer": ["locker2", "locker2", "km20"], "tempo": ["tempo1", "tempo1", "morgen1"],
             "strecke": ["lang1", "lang1", "km20"], "last": ["laeufe3", "laeufe3", "km20"]}
ALL_LAUF = [k for k, v in QUESTS.items() if v[0] == "lauf"]
CATS = {c: [k for k, v in QUESTS.items() if v[0] == c] for c in ("lauf", "kraft", "pflege")}


def _rng(*parts) -> random.Random:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def pick(week: date, spec: str | None, extra: str | None) -> list[str]:
    rng = _rng("quests", week.isoformat())
    pool = SPEC_LAUF.get(spec or "", []) + ALL_LAUF
    endurance = week >= ENDURANCE_FROM
    if endurance:
        pool += SPEC_ENDURANCE.get(spec or "", []) + ENDURANCE
    chosen = [rng.choice(pool), rng.choice(CATS["kraft"]), rng.choice(CATS["pflege"])]
    if extra in CATS:
        rest = [k for k in CATS[extra] + (ENDURANCE if extra == "lauf" and endurance else []) if k not in chosen]
        if rest:
            chosen.append(rng.choice(rest))
    return chosen


def _daily_values(qid: str, week: date, d: date, data: dict) -> float:
    """Beitrag des Tages d zum Auftrag (summiert sich über die Woche)."""
    runs, workouts = data["runs"], data["workouts"]
    day_runs = runs[runs["day"] == d] if not runs.empty else runs
    if qid in ENDURANCE:  # Lauf ODER Indoor-Fahrt; Zone beider in Lauf-Skala (0..3)
        rides = data.get("indoor")
        day_rides = rides[rides["day"] == d] if rides is not None and not rides.empty else None
        frames = [f for f in (day_runs, day_rides) if f is not None and not f.empty]
        if not frames:
            return 0.0
        both = pd.concat([f[["dur_min", "zone"]] for f in frames], ignore_index=True)
        zone = pd.to_numeric(both["zone"], errors="coerce")
        mask = {"ausdauer150": pd.Series(True, index=both.index), "grundlage90": zone <= 1, "tempo30": zone >= 2}[qid]
        return float(both.loc[mask, "dur_min"].sum())
    zone = day_runs["zone"] if not day_runs.empty else pd.Series(dtype=float)
    if qid == "locker2":
        return float((zone.dropna() <= 1).sum())
    if qid == "tempo1":
        return float((zone.dropna() >= 2).sum())
    if qid == "lang1":
        return float((day_runs["distance_km"] >= 10).sum()) if not day_runs.empty else 0.0
    if qid == "laeufe3":
        return float(len(day_runs))
    if qid == "km20":
        return float(day_runs["distance_km"].sum()) if not day_runs.empty else 0.0
    if qid == "morgen1":
        return float((day_runs["started_at"].dt.hour < 9).sum()) if not day_runs.empty else 0.0
    day_wo = workouts[workouts["day"] == d] if not workouts.empty else workouts
    if qid == "kraft2":
        return float(len(day_wo))
    if qid == "saetze30":
        return float(day_wo["sets"].sum()) if not day_wo.empty else 0.0
    if qid == "protein5":
        target = data.get("protein_target")
        return 1.0 if target and data["protein"].get(d, 0) >= 0.9 * target else 0.0
    if qid == "schlaf3":
        return 1.0 if data["sleep"].get(d, 0) >= 420 else 0.0
    if qid == "schritte60":
        return float(data["steps"].get(d, 0))
    if qid == "ruhetag1":
        return 1.0 if day_runs.empty and day_wo.empty else 0.0
    return 0.0


def week_quests(week: date, spec: str | None, extra: str | None, data: dict, today: date) -> dict:
    sick = sum(1 for i in range(7) if week + timedelta(days=i) in data["sick"])
    halved = sick >= 3
    out = []
    for qid in pick(week, spec, extra):
        cat, title, goal, target, unit = QUESTS[qid]
        if halved:
            target = max(1, math.ceil(target / 2))
        total, done_on = 0.0, None
        for i in range(7):
            d = week + timedelta(days=i)
            if d > today:
                break
            total += _daily_values(qid, week, d, data)
            if done_on is None and total >= target:
                done_on = d
        out.append({"id": qid, "category": cat, "title": title, "goal": goal, "target": target, "unit": unit,
                    "progress": round(min(total, target), 1), "done": done_on is not None,
                    "done_on": done_on.isoformat() if done_on else None, "xp": QUEST_XP})
    all_done = all(q["done"] for q in out)
    return {"week": week.isoformat(), "quests": out, "halved": halved, "sick_days": sick,
            "complete": all_done, "complete_on": max(q["done_on"] for q in out) if all_done else None}
