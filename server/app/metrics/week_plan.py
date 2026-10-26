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

import json

import pandas as pd
from sqlmodel import Field, Session, SQLModel, select

from .. import bike_plan
from ..config import settings
from ..db import engine
from ..models import Workout

WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
DEFAULT_GYM = {0: "ok", 2: "uk", 4: "ok"}  # außerhalb eines Rad-Plans
PROGRAM_TITLE = {"ok": "Milon OK", "uk": "Milon UK"}
MAX_HARD = 2
GYM_LABEL = {"ok": "Gym Oberkörper", "uk": "Gym Beine"}
HARD_RUN_SHARE = 0.80   # Lauf gilt als hart ab Ø-Puls ≥ 80 % HFmax (Z3+ wie running._ZONE_DEFS)
HARD_RIDE_IF = 0.85     # Fahrt gilt als hart ab IF 0,85 (NP/eFTP)
LEG_GAP_H = 6.0         # harte Ausdauer und Beintraining: mindestens 6 h Abstand (Robineau 2016)


class WeekGym(SQLModel, table=True):
    """Kraft-Tag außerhalb eines Rad-Plans: übersteuert das Standard-Schema (program 'ok'|'uk'|'none')."""
    __tablename__ = "week_gym"

    day: date = Field(primary_key=True)
    program: str


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


def _overrides(first: date, last: date) -> dict[str, str]:
    with Session(engine) as db:
        rows = db.exec(select(WeekGym).where(WeekGym.day >= first, WeekGym.day <= last)).all()
    return {r.day.isoformat(): r.program for r in rows}


def gym_program(day: date) -> str | None:
    """Geplantes Kraftprogramm eines Tages: Rad-Plan (falls aktiv) > eigene Übersteuerung > Standard-Schema."""
    plan = bike_plan.active_plan()
    if plan and plan.start <= day <= plan.end:
        weeks = json.loads(plan.weeks_json)
        return program_of(bike_plan._gym_map(weeks, bike_plan._sessions(plan.id)).get(day.isoformat()))
    override = _overrides(day, day).get(day.isoformat())
    if override is not None:
        return None if override == "none" else override
    return DEFAULT_GYM.get(day.weekday())


def set_gym(day: date, program: str | None) -> None:
    """Kraft-Tag setzen/löschen: im Rad-Plan als Gym-Label, sonst als eigene Übersteuerung."""
    if program not in ("ok", "uk", None):
        raise ValueError("Programm muss ok, uk oder leer sein.")
    plan = bike_plan.active_plan()
    if plan and plan.start <= day <= plan.end:
        bike_plan.set_gym(plan.id, day, GYM_LABEL.get(program) if program else None)
        return
    with Session(engine) as db:
        row = db.get(WeekGym, day) or WeekGym(day=day, program="none")
        row.program = program or "none"
        db.add(row)
        db.commit()


