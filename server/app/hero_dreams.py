"""Heldenreise: Traumreiche — Zwift-Welten und -Routen aus den Fahrttiteln, ohne Karte und ohne Koordinaten."""
from __future__ import annotations

import pandas as pd

# Bekannte Zwift-Welten (kanonische Schreibweise); „alle Welten“ = diese Liste.
KNOWN_WORLDS = ["Watopia", "London", "New York", "Innsbruck", "Richmond", "Yorkshire", "France", "Paris",
                "Makuri Islands", "Scotland", "Crit City"]
_ALIASES = {"new york city": "New York", "nyc": "New York", "makuri": "Makuri Islands", "makuri island": "Makuri Islands",
            "critcity": "Crit City", "crit-city": "Crit City"}
_BY_FOLD = {w.casefold(): w for w in KNOWN_WORLDS}
ROUND_TIERS = (5, 10, 25)                                # verschiedene Routen in einer Welt
HM_TIERS = (1000, 5000, 10000, 25000, 50000, 100000)     # Zwift-Höhenmeter insgesamt


def canon_world(world) -> str | None:
    """Welt-Name tolerant auf die kanonische Schreibweise abbilden; Unbekanntes bleibt wie geschrieben."""
    if world is None or (isinstance(world, float) and pd.isna(world)):
        return None
    name = " ".join(str(world).split())
    if not name:
        return None
    fold = name.casefold()
    return _BY_FOLD.get(fold) or _ALIASES.get(fold) or name


def _route_key(route) -> str | None:
    if route is None or (isinstance(route, float) and pd.isna(route)):
        return None
    key = " ".join(str(route).split()).casefold()
    return key or None


def dreams(rides: pd.DataFrame | None = None) -> dict:
    """Welten/Routen über die gesamte Zwift-Historie (Spalten `world`, `route`, `day`, `distance_km`, `elevation_gain_m`)."""
    if rides is None:
        from .metrics import cycling
        rides = cycling.indoor_rides()
    worlds: dict[str, dict] = {}
    total_hm = 0.0
    if rides is not None and not rides.empty:
        for r in rides.itertuples():
            hm = float(r.elevation_gain_m) if pd.notna(r.elevation_gain_m) and 0 < float(r.elevation_gain_m) <= 5000 else 0.0
            total_hm += hm
            w = canon_world(r.world)
            if w is None:
                continue
            row = worlds.setdefault(w, {"world": w, "known": w in KNOWN_WORLDS, "rides": 0, "routes": {}, "km": 0.0, "hm": 0.0,
                                        "first_on": r.day.isoformat(), "last_on": r.day.isoformat()})
            row["rides"] += 1
            row["km"] += float(r.distance_km) if pd.notna(r.distance_km) else 0.0
            row["hm"] += hm
            row["first_on"] = min(row["first_on"], r.day.isoformat())
            row["last_on"] = max(row["last_on"], r.day.isoformat())
            key = _route_key(getattr(r, "route", None))
            if key:
                shown = " ".join(str(r.route).split())
                row["routes"].setdefault(key, {"route": shown, "rides": 0})["rides"] += 1
    out = []
    for w in worlds.values():
        routes = sorted(w["routes"].values(), key=lambda x: (-x["rides"], x["route"]))
        out.append({**w, "km": round(w["km"], 1), "hm": round(w["hm"]), "route_count": len(routes), "routes": routes[:12]})
    out.sort(key=lambda w: (not w["known"], -w["rides"], w["world"]))
    visited_known = sum(1 for w in out if w["known"])
    return {"worlds": out, "known": KNOWN_WORLDS, "visited_known": visited_known, "known_total": len(KNOWN_WORLDS),
            "all_worlds": visited_known >= len(KNOWN_WORLDS), "total_hm": round(total_hm),
            "best_routes": max((w["route_count"] for w in out), default=0),
            "route_tiers": list(ROUND_TIERS),
            "hm_tiers": [{"hm": t, "reached": total_hm >= t} for t in HM_TIERS]}


def timeline(rides: pd.DataFrame) -> dict:
    """Chronik für Erfolge: erster Besuch je Welt, Tage neuer Routen je Welt, Zwift-Hm kumuliert je Fahrt."""
    first: dict[str, str] = {}
    routes: dict[str, dict[str, str]] = {}
    cum, hm_steps = 0.0, []
    if rides is not None and not rides.empty:
        for r in rides.sort_values("started_at").itertuples():
            hm = float(r.elevation_gain_m) if pd.notna(r.elevation_gain_m) and 0 < float(r.elevation_gain_m) <= 5000 else 0.0
            cum += hm
            hm_steps.append((cum, r.day.isoformat()))
            w = canon_world(r.world)
            if w is None:
                continue
            first.setdefault(w, r.day.isoformat())
            key = _route_key(getattr(r, "route", None))
            if key:
                routes.setdefault(w, {}).setdefault(key, r.day.isoformat())
    return {"first": first, "routes": {w: sorted(d.values()) for w, d in routes.items()}, "hm": hm_steps}
