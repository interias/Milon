"""Mein Wochenplan: geplant vs. erledigt über Rad, Kraft und Lauf für eine Kalenderwoche (Mo–So).

Je Sportart genau eine Soll-Quelle: Rad = aktiver Rad-Plan (bike_plan), Kraft = Gym-Tage des Rad-Plans
(Oberkörper → Milon OK, Beine → Milon UK), außerhalb eines Plans das feste Schema Mo OK / Mi UK / Fr OK;
Lauf hat kein eigenes Soll (Lauf-Variante der Rad-Einheit oder ungeplant). Erledigt kommt aus den
Importen (Indoor/Outdoor-Fahrten, Läufe, Hevy). Last wird nie über Sportarten addiert.

Farben (angelehnt an TrainingPeaks): green = im Soll (Rad: Dauer ±20 %), yellow = 50–79 % oder
121–150 % bzw. anderes Kraftprogramm, orange = weiter daneben, red = verpasst, grey = ungeplant
erledigt (neutral), open = heute/kommend, skipped = optionale Einheit nicht gefahren, sick = Soll an
einem Krankheitstag offen (pausiert wie die Serie, zählt nicht als verpasst)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlmodel import Session, select

from .. import bike_plan
from ..config import settings
from ..db import engine
from ..models import Workout

WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
DEFAULT_GYM = {0: "ok", 2: "uk", 4: "ok"}  # außerhalb eines Rad-Plans
PROGRAM_TITLE = {"ok": "Milon OK", "uk": "Milon UK"}
MAX_HARD = 2


def _today(today: date | None) -> date:
    return today or datetime.now(ZoneInfo(settings.timezone)).date()


def program_of(label: str | None) -> str | None:
    """Gym-Label → Programm: Beine/Leg/UK = Unterkörper, sonst Oberkörper."""
    if not label:
        return None
    low = label.lower()
    return "uk" if ("bein" in low or "leg" in low or "uk" in low.split()) else "ok"


def ratio_color(ratio: float | None) -> str:
    if ratio is None:
        return "green"
    if 0.8 <= ratio <= 1.2:
        return "green"
    if 0.5 <= ratio <= 1.5:
        return "yellow"
    return "orange"


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 -- eine fehlende Quelle kürzt nur die Woche
        return default


def _workouts(first: date, last: date) -> list[dict]:
    """Hevy-Workouts der Woche mit Programm (ok/uk, falls Planübungen erkennbar)."""
    from . import strength_plan
    with Session(engine) as db:
        rows = db.exec(select(Workout).where(Workout.started_at >= datetime.combine(first, datetime.min.time()),
                                             Workout.started_at < datetime.combine(last + timedelta(days=1),
                                                                                   datetime.min.time()))).all()
    kinds = _safe(lambda: strength_plan._classify(strength_plan._read_sets()), {})
    return [{"id": w.id, "day": w.started_at.date(), "title": w.title or "Krafttraining",
             "minutes": round((w.ended_at - w.started_at).total_seconds() / 60) if w.ended_at else None,
             "program": kinds.get(w.id)} for w in rows if w.started_at]


def _prescription(plans: dict, key: str) -> list[str]:
    p = plans.get(key)
    if not p:
        return []
    out = []
    for ex in p["exercises"]:
        work = [s for s in ex["sets"] if s["type"] == "normal"]
        if work and ex.get("weight_kg"):
            reps = sorted({s["reps"] for s in work})
            out.append(f"{ex['name']}: {len(work)} × {'/'.join(map(str, reps))} @ {ex['weight_kg']:g} kg".replace(".", ","))
        else:
            out.append(f"{ex['name']}: {len(work)} Sätze")
    return out


def week(offset: int = 0, today: date | None = None) -> dict:
    """Kalenderwoche `offset` relativ zur aktuellen (−1 = Vorwoche, +1 = nächste)."""
    from . import endurance, running, sleep, strength_plan
    from .. import checkins, weather
    today = _today(today)
    first = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    last = first + timedelta(days=6)
    days = [first + timedelta(days=i) for i in range(7)]
    iso = [d.isoformat() for d in days]

    plan = _safe(lambda: bike_plan.overview(today=today), {"plan": None})
    bike = {s["date"]: s for w in plan.get("weeks") or [] for s in w["sessions"] if s["date"] in iso}
    plan_gym = {d["date"]: d["gym"] for w in plan.get("weeks") or [] for d in w.get("days") or [] if d["date"] in iso}
    in_plan = {d for d in iso if plan.get("plan") and plan["plan"]["start"] <= d <= plan["plan"]["end"]}

    rides = _safe(endurance.ride_sessions, pd.DataFrame(columns=["started_at", "minutes", "kind", "title", "day"]))
    rides = rides[(rides["day"] >= first) & (rides["day"] <= last)] if not rides.empty else rides
    indoor = _safe(lambda: bike_plan._rides(), pd.DataFrame())
    indoor_ids = {}
    if not indoor.empty:
        for r in indoor[(indoor["day"] >= first) & (indoor["day"] <= last)].itertuples():
            indoor_ids[(r.day, pd.Timestamp(r.started_at))] = str(r.activity_id)
    runs = _safe(running._runs, pd.DataFrame())
    if not runs.empty:
        runs = runs[(runs["started_at"].dt.date >= first) & (runs["started_at"].dt.date <= last)].copy()
        runs["day"] = runs["started_at"].dt.date
    workouts = _workouts(first, last)
    nxt = _safe(lambda: strength_plan.next_training(today), {"plans": []})
    plans = {p["key"]: p for p in nxt.get("plans") or []}

    main_sleep = _safe(lambda: sleep._main_by_day(sleep._sleep_rows(7 + (today - first).days, today)), {})
    entries = {e["day"]: e for e in _safe(lambda: checkins.list_entries(7 + max(0, (today - first).days), max(today, last)), [])}
    forecast = {}
    for i, d in enumerate(days):
        ahead = (d - today).days
        if 0 <= ahead <= 6:
            w = _safe(lambda a=ahead: weather.today(day=a), None)
            if w and w.get("configured"):
                info = w.get("day") or {}
                run = w.get("run") or {}
                window = run.get("morning") or run.get("best")
                forecast[iso[i]] = {"temp_max": info.get("temp_max"), "temp_min": info.get("temp_min"),
                                    "rain_prob": info.get("rain_prob_max"), "label": info.get("text"),
                                    "icon": info.get("icon"),
                                    "run": {"start": window.get("start"), "end": window.get("end"),
                                            "clothing": (window.get("clothing") or {}).get("text")} if window else None}

    out_days, totals = [], {"bike_planned_min": 0.0, "bike_planned": 0, "bike_done_min": 0.0, "bike_done": 0,
                            "bike_matched": 0, "gym_planned": 0, "gym_done": 0, "gym_matched": 0,
                            "run_km": 0.0, "runs": 0, "hard_planned": 0, "hard_done": 0, "missed": 0}
    for d, key in zip(days, iso):
        past, is_today = d < today, d == today
        sick = bool((entries.get(key) or {}).get("sick"))
        items: list[dict] = []
        used_ride, used_run, used_workouts = None, None, set()
        # Rad (Soll aus dem Plan)
        s = bike.get(key)
        if s:
            color = {"missed": "sick" if sick else "red", "skipped": "skipped", "today": "open", "planned": "open",
                     "run": "green"}.get(s["status"])
            ratio = None
            if s["status"] == "done" and s["ride"]:
                used_ride = s["ride"]["activity_id"]
                ratio = (s["ride"]["minutes"] or 0) / s["duration_min"] if s["duration_min"] else None
                color = ratio_color(ratio)
            if s["status"] == "run":
                used_run = True
            hard = s["kind"] in bike_plan.HARD_KINDS
            items.append({"type": "bike", "planned": True, "title": s["title"], "kind": s["kind"],
                          "optional": s["optional"], "color": color, "status": s["status"],
                          "duration_min": s["duration_min"], "ratio": round(ratio, 2) if ratio else None,
                          "target": _bike_target(s), "ride": s["ride"], "run": s["run"], "execution": s["execution"],
                          "run_alternative": s["run_alternative"], "warnings": s.get("warnings") or [],
                          "href": "/rad/plan", "zwo": s["id"] if s["zwo"] else None})
            if not s["optional"] or s["status"] in ("done", "run"):
                totals["bike_planned"] += 0 if s["optional"] else 1
                totals["bike_planned_min"] += 0 if s["optional"] else (s["duration_min"] or 0)
            totals["bike_matched"] += s["status"] in ("done", "run")
            totals["hard_planned"] += hard
            totals["hard_done"] += hard and s["status"] in ("done", "run")
            totals["missed"] += color == "red"
        # Kraft (Soll aus Gym-Tagen)
        program = program_of(plan_gym.get(key)) if key in in_plan else DEFAULT_GYM.get(d.weekday())
        if program:
            done = [w for w in workouts if w["day"] == d]
            hit = next((w for w in done if w["program"] == program), None) or (done[0] if done else None)
            if hit:
                used_workouts.add(hit["id"])
            color = ("green" if hit["program"] in (program, None) else "yellow") if hit \
                else ("sick" if sick and (past or is_today) else "red" if past else "open")
            items.append({"type": "gym", "planned": True, "title": PROGRAM_TITLE[program], "program": program,
                          "label": plan_gym.get(key), "color": color, "done": hit,
                          "prescription": _prescription(plans, program) if not past and not hit else [],
                          "href": "/kraft"})
            totals["gym_planned"] += 1
            totals["gym_matched"] += hit is not None
            totals["missed"] += color == "red"
        # Erledigt, aber ungeplant (grau)
        for r in rides[rides["day"] == d].itertuples() if not rides.empty else []:
            rid = indoor_ids.get((d, pd.Timestamp(r.started_at)))
            totals["bike_done"] += 1
            totals["bike_done_min"] += float(r.minutes)
            if rid is not None and rid == used_ride:
                continue
            items.append({"type": "ride", "planned": False, "title": r.title, "color": "grey",
                          "minutes": round(float(r.minutes)), "href": f"/rad/{rid}" if rid else "/gesundheit"})
        day_runs = runs[runs["day"] == d].sort_values("dur_min", ascending=False) if not runs.empty else runs
        for i, r in enumerate(day_runs.itertuples() if not day_runs.empty else []):
            totals["runs"] += 1
            totals["run_km"] += float(r.distance_km)
            if used_run and i == 0:
                continue
            items.append({"type": "run", "planned": False, "title": "Lauf", "color": "grey",
                          "km": round(float(r.distance_km), 1), "minutes": round(float(r.dur_min)),
                          "avg_hr": round(float(r.avg_hr)) if pd.notna(r.avg_hr) else None, "href": "/laufen"})
        for w in workouts:
            if w["day"] != d:
                continue
            totals["gym_done"] += 1
            if w["id"] in used_workouts:
                continue
            items.append({"type": "strength", "planned": False, "title": w["title"], "color": "grey",
                          "program": w["program"], "minutes": w["minutes"], "href": "/kraft"})
        night = main_sleep.get(d)
        entry = entries.get(key) or {}
        out_days.append({
            "date": key, "weekday": WEEKDAYS[d.weekday()], "today": is_today, "past": past, "items": items,
            "context": {"sleep_h": round(night.asleep_minutes / 60, 1) if night and night.asleep_minutes else None,
                        "energy": entry.get("energy"), "sick": bool(entry.get("sick")),
                        "weather": forecast.get(key)},
        })
    form = _safe(lambda: _form(endurance, min(today, last), first), None)
    volume = _safe(lambda: strength_plan.weekly_volume(min(today, last)) if first <= today else None, None)
    totals["bike_planned_min"] = round(totals["bike_planned_min"])
    totals["bike_done_min"] = round(totals["bike_done_min"])
    totals["run_km"] = round(totals["run_km"], 1)
    week_warnings = [w for wk in plan.get("weeks") or [] for w in (wk.get("warnings") or [])
                     if wk["start"] <= last.isoformat() and wk["end"] >= first.isoformat()]
    return {
        "offset": offset, "from": first.isoformat(), "to": last.isoformat(), "today": today.isoformat(),
        "iso_week": first.isocalendar().week,
        "plan": {"name": plan["plan"]["name"], "week": next((w["week"] for w in plan.get("weeks") or []
                                                               if w["start"] <= first.isoformat() <= w["end"]), None),
                 "phase": next((w.get("phase") for w in plan.get("weeks") or []
                                if w["start"] <= first.isoformat() <= w["end"]), None),
                 "goal": next((w.get("goal") for w in plan.get("weeks") or []
                               if w["start"] <= first.isoformat() <= w["end"]), None)}
        if plan.get("plan") and in_plan else None,
        "days": out_days, "totals": totals, "max_hard": MAX_HARD,
        "hard_sets": _hard_sets(volume), "form": form, "warnings": week_warnings,
    }


def _bike_target(s: dict) -> str | None:
    if s["steering"] == "heart_rate" and s.get("hr"):
        lo, hi = s["hr"]
        return f"Puls {f'{lo:g}–' if lo else '< '}{hi:g} bpm"
    main = [st for st in s["steps"] if st.get("watts") and st.get("power_pct") and sum(st["power_pct"]) / 2 >= 76]
    if main:
        big = max(main, key=lambda st: sum(st["power_pct"]))
        n = sum(1 for st in main if st["label"] == big["label"] and st["power_pct"] == big["power_pct"])
        return f"{n}× {big['label']} {big['duration_min']:g} min @ {big['watts'][0]}–{big['watts'][1]} W" if n > 1 \
            else f"{big['label']} {big['watts'][0]}–{big['watts'][1]} W"
    return "Ramp-Test" if s["kind"] == "test" else None


def _form(endurance, day: date, first: date) -> dict | None:
    fit = endurance.fitness(days=max(14, (date.today() - first).days + 14), today=day)
    row = next((r for r in reversed(fit.get("series") or []) if r["date"] <= day.isoformat()), None)
    if row is None:
        return None
    return {"date": row["date"], "tsb": row["tsb"], "ctl": row["ctl"], "atl": row["atl"]}


def _hard_sets(volume: dict | None) -> dict | None:
    if not volume:
        return None
    muscles = volume.get("muscles") or []
    done = sum(m.get("this_week") or 0 for m in muscles)
    planned = sum(m.get("planned") or 0 for m in muscles)
    return {"done": round(done, 1), "planned": round(planned, 1)} if planned else None