def move_gym(src: date, dst: date) -> None:
    """Kraft-Tag verschieben; liegt am Ziel schon einer, tauschen die beiden."""
    a, b = gym_program(src), gym_program(dst)
    if a is None:
        raise ValueError("Am Ausgangstag ist kein Krafttraining geplant.")
    set_gym(dst, a)
    set_gym(src, b)


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
             "program": kinds.get(w.id), "start": w.started_at.isoformat(),
             "end": (w.ended_at or w.started_at + timedelta(hours=1)).isoformat()} for w in rows if w.started_at]


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
    from . import cycling, endurance, running, sleep, strength_plan
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
    hr_max = _safe(lambda: running._resolved_hr_max(runs)[0], 180.0)
    intensity = _safe(lambda: {str(a): i for a, i in cycling._with_load(cycling.indoor_rides())[["activity_id", "intensity"]]
                               .itertuples(index=False) if pd.notna(i)}, {})
    overrides = _safe(lambda: _overrides(first - timedelta(days=1), last), {})
    bike_all = {s["date"]: s for w in plan.get("weeks") or [] for s in w["sessions"]}
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
                          "run_alternative": s["run_alternative"], "warnings": [],
                          "href": "/rad/plan", "zwo": s["id"] if s["zwo"] else None, "session_id": s["id"],
                          "hard": hard and color not in ("red", "sick", "skipped")})
            if not s["optional"] or s["status"] in ("done", "run"):
                totals["bike_planned"] += 0 if s["optional"] else 1
                totals["bike_planned_min"] += 0 if s["optional"] else (s["duration_min"] or 0)
            totals["bike_matched"] += s["status"] in ("done", "run")
            totals["hard_planned"] += hard
            totals["hard_done"] += hard and s["status"] in ("done", "run")
            totals["missed"] += color == "red"
        # Kraft (Soll aus Gym-Tagen)
        program = _program_for(d, plan_gym, in_plan, overrides)
        if program:
            done = [w for w in workouts if w["day"] == d]
            hit = next((w for w in done if w["program"] == program), None) or (done[0] if done else None)
            if hit:
                used_workouts.add(hit["id"])
            color = ("green" if hit["program"] in (program, None) else "yellow") if hit \
                else ("sick" if sick and (past or is_today) else "red" if past else "open")
            items.append({"type": "gym", "planned": True, "title": PROGRAM_TITLE[program], "program": program,
                          "label": plan_gym.get(key), "color": color, "done": hit, "day": key,
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
            start = pd.Timestamp(r.started_at)
            times = {"start": start.isoformat(), "end": (start + pd.Timedelta(minutes=float(r.minutes))).isoformat()}
            if rid is not None and rid == used_ride:
                items[0].update(times)  # geplante Rad-Einheit steht immer zuerst
                continue
            hard = (intensity.get(rid) or 0) >= HARD_RIDE_IF
            items.append({"type": "ride", "planned": False, "title": r.title, "color": "grey", "hard": hard,
                          "minutes": round(float(r.minutes)), "href": f"/rad/{rid}" if rid else "/gesundheit", **times})
        day_runs = runs[runs["day"] == d].sort_values("dur_min", ascending=False) if not runs.empty else runs
        for i, r in enumerate(day_runs.itertuples() if not day_runs.empty else []):
            totals["runs"] += 1
            totals["run_km"] += float(r.distance_km)
            times = {"start": pd.Timestamp(r.started_at).isoformat(), "end": pd.Timestamp(r.ended_at).isoformat()}
            if used_run and i == 0:
                items[0].update(times)
                continue
            hard = bool(pd.notna(r.avg_hr) and r.avg_hr >= HARD_RUN_SHARE * hr_max)
            items.append({"type": "run", "planned": False, "title": "Lauf", "color": "grey", "hard": hard,
                          "km": round(float(r.distance_km), 1), "minutes": round(float(r.dur_min)),
                          "avg_hr": round(float(r.avg_hr)) if pd.notna(r.avg_hr) else None, "href": "/laufen", **times})
        for w in workouts:
            if w["day"] != d:
                continue
            totals["gym_done"] += 1
            if w["id"] in used_workouts:
                continue
            items.append({"type": "strength", "planned": False, "title": w["title"], "color": "grey",
                          "program": w["program"], "minutes": w["minutes"], "href": "/kraft",
                          "start": w["start"], "end": w["end"]})
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
    before = first - timedelta(days=1)
    prev = bike_all.get(before.isoformat())
    prev_gym = {dd["date"]: dd["gym"] for wk in plan.get("weeks") or [] for dd in wk.get("days") or []}
    prev_in_plan = bool(plan.get("plan")) and plan["plan"]["start"] <= before.isoformat() <= plan["plan"]["end"]
    prev_leg = _program_for(before, prev_gym, {before.isoformat()} if prev_in_plan else set(), overrides) == "uk"
    hard_count = apply_rules(out_days, prev_hard=bool(prev and prev["kind"] in bike_plan.HARD_KINDS), prev_leg=prev_leg)
    totals["hard_done"] += sum(1 for dd in out_days for it in dd["items"] if not it["planned"] and it.get("hard"))
    week_warnings = [f"{hard_count} harte Einheiten (Rad + Lauf, Regel: höchstens {MAX_HARD} pro Woche)"] \
        if hard_count > MAX_HARD else []
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


def _program_for(d: date, plan_gym: dict, in_plan: set, overrides: dict) -> str | None:
    key = d.isoformat()
    if key in in_plan:
        return program_of(plan_gym.get(key))
    if key in overrides:
        return None if overrides[key] == "none" else overrides[key]
    return DEFAULT_GYM.get(d.weekday())


def _gap_hours(a: dict, b: dict) -> float | None:
    if not all(x.get(k) for x in (a, b) for k in ("start", "end")):
        return None
    sa, ea = datetime.fromisoformat(a["start"]), datetime.fromisoformat(a["end"])
    sb, eb = datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])
    return max(0.0, (max(sa, sb) - min(ea, eb)).total_seconds() / 3600)


