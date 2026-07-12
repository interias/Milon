"""Lauf-Achievements im MMORPG-/WoW-Loot-Stil: sammelbare Trophäen mit Punkten, Seltenheit,
Läufer-Level & Fortschritt.

Alle Erfolge werden LIVE aus den Daten berechnet (Läufe, Best-Effort-Splits, Wochenvolumen,
Cross-Domain, Kalender), aktualisieren sich also automatisch nach jedem Import. Jeder Erfolg hat
Punkte (Schwierigkeit) → daraus die WoW-Seltenheit (grau→weiß→grün→blau→lila→orange→rot;
orange = Legendär, rot = Artefakt/quasi unerreichbar). Nicht erreichte Erfolge zeigen einen
Fortschrittsbalken. Architektur: deklarative Specs + Runner mit per-Erfolg-Fehlerschutz — ein
einzelner defekter Evaluator sperrt nur seinen Erfolg, nie den ganzen Endpoint.

Optionale Lore (Icon + Flavor-Text „Symbolik") kommt aus achievements_lore.LORE (falls vorhanden).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd

from . import running

log = logging.getLogger(__name__)

try:
    from .achievements_lore import LORE  # {id: {"icon": str, "flavor": str}}
except Exception:  # noqa: BLE001
    LORE = {}

# --- Seltenheit (WoW-Loot). Ableitung aus den Punkten; rot = Artefakt (quasi unerreichbar). ---
RARITIES = ["grau", "weiss", "gruen", "blau", "lila", "orange", "rot"]
RARITY_LABEL = {
    "grau": "Schrott", "weiss": "Gewöhnlich", "gruen": "Ungewöhnlich", "blau": "Selten",
    "lila": "Episch", "orange": "Legendär", "rot": "Artefakt",
}


def _rarity(points: int) -> str:
    if points <= 10:
        return "grau"
    if points <= 20:
        return "weiss"
    if points <= 40:
        return "gruen"
    if points <= 75:
        return "blau"
    if points <= 149:
        return "lila"
    if points <= 249:
        return "orange"
    return "rot"


# Läufer-Level nach Gesamtpunkten (Untergrenze, Titel) — auf das größere Punktevolumen skaliert.
_LEVELS = [
    (0, "Frischling"), (200, "Einsteiger"), (500, "Läufer"), (1000, "Ambitioniert"),
    (1800, "Wettkämpfer"), (2800, "Halbprofi"), (4000, "Routinier"), (5500, "Elite"),
    (7500, "Meister"), (10000, "Champion"), (13000, "Legende"), (16500, "Mythos"),
]


def _level(points: int) -> dict:
    idx = 0
    for i, (floor, _) in enumerate(_LEVELS):
        if points >= floor:
            idx = i
    floor, title = _LEVELS[idx]
    nxt = _LEVELS[idx + 1][0] if idx + 1 < len(_LEVELS) else None
    span = (nxt - floor) if nxt else 1
    return {
        "level": idx + 1, "title": title, "floor": floor, "next_points": nxt,
        "to_next": (nxt - points) if nxt else 0,
        "progress": round((points - floor) / span, 3) if nxt else 1.0,
    }


# --- Ergebnis-Helfer: jede Evaluator-Funktion gibt (earned, date, progress, plabel) zurück. ---
def R(earned, date_=None, progress=0.0, plabel=None):
    return (bool(earned), date_, float(min(1.0, max(0.0, progress))), plabel)


def _mmss(sec: float | None) -> str:
    if sec is None:
        return "—"
    s = int(round(sec))
    return f"{s // 60}:{s % 60:02d}"


def _iso(d) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def _season(m: int) -> str:
    return ("Winter" if m in (12, 1, 2) else "Frühling" if m in (3, 4, 5)
            else "Sommer" if m in (6, 7, 8) else "Herbst")


def _pr_events(sub: pd.DataFrame, value_col: str, better="max"):
    """Zählt „neue Rekord"-Ereignisse (streng besser als alle vorher) chronologisch.
    Gibt (anzahl_events, datum_des_2ten_events) — das 2. Event = erstmals einen Rekord GEBROCHEN."""
    sub = sub.sort_values("started_at")
    best = None
    events = []
    for _, r in sub.iterrows():
        v = r[value_col]
        if pd.isna(v):
            continue
        if best is None or (v > best if better == "max" else v < best):
            best = v
            events.append(r["started_at"])
    second = events[1].date().isoformat() if len(events) >= 2 else None
    return len(events), second


def _longest_run(sorted_periods, step_days):
    """Längste Kette aufeinanderfolgender Perioden (Abstand == step_days)."""
    longest = cur = 0
    prev = None
    for d in sorted_periods:
        cur = cur + 1 if (prev is not None and (d - prev).days == step_days) else 1
        longest = max(longest, cur)
        prev = d
    return longest


def _build_context() -> SimpleNamespace:
    runs = running._runs()
    c = SimpleNamespace(runs=runs, empty=runs.empty)
    if runs.empty:
        return c
    runs = runs.sort_values("started_at").copy()
    runs["dte"] = runs["started_at"].dt.date
    runs["hour"] = runs["started_at"].dt.hour
    runs["minute"] = runs["started_at"].dt.minute
    runs["wd"] = runs["started_at"].dt.weekday
    runs["month"] = runs["started_at"].dt.month
    runs["day"] = runs["started_at"].dt.day
    runs["year"] = runs["started_at"].dt.year
    iso = runs["started_at"].dt.isocalendar()
    runs["iso_year"] = iso["year"].astype(int).values
    runs["iso_week"] = iso["week"].astype(int).values
    runs["season"] = runs["month"].map(_season)
    runs["cum_km"] = runs["distance_km"].cumsum()
    runs["cum_min"] = runs["dur_min"].cumsum()
    c.runs = runs
    c.n_runs = int(len(runs))
    c.total_km = float(runs["distance_km"].sum())
    c.total_min = float(runs["dur_min"].sum())
    c.maxdist = float(runs["distance_km"].max())
    c.maxdur = float(runs["dur_min"].max())
    c.maxef = float(runs["ef"].max()) if runs["ef"].notna().any() else None

    # Best-Efforts
    try:
        c.be = running._read("SELECT distance_m, seconds, started_at FROM run_best_efforts",
                             parse_dates=["started_at"])
    except Exception:  # noqa: BLE001
        c.be = pd.DataFrame(columns=["distance_m", "seconds", "started_at"])

    # Wochen-Aggregate
    weeks: dict[tuple, dict] = {}
    for r in runs.itertuples():
        k = (r.iso_year, r.iso_week)
        w = weeks.setdefault(k, {"km": 0.0, "runs": 0, "dur": 0.0, "wd": set(), "hr": [],
                                 "start": None})
        w["km"] += r.distance_km
        w["runs"] += 1
        w["dur"] += r.dur_min
        w["wd"].add(r.wd)
        if pd.notna(r.avg_hr):
            w["hr"].append(r.avg_hr)
    # Wochen-Startdatum (Montag der ISO-Woche)
    for (iy, iw), w in weeks.items():
        try:
            w["start"] = date.fromisocalendar(iy, iw, 1)
        except Exception:  # noqa: BLE001
            w["start"] = None
    c.weeks = weeks
    c.max_week_km = max((w["km"] for w in weeks.values()), default=0.0)
    c.max_week_dur = max((w["dur"] for w in weeks.values()), default=0.0)
    c.max_week_runs = max((w["runs"] for w in weeks.values()), default=0)
    c.max_week_wdays = max((len(w["wd"]) for w in weeks.values()), default=0)

    def _hr_zone(h):
        return 0 if h < 130 else 1 if h < 140 else 2 if h < 150 else 3
    c.max_week_zones = max((len({_hr_zone(h) for h in w["hr"]}) for w in weeks.values() if w["hr"]),
                           default=0)

    # Tage / Streaks
    day_dates = sorted(set(runs["dte"]))
    c.day_dates = day_dates
    c.distinct_days = len(day_dates)
    c.longest_day_streak = _longest_run(day_dates, 1)
    week_starts = sorted(w["start"] for w in weeks.values() if w["start"])
    c.longest_week_streak = _longest_run(week_starts, 7)
    c.distinct_weeks = len(weeks)

    # Monate / Jahre
    mk = runs.groupby(["year", "month"])["distance_km"].sum()
    c.month_km = mk
    months_sorted = sorted(mk.index.tolist())
    c.months_sorted = months_sorted
    c.month_first = [date(y, m, 1) for (y, m) in months_sorted]
    # Monats-Streak (aufeinanderfolgende Kalendermonate)
    longest_m = cur = 0
    prev = None
    for (y, m) in months_sorted:
        cur = cur + 1 if (prev is not None and ((y - prev[0]) * 12 + (m - prev[1]) == 1)) else 1
        longest_m = max(longest_m, cur)
        prev = (y, m)
    c.longest_month_streak = longest_m
    c.year_km = runs.groupby("year")["distance_km"].sum()
    c.distinct_month_numbers = set(runs["month"].unique().tolist())
    c.distinct_weekdays = set(runs["wd"].unique().tolist())
    c.distinct_seasons = set(runs["season"].unique().tolist())

    # Cross-Domain: alle Sessions
    try:
        alls = running._read(
            "SELECT exercise_type, started_at, ended_at, distance_km FROM exercise_sessions",
            parse_dates=["started_at", "ended_at"])
        alls = alls[alls["started_at"].notna()].copy()
        alls["dte"] = alls["started_at"].dt.date
        c.run_days = set(alls[alls["exercise_type"] == 33]["dte"])
        c.strength_days = set(alls[alls["exercise_type"] == 45]["dte"])
        c.bike_days = set(alls[alls["exercise_type"] == 4]["dte"])
        c.sessions_per_day = alls.groupby("dte").size()
        iso2 = alls["started_at"].dt.isocalendar()
        alls["wk"] = list(zip(iso2["year"].astype(int), iso2["week"].astype(int)))
        c.types_per_week = alls.groupby("wk")["exercise_type"].apply(lambda s: set(s.tolist()))
        c.treadmill_km = float(alls[alls["exercise_type"] == 58]["distance_km"].fillna(0).sum())
    except Exception:  # noqa: BLE001
        c.run_days = set(runs["dte"]); c.strength_days = set(); c.bike_days = set()
        c.sessions_per_day = pd.Series(dtype=int); c.types_per_week = pd.Series(dtype=object)
        c.treadmill_km = 0.0

    # Schritte je Woche
    try:
        st = running._read("SELECT day, steps FROM steps_daily", parse_dates=["day"])
        if not st.empty:
            iso3 = st["day"].dt.isocalendar()
            st["wk"] = list(zip(iso3["year"].astype(int), iso3["week"].astype(int)))
            c.steps_week = st.groupby("wk")["steps"].sum()
        else:
            c.steps_week = pd.Series(dtype=int)
    except Exception:  # noqa: BLE001
        c.steps_week = pd.Series(dtype=int)

    return c


def _rarity_dot(pts):
    return _rarity(pts)


def evaluate() -> dict:
    c = _build_context()
    specs = _specs()
    ach: list[dict] = []

    if c.empty:
        # Alle als gesperrt (0 %) ausgeben, damit die Sammlung sichtbar bleibt.
        for sp in specs:
            if sp[0] == "__meta__":
                continue
            id_, cat, name, desc, pts, icon, _fn = sp
            ach.append(_mk(id_, cat, name, desc, pts, icon, R(False, None, 0.0, None)))
        return _finish(ach)

    # 1) Alle Nicht-Meta-Erfolge sicher auswerten
    for sp in specs:
        if sp[0] == "__meta__":
            continue
        id_, cat, name, desc, pts, icon, fn = sp
        try:
            res = fn(c)
        except Exception as e:  # noqa: BLE001
            log.warning("Achievement %s fehlgeschlagen: %s", id_, e)
            res = R(False, None, 0.0, None)
        ach.append(_mk(id_, cat, name, desc, pts, icon, res))

    # 2) Meta-Erfolge auf Basis der bereits ausgewerteten Erfolge
    for id_, cat, name, desc, pts, icon, fn in _meta_specs():
        try:
            res = fn(ach)
        except Exception as e:  # noqa: BLE001
            log.warning("Meta-Achievement %s fehlgeschlagen: %s", id_, e)
            res = R(False, None, 0.0, None)
        ach.append(_mk(id_, cat, name, desc, pts, icon, res))

    # Completionist: alle ANDEREN Erfolge erreicht (nach vollständigem Bau berechnet)
    comp = next((a for a in ach if a["id"] == "meta_complete"), None)
    if comp is not None:
        others = [a for a in ach if a["id"] != "meta_complete"]
        done = sum(1 for a in others if a["earned"])
        comp["earned"] = done == len(others)
        comp["progress"] = round(done / len(others), 3) if others else 0.0
        comp["progress_label"] = f"{done} / {len(others)} Erfolge"

    return _finish(ach)


def _mk(id_, cat, name, desc, pts, icon, res) -> dict:
    earned, date_, progress, plabel = res
    lore = LORE.get(id_, {})
    return {
        "id": id_, "category": cat, "name": name, "desc": desc, "points": pts,
        "icon": lore.get("icon") or icon, "rarity": _rarity(pts),
        "rarity_label": RARITY_LABEL[_rarity(pts)],
        "flavor": lore.get("flavor", ""),
        "earned": bool(earned), "earned_date": date_,
        "progress": round(min(1.0, max(0.0, progress)), 3), "progress_label": plabel,
    }


def _finish(ach: list[dict]) -> dict:
    earned = [a for a in ach if a["earned"]]
    points = sum(a["points"] for a in earned)
    rarity_counts = {r: {"earned": 0, "total": 0} for r in RARITIES}
    for a in ach:
        rarity_counts[a["rarity"]]["total"] += 1
        if a["earned"]:
            rarity_counts[a["rarity"]]["earned"] += 1
    return {
        "achievements": ach,
        "summary": {
            "points": points,
            "points_possible": sum(a["points"] for a in ach),
            "earned": len(earned),
            "total": len(ach),
            "rarity_counts": rarity_counts,
            **_level(points),
        },
    }


# =========================================================================================
#  Evaluator-Helfer (nutzen ctx `c`)
# =========================================================================================
def _run_reach(c, col, target, unit, fmt="{:.1f}"):
    q = c.runs[c.runs[col] >= target]
    best = float(c.runs[col].max())
    if len(q):
        return R(True, q.iloc[0]["dte"].isoformat(), 1.0, None)
    return R(False, None, best / target, f"best {fmt.format(best)} / {target:g} {unit}")


def _count_reach(c, mask, target, noun="Läufe"):
    q = c.runs[mask]
    cnt = int(len(q))
    if cnt >= target:
        return R(True, q.iloc[target - 1]["dte"].isoformat(), 1.0, None)
    return R(False, None, cnt / target, f"{cnt} / {target} {noun}")


def _cum_reach(c, col, total, target, unit, fmt="{:.0f}"):
    if total >= target:
        crossed = c.runs[c.runs[col] >= target]
        d = crossed.iloc[0]["dte"].isoformat() if len(crossed) else None
        return R(True, d, 1.0, None)
    return R(False, None, total / target, f"{fmt.format(total)} / {target:g} {unit}")


def _distinct_reach(c, count, target, noun):
    if count >= target:
        return R(True, None, 1.0, None)
    return R(False, None, count / target, f"{count} / {target} {noun}")


def _streak_reach(longest, target, noun="Wochen"):
    if longest >= target:
        return R(True, None, 1.0, None)
    return R(False, None, longest / target, f"best {longest} / {target} {noun}")


def _split_under(c, dist_m, thr_sec, dl):
    sub = c.be[c.be["distance_m"] == dist_m] if not c.be.empty else c.be
    best = float(sub["seconds"].min()) if not sub.empty else None
    if best is not None and best <= thr_sec:
        first = sub[sub["seconds"] <= thr_sec].sort_values("started_at").iloc[0]
        return R(True, first["started_at"].date().isoformat(), 1.0, None)
    prog = (thr_sec / best) if best else 0.0
    return R(False, None, prog, f"best {_mmss(best)} / {_mmss(thr_sec)} · {dl}")


def _date_match(c, pred, label):
    q = c.runs[c.runs.apply(lambda r: pred(r), axis=1)]
    if len(q):
        return R(True, q.iloc[0]["dte"].isoformat(), 1.0, None)
    return R(False, None, 0.0, label)


def _weekly_reach(c, key, target, unit, fmt="{:.0f}"):
    cur = {"km": c.max_week_km, "dur": c.max_week_dur, "runs": c.max_week_runs,
           "wdays": c.max_week_wdays}[key]
    if cur >= target:
        # frühestes Wochen-Startdatum, das die Schwelle erfüllt
        d = None
        for w in sorted((w for w in c.weeks.values() if w["start"]), key=lambda x: x["start"]):
            val = {"km": w["km"], "dur": w["dur"], "runs": w["runs"], "wdays": len(w["wd"])}[key]
            if val >= target:
                d = w["start"].isoformat(); break
        return R(True, d, 1.0, None)
    return R(False, None, cur / target, f"best {fmt.format(cur)} / {target:g} {unit}")


# =========================================================================================
#  Easter / Feiertage / Astronomie (reine Datumslogik, keine neue Datenquelle)
# =========================================================================================
def _easter(year: int) -> date:
    a = year % 19
    b, cc = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(cc, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month = (h + ll - 7 * m + 114) // 31
    day = ((h + ll - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _is_holiday_de(d: date) -> bool:
    fixed = {(1, 1), (5, 1), (10, 3), (12, 25), (12, 26)}
    if (d.month, d.day) in fixed:
        return True
    e = _easter(d.year)
    for off in (-2, 1, 39, 50):  # Karfreitag, Ostermontag, Christi Himmelfahrt, Pfingstmontag
        if d == e + timedelta(days=off):
            return True
    return False


def _is_full_moon(d: date) -> bool:
    # Näherung (Conway): synodischer Monat 29,53 Tage; Vollmond ~ Tag 14-15 des Zyklus.
    ref = date(2000, 1, 6)  # Neumond
    days = (d - ref).days
    phase = days % 29.53059
    return 13.0 <= phase <= 16.0


# =========================================================================================
#  Spec-Tabelle: (id, category, name, desc, points, icon, fn(c)->R)
# =========================================================================================
def _specs():
    S = []
    a = S.append

    # ---------------- DISTANZ (Einzellauf) ----------------
    for km, name, pts, icon, iid in [
        (5, "5-km-Läufer", 10, "🏃", "dist_5"), (10, "Zweistellig", 20, "🏃", "dist_10"),
        (15, "15 am Stück", 35, "🏃", "dist_15"), (16.09, "10-Meilen-Lauf", 30, "🏃", "dist_16"),
        (20, "20er-Klub", 50, "🥾", "dist_20"), (21.0975, "Halbmarathon", 75, "🎽", "dist_hm"),
        (25, "Ultra-Vorbote", 100, "🥾", "dist_25"), (30, "30-km-Grenze", 140, "⛰️", "dist_30"),
        (35, "Ultra-Einstieg", 150, "⛰️", "dist_35"), (42.195, "Marathon", 250, "🏅", "dist_marathon"),
        (50, "Ultramarathon", 250, "🏔️", "dist_50"), (80.5, "50-Meilen-Ultra", 400, "🗻", "dist_80"),
    ]:
        a((iid, "distanz", name, f"Ein Lauf über {km:g} km", pts, icon,
           (lambda km: lambda c: _run_reach(c, "distance_km", km, "km"))(km)))
    a(("dist_pr", "distanz", "Neue Bestweite", "Die bisher längste Einzeldistanz übertreffen (wiederholbar)",
       20, "📏", lambda c: _pr_generic(c, "distance_km", "max")))
    a(("dist_round", "distanz", "Rundzahl-Lauf", "Lauf mit exakter Rundzahl-Distanz (5/10/15/20,00 km ±0,02)",
       25, "🎯", lambda c: _date_match(c, lambda r: any(abs(r["distance_km"] - t) <= 0.02 for t in (5, 10, 15, 20)), "keine Rundzahl bisher")))
    a(("dist_hm5", "distanz", "Halbmarathon-Sammler", "5 Läufe über je 21,1 km", 100, "🎽",
       lambda c: _count_reach(c, c.runs["distance_km"] >= 21.0975, 5)))
    a(("dist_hm10", "distanz", "Halbmarathon-Veteran", "10 Läufe über je 21,1 km", 150, "🎽",
       lambda c: _count_reach(c, c.runs["distance_km"] >= 21.0975, 10)))
    a(("dist_m3", "distanz", "Marathon-Club", "3 Läufe über je 42,2 km", 300, "🏅",
       lambda c: _count_reach(c, c.runs["distance_km"] >= 42.195, 3)))

    # ---------------- DAUER ----------------
    a(("dur_90", "dauer", "Dauerbrenner", "Ein Lauf über 90 Minuten", 40, "⏱️",
       lambda c: _run_reach(c, "dur_min", 90, "min", "{:.0f}")))
    a(("dur_120", "dauer", "2-Stunden-Läufer", "Ein Lauf über 2 Stunden", 75, "⏱️",
       lambda c: _run_reach(c, "dur_min", 120, "min", "{:.0f}")))
    a(("dur_180", "dauer", "3-Stunden-Marsch", "Ein Lauf über 3 Stunden", 150, "⏱️",
       lambda c: _run_reach(c, "dur_min", 180, "min", "{:.0f}")))
    a(("dur_round", "dauer", "Runde Dauer", "Lauf exakt 45:00 oder 60:00 lang (±5 s)", 25, "🕰️",
       lambda c: _date_match(c, lambda r: any(abs(r["dur_min"] * 60 - t) <= 5 for t in (2700, 3600)), "noch keine runde Dauer")))

    # ---------------- GESAMTDISTANZ (kumuliert) ----------------
    for km, pts, iid in [(25, 10, "total_25"), (50, 20, "total_50"), (100, 35, "total_100"),
                         (250, 75, "total_250"), (500, 150, "total_500"), (1000, 300, "total_1000"),
                         (2000, 600, "total_2000"), (3000, 300, "total_3000"), (5000, 400, "total_5000"),
                         (10000, 600, "total_10000")]:
        a((iid, "kumulativ", f"{km:g} km gesamt", f"Insgesamt {km:g} km erlaufen", pts, "🌍",
           (lambda km: lambda c: _cum_reach(c, "cum_km", c.total_km, km, "km"))(km)))
    a(("total_marathons25", "kumulativ", "Marathon-Äquivalente", "Kumuliert 25 Marathons (~1.055 km) gelaufen",
       60, "🏅", lambda c: _cum_reach(c, "cum_km", c.total_km, 25 * 42.195, "km")))
    a(("tm_100", "kumulativ", "Laufband-Kilometer I", "100 km auf dem Laufband", 30, "🏃",
       lambda c: R(c.treadmill_km >= 100, None, c.treadmill_km / 100, f"{c.treadmill_km:.0f} / 100 km")))
    a(("tm_250", "kumulativ", "Laufband-Kilometer II", "250 km auf dem Laufband", 60, "🏃",
       lambda c: R(c.treadmill_km >= 250, None, c.treadmill_km / 250, f"{c.treadmill_km:.0f} / 250 km")))

    # kumulierte Laufzeit (Stunden)
    for h, pts, iid in [(24, 20, "hrs_24"), (50, 40, "hrs_50"), (100, 150, "hrs_100"), (200, 250, "hrs_200")]:
        a((iid, "kumulativ", f"{h} Stunden gelaufen", f"Kumulierte Laufzeit von {h} Stunden", pts, "⌛",
           (lambda h: lambda c: _cum_hours(c, h))(h)))

    # Lauf-Tage / Wochen (distinct)
    for n, pts, iid in [(100, 40, "days_100"), (200, 60, "days_200"), (365, 150, "days_365")]:
        a((iid, "kumulativ", f"{n} Lauf-Tage", f"{n} verschiedene Kalendertage mit Lauf", pts, "📆",
           (lambda n: lambda c: _distinct_reach(c, c.distinct_days, n, "Tage"))(n)))
    a(("weeks_100", "kumulativ", "Ewiger Kalender-Streifen", "100 verschiedene Kalenderwochen mit Lauf", 40, "🗓️",
       lambda c: _distinct_reach(c, c.distinct_weeks, 100, "Wochen")))
    a(("month_record", "kumulativ", "Monats-Rekordmonat", "Ein Kalendermonat mit neuer Höchst-Distanz", 40, "📈",
       lambda c: _month_record(c)))

    # ---------------- WOCHENVOLUMEN ----------------
    for km, pts, iid in [(20, 15, "wkm_20"), (30, 25, "wkm_30"), (40, 50, "wkm_40"), (50, 85, "wkm_50"),
                         (75, 160, "wkm_75"), (100, 200, "wkm_100")]:
        a((iid, "wochenvolumen", f"{km} km / Woche", f"{km} km in einer Kalenderwoche", pts, "📊",
           (lambda km: lambda c: _weekly_reach(c, "km", km, "km"))(km)))
    a(("wdur_5h", "wochenvolumen", "Ausdauer-Woche", "5 Stunden Laufdauer in einer Woche", 60, "⏳",
       lambda c: _weekly_reach(c, "dur", 300, "min", "{:.0f}")))
    a(("wallround", "wochenvolumen", "Wochen-Allrounder", "An 5 verschiedenen Wochentagen einer Woche gelaufen",
       50, "🔀", lambda c: _weekly_reach(c, "wdays", 5, "Tage", "{:.0f}")))
    a(("wdbl_long", "wochenvolumen", "Wochen-Doppel-Langlauf", "2 Läufe je ≥15 km, zusammen ≥42,2 km in einer Woche",
       80, "👣", lambda c: _week_double_long(c)))

    # ---------------- LÄUFE / HÄUFIGKEIT ----------------
    for n, pts, name, iid in [(1, 5, "Der erste Schritt", "cnt_1"), (10, 15, "Angefixt", "cnt_10"),
                              (25, 30, "Stammläufer", "cnt_25"), (50, 60, "Halbhundert", "cnt_50"),
                              (100, 120, "Hundertfach", "cnt_100"), (250, 250, "Besessen", "cnt_250")]:
        a((iid, "volumen", name, f"{n} Läufe absolvieren", pts, "🔢",
           (lambda n: lambda c: _count_reach(c, c.runs["distance_km"] >= 0, n))(n)))
    for r, pts, name, iid in [(3, 15, "Dreimal die Woche", "wrun_3"), (4, 30, "Viermal die Woche", "wrun_4"),
                              (5, 60, "Fünfmal die Woche", "wrun_5")]:
        a((iid, "volumen", name, f"{r} Läufe in einer Woche", pts, "🗓️",
           (lambda r: lambda c: _weekly_reach(c, "runs", r, "Läufe", "{:.0f}"))(r)))

    # ---------------- TEMPO (Best-Effort-Schwellen) ----------------
    for thr, name, pts, iid in [(360, "Flott", 15, "spd1_360"), (330, "Zügig", 30, "spd1_330"),
                                (300, "Schnell", 60, "spd1_300"), (270, "Rakete", 120, "spd1_270")]:
        a((iid, "tempo", name, f"1 km unter {_mmss(thr)} / km", pts, "⚡",
           (lambda t: lambda c: _split_under(c, 1000, t, "1 km"))(thr)))
    for thr, name, pts, iid in [(1800, "5k unter 30", 25, "spd5_1800"), (1650, "5k unter 27:30", 55, "spd5_1650"),
                                (1500, "5k unter 25", 110, "spd5_1500")]:
        a((iid, "tempo", name, f"5 km unter {_mmss(thr)}", pts, "⚡",
           (lambda t: lambda c: _split_under(c, 5000, t, "5 km"))(thr)))
    for thr, name, pts, iid in [(3600, "10k unter 60", 40, "spd10_3600"), (3300, "10k unter 55", 85, "spd10_3300"),
                                (3000, "10k unter 50", 170, "spd10_3000")]:
        a((iid, "tempo", name, f"10 km unter {_mmss(thr)}", pts, "⚡",
           (lambda t: lambda c: _split_under(c, 10000, t, "10 km"))(thr)))
    a(("spd15", "tempo", "15-km-Tempoläufer", "Best-Effort 15 km unter 1:30:00", 50, "⚡",
       lambda c: _split_under(c, 15000, 5400, "15 km")))
    a(("spd20", "tempo", "20-km-Tempoläufer", "Best-Effort 20 km unter 2:00:00", 75, "⚡",
       lambda c: _split_under(c, 20000, 7200, "20 km")))
    a(("pr_broken", "tempo", "Bestzeit gebrochen", "Einen All-Time-Best auf einer Distanz verbessern", 40, "⏲️",
       lambda c: _be_pr(c)))
    a(("pr_trophyroom", "tempo", "Trophäenschrank der Distanzen", "Für alle 5 Best-Effort-Distanzen einen Eintrag haben",
       50, "🗄️", lambda c: _distinct_reach(c, int(c.be["distance_m"].nunique()) if not c.be.empty else 0, 5, "Distanzen")))
    a(("attack", "tempo", "Attacke im Feld", "Schnellster 1 km ≥30 % schneller als die Gesamt-Pace des Laufs", 30, "💨",
       lambda c: _attack(c)))
    a(("even_month", "tempo", "Eiserne Konstanz", "Alle Läufe (≥3 km) eines Monats ±10 s/km um die Monats-Pace", 35, "📏",
       lambda c: _even_month(c)))
    a(("month_king", "tempo", "Monatskönig", "Schnellster Lauf (≥5 km) eines Kalendermonats", 15, "👑",
       lambda c: R(len(c.runs[c.runs["distance_km"] >= 5]) > 0, None,
                   1.0 if len(c.runs[c.runs["distance_km"] >= 5]) else 0.0, None)))

    # ---------------- HERZFREQUENZ ----------------
    a(("hr_iron", "herzfrequenz", "Eisernes Herz", "Lauf ≥10 km mit Ø-HF unter 140 bpm", 40, "❤️",
       lambda c: _hr_combo(c, 10, 140, "≥10 km <140")))
    a(("hr_steel", "herzfrequenz", "Stahlpuls", "Lauf ≥5 km mit Ø-HF unter 130 bpm", 50, "❤️",
       lambda c: _hr_combo(c, 5, 130, "≥5 km <130")))
    a(("hr_giant", "herzfrequenz", "Der Ruhige Riese", "≥21 km mit Ø-HF unter 150 bpm", 100, "❤️",
       lambda c: _hr_combo(c, 21, 150, "≥21 km <150")))
    a(("hr_zoneweek", "herzfrequenz", "Zonen-Woche", "In einer Woche je ein Lauf <130 / 130–139 / 140–149 / ≥150 bpm",
       60, "🎯", lambda c: R(c.max_week_zones >= 4, None, c.max_week_zones / 4, f"best {c.max_week_zones} / 4 Zonen")))
    a(("hr_decouple", "herzfrequenz", "Entkoppelt", "Lauf ≥45 min mit HF-Drift ≤3 %", 60, "📉",
       lambda c: _drift(c, 45, 3.0, sign=False)))
    a(("hr_neg", "herzfrequenz", "Eisern bis zum Schluss", "Lauf ≥60 min mit HF-Drift ≤0 % (negativ)", 75, "📉",
       lambda c: _drift(c, 60, 0.0, sign=True)))
    a(("hr_neg_series", "herzfrequenz", "Negativ-Drift-Serie", "3 Läufe in Folge (≥30 min) mit Drift ≤2 %", 80, "📉",
       lambda c: _drift_series(c)))
    a(("hr_lowdrift_long", "herzfrequenz", "Doppelt so lang, kaum Drift", "Lauf ≥90 min mit HF-Drift ≤5 %", 100, "📉",
       lambda c: _drift(c, 90, 5.0, sign=False)))
    a(("hr_maxpr", "herzfrequenz", "Grenzgänger", "Einen neuen persönlichen Max-Puls-Rekord aufstellen", 30, "🔥",
       lambda c: _pr_generic(c, "max_hr", "max")))
    a(("hr_redzone", "herzfrequenz", "Rote Zone", "Lauf mit Max-Puls ≥90 % des höchsten je gemessenen", 45, "🔥",
       lambda c: _red_zone(c)))
    a(("hr_spurt", "herzfrequenz", "Spurt am Limit", "Ein Lauf mit Max-Puls ≥175 bpm", 30, "🔥",
       lambda c: _run_reach(c, "max_hr", 175, "bpm", "{:.0f}")))
    a(("hr_calm", "herzfrequenz", "Der Gelassene", "5 Läufe in Folge mit Max-Puls unter 85 % des All-Time-Max", 55, "🧘",
       lambda c: _calm_series(c)))
    a(("hr_reserve", "herzfrequenz", "Puls-Reserve wächst", "Neuer Höchstwert bei Max−Ø-Puls in einem Lauf", 35, "💓",
       lambda c: _pr_reserve(c)))
    a(("hr_diet", "herzfrequenz", "Puls-Diät", "Im Locker-Korridor Ø-HF ≥10 bpm niedriger als früher", 90, "💚",
       lambda c: _easy_delta(c, 10)))

    # ---------------- EFFIZIENZ ----------------
    a(("ef_1", "effizienz", "Ökonomisch", "Aerobe Effizienz ≥1,0 m/Herzschlag in einem Lauf", 20, "🫀",
       lambda c: _ef_reach(c, 1.0)))
    a(("ef_11", "effizienz", "Effizient", "Aerobe Effizienz ≥1,1 m/Herzschlag", 50, "🫀",
       lambda c: _ef_reach(c, 1.1)))
    a(("ef_12", "effizienz", "Herz-Sparer", "Aerobe Effizienz ≥1,2 m/Herzschlag", 120, "🫀",
       lambda c: _ef_reach(c, 1.2)))
    a(("ef_13", "effizienz", "Effizienz-Elite", "Aerobe Effizienz ≥1,3 m/Herzschlag", 60, "🫀",
       lambda c: _ef_reach(c, 1.3)))
    a(("ef_pr", "effizienz", "Effizienz-Höchstwert", "Einen neuen persönlichen EF-Bestwert aufstellen", 30, "🫀",
       lambda c: _pr_generic(c, "ef", "max")))
    a(("ef_rise4", "effizienz", "Puls-Talfahrt", "Ø-Effizienz steigt 4 Wochen in Folge", 70, "📈",
       lambda c: _ef_rise(c, 4)))

    # ---------------- PULS ↔ PACE (Signifikanz-Trends) ----------------
    a(("fit_pah", "puls_pace", "Schneller bei gleichem Puls", "Pace@Referenzpuls verbessert sich signifikant", 100, "🚀",
       lambda c: _trend_ok(running.pace_at_hr())))
    a(("fit_easy", "puls_pace", "Ruhiger Puls bei Tempo", "Puls im Locker-Korridor sinkt signifikant", 100, "🍃",
       lambda c: _trend_ok(running.easy_hr_trend())))
    a(("fit_double", "puls_pace", "Doppelter Fortschritt", "Ein Lauf schneller UND bei niedrigerer HF als ein früher vergleichbarer",
       40, "⏫", lambda c: _double_progress(c)))
    a(("fit_all", "puls_pace", "Konstant im Fortschritt", "Alle drei Fitness-Trends gleichzeitig signifikant „besser“",
       150, "🌟", lambda c: _all_trends(c)))

    # ---------------- VO2MAX ----------------
    a(("vo2_pr", "vo2max", "Neuer Sauerstoff-Rekord", "Einen neuen VO₂max-Höchstwert erreichen", 40, "🫁",
       lambda c: _vo2_pr(c)))

    # ---------------- SERIEN (Wochen/Tage/Monate) ----------------
    for w, pts, name, iid in [(4, 25, "Monat dabei", "wk_streak_4"), (8, 50, "Dranbleiber", "wk_streak_8"),
                              (12, 100, "Quartals-Serie", "wk_streak_12"), (26, 200, "Halbjahres-Serie", "wk_streak_26"),
                              (52, 400, "Ganzjahres-Serie", "wk_streak_52")]:
        a((iid, "serie", name, f"{w} Wochen in Folge laufen", pts, "🔥",
           (lambda w: lambda c: _streak_reach(c.longest_week_streak, w, "Wochen"))(w)))
    a(("day_streak_7", "streak", "Woche ohne Pause", "7 Kalendertage in Folge gelaufen", 40, "🔥",
       lambda c: _streak_reach(c.longest_day_streak, 7, "Tage")))
    a(("day_streak_10", "streak", "Zehn-Tage-Marathon", "10 Kalendertage in Folge gelaufen", 75, "🔥",
       lambda c: _streak_reach(c.longest_day_streak, 10, "Tage")))
    a(("month_streak_6", "streak", "Halbjahres-Treue", "6 Kalendermonate in Folge gelaufen", 60, "📅",
       lambda c: _streak_reach(c.longest_month_streak, 6, "Monate")))
    a(("month_streak_12", "streak", "Kein Monat ohne Lauf", "12 Kalendermonate in Folge gelaufen", 150, "📅",
       lambda c: _streak_reach(c.longest_month_streak, 12, "Monate")))
    a(("wk_10of12", "streak", "Trotz allem dran geblieben", "In 10 von 12 rollierenden Wochen gelaufen", 55, "💪",
       lambda c: _rolling_weeks(c, 12, 10)))
    a(("wk_no2zero", "streak", "Nie zwei Nuller in Folge", "Über 26 Wochen nie zwei Nuller-Wochen hintereinander", 70, "🛡️",
       lambda c: _no_two_zero(c, 26)))
    a(("wd_ritual", "streak", "Wochentags-Ritual", "Am selben Wochentag 6 Wochen in Folge gelaufen", 45, "📌",
       lambda c: _weekday_ritual(c, 6)))
    a(("early_series", "serie", "Frühstarter-Serie", "4 Läufe in Folge zur selben Tagesstunde gestartet", 20, "🌅",
       lambda c: _same_hour_series(c, 4)))

    # ---------------- COMEBACK ----------------
    a(("cb_14", "comeback", "Comeback-Lauf", "Erster Lauf nach ≥14 Tagen Pause", 10, "💪",
       lambda c: _comeback(c, 14)))
    a(("cb_60", "comeback", "Große Rückkehr", "Erster Lauf nach ≥60 Tagen Pause", 60, "💪",
       lambda c: _comeback(c, 60)))
    a(("cb_x3", "comeback", "Auferstehung x3", "3 Comebacks (je ≥14 Tage Pause) in einem Jahr", 40, "♻️",
       lambda c: _comeback_count(c, 14, 3)))
    a(("cb_rhythm", "comeback", "Wieder im Rhythmus", "Nach einem Comeback 4 Wochen in Folge gelaufen", 50, "🎶",
       lambda c: R(c.longest_week_streak >= 4, None, c.longest_week_streak / 4, f"best {c.longest_week_streak} / 4 Wochen")))

    # ---------------- KALENDER ----------------
    for km, pts, iid, name in [(500, 100, "ykm_500", "Jahres-Kilometer 500"),
                               (1000, 250, "ykm_1000", "Jahres-Kilometer 1000")]:
        a((iid, "kalender", name, f"{km} km in einem Kalenderjahr", pts, "📅",
           (lambda km: lambda c: _year_km(c, km))(km)))
    a(("y_allmonths", "kalender", "Jahresrunde komplett", "In einem Jahr in jedem der 12 Monate gelaufen", 150, "🗓️",
       lambda c: _year_all_months(c)))
    a(("y_allweeks", "kalender", "Ganzes Jahr ohne Nuller-Woche", "In jeder Woche eines Kalenderjahres gelaufen", 250, "🗓️",
       lambda c: _year_all_weeks(c)))
    a(("y_quarters", "kalender", "Quartals-Konstanz", "In jedem Quartal eines Jahres ≥3 Läufe", 60, "🗓️",
       lambda c: _year_quarters(c)))
    a(("m_rise3", "kalender", "Monat für Monat mehr", "Monatsdistanz steigt 3 Monate in Folge", 45, "📈",
       lambda c: _month_rise(c, 3)))
    a(("m_yoy", "kalender", "Aufsteiger im Jahresvergleich", "Monat +30 % gegenüber demselben Monat im Vorjahr", 60, "📈",
       lambda c: _month_yoy(c, 0.30)))
    a(("m_rebound", "kalender", "Trendwende geschafft", "Nach 2 sinkenden Monaten wieder +10 %", 30, "↩️",
       lambda c: _month_rebound(c)))
    a(("wk_in_month", "kalender", "Jede Woche im Monat", "In jeder Woche eines Kalendermonats gelaufen", 30, "🗓️",
       lambda c: _weeks_in_a_month(c)))
    a(("all_weekdays", "kalender", "Wochen-Komplettist", "An allen 7 Wochentagen jemals gelaufen", 20, "📆",
       lambda c: _distinct_reach(c, len(c.distinct_weekdays), 7, "Wochentage")))
    a(("all_months", "kalender", "Zwölf-Monats-Läufer", "In allen 12 Monatsnummern jemals gelaufen", 60, "📆",
       lambda c: _distinct_reach(c, len(c.distinct_month_numbers), 12, "Monate")))
    a(("seasons_ever", "kalender", "Jahreszeiten-Quartett", "In allen 4 Jahreszeiten jemals gelaufen", 40, "🍂",
       lambda c: _distinct_reach(c, len(c.distinct_seasons), 4, "Jahreszeiten")))
    a(("seasons_year", "kalender", "Vier-Jahreszeiten-Jahr", "In allen 4 Jahreszeiten EINES Jahres gelaufen", 70, "🍂",
       lambda c: _seasons_in_year(c)))
    a(("season_solid", "kalender", "Saison-Fels in der Brandung", "In jeder Woche einer Jahreszeit (13) gelaufen", 90, "🧱",
       lambda c: _season_all_weeks(c)))
    a(("y_end_km", "kalender", "Jahresabschluss-Kilometer", "In der letzten Woche des Jahres (23.–31.12.) ≥15 km", 35, "🎆",
       lambda c: _window_km(c, lambda r: r["month"] == 12 and r["day"] >= 23, 15, "23.–31.12.")))
    a(("y_start_km", "kalender", "Jahresauftakt-Kilometer", "In der ersten Woche des Jahres (1.–7.1.) ≥15 km", 35, "🎉",
       lambda c: _window_km(c, lambda r: r["month"] == 1 and r["day"] <= 7, 15, "1.–7.1.")))
    a(("doppelpack", "kalender", "Doppelpack", "Zwei Läufe am selben Kalendertag", 40, "2️⃣",
       lambda c: _two_runs_day(c)))

    # ---------------- FUN & KURIOS ----------------
    a(("fun_silvester", "fun", "Silvesterlauf", "Ein Lauf am 31. Dezember", 30, "🎇",
       lambda c: _date_match(c, lambda r: r["month"] == 12 and r["day"] == 31, "noch nie am 31.12.")))
    a(("fun_neujahr", "fun", "Neujahrslauf", "Ein Lauf am 1. Januar", 30, "🎊",
       lambda c: _date_match(c, lambda r: r["month"] == 1 and r["day"] == 1, "noch nie am 1.1.")))
    a(("fun_valentin", "fun", "Valentins-Lauf", "Ein Lauf am 14. Februar", 25, "💝",
       lambda c: _date_match(c, lambda r: r["month"] == 2 and r["day"] == 14, "noch nie am 14.2.")))
    a(("fun_halloween", "fun", "Halloween-Lauf", "Ein Lauf am 31. Oktober", 25, "🎃",
       lambda c: _date_match(c, lambda r: r["month"] == 10 and r["day"] == 31, "noch nie am 31.10.")))
    a(("fun_sommer", "fun", "Sommersonnenwende-Lauf", "Ein Lauf am 20.–22. Juni", 25, "☀️",
       lambda c: _date_match(c, lambda r: r["month"] == 6 and r["day"] in (20, 21, 22), "noch nie")))
    a(("fun_winter", "fun", "Wintersonnenwende-Lauf", "Ein Lauf am 20.–22. Dezember", 30, "❄️",
       lambda c: _date_match(c, lambda r: r["month"] == 12 and r["day"] in (20, 21, 22), "noch nie")))
    a(("fun_leap", "fun", "Schalttags-Läufer", "Ein Lauf am 29. Februar (nur alle 4 Jahre)", 250, "🐸",
       lambda c: _date_match(c, lambda r: r["month"] == 2 and r["day"] == 29, "nur alle 4 Jahre möglich")))
    a(("fun_firsts", "fun", "Erster-des-Monats-Klub", "An 6 verschiedenen Monats-Ersten gelaufen", 50, "1️⃣",
       lambda c: _first_of_month(c, 6)))
    a(("fun_anniversary", "fun", "Jahrestag-Lauf", "Genau 1 Jahr nach dem allerersten Lauf gelaufen", 40, "🎂",
       lambda c: _anniversary(c)))
    a(("fun_yearcombo", "fun", "Jahreswechsel-Kombo", "Letzter Lauf des alten + erster des neuen Jahres", 60, "🥂",
       lambda c: _year_combo(c)))
    a(("fun_holiday", "fun", "Feiertagsflitzer", "Lauf an einem deutschen Feiertag", 15, "🎈",
       lambda c: _date_match(c, lambda r: _is_holiday_de(r["dte"]), "noch nie an einem Feiertag")))
    a(("fun_moon", "fun", "Vollmond-Läufer", "Lauf um einen Vollmond (±1 Tag)", 40, "🌕",
       lambda c: _date_match(c, lambda r: _is_full_moon(r["dte"]), "noch nie bei Vollmond")))
    a(("fun_palindrome", "fun", "Palindrom-Datum", "Lauf an einem TT.MM-Palindrom-Datum", 10, "🔁",
       lambda c: _date_match(c, lambda r: _is_palindrome_date(r["day"], r["month"]), "noch nie")))
    a(("fun_bingo", "fun", "Bingo-Uhrzeit", "Startzeit mit gleicher Stunde und Minute (z. B. 14:14)", 15, "🎰",
       lambda c: _date_match(c, lambda r: r["hour"] == r["minute"], "noch nie")))
    a(("fun_pacepal", "fun", "Pace-Palindrom", "Ø-Pace liest sich vor- und rückwärts gleich (z. B. 5:05)", 35, "🔁",
       lambda c: _pace_palindrome(c)))
    a(("fun_ghost", "fun", "Geisterstunde", "Lauf-Start zwischen 00:00 und 02:59 Uhr", 80, "👻",
       lambda c: _date_match(c, lambda r: 0 <= r["hour"] <= 2, "noch nie tief in der Nacht")))
    a(("fun_midnight", "fun", "Punkt Mitternacht", "Lauf-Start zwischen 23:55 und 00:05 Uhr", 100, "🕛",
       lambda c: _date_match(c, lambda r: (r["hour"] == 23 and r["minute"] >= 55) or (r["hour"] == 0 and r["minute"] <= 5), "noch nie")))

    # ---------------- SPEZIAL / ZEIT ----------------
    a(("sp_early", "fun", "Frühaufsteher", "Vor 7 Uhr morgens loslaufen", 20, "🌅",
       lambda c: _date_match(c, lambda r: r["hour"] < 7, "noch nie vor 7 Uhr")))
    a(("sp_night", "fun", "Nachteule", "Nach 21 Uhr abends laufen", 20, "🌙",
       lambda c: _date_match(c, lambda r: r["hour"] >= 21, "noch nie nach 21 Uhr")))
    a(("sp_weekend", "fun", "Wochenend-Krieger", "Samstag UND Sonntag derselben Woche laufen", 25, "⚔️",
       lambda c: _weekend_double(c)))

    # ---------------- CROSS-DOMAIN (Athlet) ----------------
    a(("cd_run_str", "cross-domain", "Zweikampf des Tages", "Lauf und Kraft-Session am selben Tag", 20, "🤼",
       lambda c: _same_day(c, c.run_days & c.strength_days, "Lauf+Kraft-Tage")))
    a(("cd_str25", "cross-domain", "Doppel-Tage-Sammler", "25 Tage mit Lauf UND Kraft", 45, "🤼",
       lambda c: _count_days(c, c.run_days & c.strength_days, 25, "Tage")))
    a(("cd_triath", "cross-domain", "Triathlet-Tag", "Lauf + Rad + Kraft am selben Tag", 60, "🏅",
       lambda c: _same_day(c, c.run_days & c.bike_days & c.strength_days, "Triathlon-Tage")))
    a(("cd_triweek", "cross-domain", "Aktiver Dreiklang der Woche", "Lauf, Kraft UND Rad in einer Woche", 40, "🎼",
       lambda c: _types_week(c, {33, 45, 4})))
    a(("cd_variety", "cross-domain", "Trainingsvielfalt", "3 verschiedene Sportarten in einer Woche", 35, "🎨",
       lambda c: _types_week_count(c, 3)))
    a(("cd_cross4", "cross-domain", "Cross-Trainer", "4 Wochen in Folge je ≥2 Sportarten", 60, "🔄",
       lambda c: _cross_streak(c, 2, 4)))
    a(("cd_double", "cross-domain", "Doppelschicht", "Zwei oder mehr Sessions am selben Tag", 20, "🔂",
       lambda c: _two_sessions_day(c)))
    a(("cd_ampm", "cross-domain", "Frühsport-Doppel", "Am selben Tag eine Session vor 8 und eine nach 18 Uhr", 30, "🌗",
       lambda c: _am_pm(c)))
    a(("cd_fullbody", "cross-domain", "Ganzkörper-Woche", "In einer Woche Lauf + Kraft + ≥70.000 Schritte", 50, "🏋️",
       lambda c: _fullbody_week(c)))
    a(("cd_form_km", "cross-domain", "Formkurve & Kilometer", "8 Wochen steigendes Lauf-Volumen bei stabilem/sinkendem Gewicht",
       75, "⚖️", lambda c: _form_km(c)))

    # Frühere „Zonen-Sammler“ (alle 4 Zonen lifetime)
    a(("zone_collector", "herzfrequenz", "Zonen-Sammler", "In allen 4 Puls-Zonen jemals gelaufen", 50, "🎯",
       lambda c: _zone_collector(c)))

    return S


# =========================================================================================
#  Komplexe Evaluatoren
# =========================================================================================
def _cum_hours(c, hours):
    target = hours * 60
    if c.total_min >= target:
        crossed = c.runs[c.runs["cum_min"] >= target]
        return R(True, crossed.iloc[0]["dte"].isoformat() if len(crossed) else None, 1.0, None)
    return R(False, None, c.total_min / target, f"{c.total_min / 60:.0f} / {hours} h")


def _pr_generic(c, col, better):
    sub = c.runs[c.runs[col].notna()]
    n, second = _pr_events(sub, col, better)
    return R(n >= 2, second, 1.0 if n >= 2 else (0.5 if n == 1 else 0.0),
             None if n >= 2 else "noch kein Rekord gebrochen")


def _be_pr(c):
    if c.be.empty:
        return R(False, None, 0.0, "noch keine Best-Efforts")
    for d, sub in c.be.groupby("distance_m"):
        n, second = _pr_events(sub, "seconds", "min")
        if n >= 2:
            return R(True, second, 1.0, None)
    return R(False, None, 0.5, "noch keinen Best-Effort verbessert")


def _vo2_pr(c):
    try:
        v = running._read("SELECT measured_at, vo2 FROM vo2max ORDER BY measured_at",
                          parse_dates=["measured_at"])
    except Exception:  # noqa: BLE001
        return R(False, None, 0.0, "keine VO₂max-Daten")
    if v.empty:
        return R(False, None, 0.0, "keine VO₂max-Daten")
    v = v.rename(columns={"measured_at": "started_at"})
    n, second = _pr_events(v, "vo2", "max")
    return R(n >= 2, second, 1.0 if n >= 2 else 0.5, None if n >= 2 else "noch kein neuer Höchstwert")


def _hr_combo(c, dist, hr, label):
    q = c.runs[(c.runs["distance_km"] >= dist) & (c.runs["avg_hr"].notna()) & (c.runs["avg_hr"] < hr)]
    if len(q):
        return R(True, q.iloc[0]["dte"].isoformat(), 1.0, None)
    # Fortschritt: bester Lauf ≥dist, wie nah avg_hr an Schwelle
    cand = c.runs[(c.runs["distance_km"] >= dist) & (c.runs["avg_hr"].notna())]
    if len(cand):
        best = float(cand["avg_hr"].min())
        return R(False, None, hr / best, f"best {best:.0f} bpm bei ≥{dist:g} km · Ziel <{hr}")
    return R(False, None, 0.0, label)


def _drift(c, dur, thr, sign):
    d = c.runs[(c.runs["dur_min"] >= dur) & (c.runs["hr_drift_pct"].notna())]
    if sign:
        q = d[d["hr_drift_pct"] <= thr]
    else:
        q = d[d["hr_drift_pct"].abs() <= thr]
    if len(q):
        return R(True, q.iloc[0]["dte"].isoformat(), 1.0, None)
    return R(False, None, 0.0, f"noch kein Lauf ≥{dur} min mit Drift-Ziel")


def _drift_series(c):
    d = c.runs[(c.runs["dur_min"] >= 30) & (c.runs["hr_drift_pct"].notna())].sort_values("started_at")
    run = 0
    for r in d.itertuples():
        run = run + 1 if r.hr_drift_pct <= 2 else 0
        if run >= 3:
            return R(True, r.dte.isoformat(), 1.0, None)
    return R(False, None, run / 3, f"best {run} / 3 in Folge")


def _red_zone(c):
    m = c.runs[c.runs["max_hr"].notna()]
    if m.empty:
        return R(False, None, 0.0, "keine Max-HF-Daten")
    allmax = float(m["max_hr"].max())
    thr = 0.9 * allmax
    q = m[m["max_hr"] >= thr]
    return R(len(q) > 0, q.iloc[0]["dte"].isoformat() if len(q) else None,
             1.0 if len(q) else 0.0, None if len(q) else f"Ziel ≥{thr:.0f} bpm")


def _calm_series(c):
    m = c.runs[c.runs["max_hr"].notna()].sort_values("started_at")
    if m.empty:
        return R(False, None, 0.0, "keine Max-HF-Daten")
    allmax = float(m["max_hr"].max())
    thr = 0.85 * allmax
    run = 0
    best = 0
    dt = None
    for r in m.itertuples():
        run = run + 1 if r.max_hr < thr else 0
        if run > best:
            best = run; dt = r.dte
        if best >= 5:
            return R(True, dt.isoformat(), 1.0, None)
    return R(False, None, best / 5, f"best {best} / 5 in Folge")


def _pr_reserve(c):
    sub = c.runs[c.runs["max_hr"].notna() & c.runs["avg_hr"].notna()].copy()
    if sub.empty:
        return R(False, None, 0.0, "keine HF-Daten")
    sub["reserve"] = sub["max_hr"] - sub["avg_hr"]
    n, second = _pr_events(sub, "reserve", "max")
    return R(n >= 2, second, 1.0 if n >= 2 else 0.5, None if n >= 2 else "noch kein Rekord")


def _easy_delta(c, bpm):
    try:
        e = running.easy_hr_trend()
    except Exception:  # noqa: BLE001
        return R(False, None, 0.0, "keine Daten")
    d = (e.get("trend") or {}).get("delta")
    if d is None:
        return R(False, None, 0.0, "zu wenig Daten")
    # delta negativ = Puls gesunken
    prog = min(1.0, max(0.0, (-d) / bpm))
    return R(d <= -bpm, None, prog, f"Δ {d:+.1f} bpm · Ziel −{bpm}")


def _ef_reach(c, thr):
    q = c.runs[(c.runs["ef"].notna()) & (c.runs["ef"] >= thr)]
    if len(q):
        return R(True, q.iloc[0]["dte"].isoformat(), 1.0, None)
    best = c.maxef
    return R(False, None, (best / thr) if best else 0.0,
             f"best {best:.2f} / {thr:.1f}" if best else f"— / {thr:.1f}")


def _ef_rise(c, n):
    ef = c.runs[c.runs["ef"].notna()].copy()
    if ef.empty:
        return R(False, None, 0.0, "keine EF-Daten")
    ef["wk"] = list(zip(ef["iso_year"], ef["iso_week"]))
    wk = ef.groupby("wk")["ef"].mean().reset_index().sort_values("wk")
    vals = wk["ef"].tolist()
    best = run = 0
    for i in range(1, len(vals)):
        run = run + 1 if vals[i] > vals[i - 1] else 0
        best = max(best, run)
    return R(best >= n, None, best / n, f"best {best} / {n} Wochen steigend")


def _trend_ok(obj):
    t = (obj or {}).get("trend") or {}
    ok = t.get("verdict") == "besser" and t.get("significant")
    return R(bool(ok), None, 1.0 if ok else (0.5 if t.get("verdict") == "besser" else 0.0),
             None if ok else "noch kein signifikanter Trend")


def _all_trends(c):
    try:
        oks = [_trend_ok(running.pace_at_hr())[0], _trend_ok(running.easy_hr_trend())[0]]
        ef = running.ef_trend()
        eft = (ef or {}).get("trend") or {}
        oks.append(eft.get("verdict") == "besser" and eft.get("significant"))
    except Exception:  # noqa: BLE001
        return R(False, None, 0.0, "Daten unvollständig")
    n = sum(1 for x in oks if x)
    return R(n == 3, None, n / 3, f"{n} / 3 Trends signifikant „besser“")


def _double_progress(c):
    df = c.runs[c.runs["avg_hr"].notna()].sort_values("started_at").reset_index(drop=True)
    for i in range(len(df)):
        cur = df.iloc[i]
        prev = df.iloc[:i]
        cand = prev[(prev["distance_km"].between(cur["distance_km"] * 0.9, cur["distance_km"] * 1.1))
                    & (prev["started_at"] >= cur["started_at"] - pd.Timedelta(days=90))]
        if len(cand):
            last = cand.iloc[-1]
            if cur["pace"] < last["pace"] and cur["avg_hr"] < last["avg_hr"]:
                return R(True, cur["dte"].isoformat(), 1.0, None)
    return R(False, None, 0.0, "noch kein Doppel-Fortschritt")


def _attack(c):
    if c.be.empty:
        return R(False, None, 0.0, "keine Best-Efforts")
    km1 = c.be[c.be["distance_m"] == 1000]
    hit = False
    dt = None
    for r in km1.itertuples():
        run = c.runs[c.runs["started_at"] == r.started_at]
        if len(run):
            gpace = run.iloc[0]["pace"]  # min/km
            fast_pace = (r.seconds / 60.0)  # 1km split min/km
            if gpace > 0 and fast_pace <= gpace * 0.7:
                hit = True; dt = run.iloc[0]["dte"]; break
    return R(hit, dt.isoformat() if dt else None, 1.0 if hit else 0.0, None if hit else "noch kein Tempo-Ausreißer")


def _even_month(c):
    ok = False
    for (_, _), g in c.runs[c.runs["distance_km"] >= 3].groupby([c.runs["year"], c.runs["month"]]):
        if len(g) >= 3:
            mean = g["pace"].mean()
            if (g["pace"] - mean).abs().max() * 60 <= 10:
                ok = True; break
    return R(ok, None, 1.0 if ok else 0.0, None if ok else "noch kein konstanter Monat")


def _month_record(c):
    if len(c.months_sorted) < 2:
        return R(False, None, 0.0, "zu wenig Monate")
    vals = [c.month_km.loc[k] for k in c.months_sorted]
    # ein Monat, der alle vorherigen übertrifft (nach dem ersten)
    best = vals[0]
    for i in range(1, len(vals)):
        if vals[i] > best:
            y, m = c.months_sorted[i]
            return R(True, date(y, m, 1).isoformat(), 1.0, None)
        best = max(best, vals[i])
    return R(False, None, 0.5, "noch kein Rekordmonat")


def _week_double_long(c):
    ok = False
    for _, g in c.runs.groupby([c.runs["iso_year"], c.runs["iso_week"]]):
        longs = g[g["distance_km"] >= 15]
        if len(longs) >= 2 and longs["distance_km"].sum() >= 42.195:
            ok = True; break
    return R(ok, None, 1.0 if ok else 0.0, None if ok else "noch nicht erreicht")


def _rolling_weeks(c, window, need):
    weeks_present = sorted(w["start"] for w in c.weeks.values() if w["start"])
    if not weeks_present:
        return R(False, None, 0.0, "keine Läufe")
    start = min(weeks_present)
    end = max(weeks_present)
    allw = []
    d = start
    while d <= end:
        allw.append(d in set(weeks_present))
        d += timedelta(days=7)
    best = 0
    for i in range(len(allw)):
        window_slice = allw[max(0, i - window + 1):i + 1]
        best = max(best, sum(window_slice))
    return R(best >= need, None, best / need, f"best {best} / {need} in {window} Wochen")


def _no_two_zero(c, window):
    weeks_present = sorted(w["start"] for w in c.weeks.values() if w["start"])
    if len(weeks_present) < 2:
        return R(False, None, len(weeks_present) / window if window else 0, "zu wenig Wochen")
    start, end = min(weeks_present), max(weeks_present)
    flags = []
    d = start
    pset = set(weeks_present)
    while d <= end:
        flags.append(d in pset)
        d += timedelta(days=7)
    # längstes Fenster ohne zwei aufeinanderfolgende False
    best = cur = 0
    for i in range(len(flags)):
        two_zero = (i >= 1 and not flags[i] and not flags[i - 1])
        cur = 0 if two_zero else cur + 1
        best = max(best, cur)
    return R(best >= window, None, best / window, f"best {best} / {window} Wochen sauber")


def _weekday_ritual(c, n):
    best = 0
    for wd, g in c.runs.groupby("wd"):
        starts = sorted({date.fromisocalendar(iy, iw, 1) for iy, iw in zip(g["iso_year"], g["iso_week"])})
        best = max(best, _longest_run(starts, 7))
    return R(best >= n, None, best / n, f"best {best} / {n} Wochen (fixer Wochentag)")


def _same_hour_series(c, n):
    df = c.runs.sort_values("started_at")
    run = best = 0
    prev = None
    for h in df["hour"]:
        run = run + 1 if (prev is not None and h == prev) else 1
        best = max(best, run)
        prev = h
    return R(best >= n, None, best / n, f"best {best} / {n} in Folge")


def _comeback(c, gap):
    dts = sorted(set(c.runs["dte"]))
    for i in range(1, len(dts)):
        if (dts[i] - dts[i - 1]).days >= gap:
            return R(True, dts[i].isoformat(), 1.0, None)
    # Fortschritt: aktuelle Pause seit letztem Lauf? (nicht sinnvoll) → 0
    return R(False, None, 0.0, f"noch keine ≥{gap}-Tage-Pause überwunden")


def _comeback_count(c, gap, need):
    dts = sorted(set(c.runs["dte"]))
    by_year: dict[int, int] = {}
    for i in range(1, len(dts)):
        if (dts[i] - dts[i - 1]).days >= gap:
            by_year[dts[i].year] = by_year.get(dts[i].year, 0) + 1
    best = max(by_year.values(), default=0)
    return R(best >= need, None, best / need, f"best {best} / {need} in einem Jahr")


def _year_km(c, target):
    if c.year_km.empty:
        return R(False, None, 0.0, "keine Läufe")
    best = float(c.year_km.max())
    hit_year = c.year_km[c.year_km >= target]
    if len(hit_year):
        y = int(hit_year.index[0])
        return R(True, date(y, 12, 31).isoformat(), 1.0, None)
    return R(False, None, best / target, f"best {best:.0f} / {target} km (Jahr)")


def _year_all_months(c):
    best = 0
    dt = None
    for y, g in c.runs.groupby("year"):
        cnt = g["month"].nunique()
        if cnt > best:
            best = cnt
            if cnt == 12:
                dt = date(int(y), 12, 31)
    return R(best >= 12, dt.isoformat() if dt else None, best / 12, f"best {best} / 12 Monate")


def _year_all_weeks(c):
    best = 0
    for y, g in c.runs.groupby("iso_year"):
        best = max(best, g["iso_week"].nunique())
    return R(best >= 52, None, best / 52, f"best {best} / 52 Wochen")


def _year_quarters(c):
    best = 0
    for y, g in c.runs.groupby("year"):
        q = ((g["month"] - 1) // 3)
        counts = q.value_counts()
        full = sum(1 for k in range(4) if counts.get(k, 0) >= 3)
        best = max(best, full)
        if full == 4:
            return R(True, date(int(y), 12, 31).isoformat(), 1.0, None)
    return R(False, None, best / 4, f"best {best} / 4 Quartale (≥3 Läufe)")


def _month_rise(c, n):
    vals = [c.month_km.loc[k] for k in c.months_sorted]
    best = run = 0
    for i in range(1, len(vals)):
        run = run + 1 if vals[i] > vals[i - 1] else 0
        best = max(best, run)
    return R(best >= n, None, best / n, f"best {best} / {n} Monate steigend")


def _month_yoy(c, frac):
    ok = False
    for (y, m) in c.months_sorted:
        prev = c.month_km.get((y - 1, m))
        cur = c.month_km.get((y, m))
        if prev and cur and cur >= prev * (1 + frac):
            ok = True; break
    return R(ok, None, 1.0 if ok else 0.0, None if ok else "braucht ≥13 Monate Historie")


def _month_rebound(c):
    vals = [c.month_km.loc[k] for k in c.months_sorted]
    for i in range(3, len(vals)):
        if vals[i - 2] < vals[i - 3] and vals[i - 1] < vals[i - 2] and vals[i] >= vals[i - 1] * 1.1:
            y, m = c.months_sorted[i]
            return R(True, date(y, m, 1).isoformat(), 1.0, None)
    return R(False, None, 0.0, "noch keine Trendwende")


def _weeks_in_a_month(c):
    # in jeder ISO-Woche, die einen Monat berührt, mind. 1 Lauf
    ok = False
    for (y, m), g in c.runs.groupby([c.runs["year"], c.runs["month"]]):
        weeks_needed = set()
        d = date(int(y), int(m), 1)
        while d.month == m:
            weeks_needed.add(d.isocalendar()[1])
            d += timedelta(days=1)
        weeks_have = set(g["iso_week"].tolist())
        if weeks_needed <= weeks_have:
            ok = True; break
    return R(ok, None, 1.0 if ok else 0.0, None if ok else "noch nicht erreicht")


def _seasons_in_year(c):
    best = 0
    for y, g in c.runs.groupby("year"):
        best = max(best, g["season"].nunique())
        if g["season"].nunique() == 4:
            return R(True, date(int(y), 12, 31).isoformat(), 1.0, None)
    return R(False, None, best / 4, f"best {best} / 4 Jahreszeiten (ein Jahr)")


def _season_all_weeks(c):
    # in jeder Woche einer Jahreszeit gelaufen (13 Wochen) — grobe Näherung über Saison-Wochen je Jahr
    best = 0
    for (y, s), g in c.runs.groupby([c.runs["year"], c.runs["season"]]):
        best = max(best, g["iso_week"].nunique())
    return R(best >= 13, None, best / 13, f"best {best} / 13 Saison-Wochen")


def _window_km(c, pred, target, label):
    mask = c.runs.apply(lambda r: pred(r), axis=1)
    sub = c.runs[mask]
    if sub.empty:
        return R(False, None, 0.0, f"{label}: noch nichts")
    by_year = sub.groupby("year")["distance_km"].sum()
    best = float(by_year.max())
    if best >= target:
        return R(True, None, 1.0, None)
    return R(False, None, best / target, f"best {best:.0f} / {target} km ({label})")


def _two_runs_day(c):
    counts = c.runs.groupby("dte").size()
    hit = counts[counts >= 2]
    if len(hit):
        return R(True, hit.index[0].isoformat(), 1.0, None)
    return R(False, None, 0.0, "noch kein Doppel-Tag")


def _first_of_month(c, n):
    firsts = c.runs[c.runs["day"] == 1]
    cnt = firsts.groupby([firsts["year"], firsts["month"]]).ngroups
    return R(cnt >= n, None, cnt / n, f"{cnt} / {n} Monats-Erste")


def _anniversary(c):
    if c.runs.empty:
        return R(False, None, 0.0, "keine Läufe")
    first = c.runs.iloc[0]["started_at"]
    q = c.runs[(c.runs["month"] == first.month) & (c.runs["day"] == first.day)
              & (c.runs["year"] > first.year)]
    return R(len(q) > 0, q.iloc[0]["dte"].isoformat() if len(q) else None,
             1.0 if len(q) else 0.0, None if len(q) else "erst nach 1 Jahr möglich")


def _year_combo(c):
    years = sorted(c.runs["year"].unique().tolist())
    for y in years:
        late = c.runs[(c.runs["year"] == y) & (c.runs["month"] == 12) & (c.runs["day"] >= 27)]
        early = c.runs[(c.runs["year"] == y + 1) & (c.runs["month"] == 1) & (c.runs["day"] <= 5)]
        if len(late) and len(early):
            return R(True, early.iloc[0]["dte"].isoformat(), 1.0, None)
    return R(False, None, 0.0, "noch keine Jahreswechsel-Kombo")


def _is_palindrome_date(day, month):
    s = f"{day:02d}{month:02d}"
    return s == s[::-1]


def _pace_is_palindrome(pace_min):
    """m:ss als Ziffernkette (z. B. 5:05 → '505', 10:01 → '1001') — Palindrom?"""
    if pace_min is None or pace_min <= 0:
        return False
    m = int(pace_min)
    s = int(round((pace_min - m) * 60))
    if s == 60:
        m += 1; s = 0
    txt = f"{m}{s:02d}"
    return txt == txt[::-1]


def _pace_palindrome(c):
    q = c.runs[c.runs["pace"].apply(_pace_is_palindrome)]
    if len(q):
        return R(True, q.iloc[0]["dte"].isoformat(), 1.0, None)
    return R(False, None, 0.0, "noch keine Palindrom-Pace")


def _weekend_double(c):
    for _, g in c.runs.groupby([c.runs["iso_year"], c.runs["iso_week"]]):
        wds = set(g["wd"])
        if 5 in wds and 6 in wds:
            return R(True, g[g["wd"] == 6].iloc[0]["dte"].isoformat(), 1.0, None)
    return R(False, None, 0.0, "noch nie Sa+So dieselbe Woche")


def _zone_collector(c):
    hr = c.runs[c.runs["avg_hr"].notna()]["avg_hr"]
    zones = set()
    for h in hr:
        zones.add(0 if h < 130 else 1 if h < 140 else 2 if h < 150 else 3)
    return R(len(zones) >= 4, None, len(zones) / 4, f"{len(zones)} / 4 Zonen")


def _same_day(c, dayset, label):
    if dayset:
        return R(True, min(dayset).isoformat(), 1.0, None)
    return R(False, None, 0.0, f"noch keine {label}")


def _count_days(c, dayset, target, noun):
    n = len(dayset)
    return R(n >= target, None, n / target, f"{n} / {target} {noun}")


def _types_week(c, needed):
    if c.types_per_week is None or len(c.types_per_week) == 0:
        return R(False, None, 0.0, "keine Sessions")
    for wk, s in c.types_per_week.items():
        if needed <= s:
            return R(True, None, 1.0, None)
    best = max((len(needed & s) for s in c.types_per_week), default=0)
    return R(False, None, best / len(needed), f"best {best} / {len(needed)} Sportarten/Woche")


def _types_week_count(c, n):
    if len(c.types_per_week) == 0:
        return R(False, None, 0.0, "keine Sessions")
    best = max(len(s) for s in c.types_per_week)
    return R(best >= n, None, best / n, f"best {best} / {n} Sportarten/Woche")


def _cross_streak(c, min_types, need):
    if len(c.types_per_week) == 0:
        return R(False, None, 0.0, "keine Sessions")
    weeks = sorted(c.types_per_week.index.tolist())
    starts = []
    for (iy, iw) in weeks:
        try:
            starts.append((date.fromisocalendar(iy, iw, 1), len(c.types_per_week[(iy, iw)])))
        except Exception:  # noqa: BLE001
            pass
    starts.sort()
    best = run = 0
    prev = None
    for d, cnt in starts:
        good = cnt >= min_types
        if good and prev is not None and (d - prev).days == 7:
            run += 1
        elif good:
            run = 1
        else:
            run = 0
        best = max(best, run)
        prev = d
    return R(best >= need, None, best / need, f"best {best} / {need} Wochen")


def _two_sessions_day(c):
    if c.sessions_per_day is None or len(c.sessions_per_day) == 0:
        return R(False, None, 0.0, "keine Sessions")
    hit = c.sessions_per_day[c.sessions_per_day >= 2]
    return R(len(hit) > 0, hit.index[0].isoformat() if len(hit) else None,
             1.0 if len(hit) else 0.0, None if len(hit) else "noch kein Doppel-Tag")


def _am_pm(c):
    try:
        alls = running._read("SELECT started_at FROM exercise_sessions", parse_dates=["started_at"])
    except Exception:  # noqa: BLE001
        return R(False, None, 0.0, "keine Sessions")
    alls = alls[alls["started_at"].notna()].copy()
    alls["dte"] = alls["started_at"].dt.date
    alls["hour"] = alls["started_at"].dt.hour
    for d, g in alls.groupby("dte"):
        if (g["hour"] < 8).any() and (g["hour"] >= 18).any():
            return R(True, d.isoformat(), 1.0, None)
    return R(False, None, 0.0, "noch kein Morgen+Abend-Tag")


def _fullbody_week(c):
    if len(c.steps_week) == 0:
        return R(False, None, 0.0, "keine Schritt-Daten")
    for wk, s in (c.types_per_week.items() if len(c.types_per_week) else []):
        if {33, 45} <= s and c.steps_week.get(wk, 0) >= 70000:
            return R(True, None, 1.0, None)
    return R(False, None, 0.0, "noch keine Ganzkörper-Woche")


def _form_km(c):
    try:
        w = running._read("SELECT measured_at, weight_kg FROM body_measurements WHERE weight_kg IS NOT NULL ORDER BY measured_at",
                          parse_dates=["measured_at"])
    except Exception:  # noqa: BLE001
        w = pd.DataFrame()
    # 8 Wochen steigendes Volumen
    weeks = sorted((w_["start"], w_["km"]) for w_ in c.weeks.values() if w_["start"])
    kmvals = [k for _, k in weeks]
    best = run = 0
    for i in range(1, len(kmvals)):
        run = run + 1 if kmvals[i] > kmvals[i - 1] else 0
        best = max(best, run)
    rising = best >= 8
    # Gewicht stabil/sinkend über den Zeitraum
    weight_ok = True
    if not w.empty and len(w) >= 2:
        weight_ok = w["weight_kg"].iloc[-1] <= w["weight_kg"].iloc[0] + 0.5
    ok = rising and weight_ok
    return R(ok, None, min(1.0, best / 8), f"best {best} / 8 Wochen Volumen↑")


# =========================================================================================
#  META-Erfolge (auf Basis der ausgewerteten Erfolge)
# =========================================================================================
def _meta_specs():
    M = []
    m = M.append
    m(("meta_10", "meta", "Trophäenjäger", "10 Erfolge freischalten", 20, "🏆",
       lambda A: _meta_count(A, 10)))
    m(("meta_25", "meta", "Trophäensammler", "25 Erfolge freischalten", 40, "🏆",
       lambda A: _meta_count(A, 25)))
    m(("meta_50", "meta", "Trophäenmeister", "50 Erfolge freischalten", 75, "🏆",
       lambda A: _meta_count(A, 50)))
    m(("meta_100", "meta", "Trophäen-Titan", "100 Erfolge freischalten", 150, "🏆",
       lambda A: _meta_count(A, 100)))
    m(("meta_complete", "meta", "Completionist", "Alle anderen Erfolge freischalten", 250, "💯",
       lambda A: R(False, None, 0.0, None)))  # wird in evaluate() korrekt nachberechnet
    m(("meta_pts_1000", "meta", "Punktesammler I", "1.000 Punkte sammeln", 25, "💠",
       lambda A: _meta_points(A, 1000)))
    m(("meta_pts_3000", "meta", "Punktesammler II", "3.000 Punkte sammeln", 60, "💠",
       lambda A: _meta_points(A, 3000)))
    m(("meta_pts_6000", "meta", "Punktesammler III", "6.000 Punkte sammeln", 150, "💠",
       lambda A: _meta_points(A, 6000)))
    m(("meta_variety", "meta", "Vielseitigkeits-Abzeichen", "Mind. 1 Erfolg aus jeder Kategorie", 45, "🎖️",
       lambda A: _meta_variety(A)))
    m(("meta_sameday", "meta", "Alles auf einmal", "3 Erfolge am selben Tag freigeschaltet", 30, "🎆",
       lambda A: _meta_sameday(A, 3)))
    m(("meta_cat_tempo", "meta", "Kategorie-Meister: Tempo", "Alle Tempo-Erfolge freischalten", 90, "🥇",
       lambda A: _meta_category(A, "tempo")))
    m(("meta_cat_serie", "meta", "Serien-Ass", "Alle Wochen-Serien-Erfolge freischalten", 120, "🥇",
       lambda A: _meta_category(A, "serie")))
    return M


def _meta_count(A, n):
    e = sum(1 for a in A if a["earned"])
    return R(e >= n, None, e / n, f"{e} / {n} Erfolge")


def _meta_points(A, n):
    p = sum(a["points"] for a in A if a["earned"])
    return R(p >= n, None, p / n, f"{p} / {n} Punkte")


def _meta_variety(A):
    cats = {a["category"] for a in A}
    have = {a["category"] for a in A if a["earned"]}
    return R(have >= cats, None, len(have) / max(1, len(cats)), f"{len(have)} / {len(cats)} Kategorien")


def _meta_sameday(A, n):
    from collections import Counter
    dates = Counter(a["earned_date"] for a in A if a["earned"] and a["earned_date"])
    best = max(dates.values(), default=0)
    day = None
    for d, cnt in dates.items():
        if cnt >= n:
            day = d; break
    return R(best >= n, day, best / n, f"best {best} / {n} an einem Tag")


def _meta_category(A, cat):
    items = [a for a in A if a["category"] == cat]
    if not items:
        return R(False, None, 0.0, "—")
    done = sum(1 for a in items if a["earned"])
    return R(done == len(items), None, done / len(items), f"{done} / {len(items)} in {cat}")
