"""Heldenreise: Monatsbosse und Instanzen — aus Rohdaten, ohne gespeicherten Zustand.

Monatsbosse sind persönliche Ziele relativ zu den 90 Tagen vor Monatsbeginn (Tempo, Distanz,
Volumen, Kraft). Die Lebensleiste zeigt den Abstand zum Ziel; besiegt am Tag, an dem das Ziel
erreicht wurde. Instanzen sind lange Läufe (ab 10 km): Kilometermarken sind die Bosse, dazu ein
Bonusboss für Tempo über dem eigenen Langlauf-Median.
"""
from __future__ import annotations

import calendar
import hashlib
import random
from datetime import date, timedelta

import pandas as pd

BOSS_XP = 400
DUNGEON_BOSS_XP = 50


def _rng(*parts) -> random.Random:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _mmss(sec: float) -> str:
    s = int(round(sec))
    return f"{s // 60}:{s % 60:02d}"


def _month_end(month: date) -> date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def month_bosses(month: date, data: dict, today: date) -> list[dict]:
    """Bosse des Kalendermonats `month` (1. des Monats)."""
    runs, workouts, efforts = data["runs"], data["workouts"], data["efforts"]
    end = min(_month_end(month), today)
    prior = month - timedelta(days=90)
    days_in = _month_end(month).day
    sick = sum(1 for i in range(days_in) if month + timedelta(days=i) in data["sick"])
    healthy = max(0.25, (days_in - sick) / days_in)
    in_month = runs[(runs["day"] >= month) & (runs["day"] <= end)] if not runs.empty else runs
    before = runs[(runs["day"] >= prior) & (runs["day"] < month)] if not runs.empty else runs
    out = []

    # Tempo: 5-km-Bestzeit 2 % unterbieten
    e5 = efforts[efforts["distance_m"] == 5000] if not efforts.empty else efforts
    base_e = e5[(e5["started_at"].dt.date >= prior) & (e5["started_at"].dt.date < month)] if not e5.empty else e5
    baseline = float(base_e["seconds"].min()) if not base_e.empty else 2100.0
    target = int(baseline * 0.98)
    cur = e5[(e5["started_at"].dt.date >= month) & (e5["started_at"].dt.date <= end)].sort_values("started_at") if not e5.empty else e5
    best, won = None, None
    for r in cur.itertuples():
        best = r.seconds if best is None else min(best, r.seconds)
        if won is None and r.seconds <= target:
            won = r.started_at.date()
    hp = 1.0 if best is None else max(0.0, min(1.0, (best - target) / max(1.0, baseline - target)))
    out.append(_boss("waechter", "Der 5-km-Wächter", "Tempo", f"5 km unter {_mmss(target)}",
                     f"Monatsbestwert {_mmss(best)}" if best else "noch kein 5-km-Abschnitt", hp, won, "orange"))

    # Distanz: längster Lauf + 1 km
    longest_before = float(before["distance_km"].max()) if not before.empty else 9.0
    target_km = max(10.0, round(longest_before + 1.0, 1))
    won = None
    for r in in_month.sort_values("started_at").itertuples():
        if r.distance_km >= target_km:
            won = r.day
            break
    longest = float(in_month["distance_km"].max()) if not in_month.empty else 0.0
    out.append(_boss("wyrm", "Wyrm der langen Straße", "Distanz", f"ein Lauf ab {target_km:.1f} km".replace(".", ","),
                     f"längster Lauf {longest:.1f} km".replace(".", ","), max(0.0, 1 - longest / target_km), won, "lila"))

    # Volumen: Monats-km 10 % über dem Schnitt der letzten 3 Monate
    prev3 = float(before["distance_km"].sum()) / 3 if not before.empty else 30.0
    target_vol = round(max(40.0, prev3 * 1.1) * healthy)
    cum, won = 0.0, None
    for r in in_month.sort_values("started_at").itertuples():
        cum += r.distance_km
        if won is None and cum >= target_vol:
            won = r.day
    out.append(_boss("fresser", "Der Kilometerfresser", "Volumen", f"{target_vol} km im Monat",
                     f"{cum:.0f} km gelaufen", max(0.0, 1 - cum / target_vol), won, "lila"))

    # Kraft: Arbeitssätze 10 % über dem Schnitt
    wo_month = workouts[(workouts["day"] >= month) & (workouts["day"] <= end)] if not workouts.empty else workouts
    wo_before = workouts[(workouts["day"] >= prior) & (workouts["day"] < month)] if not workouts.empty else workouts
    target_sets = round(max(40.0, float(wo_before["sets"].sum()) / 3 * 1.1) * healthy) if not wo_before.empty else round(40 * healthy)
    cum, won = 0.0, None
    for w in wo_month.sort_values("started_at").itertuples():
        cum += w.sets
        if won is None and cum >= target_sets:
            won = w.day
    out.append(_boss("koloss", "Der Eisenkoloss", "Kraft", f"{target_sets} Arbeitssätze im Monat",
                     f"{cum:.0f} Sätze", max(0.0, 1 - cum / target_sets), won, "lila"))
    chain = _chain_eater(month, end, prior, healthy, data.get("ride_min") or [])
    if chain:
        out.append(chain)
    for b in out:
        b["month"] = month.isoformat()
    return out