def apply_rules(days: list[dict], prev_hard: bool = False, prev_leg: bool = False) -> int:
    """Regeln über Rad, Lauf und Kraft als Hinweise an harten Einheiten; liefert die Zahl harter Einheiten.
    Beintraining und harte Ausdauer: ≥ 6 h Abstand (Robineau 2016), sonst Kraft zuerst (Eddens 2018);
    harte Einheit nicht am Tag nach dem Beintag; keine zwei harten Tage hintereinander; Gym-Tag = Plan-Regel."""
    count = 0
    for day in days:
        hard = [it for it in day["items"] if it.get("hard")]
        gym = [it for it in day["items"] if it["type"] in ("gym", "strength") and it["color"] not in ("sick", "red")]
        legs = [it for it in gym if it.get("program") == "uk" or (it.get("done") or {}).get("program") == "uk"]
        timed = [it if it["type"] == "strength" else it["done"] for it in legs
                 if it["type"] == "strength" or it.get("done")]
        for it in hard:
            notes = it.setdefault("warnings", [])
            if legs:
                gaps = [g for g in (_gap_hours(it, leg) for leg in timed) if g is not None]
                if not gaps:
                    notes.append("Harte Einheit am Beintag: mindestens 6 h Abstand, Kraft zuerst")
                elif min(gaps) < LEG_GAP_H:
                    notes.append(f"Nur {min(gaps):.1f} h Abstand zum Beintraining (empfohlen ≥ 6 h)".replace(".", ","))
            elif gym:
                notes.append("Harte Einheit am Gym-Tag")
            if prev_leg:
                notes.append("Tag nach dem Beintag — Beine noch nicht erholt")
            if prev_hard:
                notes.append("Zwei harte Tage hintereinander")
        count += len(hard)
        prev_hard, prev_leg = bool(hard), bool(legs)
    return count


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


# ---------------- Heute dran (Etappe 3) ----------------
LOW_SLEEP_H = 6.0       # wie der Debuff „Übermüdet“
LOW_ENERGY = 2          # Check-in ≤ 2 = „Erschöpft“
TIRED_TSB = -25         # Form wie coach/rad.intensity_for_form: ≤ −25 → Z1/Ruhetag
RUN_WEATHER_RAIN = 40   # Lauf-Variante nur bei Regenwahrscheinlichkeit < 40 %


def _briefing_headline(day: date) -> str | None:
    """Erste Zeile des heutigen Morgenbriefings ohne „**Heute:**“."""
    from ..coach import briefing
    report = briefing.report_for(day)
    if not report or not report.content:
        return None
    first = report.content.strip().splitlines()[0]
    return first.replace("**Heute:**", "").replace("**", "").strip() or None


def adjustments(day: dict, form: dict | None) -> list[str]:
    """Vorlagen statt LLM: harte Einheit bei Müdigkeit locker fahren, bei gutem Wetter die Lauf-Variante."""
    ctx, out = day["context"], []
    reasons = []
    if ctx.get("sleep_h") is not None and ctx["sleep_h"] < LOW_SLEEP_H:
        reasons.append(f"nur {ctx['sleep_h']:g} h Schlaf".replace(".", ","))
    if ctx.get("energy") is not None and ctx["energy"] <= LOW_ENERGY:
        reasons.append(f"Energie {ctx['energy']}/5")
    if form and form.get("tsb") is not None and form["tsb"] <= TIRED_TSB:
        reasons.append(f"Form {form['tsb']:.0f}")
    open_items = [it for it in day["items"] if it["planned"] and it["color"] == "open"]
    for it in open_items:
        if it["type"] == "bike" and it.get("hard") and reasons:
            out.append(f"{it['title']} heute lieber locker: Z2 45–60 min nach Puls ({', '.join(reasons)}); "
                       "die harte Einheit auf einen frischen Tag schieben.")
        weather = ctx.get("weather") or {}
        if (it["type"] == "bike" and it.get("run_alternative") and it.get("kind") != "test" and weather.get("run")
                and (weather.get("rain_prob") or 0) < RUN_WEATHER_RAIN):
            run = weather["run"]
            out.append(f"Gutes Laufwetter {run['start'][11:16]}–{run['end'][11:16]}: statt Rad geht auch "
                       f"„{it['run_alternative']}“.")
    if reasons and not any(it.get("hard") for it in open_items) and open_items:
        out.append(f"Heute eher müde ({', '.join(reasons)}): locker bleiben, Puls-Deckel ernst nehmen.")
    return out


