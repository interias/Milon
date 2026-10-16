"""Heldenreise: Tagesaufgaben, Saison-Events und der Trainer-NPC — aus Rohdaten, ohne Zustand."""
from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta

DAILY_XP = 50
DAILY_STREAK_LOOT = 7
EVENT_XP = 300
EVENT_GOAL = 12

# (key, Titel, Ziel-Beschreibung)
DAILIES = {
    "schritte": ("Wanderschaft", "8.000 Schritte gehen"),
    "protein": ("Gut gestärkt", "Protein-Ziel erreichen (≥ 90 %)"),
    "checkin": ("Lagebericht", "Den Tages-Check-in ausfüllen"),
    "bewegung": ("In Bewegung", "Trainieren oder 20 Minuten gehen/radeln"),
    "schlaf": ("Erholsame Nacht", "Letzte Nacht mindestens 7 h schlafen"),
}


def _rng(*parts) -> random.Random:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def daily_key(d: date, data: dict) -> str:
    keys = list(DAILIES)
    if not data.get("protein_target"):
        keys.remove("protein")
    if not data.get("sleep"):
        keys.remove("schlaf")
    return _rng("daily", d.isoformat()).choice(keys)


def daily_done(key: str, d: date, data: dict) -> bool:
    runs, workouts = data["runs"], data["workouts"]
    if key == "schritte":
        return data["steps"].get(d, 0) >= 8000
    if key == "protein":
        target = data.get("protein_target")
        return bool(target) and data["protein"].get(d, 0) >= 0.9 * target
    if key == "checkin":
        return data["checkins"].get(d) is not None
    if key == "bewegung":
        trained = (not runs.empty and bool((runs["day"] == d).any())) or \
                  (not workouts.empty and bool((workouts["day"] == d).any()))
        return trained or data["other"].get(d, 0.0) >= 20
    if key == "schlaf":
        return data["sleep"].get(d, 0) >= 420
    return False


def dailies(start: date, today: date, data: dict) -> dict:
    """Tagesaufgaben seit dem Starttag; Serie überspringt Krankheitstage."""
    days, streak, loot_days = [], 0, []
    d = start
    while d <= today:
        key = daily_key(d, data)
        done = daily_done(key, d, data)
        days.append({"date": d.isoformat(), "key": key, "title": DAILIES[key][0], "goal": DAILIES[key][1], "done": done,
                     "sick": d in data["sick"]})
        if done:
            streak += 1
            if streak % DAILY_STREAK_LOOT == 0:
                loot_days.append(d)
        elif d in data["sick"] or d == today:
            pass  # krank pausiert; heute ist noch offen
        else:
            streak = 0
        d += timedelta(days=1)
    return {"today": days[-1] if days else None, "streak": streak, "last7": days[-7:], "loot_days": loot_days,
            "xp": [(date.fromisoformat(x["date"]), DAILY_XP, x["title"]) for x in days if x["done"]]}


# Saison-Events je Kalendermonat: (Name, Sammelgut, Einzahl, Gegenstand, Szenen-Effekt)
EVENTS = {
    1: ("Neujahrsfeuer", "Funken", "Funken", "Fackel des neuen Jahres", "funken"),
    2: ("Frostlauf", "Eiskristalle", "Eiskristall", "Frostgeschmiedete Spikes", "schnee"),
    3: ("Frühlingserwachen", "Knospen", "Knospe", "Krone des Erwachens", "blueten"),
    4: ("Blütenlauf", "Blütenblätter", "Blütenblatt", "Blütenkranz der Ausdauer", "blueten"),
    5: ("Maienfest", "Maiglöckchen", "Maiglöckchen", "Maibaumstab", "blueten"),
    6: ("Sonnenwende", "Sonnensplitter", "Sonnensplitter", "Amulett der längsten Tage", "gluehwuermchen"),
    7: ("Hochsommer", "Glühwürmchen", "Glühwürmchen", "Laterne der Sommernacht", "gluehwuermchen"),
    8: ("Sternschnuppennacht", "Sternenstaub", "Prise Sternenstaub", "Sternenstaub-Talisman", "gluehwuermchen"),
    9: ("Erntezeit", "Ähren", "Ähre", "Sichel der Erntezeit", "blaetter"),
    10: ("Herbstfest", "Herbstblätter", "Herbstblatt", "Kürbislaterne des Herbstfests", "blaetter"),
    11: ("Nebelmond", "Nebelperlen", "Nebelperle", "Nebelumhang des Deichs", "blaetter"),
    12: ("Winterhauch", "Schneeflocken", "Schneeflocke", "Wintermantel des Winterhauchs", "schnee"),
}


