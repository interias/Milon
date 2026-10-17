"""Heldenreise: Doppelgänger-Duelle gegen das eigene frühere Ich und Reittiere als Sammlung."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

DUEL_XP = 75


def _twin(runs: pd.DataFrame, r) -> object | None:
    """Ähnlich langer Lauf ~3 Monate vorher (80–100 Tage, Distanz ±20 %), nächste Distanz gewinnt."""
    lo, hi = r.day - timedelta(days=100), r.day - timedelta(days=80)
    cand = runs[(runs["day"] >= lo) & (runs["day"] <= hi)
                & (runs["distance_km"].between(r.distance_km * 0.8, r.distance_km * 1.2))]
    if cand.empty:
        return None
    return cand.loc[(cand["distance_km"] - r.distance_km).abs().idxmin()]


def run_duels(runs: pd.DataFrame, start: date) -> list[dict]:
    out = []
    if runs.empty:
        return out
    for r in runs[runs["day"] >= start].itertuples():
        t = _twin(runs, r)
        if t is None:
            continue
        faster = r.pace < t["pace"]
        ef_ok = pd.isna(r.ef) or pd.isna(t["ef"]) or r.ef > t["ef"]
        out.append({"date": r.day.isoformat(), "km": round(float(r.distance_km), 1), "pace": round(float(r.pace), 2),
                    "ef": None if pd.isna(r.ef) else round(float(r.ef), 2),
                    "twin_date": t["day"].isoformat(), "twin_km": round(float(t["distance_km"]), 1),
                    "twin_pace": round(float(t["pace"]), 2), "twin_ef": None if pd.isna(t["ef"]) else round(float(t["ef"]), 2),
                    "won": bool(faster and ef_ok), "xp": DUEL_XP if faster and ef_ok else 0})
    return out


def _window(runs: pd.DataFrame, end: date, days: int = 28) -> dict | None:
    sub = runs[(runs["day"] > end - timedelta(days=days)) & (runs["day"] <= end)] if not runs.empty else runs
    if sub.empty:
        return None
    return {"km": round(float(sub["distance_km"].sum()), 1), "runs": int(len(sub)),
            "pace": round(float(sub["pace"].mean()), 2),
            "ef": round(float(sub["ef"].mean()), 2) if sub["ef"].notna().any() else None}


def shadow(runs: pd.DataFrame, today: date, back_days: int, label: str) -> dict:
    """Letzte 28 Tage gegen dieselben 28 Tage vor `back_days`."""
    now, then = _window(runs, today), _window(runs, today - timedelta(days=back_days))
    if not now or not then:
        first = runs["day"].min() if not runs.empty else None
        appears = (first + timedelta(days=back_days)).isoformat() if first else None
        return {"label": label, "available": False, "appears": appears}
    metrics = [("km", "Kilometer", True), ("runs", "Läufe", True), ("pace", "Ø Pace", False), ("ef", "Ø Effizienz", True)]
    rows = []
    for key, name, higher in metrics:
        a, b = now[key], then[key]
        better = None if a is None or b is None or a == b else (a > b if higher else a < b)
        rows.append({"key": key, "name": name, "now": a, "then": b, "better": better})
    wins = sum(1 for x in rows if x["better"])
    return {"label": label, "available": True, "rows": rows, "wins": wins, "won": wins >= 3}


# (key, Name, Art, Schwelle, Glyphe)
MOUNTS = [
    ("deichschaf", "Deichschaf", "km", 100, "🐑"),
    ("rheinpony", "Rheinpony", "km", 250, "🐴"),
    ("schlachtross", "Schlachtross von Wesel", "km", 500, "🐎"),
    ("nebelwolf", "Nebelwolf", "km", 750, "🐺"),
    ("greif", "Greif der Zitadelle", "km", 1000, "🦅"),
    ("sturmhirsch", "Sturmhirsch", "km", 1500, "🦌"),
    ("drachling", "Drachling der Lippe", "km", 2000, "🐉"),
    ("phoenix", "Phönix des Niederrheins", "km", 3000, "🔥"),
    ("kriegsbaer", "Kriegsbär", "saetze", 2000, "🐻"),
    ("mammut", "Eisenmammut", "saetze", 5000, "🦣"),
    # Rad-Reittiere: schalten sich über Rad-km (GPS-Fahrten aus Garmin) frei
    ("deichgaul", "Deichgaul", "rad", 100, "🏇"),
    ("auenhengst", "Auenhengst", "rad", 500, "🐎"),
]

MOUNT_KM_PER_LEVEL = 25  # Reittier-Stufe: 1 + gefütterte Rad-km / 25, höchstens 10
MOUNT_MAX_LEVEL = 10
_UNITS = {"km": "km", "saetze": "Arbeitssätze", "rad": "Rad-km"}


def mount_level(km: float) -> int:
    return min(MOUNT_MAX_LEVEL, 1 + int(km // MOUNT_KM_PER_LEVEL))


def ride_feed(rides: list[tuple[date, float]], owner) -> list[dict]:
    """Rad-Fahrten, je dem zur Fahrtzeit gewählten Reittier (`owner(day)` -> Schlüssel oder None) zugeordnet."""
    out = []
    for d, km in sorted(rides, key=lambda r: r[0]):
        key = owner(d)
        if key and km > 0:
            out.append({"date": d.isoformat(), "km": round(float(km), 1), "mount": key})
    return out


def mounts(runs: pd.DataFrame, workouts: pd.DataFrame, chosen: str | None,
           rides: list[tuple[date, float]] | None = None, fed: dict[str, float] | None = None) -> list[dict]:
    """Reittiere mit Freischaltdatum (Tag, an dem die Summe die Schwelle überschritt).

    `rides` = Rad-km je Tag seit Starttag (schaltet Rad-Reittiere frei), `fed` = gefütterte km je Reittier (Stufe)."""
    series = {
        "km": runs.sort_values("started_at")[["day", "distance_km"]].values.tolist() if not runs.empty else [],
        "saetze": workouts.sort_values("started_at")[["day", "sets"]].values.tolist() if not workouts.empty else [],
        "rad": sorted(rides or [], key=lambda r: r[0]),
    }
    fed = fed or {}
    out = []
    for key, name, kind, need, glyph in MOUNTS:
        total, unlocked = 0.0, None
        for d, v in series[kind]:
            total += float(v or 0)
            if unlocked is None and total >= need:
                unlocked = d
        ride_km = round(fed.get(key, 0.0), 1)
        out.append({"key": key, "name": name, "kind": kind, "need": need, "glyph": glyph,
                    "value": round(min(total, need)), "unlocked": unlocked is not None,
                    "unlocked_on": unlocked.isoformat() if unlocked else None, "chosen": key == chosen and unlocked is not None,
                    "unit": _UNITS[kind], "ride_km": ride_km, "level": mount_level(ride_km)})
    return out