def today_focus(today: date | None = None) -> dict:
    """„Heute dran“: offene und erledigte Einheiten von heute, Anpassungen, Kontext, Briefing-Überschrift."""
    today = _today(today)
    w = week(0, today=today)
    day = next(d for d in w["days"] if d["date"] == today.isoformat())
    planned = [it for it in day["items"] if it["planned"]]
    open_items = [it for it in planned if it["color"] == "open"]
    done = [it for it in day["items"] if it not in open_items]
    if day["context"]["sick"]:
        status = "sick"
    elif not planned:
        status = "rest"
    elif not open_items:
        status = "done"
    else:
        status = "open"
    return {
        "date": today.isoformat(), "weekday": day["weekday"], "status": status,
        "headline": _safe(lambda: _briefing_headline(today), None),
        "open": open_items, "done": done, "adjustments": [] if status == "sick" else adjustments(day, w["form"]),
        "warnings": sorted({x for it in open_items for x in it.get("warnings") or []}),
        "context": day["context"], "form": w["form"],
        "week": {"totals": w["totals"], "warnings": w["warnings"], "plan": w["plan"]},
    }


def _item_text(it: dict) -> str:
    if it["type"] == "bike":
        return f"{it['title']} ({', '.join(x for x in (f'{it['duration_min']:g} min' if it.get('duration_min') else None, it.get('target')) if x)})"
    if it["type"] == "gym":
        return it["title"] + (f": {'; '.join(it['prescription'][:4])}" if it.get("prescription") else "")
    return it["title"]


def briefing_lines(day: date) -> list[str]:
    """Faktenzeilen fürs Morgenbriefing aus der Wochenseite: Stand der Woche, Kraft heute, Regel-Hinweise."""
    f = today_focus(day)
    t = f["week"]["totals"]
    lines = [f"WOCHE BISHER (erledigt bis heute von geplant Mo–So): Rad {t['bike_done_min']} von {t['bike_planned_min']} min, "
             f"Kraft {t['gym_matched']} von {t['gym_planned']} nach Plan, harte Einheiten {t['hard_done']} von {t['hard_planned']} "
             f"(Regel höchstens {MAX_HARD}), verpasst {t['missed']}."]
    gym = [it for it in f["open"] if it["type"] == "gym"]
    if gym:
        lines.append("KRAFT HEUTE: " + _item_text(gym[0]) + ".")
    notes = f["warnings"] + f["week"]["warnings"]
    if notes:
        lines.append("REGEL-HINWEISE: " + "; ".join(notes) + ".")
    if f["adjustments"]:
        lines.append("ANPASSUNG (aus Schlaf/Check-in/Form/Wetter): " + " ".join(f["adjustments"]))
    return lines


def compact(offset: int = 0, today: date | None = None) -> dict:
    """Wochenplan für Coach/MCP: Summen, Hinweise, je Tag die Einheiten mit Status (ohne Gewichte/Serien)."""
    w = week(offset, today=today)
    keep = ("type", "title", "color", "status", "duration_min", "target", "hard", "warnings", "km", "minutes")
    return {"from": w["from"], "to": w["to"], "plan": w["plan"], "totals": w["totals"], "hard_sets": w["hard_sets"],
            "form": w["form"], "warnings": w["warnings"],
            "days": [{"date": d["date"], "weekday": d["weekday"], "sick": d["context"]["sick"],
                      "sleep_h": d["context"]["sleep_h"],
                      "items": [{k: it.get(k) for k in keep if it.get(k) not in (None, [], "")} for it in d["items"]]}
                     for d in w["days"]],
            "hinweis": "color: green=im Soll, yellow/orange=teilweise/daneben, red=verpasst, grey=ungeplant, "
                       "sick=Krankheitstag (pausiert, kein Versäumnis), open=offen. Last nie über Sportarten addieren."}