def season_event(month: date, data: dict, today: date) -> dict:
    name, token, one, item, effect = EVENTS[month.month]
    runs = data["runs"]
    end = min((month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1), today)
    got, done_on = 0, None
    if not runs.empty:
        for r in runs[(runs["day"] >= month) & (runs["day"] <= end)].sort_values("started_at").itertuples():
            got += 2 if r.distance_km >= 10 else 1
            if done_on is None and got >= EVENT_GOAL:
                done_on = r.day
    return {"month": month.isoformat(), "name": name, "token": token, "item": item, "effect": effect,
            "tokens": got, "goal": EVENT_GOAL, "done": done_on is not None,
            "done_on": done_on.isoformat() if done_on else None, "xp": EVENT_XP,
            "rule": f"Jeder Lauf bringt 1 {one}, Läufe ab 10 km bringen 2"}


# --- Trainer-NPC --------------------------------------------------------------------------
TRAINER = "Meister Gorm"
TRAINER_ROLE = "Ausbilder der Läufergilde"
FALLBACK = [
    "Jeder Kilometer ist ein Ziegel in deiner Festung, Held.",
    "Locker laufen ist keine Schwäche – es ist das Fundament.",
    "Die besten Krieger wissen, wann sie ruhen.",
    "Der Deich läuft nicht weg. Du schon – und das ist gut so.",
    "Heute zählt nur eins: aufstehen, Schuhe an, raus.",
    "Konstanz schlägt Heldentaten. Ein Schritt nach dem anderen.",
]


def trainer_quote(ctx: dict, today: date) -> str:
    """Wählt die passendste Botschaft für heute (Priorität von oben nach unten)."""
    name = ctx["class_label"]
    if ctx.get("sick"):
        return f"Krank kämpft niemand gut. Ruh dich aus, {name} – die Gilde wartet auf dich."
    if ctx.get("long_run_yesterday"):
        return f"Gestern {ctx['long_run_yesterday']:.1f} km! Heute gönnst du den Beinen Ruhe oder nur einen lockeren Trab.".replace(".", ",", 1)
    if ctx.get("tired"):
        return "Wenig Schlaf letzte Nacht? Dann heute nur locker – Übermut hat schon manchen Helden gefällt."
    if ctx.get("weak_boss"):
        b = ctx["weak_boss"]
        return f"‚{b['name']}‘ wankt schon! Ziel: {b['goal']}. Gib ihm den Rest."
    if ctx.get("vault_runs_missing"):
        n = ctx["vault_runs_missing"]
        return f"Noch {n} {'Lauf' if n == 1 else 'Läufe'} bis zum nächsten Platz in der Wochentruhe."
    if ctx.get("open_quest"):
        return f"Auf dem Auftragsbrett wartet noch ‚{ctx['open_quest']}‘. Bis Sonntag schaffst du das."
    if ctx.get("rested_full"):
        return "Dein Ruhebonus ist randvoll – das nächste Training zählt doppelt. Nutz es!"
    if ctx.get("event_left"):
        return f"Das {ctx['event_name']} läuft! Noch {ctx['event_left']} {ctx['event_token']} bis zur Belohnung."
    return _rng("trainer", today.isoformat()).choice(FALLBACK)
