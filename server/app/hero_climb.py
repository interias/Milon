"""Heldenreise: Kletter-Bosse und Traumreiche aus Zwift-Fahrten — ohne gespeicherten Zustand, nie Koordinaten.

Kletter-Bosse sind Gipfel auf der Leiter der kumulierten Zwift-Höhenmeter seit dem Starttag; nach dem
Everest folgt alle weiteren 8.848 Hm eine Wiederholungsrunde. Traumreiche sind die Zwift-Welten und
-Routen aus den Fahrttiteln (Welt/Route-Namen, keine Karte).
"""
from __future__ import annotations

from datetime import date

import pandas as pd

# (key, Name, kumulierte Hm, EP, Beute-Rarität)
PEAKS = [
    ("alpe", "Alpe du Zwift", 1036, 150, "blau"),
    ("ventoux", "Mont Ventoux", 1600, 200, "blau"),
    ("stelvio", "Passo dello Stelvio", 1808, 250, "lila"),
    ("montblanc", "Mont Blanc", 4808, 500, "lila"),
    ("kilimandscharo", "Kilimandscharo", 5895, 750, "orange"),
    ("everest", "Mount Everest", 8848, 1500, "rot"),
]
ROUND_HM = 8848          # jede weitere Runde nach dem Everest
ROUND_XP = 500
ROUND_LOOT = "lila"
MAX_RIDE_HM = 5000.0     # Sanity je Fahrt


def _hm(ride) -> float:
    v = ride.elevation_m
    return float(v) if pd.notna(v) and 0 < float(v) <= MAX_RIDE_HM else 0.0


def climb(indoor: pd.DataFrame, start: date) -> dict:
    """Gipfel-Fortschritt aus den Indoor-Fahrten ab `start`."""
    rides = indoor[indoor["day"] >= start].sort_values("started_at") if indoor is not None and not indoor.empty else None
    reached: dict[str, str] = {}
    cum = 0.0
    rounds: list[dict] = []
    if rides is not None:
        for r in rides.itertuples():
            before, cum = cum, cum + _hm(r)
            for key, _name, hm, _xp, _loot in PEAKS:
                if key not in reached and before < hm <= cum:
                    reached[key] = r.day.isoformat()
            # Wiederholungsrunden: Everest + n × 8.848 Hm
            n = len(rounds) + 1
            while PEAKS[-1][2] + n * ROUND_HM <= cum:
                rounds.append({"n": n + 1, "name": f"Mount Everest · Runde {n + 1}", "hm": PEAKS[-1][2] + n * ROUND_HM,
                               "reached_on": r.day.isoformat(), "xp": ROUND_XP, "loot": ROUND_LOOT, "reached": True})
                n += 1
    peaks, nxt = [], None
    prev = 0
    for key, name, hm, xp, loot in PEAKS:
        done = key in reached
        item = {"key": key, "name": name, "hm": hm, "xp": xp, "loot": loot, "reached": done,
                "reached_on": reached.get(key), "progress": round(min(1.0, max(0.0, (cum - prev) / (hm - prev))), 3)}
        if not done and nxt is None:
            nxt = item
        peaks.append(item)
        prev = hm
    if nxt is None:  # Everest geschafft → nächste Wiederholungsrunde
        n = len(rounds) + 2
        base = PEAKS[-1][2] + (n - 1) * ROUND_HM
        nxt = {"key": f"runde{n}", "name": f"Mount Everest · Runde {n}", "hm": base, "xp": ROUND_XP, "loot": ROUND_LOOT,
               "reached": False, "reached_on": None,
               "progress": round(min(1.0, max(0.0, (cum - (base - ROUND_HM)) / ROUND_HM)), 3)}
    return {"total_hm": round(cum), "peaks": peaks, "rounds": rounds, "next": nxt,
            "next_in_hm": max(0, round(nxt["hm"] - cum)), "rides": int(len(rides)) if rides is not None else 0}


def events(c: dict) -> list[dict]:
    """Erreichte Gipfel und Runden als Ereignisse (Datum, EP, Beute) für EP-Buch, Log und Beute."""
    out = [{"id": p["key"], "name": p["name"], "hm": p["hm"], "date": p["reached_on"], "xp": p["xp"], "loot": p["loot"]}
           for p in c["peaks"] if p["reached"]]
    out += [{"id": f"runde{r['n']}", "name": r["name"], "hm": r["hm"], "date": r["reached_on"], "xp": r["xp"], "loot": r["loot"]}
            for r in c["rounds"]]
    return sorted(out, key=lambda e: (e["date"], e["hm"]))