def _hours(minutes: float) -> str:
    h, m = divmod(int(round(minutes)), 60)
    return f"{h} h {m:02d} min" if m else f"{h} h"


def _chain_eater(month: date, end: date, prior: date, healthy: float, ride_min: list[tuple[date, float]]) -> dict | None:
    """Rad-Zeit im Monat (Indoor + GPS) 10 % über dem Schnitt der letzten 3 Monate, mindestens 4 h; der erste
    Rad-Monat hat fest 4 h. Erscheint nur, wenn in den 90 Tagen bis Monatsende (bzw. heute) eine Fahrt lag."""
    if not any(end - timedelta(days=90) < d <= end for d, _ in ride_min):
        return None
    before = [m for d, m in ride_min if prior <= d < month]
    target = round(max(240.0, sum(before) / 3 * 1.1) * healthy) if before else round(240 * healthy)
    cum, won = 0.0, None
    for d, m in sorted((x for x in ride_min if month <= x[0] <= end), key=lambda x: x[0]):
        cum += m
        if won is None and cum >= target:
            won = d
    return _boss("kettenfresser", "Der Kettenfresser", "Rad-Zeit", f"{_hours(target)} auf dem Rad im Monat",
                 f"{_hours(cum)} gefahren", max(0.0, 1 - cum / target), won, "lila")


def _boss(key, name, kind, goal, status, hp, won, loot):
    return {"key": key, "name": name, "kind": kind, "goal": goal, "status": status, "hp": round(hp, 3),
            "defeated": won is not None, "defeated_on": won.isoformat() if won else None, "xp": BOSS_XP, "loot": loot}


DUNGEON_NAMES = ["Die Katakomben der Rheinauen", "Die Zitadelle von Wesel", "Der Diersfordter Forst",
                 "Der Pfad an der Lippe", "Die Hallen der Ausdauer", "Die Deichkrone", "Das Auenmoor"]
TIERS = [(21.0975, "mythisch", "Mythisch", "orange"), (15.0, "heroisch", "Heroisch", "lila"), (10.0, "normal", "Normal", "blau")]
CHECKPOINTS = [(5.0, "Torwächter"), (10.0, "Hallenfürst"), (15.0, "Der Unermüdliche"), (21.0975, "Halbmarathon-Drache")]


def dungeons(runs: pd.DataFrame, start: date) -> list[dict]:
    """Jeder Lauf ab 10 km seit dem Starttag ist eine Instanz."""
    if runs.empty:
        return []
    out = []
    for i, r in enumerate(runs.itertuples()):
        if r.day < start or r.distance_km < 10:
            continue
        tier = next(t for t in TIERS if r.distance_km >= t[0])
        prior = runs.iloc[:i]
        prior = prior[(prior["distance_km"] >= 10) & (prior["started_at"] >= r.started_at - pd.Timedelta(days=180))]
        # Erreichte Kilometermarken sind besiegt; die nächste Marke steht als optionaler Ausblick dabei.
        bosses = [{"name": n, "km": km, "defeated": True} for km, n in CHECKPOINTS if r.distance_km >= km]
        nxt = next(((km, n) for km, n in CHECKPOINTS if r.distance_km < km), None)
        if nxt:
            bosses.append({"name": nxt[1], "km": nxt[0], "defeated": False, "optional": True})
        if len(prior) >= 2:
            median = float(prior["pace"].median())
            bosses.append({"name": "Schatten des Tempos", "km": None, "defeated": r.pace < median,
                           "hint": f"schneller als {int(median)}:{round((median % 1) * 60):02d} min/km"})
        rng = _rng("dungeon", r.key)
        out.append({"id": f"dungeon:{r.key}", "name": rng.choice(DUNGEON_NAMES), "tier": tier[1], "tier_label": tier[2],
                    "loot": tier[3], "date": r.day.isoformat(), "km": round(float(r.distance_km), 1), "bosses": bosses,
                    "cleared": all(b["defeated"] for b in bosses if not b.get("optional")),
                    "xp": DUNGEON_BOSS_XP * sum(b["defeated"] for b in bosses)})
    return out
