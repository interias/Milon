"""Rad-Trainingsplan: importierter Block (Plan → Woche → Einheit → Schritte), Plan-FTP,
Abgleich mit Fahrten/Läufen, Ausführung aus der Sekunden-Serie, Messpunkte und .zwo-Export.

Watt stehen im Plan nur als Anteil der FTP (power_pct) und werden immer aus der Plan-FTP am
jeweiligen Tag gerechnet: Handwert > erkannter Ramp-Test (75 % der besten Minute) > Startwert
des Plans. Der Plan liegt nur in der lokalen DB (persönliche Werte, Repo ist öffentlich).
Das Modell ist allgemein gehalten, damit Editor und Generator später dieselben Tabellen schreiben."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlmodel import Field, Session, SQLModel, delete, select

from . import garmin_indoor
from .config import settings
from .db import engine

MAX_IMPORT_BYTES = 5 * 1024 * 1024
HR_TRIM_S = 300             # Z2-Ausführung ohne Ein-/Ausrollen
POWER_TOLERANCE = 0.05      # Intervall getroffen: 10-s-Mittel im Zielband ±5 %
ALIGN_MAX_S = 900           # Workout darf bis 15 min nach Fahrtbeginn starten
_AGENT_JSON = re.compile(r'<script[^>]*id="agent-context"[^>]*>(.*?)</script>', re.S)
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


class Duplicate(ValueError):
    """Gleicher Plan schon importiert."""


class BikePlan(SQLModel, table=True):
    __tablename__ = "bike_plans"

    id: str = Field(primary_key=True)          # plan-<sha12> des Inhalts
    name: str
    start: date
    end: date
    ftp_default: float
    active: bool = True
    imported_at: datetime
    meta_json: str = "{}"                      # alles außer plan[] (Zonen, Regeln, Metriken, Hintergrund)
    weeks_json: str = "[]"                     # [{week, start, end, phase, goal}]


class BikePlanSession(SQLModel, table=True):
    __tablename__ = "bike_plan_sessions"

    id: int | None = Field(default=None, primary_key=True)
    plan_id: str = Field(index=True)
    week: int
    day: date = Field(index=True)
    gym: str | None = None
    title: str
    kind: str                                  # z2 | z2_optional | hard | test | …
    optional: bool = False
    steering: str | None = None                # heart_rate | power_erg
    hr_min: float | None = None
    hr_max: float | None = None
    duration_min: float | None = None
    steps_json: str = "[]"                     # [{label, duration_min, power_pct:[lo,hi], cadence_rpm}]
    run_alternative: str | None = None
    note: str | None = None
    zwift_workout: str | None = None


class BikePlanFtp(SQLModel, table=True):
    __tablename__ = "bike_plan_ftp"

    id: int | None = Field(default=None, primary_key=True)
    plan_id: str = Field(index=True)
    day: date
    watts: float


class BikePlanCheckpoint(SQLModel, table=True):
    __tablename__ = "bike_plan_checkpoints"

    plan_id: str = Field(primary_key=True)
    checkpoint: str = Field(primary_key=True)  # start | w4 | w8
    key: str = Field(primary_key=True)
    value: float
    estimated: bool = False


def _today(today: date | None = None) -> date:
    return today or datetime.now(ZoneInfo(settings.timezone)).date()


def _r(value, digits: int = 0):
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return round(float(value), digits) if digits else int(round(float(value)))


# ---------------- Import ----------------
def _extract(content: bytes) -> dict:
    text = content.decode("utf-8-sig", errors="replace").strip()
    if not text.startswith("{"):
        match = _AGENT_JSON.search(text)
        if not match:
            raise ValueError("Keine Plandaten gefunden — erwartet wird JSON oder eine HTML-Datei mit #agent-context.")
        text = match.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Plandaten sind kein gültiges JSON ({exc.msg}).") from exc
    if not isinstance(data, dict) or not isinstance(data.get("plan"), list) or not data["plan"]:
        raise ValueError("Plandaten ohne Wochen (Feld „plan“ fehlt oder ist leer).")
    return data


def _steps(raw: list) -> list[dict]:
    out = []
    for step in raw or []:
        pct = step.get("power_pct")
        cad = step.get("cadence_rpm") or {}
        out.append({
            "label": str(step.get("label") or ""),
            "duration_min": float(step["duration_min"]) if step.get("duration_min") else None,
            "power_pct": [float(pct[0]), float(pct[-1])] if isinstance(pct, list) and pct else None,
            "cadence": [cad.get("min"), cad.get("max")] if cad else None,
        })
    return out


def import_plan(content: bytes) -> dict:
    """Plan aus JSON oder HTML (mit #agent-context) übernehmen und aktiv setzen."""
    if len(content) > MAX_IMPORT_BYTES:
        raise ValueError("Datei ist zu groß (max. 5 MB).")
    data = _extract(content)
    plan_id = "plan-" + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]
    sessions, weeks = [], []
    for w in data["plan"]:
        try:
            number, start, end = int(w["week"]), date.fromisoformat(w["start"]), date.fromisoformat(w["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Jede Woche braucht week, start und end (JJJJ-MM-TT).") from exc
        gym = {d["date"]: str(d["gym"]) for d in w.get("days") or [] if d.get("gym") and d.get("date")}
        weeks.append({"week": number, "start": start.isoformat(), "end": end.isoformat(),
                      "phase": w.get("phase"), "goal": w.get("goal"), "gym": gym})
        for d in w.get("days") or []:
            s = d.get("session")
            if not s:
                continue
            hr = s.get("hr_target_bpm") or {}
            sessions.append(BikePlanSession(
                plan_id=plan_id, week=number, day=date.fromisoformat(d["date"]), gym=d.get("gym"),
                title=str(s.get("title") or "Einheit"), kind=str(s.get("kind") or "z2"),
                optional=bool(s.get("optional")), steering=s.get("steering"),
                hr_min=hr.get("min"), hr_max=hr.get("max"), duration_min=s.get("duration_min"),
                steps_json=json.dumps(_steps(s.get("steps"))), run_alternative=s.get("run_alternative"),
                note=s.get("note"), zwift_workout=s.get("zwift_workout")))
    if not sessions:
        raise ValueError("Der Plan enthält keine Einheiten.")
    ftp = (data.get("ftp") or {}).get("value_w")
    meta = {k: v for k, v in data.items() if k != "plan"}
    with Session(engine) as db:
        if db.get(BikePlan, plan_id):
            raise Duplicate("Dieser Plan ist schon importiert.")
        for other in db.exec(select(BikePlan).where(BikePlan.active)).all():
            other.active = False
            db.add(other)
        plan = BikePlan(id=plan_id, name=str(data.get("title") or "Rad-Grundlagenblock"),
                        start=date.fromisoformat(weeks[0]["start"]), end=date.fromisoformat(weeks[-1]["end"]),
                        ftp_default=float(ftp) if ftp else 200.0, imported_at=datetime.now(),
                        meta_json=json.dumps(meta, ensure_ascii=False), weeks_json=json.dumps(weeks))
        name = plan.name
        db.add(plan)
        db.add_all(sessions)
        db.commit()
    return {"id": plan_id, "name": name, "weeks": len(weeks), "sessions": len(sessions)}


def delete_plan(plan_id: str) -> bool:
    with Session(engine) as db:
        plan = db.get(BikePlan, plan_id)
        if not plan:
            return False
        for model in (BikePlanSession, BikePlanFtp, BikePlanCheckpoint):
            db.exec(delete(model).where(model.plan_id == plan_id))
        db.delete(plan)
        db.commit()
    return True


def active_plan() -> BikePlan | None:
    with Session(engine) as db:
        return db.exec(select(BikePlan).where(BikePlan.active).order_by(BikePlan.imported_at.desc())).first()


def _sessions(plan_id: str) -> list[BikePlanSession]:
    with Session(engine) as db:
        return list(db.exec(select(BikePlanSession).where(BikePlanSession.plan_id == plan_id)
                            .order_by(BikePlanSession.day)).all())


# ---------------- Plan-FTP ----------------
def _rides() -> pd.DataFrame:
    from .metrics import cycling  # lazy: Metrik-Schicht lädt Körperdaten
    return cycling.indoor_rides()


def ftp_history(plan: BikePlan, rides: pd.DataFrame | None = None) -> list[dict]:
    """Alle FTP-Stände chronologisch: Startwert, erkannte Ramp-Tests, Handwerte."""
    from .metrics import cycling  # gleiche Ramp-Erkennung wie Milons eFTP
    rides = _rides() if rides is None else rides
    entries = [{"date": plan.start.isoformat(), "watts": plan.ftp_default, "source": "plan", "id": None}]
    if not rides.empty:
        for _, r in rides[rides["day"] >= plan.start - timedelta(days=60)].iterrows():
            best_min = (r["power_curve"] or {}).get(60)
            if cycling.RAMP_TITLE.search(str(r["title"] or "")) and best_min:
                entries.append({"date": r["day"].isoformat(), "watts": float(round(cycling.RAMP_FACTOR * best_min)),
                                "source": "ramp", "id": str(r["activity_id"])})
    with Session(engine) as db:
        for m in db.exec(select(BikePlanFtp).where(BikePlanFtp.plan_id == plan.id)).all():
            entries.append({"date": m.day.isoformat(), "watts": m.watts, "source": "manual", "id": m.id})
    order = {"plan": 0, "ramp": 1, "manual": 2}
    return sorted(entries, key=lambda e: (e["date"], order[e["source"]]))


def ftp_at(history: list[dict], day: date) -> dict:
    valid = [e for e in history if e["date"] <= day.isoformat()]
    return valid[-1] if valid else history[0]


def set_manual_ftp(plan_id: str, watts: float, day: date | None = None) -> None:
    with Session(engine) as db:
        db.add(BikePlanFtp(plan_id=plan_id, day=_today(day), watts=watts))
        db.commit()


def delete_manual_ftp(entry_id: int) -> bool:
    with Session(engine) as db:
        entry = db.get(BikePlanFtp, entry_id)
        if not entry:
            return False
        db.delete(entry)
        db.commit()
    return True


def _watts(step: dict, ftp: float) -> list[int] | None:
    pct = step.get("power_pct")
    return [_r(pct[0] * ftp / 100), _r(pct[1] * ftp / 100)] if pct else None


# ---------------- Editor ----------------
KINDS = ("z2", "z2_optional", "hard", "test")
STEERINGS = ("heart_rate", "power_erg")
HARD_KINDS = ("hard", "test")
DEFAULT_STEPS = [{"label": "Einrollen", "duration_min": 5, "power_pct": [40, 50], "cadence": [85, 90]},
                 {"label": "Z2", "duration_min": 50, "power_pct": [55, 64], "cadence": [85, 90]},
                 {"label": "Ausrollen", "duration_min": 5, "power_pct": [40, 50], "cadence": [85, 90]}]


class Conflict(ValueError):
    """Tag schon belegt."""


def _num(value, lo: float, hi: float, what: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what}: keine Zahl.") from exc
    if not (lo <= number <= hi) or not math.isfinite(number):
        raise ValueError(f"{what}: erlaubt {lo:g}–{hi:g}.")
    return number


def clean_steps(raw) -> list[dict]:
    """Schritte aus dem Editor prüfen: Bezeichnung, Dauer (min), Leistung in % FTP, Trittfrequenz."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= 60:
        raise ValueError("Eine Einheit braucht 1–60 Schritte.")
    out = []
    for i, step in enumerate(raw, 1):
        label = str((step or {}).get("label") or "").strip()[:60]
        if not label:
            raise ValueError(f"Schritt {i}: Bezeichnung fehlt.")
        pct = step.get("power_pct")
        if pct is not None:
            if not isinstance(pct, list) or len(pct) != 2:
                raise ValueError(f"Schritt {i}: Leistung als [von, bis] in % FTP.")
            pct = [_num(pct[0], 0, 250, f"Schritt {i} Leistung"), _num(pct[1], 0, 250, f"Schritt {i} Leistung")]
            if None in pct or pct[0] > pct[1]:
                raise ValueError(f"Schritt {i}: Leistung „von“ muss ≤ „bis“ sein.")
        cad = step.get("cadence") or [None, None]
        cad = [_num(cad[0], 30, 150, f"Schritt {i} Trittfrequenz"), _num(cad[1] if len(cad) > 1 else None, 30, 150, f"Schritt {i} Trittfrequenz")]
        out.append({"label": label, "duration_min": _num(step.get("duration_min"), 0.25, 600, f"Schritt {i} Dauer"),
                    "power_pct": pct, "cadence": cad if any(c is not None for c in cad) else None})
    return out


def _week_of(plan: BikePlan, day: date) -> int:
    return (day - plan.start).days // 7 + 1


def _total(steps: list[dict]) -> float | None:
    return sum(st["duration_min"] for st in steps) if all(st.get("duration_min") for st in steps) else None


def update_session(session_id: int, changes: dict) -> None:
    """Felder ändern; ein neuer Tag auf einem belegten Tag tauscht die beiden Einheiten."""
    with Session(engine) as db:
        s = db.get(BikePlanSession, session_id)
        if s is None:
            raise KeyError(session_id)
        plan = db.get(BikePlan, s.plan_id)
        _ensure_gym(db, plan)
        if "title" in changes:
            title = str(changes["title"] or "").strip()[:80]
            if not title:
                raise ValueError("Titel fehlt.")
            s.title = title
        if "kind" in changes:
            if changes["kind"] not in KINDS:
                raise ValueError("Unbekannte Art.")
            s.kind = changes["kind"]
            s.optional = changes["kind"] == "z2_optional" or bool(changes.get("optional", s.optional))
        if "optional" in changes:
            s.optional = bool(changes["optional"])
        if "steering" in changes:
            if changes["steering"] not in (*STEERINGS, None):
                raise ValueError("Unbekannte Steuerung.")
            s.steering = changes["steering"]
        for key in ("hr_min", "hr_max"):
            if key in changes:
                setattr(s, key, _num(changes[key], 60, 220, "Puls"))
        if s.hr_min and s.hr_max and s.hr_min > s.hr_max:
            raise ValueError("Puls „von“ muss ≤ „bis“ sein.")
        if "steps" in changes:
            steps = clean_steps(changes["steps"])
            s.steps_json = json.dumps(steps)
            s.duration_min = _total(steps) or s.duration_min
        if "duration_min" in changes and _total(json.loads(s.steps_json)) is None:
            s.duration_min = _num(changes["duration_min"], 1, 600, "Dauer")
        for key in ("run_alternative", "note", "zwift_workout"):
            if key in changes:
                setattr(s, key, (str(changes[key]).strip()[:300] or None) if changes[key] is not None else None)
        if changes.get("day"):
            day = date.fromisoformat(str(changes["day"]))
            if not plan.start <= day <= plan.end:
                raise ValueError("Der Tag liegt außerhalb des Plans.")
            if day != s.day:
                other = db.exec(select(BikePlanSession).where(BikePlanSession.plan_id == s.plan_id,
                                                              BikePlanSession.day == day)).first()
                if other is not None:
                    other.day, other.week = s.day, _week_of(plan, s.day)
                    db.add(other)
                s.day, s.week = day, _week_of(plan, day)
        db.add(s)
        db.commit()


def create_session(plan_id: str, day: date, copy_from: int | None = None) -> int:
    with Session(engine) as db:
        plan = db.get(BikePlan, plan_id)
        if plan is None:
            raise KeyError(plan_id)
        if not plan.start <= day <= plan.end:
            raise ValueError("Der Tag liegt außerhalb des Plans.")
        if db.exec(select(BikePlanSession).where(BikePlanSession.plan_id == plan_id, BikePlanSession.day == day)).first():
            raise Conflict("An diesem Tag gibt es schon eine Einheit.")
        src = db.get(BikePlanSession, copy_from) if copy_from else None
        if src is not None and src.plan_id == plan_id:
            fields = src.model_dump(exclude={"id", "day", "week", "gym"})
        else:
            fields = {"plan_id": plan_id, "title": "Z2", "kind": "z2", "steering": "heart_rate", "hr_min": 115,
                      "hr_max": 125, "duration_min": 60, "steps_json": json.dumps(DEFAULT_STEPS)}
        new = BikePlanSession(**fields, day=day, week=_week_of(plan, day))
        db.add(new)
        db.commit()
        db.refresh(new)
        return new.id


def delete_session(session_id: int) -> bool:
    with Session(engine) as db:
        s = db.get(BikePlanSession, session_id)
        if s is None:
            return False
        _ensure_gym(db, db.get(BikePlan, s.plan_id))
        db.delete(s)
        db.commit()
    return True


def set_gym(plan_id: str, day: date, label: str | None) -> None:
    """Gym-Tag setzen oder löschen (Plan-Seite; echte Krafttrainings kommen zusätzlich aus Hevy)."""
    label = (label or "").strip()[:40] or None
    with Session(engine) as db:
        plan = db.get(BikePlan, plan_id)
        if plan is None:
            raise KeyError(plan_id)
        weeks = json.loads(plan.weeks_json)
        sessions = db.exec(select(BikePlanSession).where(BikePlanSession.plan_id == plan_id)).all()
        for w in weeks:
            if w["start"] <= day.isoformat() <= w["end"]:
                gym = w.get("gym") if "gym" in w else _legacy_gym(w, sessions)
                gym.pop(day.isoformat(), None)
                if label:
                    gym[day.isoformat()] = label
                w["gym"] = gym
                break
        else:
            raise ValueError("Der Tag liegt außerhalb des Plans.")
        for s in sessions:
            if s.day == day:
                s.gym = label
                db.add(s)
        plan.weeks_json = json.dumps(weeks)
        db.add(plan)
        db.commit()


def _ensure_gym(db: Session, plan: BikePlan) -> None:
    """Gym-Tage aus der ersten Fassung (an der Einheit) einmalig an den Tag schreiben, bevor
    Einheiten verschoben oder gelöscht werden — sonst wanderte das Gym mit der Einheit."""
    weeks = json.loads(plan.weeks_json)
    if all("gym" in w for w in weeks):
        return
    sessions = db.exec(select(BikePlanSession).where(BikePlanSession.plan_id == plan.id)).all()
    for w in weeks:
        w.setdefault("gym", _legacy_gym(w, sessions))
    plan.weeks_json = json.dumps(weeks)
    db.add(plan)


def _legacy_gym(week: dict, sessions) -> dict:
    """Pläne aus der ersten Fassung kennen Gym nur an Tagen mit Einheit."""
    return {s.day.isoformat(): s.gym for s in sessions
            if s.gym and week["start"] <= s.day.isoformat() <= week["end"]}


def _gym_map(weeks: list[dict], sessions) -> dict[str, str]:
    out: dict[str, str] = {}
    for w in weeks:
        out.update(w["gym"] if "gym" in w else _legacy_gym(w, sessions))
    return out


def _hevy_days(start: date, end: date) -> dict[str, str]:
    """Tatsächliche Krafttrainings (Hevy) je Tag im Planzeitraum."""
    from .models import Workout
    with Session(engine) as db:
        rows = db.exec(select(Workout).where(Workout.started_at >= datetime.combine(start, datetime.min.time()),
                                             Workout.started_at < datetime.combine(end + timedelta(days=1),
                                                                                   datetime.min.time()))).all()
    return {w.started_at.date().isoformat(): (w.title or "Krafttraining") for w in rows if w.started_at}


def _warnings(sessions: list[dict], gym: dict[str, str], hevy: dict[str, str], hard_days: set[str]) -> None:
    """Regeln des Plans als Hinweise an Einheit (hart am Gym-Tag, Tag nach Beintag, zwei harte Tage
    hintereinander) und Woche (mehr als 2 harte Einheiten)."""
    for s in sessions:
        s["warnings"] = []
        if s["kind"] not in HARD_KINDS:
            continue
        today_gym = hevy.get(s["date"]) or gym.get(s["date"])
        before = (date.fromisoformat(s["date"]) - timedelta(days=1)).isoformat()
        prev_gym = hevy.get(before) or gym.get(before) or ""
        if today_gym:
            s["warnings"].append(f"Harte Einheit am Gym-Tag ({today_gym})")
        if "bein" in prev_gym.lower() or "leg" in prev_gym.lower() or "uk" in prev_gym.lower().split():
            s["warnings"].append("Tag nach dem Beintag — Beine noch nicht erholt")
        if before in hard_days:
            s["warnings"].append("Zwei harte Tage hintereinander")


# ---------------- Ausführung aus der Sekunden-Serie ----------------
def _hr_execution(series: dict, lo: float | None, hi: float | None) -> dict | None:
    hr = garmin_indoor.grid(series, "hr_bpm") if series.get("hr_bpm") else np.array([])
    if hr.size > 2 * HR_TRIM_S + 600:
        hr = hr[HR_TRIM_S:-HR_TRIM_S]
    hr = hr[~np.isnan(hr)]
    if hr.size < 300:
        return None
    lo_v, hi_v = lo or 0, hi or 999
    return {"type": "hr_band", "band": [lo, hi], "minutes": round(hr.size / 60),
            "in_band_pct": _r(((hr >= lo_v) & (hr <= hi_v)).mean() * 100),
            "below_pct": _r((hr < lo_v).mean() * 100), "above_pct": _r((hr > hi_v).mean() * 100),
            "avg_hr": _r(hr.mean())}


def _rolling(values: np.ndarray, window: int = 10) -> np.ndarray:
    filled = np.nan_to_num(values, nan=0.0)
    total = np.concatenate([[0.0], np.cumsum(filled)])
    out = np.full(values.size, np.nan)
    if values.size >= window:
        out[window - 1:] = (total[window:] - total[:-window]) / window
    return out


def _power_execution(series: dict, steps: list[dict], ftp: float) -> dict | None:
    """Plan-Schritte gegen das 10-s-Leistungsmittel legen; der Workout-Start wird per Verschiebung
    (0–15 min) gesucht. Getroffen = im Zielband ±5 %. Bewertet werden die Schritte über Z2."""
    if not series.get("power_w"):
        return None
    power = _rolling(garmin_indoor.grid(series, "power_w"))
    lo, hi, key, idx = [], [], [], []
    for i, step in enumerate(steps):
        seconds = int(round((step.get("duration_min") or 0) * 60))
        watts = _watts(step, ftp)
        mid = sum(step["power_pct"]) / 2 if step.get("power_pct") else 0
        lo += [watts[0] * (1 - POWER_TOLERANCE) if watts else np.nan] * seconds
        hi += [watts[1] * (1 + POWER_TOLERANCE) if watts else np.nan] * seconds
        key += [mid >= 76] * seconds
        idx += [i] * seconds
    lo, hi, key, idx = np.array(lo), np.array(hi), np.array(key, bool), np.array(idx)
    if not lo.size or not key.any() or power.size < 120:
        return None
    best_shift, best_score = 0, -1
    for shift in range(0, min(ALIGN_MAX_S, max(0, power.size - lo.size // 2)) + 1, 5):
        seg = power[shift:shift + lo.size]
        n = seg.size
        score = int(np.sum((seg >= lo[:n]) & (seg <= hi[:n])))
        if score > best_score:
            best_shift, best_score = shift, score
    seg = power[best_shift:best_shift + lo.size]
    n = seg.size
    hit = (seg >= lo[:n]) & (seg <= hi[:n])
    rows, count = [], {}
    for i, step in enumerate(steps):
        planned = (idx == i) & key
        if not planned.any():
            continue
        sel = planned[:n]
        covered = int(sel.sum())
        count[step["label"]] = count.get(step["label"], 0) + 1
        rows.append({"label": f"{step['label']} {count[step['label']]}", "target_w": _watts(step, ftp),
                     "avg_w": _r(np.nanmean(seg[sel])) if covered else None,
                     "in_band_pct": _r(hit[sel].mean() * 100) if covered else None,
                     "covered_pct": _r(covered / int(planned.sum()) * 100)})
    key_n = key[:n]
    return {"type": "intervals", "shift_s": best_shift,
            "hit_pct": _r(hit[key_n].mean() * 100) if key_n.any() else None,
            "covered_pct": _r(key_n.sum() / key.sum() * 100), "steps": rows}


# ---------------- Abgleich mit Fahrten und Läufen ----------------
def _runs() -> pd.DataFrame:
    from .metrics import running
    df = running._runs()
    if not df.empty:
        df["day"] = df["started_at"].dt.date
    return df


def _pick_ride(kind: str, day_rides: pd.DataFrame):
    """Passende Fahrt eines Tages mit mehreren Fahrten: Test = Ramp-Titel, hart = höchste NP, sonst die längste
    Fahrt ohne Ramp-Test."""
    from .metrics import cycling
    ramp = day_rides["title"].fillna("").astype(str).str.contains(cycling.RAMP_TITLE)
    power = day_rides["norm_power_w"].fillna(day_rides["avg_power_w"]).fillna(0)
    by_len = day_rides.assign(_p=power).sort_values(["duration_seconds", "_p"], ascending=False)
    if kind == "test" and ramp.any():
        return by_len[ramp.loc[by_len.index]].iloc[0]
    if kind in HARD_KINDS:
        return by_len.sort_values("_p", ascending=False, kind="stable").iloc[0]
    easy = by_len[~ramp.loc[by_len.index]]
    return (easy if not easy.empty else by_len).iloc[0]


def _match(sessions: list[BikePlanSession], rides: pd.DataFrame, runs: pd.DataFrame, today: date) -> dict:
    """Je Einheit die passende Fahrt (`_pick_ride`) bzw. (sonst) den längsten Lauf desselben Tages."""
    rides_by_day = dict(iter(rides.groupby("day"))) if not rides.empty else {}
    runs_by_day = ({d: g.sort_values("dur_min", ascending=False).iloc[0] for d, g in runs.groupby("day")}
                   if not runs.empty else {})
    out = {}
    for s in sessions:
        day_rides = rides_by_day.get(s.day)
        ride = _pick_ride(s.kind, day_rides) if day_rides is not None else None
        run = runs_by_day.get(s.day)
        if ride is not None:
            status = "done"
        elif run is not None and s.kind != "test":
            status = "run"
        elif s.day < today:
            status = "skipped" if s.optional else "missed"
        else:
            status = "today" if s.day == today else "planned"
        out[s.id] = (status, ride if status == "done" else None, run if status == "run" else None)
    return out


def _session_dict(s: BikePlanSession, ftp: dict, status: str, ride, run, execution) -> dict:
    steps = json.loads(s.steps_json)
    return {
        "id": s.id, "date": s.day.isoformat(), "weekday": WEEKDAYS[s.day.weekday()], "week": s.week, "gym": s.gym,
        "title": s.title, "kind": s.kind, "optional": s.optional, "steering": s.steering,
        "hr": [s.hr_min, s.hr_max] if (s.hr_min or s.hr_max) else None, "duration_min": s.duration_min,
        "steps": [{**st, "watts": _watts(st, ftp["watts"])} for st in steps],
        "run_alternative": s.run_alternative, "note": s.note, "zwift_workout": s.zwift_workout,
        "ftp": ftp["watts"],
        "zwo": s.kind != "test" and any(st.get("power_pct") and st.get("duration_min") for st in steps),
        "status": status, "execution": execution,
        "ride": None if ride is None else {
            "activity_id": str(ride["activity_id"]), "title": ride["title"],
            "minutes": _r((ride["duration_seconds"] or 0) / 60), "np": _r(ride["norm_power_w"]),
            "avg_power": _r(ride["avg_power_w"]), "avg_hr": _r(ride["avg_hr"]) if ride["hr_valid"] else None},
        "run": None if run is None else {
            "minutes": _r(run["dur_min"]), "km": _r(run["distance_km"], 1), "avg_hr": _r(run["avg_hr"])},
    }


def _execution(s: BikePlanSession, ride, series: dict, history: list[dict], ftp: float) -> dict | None:
    if s.kind == "test":
        entry = next((e for e in history if e["source"] == "ramp" and e["id"] == str(ride["activity_id"])), None)
        return {"type": "test", "ftp": entry["watts"] if entry else None}
    if s.steering == "heart_rate":
        return _hr_execution(series, s.hr_min, s.hr_max) if ride["hr_valid"] else {"type": "hr_invalid"}
    return _power_execution(series, json.loads(s.steps_json), ftp)


def overview(today: date | None = None) -> dict:
    """Aktiver Plan mit Wochen, Einheiten (Watt aus der Plan-FTP am Tag), Status und Ausführung."""
    from .metrics import cycling
    today = _today(today)
    plan = active_plan()
    if plan is None:
        return {"plan": None}
    meta, weeks = json.loads(plan.meta_json), json.loads(plan.weeks_json)
    rides, runs, sessions = _rides(), _runs(), _sessions(plan.id)
    history = ftp_history(plan, rides)
    current = ftp_at(history, today)
    matched = _match(sessions, rides, runs, today)
    done = [ride for status, ride, _ in matched.values() if status == "done"]
    series: dict = {}
    if done:
        attached = cycling._attach_series(pd.DataFrame(done))
        series = dict(zip(attached["activity_id"].astype(str), attached["series"]))
    by_week: dict[int, list] = {}
    for s in sessions:
        status, ride, run = matched[s.id]
        ftp = ftp_at(history, s.day)
        execution = _execution(s, ride, series.get(str(ride["activity_id"]), {}), history, ftp["watts"]) \
            if status == "done" else None
        by_week.setdefault(s.week, []).append(_session_dict(s, ftp, status, ride, run, execution))
    gym, hevy = _gym_map(weeks, sessions), _hevy_days(plan.start, min(plan.end, today))
    hard_days = {s.day.isoformat() for s in sessions if s.kind in HARD_KINDS}
    for w in weeks:
        w.pop("gym", None)
        start = date.fromisoformat(w["start"])
        w["days"] = [{"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()], "gym": gym.get(d.isoformat()),
                      "hevy": hevy.get(d.isoformat())}
                     for d in (start + timedelta(days=i) for i in range(7)) if d.isoformat() <= w["end"]]
        week_sessions = by_week.get(w["week"], [])
        for x in week_sessions:
            x["gym"] = gym.get(x["date"])
        _warnings(week_sessions, gym, hevy, hard_days)
        hard = sum(x["kind"] in HARD_KINDS for x in week_sessions)
        w["warnings"] = [f"{hard} harte Einheiten (Regel: höchstens 2 pro Woche)"] if hard > 2 else []
    weight = cycling._weight_at(cycling._weights(), today)
    zones = [{"zone": z.get("zone"), "from_pct": z.get("from_pct"), "to_pct": z.get("to_pct"),
              "watts": [_r(z.get("from_pct", 0) * current["watts"] / 100),
                        _r(z.get("to_pct", 0) * current["watts"] / 100)]}
             for z in meta.get("power_zones_pct_ftp") or []]
    all_s = [x for ws in by_week.values() for x in ws]
    core = [x for x in all_s if not x["optional"]]
    return {
        "plan": {"id": plan.id, "name": plan.name, "start": plan.start.isoformat(), "end": plan.end.isoformat(),
                 "imported_at": plan.imported_at.isoformat()},
        "today": today.isoformat(),
        "ftp": {**current, "wkg": round(current["watts"] / weight, 2) if weight else None, "history": history},
        "zones": zones,
        "hr_targets": meta.get("hr_targets_bpm"),
        "weeks": [{**w, "sessions": by_week.get(w["week"], []),
                   "current": w["start"] <= today.isoformat() <= w["end"]} for w in weeks],
        "progress": {"core": len(core), "core_done": sum(x["status"] in ("done", "run") for x in core),
                     "optional_done": sum(x["status"] in ("done", "run") for x in all_s if x["optional"]),
                     "missed": sum(x["status"] == "missed" for x in all_s)},
        "background": {k: meta.get(k) for k in ("weekly_template", "in_ride_rules", "zwift", "expectations",
                                                "evidence", "open_points")},
    }


def briefing_line(day: date) -> str | None:
    """Faktenzeile fürs Morgenbriefing: Einheit des Tages mit Watt bei Plan-FTP bzw. Puls-Ziel."""
    plan = active_plan()
    if plan is None or not plan.start <= day <= plan.end:
        return None
    with Session(engine) as db:
        s = db.exec(select(BikePlanSession).where(BikePlanSession.plan_id == plan.id,
                                                  BikePlanSession.day == day)).first()
    week = next((w for w in json.loads(plan.weeks_json) if w["start"] <= day.isoformat() <= w["end"]), {})
    head = f"RAD-PLAN HEUTE (Woche {week.get('week', '?')}, {week.get('phase') or '-'}): "
    if s is None:
        return head + "keine Einheit (Ruhetag)."
    ftp = ftp_at(ftp_history(plan), day)["watts"]
    main = [st for st in json.loads(s.steps_json) if st.get("power_pct") and st.get("duration_min")
            and sum(st["power_pct"]) / 2 >= 55]
    parts = [f"{s.title}{' (optional)' if s.optional else ''}, {_r(s.duration_min)} min"]
    if s.steering == "heart_rate" and (s.hr_min or s.hr_max):
        parts.append(f"nach Puls {_r(s.hr_min) or ''}–{_r(s.hr_max)} bpm")
    if main:
        big = max(main, key=lambda st: sum(st["power_pct"]))
        reps = sum(1 for st in main if st["power_pct"] == big["power_pct"] and st["label"] == big["label"])
        w = _watts(big, ftp)
        parts.append(f"{reps}× {big['label']} {_r(big['duration_min'])} min bei {w[0]}–{w[1]} W" if reps > 1
                     else f"{big['label']} {w[0]}–{w[1]} W")
    parts.append(f"FTP {int(ftp)} W")
    if s.kind == "test":
        parts.append("Ramp-Test, ausgeruht")
    if s.run_alternative:
        parts.append(f"Lauf-Variante: {s.run_alternative}")
    return head + "; ".join(parts) + "."


# ---------------- .zwo-Export ----------------
def zwo(session_id: int, today: date | None = None) -> tuple[str, str] | None:
    """Zwift-Workout (Leistung relativ zur FTP in Zwift); die Beschreibung nennt die Watt bei Plan-FTP."""
    with Session(engine) as db:
        s = db.get(BikePlanSession, session_id)
        plan = db.get(BikePlan, s.plan_id) if s else None
    if s is None or plan is None or s.kind == "test":
        return None
    steps = [st for st in json.loads(s.steps_json) if st.get("power_pct") and st.get("duration_min")]
    if not steps:
        return None
    ftp = ftp_at(ftp_history(plan), max(_today(today), s.day))["watts"]
    lines = []
    for i, st in enumerate(steps):
        lo, hi = (p / 100 for p in st["power_pct"])
        seconds = int(round(st["duration_min"] * 60))
        cad = (st.get("cadence") or [None])[0]
        cadence = f' Cadence="{int(cad)}"' if cad else ""
        if i == 0 and st["label"].lower().startswith("einrollen"):
            lines.append(f'    <Warmup Duration="{seconds}" PowerLow="{lo:.2f}" PowerHigh="{hi:.2f}"{cadence}/>')
        elif i == len(steps) - 1 and st["label"].lower().startswith("ausrollen"):
            lines.append(f'    <Cooldown Duration="{seconds}" PowerLow="{hi:.2f}" PowerHigh="{lo:.2f}"{cadence}/>')
        else:
            lines.append(f'    <SteadyState Duration="{seconds}" Power="{(lo + hi) / 2:.3f}"{cadence}/>')
    watts = ", ".join(f"{st['label']} {_watts(st, ftp)[0]}–{_watts(st, ftp)[1]} W" for st in steps[:6])
    hr = (f" Nach Puls fahren ({s.hr_min or ''}–{s.hr_max or ''} bpm), ERG aus."
          if s.steering == "heart_rate" else "")
    desc = f"{s.title} am {s.day.strftime('%d.%m.')}, Watt bei FTP {int(ftp)} W: {watts}.{hr}"
    name = f"Milon {s.title} {s.day.strftime('%d.%m.')}"
    xml = ("<workout_file>\n  <author>Milon</author>\n"
           f"  <name>{escape(name)}</name>\n  <description>{escape(desc)}</description>\n"
           "  <sportType>bike</sportType>\n  <tags><tag name=\"Milon\"/></tags>\n"
           "  <workout>\n" + "\n".join(lines) + "\n  </workout>\n</workout_file>\n")
    filename = re.sub(r"[^A-Za-z0-9_-]+", "_", f"milon_{s.day.isoformat()}_{s.title}").strip("_") + ".zwo"
    return xml, filename


# ---------------- Messpunkte ----------------
RIDE_WINDOW_D = 28   # Rad-Kennzahlen aus den 4 Wochen bis zum Messtag
RUN_WINDOW_D = 56    # „Puls bei gleicher Pace“ gilt nur, solange er höchstens 8 Wochen alt ist
W120_BAND = (117, 123)


class _Data:
    """Einmal geladene Quellen für alle Messtage; Sekunden-Serien nur bei Bedarf."""

    def __init__(self, plan: BikePlan):
        from .metrics import cycling, running
        self.cycling, self.plan = cycling, plan
        self.rides, self.runs = _rides(), _runs()
        self.history = ftp_history(plan, self.rides)
        self.weights = cycling._weights()
        self.vo2 = running._read("SELECT measured_at, vo2 FROM vo2max ORDER BY measured_at", parse_dates=["measured_at"])
        self._series: dict[str, dict] = {}
        self.rhr = self._rhr()
        self.std: list | None = None

    def _rhr(self) -> pd.Series:
        """Ruhepuls je Tag: Garmin-Tageswerte, sonst Health Connect (resting_hr_daily)."""
        values: dict[pd.Timestamp, float] = {}
        with engine.connect() as con:
            tables = {r[0] for r in con.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
            if "resting_hr_daily" in tables:
                for day, bpm in con.exec_driver_sql("SELECT day, bpm FROM resting_hr_daily"):
                    values[pd.Timestamp(day)] = float(bpm)
            if "garmin_daily" in tables:
                for day, js in con.exec_driver_sql("SELECT day, normalized_json FROM garmin_daily"):
                    bpm = (json.loads(js or "{}").get("summary") or {}).get("rhr_bpm")
                    if bpm:
                        values[pd.Timestamp(day)] = float(bpm)
        return pd.Series(values, dtype=float).sort_index()

    def window(self, day: date, days: int) -> pd.DataFrame:
        r = self.rides
        return r[(r["day"] > day - timedelta(days=days)) & (r["day"] <= day)] if not r.empty else r

    def series(self, frame: pd.DataFrame) -> list[dict]:
        missing = frame[~frame["activity_id"].astype(str).isin(self._series)]
        if not missing.empty:
            attached = self.cycling._attach_series(missing)
            self._series.update(zip(attached["activity_id"].astype(str), attached["series"]))
        return [self._series[str(a)] for a in frame["activity_id"]]


def _w120(data: _Data, day: date):
    rides = data.window(day, RIDE_WINDOW_D)
    rides = rides[rides["hr_valid"]] if not rides.empty else rides
    watts = []
    for ser in data.series(rides) if not rides.empty else []:
        w, h = data.cycling._wkg_hr_pairs(ser, 1.0)
        watts.extend(w[(h >= W120_BAND[0]) & (h <= W120_BAND[1])])
    return (float(np.median(watts)), f"{len(watts) // 60} min bei 117–123 bpm") if len(watts) >= 120 else None


def _decoup(data: _Data, day: date):
    rides = data.window(day, RIDE_WINDOW_D)
    rides = rides[rides["hr_valid"]].sort_values("started_at") if not rides.empty else rides
    for ser, when in reversed(list(zip(data.series(rides), rides["day"]))) if not rides.empty else []:
        dec = data.cycling._decoupling(ser)
        if dec is not None:
            return dec[0], f"gleichmäßige Fahrt {when.strftime('%d.%m.')}"
    return None


def _p5(data: _Data, day: date):
    rides = data.window(day, RIDE_WINDOW_D)
    best = max((c.get(300, 0) for c in rides["power_curve"]), default=0) if not rides.empty else 0
    return (best, "beste 5 min, 28 T") if best else None


def _vo2(data: _Data, day: date):
    v = data.vo2[(data.vo2["measured_at"].dt.date <= day)
                 & (data.vo2["measured_at"].dt.date > day - timedelta(days=60))] if not data.vo2.empty else data.vo2
    return (float(v["vo2"].iloc[-1]), None) if not v.empty else None


def _rhr(data: _Data, day: date):
    s = data.rhr[(data.rhr.index > pd.Timestamp(day - timedelta(days=7))) & (data.rhr.index <= pd.Timestamp(day))]
    return (float(s.mean()), f"Ø {len(s)} Tage") if len(s) >= 3 else None


def _std_hr(data: _Data, day: date) -> dict[int, float]:
    """Milons „Puls bei gleicher Pace“ (Laufminute 30, rollierend 8 Wochen): je Pace-Stufe der
    letzte belegte Wert bis zum Messtag."""
    if data.std is None:
        from .metrics import run_fitness_service
        data.std = run_fitness_service.standardized_hr().get("pace_series") or []
    out = {}
    for s in data.std:
        points = [p for p in s["points"] if p.get("hr") is not None and p["date"] <= day.isoformat()]
        if points and points[-1]["date"] > (day - timedelta(days=RUN_WINDOW_D)).isoformat():
            out[int(s["pace_seconds"])] = float(points[-1]["hr"])
    return out


def _pace135(data: _Data, day: date):
    hr = sorted(_std_hr(data, day).items())
    for (p1, h1), (p2, h2) in zip(hr, hr[1:]):
        if min(h1, h2) <= 135 <= max(h1, h2) and h1 != h2:
            return p1 + (135 - h1) * (p2 - p1) / (h2 - h1), f"interpoliert {p1 // 60}:{p1 % 60:02d}–{p2 // 60}:{p2 % 60:02d}"
    if len(hr) >= 2:  # knapp außerhalb: aus den zwei nächsten Stufen hochrechnen, höchstens 60 s weiter
        (p1, h1), (p2, h2) = sorted(sorted(hr, key=lambda x: abs(x[1] - 135))[:2])
        if h1 != h2:
            pace = p1 + (135 - h1) * (p2 - p1) / (h2 - h1)
            if min(abs(pace - p1), abs(pace - p2)) <= 60:
                return pace, f"hochgerechnet aus {p1 // 60}:{p1 % 60:02d} und {p2 // 60}:{p2 % 60:02d}"
    return None


def _hr630(data: _Data, day: date):
    hr = _std_hr(data, day).get(390)
    return (hr, "Puls bei gleicher Pace, Minute 30") if hr is not None else None


def _cad(data: _Data, day: date):
    ftp = ftp_at(data.history, day)["watts"]
    rides = data.window(day, 14)
    if rides.empty:
        return None
    easy = rides[(rides["avg_power_w"].fillna(0) > 0) & (rides["avg_power_w"] <= 0.76 * ftp)
                 & rides["avg_cadence_rpm"].notna()]
    if easy.empty:
        return None
    weights = easy["duration_seconds"].astype(float)
    return float(np.average(easy["avg_cadence_rpm"], weights=weights)), f"{len(easy)} lockere Fahrten, 14 T"


def _kg(data: _Data, day: date):
    w = data.cycling._weight_at(data.weights, day)
    return (w, "7-Tage-Mittel") if w else None


def _ftp(data: _Data, day: date):
    e = ftp_at(data.history, day)
    return e["watts"], {"plan": "Startwert Plan", "ramp": "Ramp-Test", "manual": "von Hand"}[e["source"]]


def _wkg(data: _Data, day: date):
    kg = _kg(data, day)
    return (_ftp(data, day)[0] / kg[0], None) if kg else None


CALCULATORS = {"w120": _w120, "decoup": _decoup, "ftp": _ftp, "wkg": _wkg, "p5": _p5, "vo2": _vo2,
               "rhr": _rhr, "pace": _pace135, "hr630": _hr630, "cad": _cad, "kg": _kg}


def _checkpoint_dates(plan: BikePlan, meta: dict) -> dict[str, date]:
    dates = {}
    for key, cp in ((meta.get("metrics") or {}).get("checkpoints") or {"start": None}).items():
        if cp and cp.get("date"):
            dates[key] = date.fromisoformat(cp["date"])
        elif key == "start":
            dates[key] = plan.start
        elif re.fullmatch(r"w\d+", key):
            dates[key] = plan.start + timedelta(days=7 * int(key[1:]) - 1)
    return dates


def _target_band(text: str | None) -> tuple[float, float] | None:
    nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", text or "")]
    return (nums[0], nums[1]) if len(nums) == 2 and "–" in (text or "") else None


def _verdict(better: str, start, latest, target: str | None) -> str | None:
    if start is None or latest is None or better == "none":
        return None
    if abs(latest - start) <= abs(start) * 0.005:
        return "eq"
    if better == "eq":
        band = _target_band(target)
        if not band:
            return None
        dist = lambda v: max(band[0] - v, 0, v - band[1])  # noqa: E731
        return "up" if dist(latest) < dist(start) else "down" if dist(latest) > dist(start) else "eq"
    return "up" if (latest > start) == (better == "up") else "down"


def checkpoints(today: date | None = None) -> dict:
    """Messpunkte des aktiven Plans: je Kennzahl Wert an jedem Messtag + heute.
    Quelle: Handwert > automatisch aus Milon > Wert aus der Plan-Datei (meist geschätzt)."""
    today = _today(today)
    plan = active_plan()
    if plan is None:
        return {"plan": None}
    meta = json.loads(plan.meta_json)
    defs = (meta.get("metrics") or {}).get("definitions") or []
    plan_cps = (meta.get("metrics") or {}).get("checkpoints") or {}
    dates = _checkpoint_dates(plan, meta)
    with Session(engine) as db:
        manual = {(m.checkpoint, m.key): m for m in
                  db.exec(select(BikePlanCheckpoint).where(BikePlanCheckpoint.plan_id == plan.id)).all()}
    data = _Data(plan)

    def auto(key: str, day: date):
        calc = CALCULATORS.get(key)
        if calc is None:
            return None
        try:
            return calc(data, day)
        except Exception:  # eine kaputte Kennzahl sperrt nur sich selbst
            return None

    rows = []
    for d in defs:
        key, cells = d["key"], {}
        for cp, day in dates.items():
            m, pc = manual.get((cp, key)), plan_cps.get(cp) or {}
            got = auto(key, day) if day <= today else None
            if m is not None:
                cells[cp] = {"value": m.value, "source": "manual", "estimated": m.estimated, "note": None}
            elif got is not None:
                cells[cp] = {"value": round(got[0], 2), "source": "auto", "estimated": False, "note": got[1]}
            elif (pc.get("values") or {}).get(key) is not None:
                cells[cp] = {"value": pc["values"][key], "source": "plan",
                             "estimated": key in (pc.get("estimated") or []), "note": (pc.get("notes") or {}).get(key)}
            else:
                cells[cp] = None
        now = auto(key, today)
        current = {"value": round(now[0], 2), "source": "auto", "estimated": False, "note": now[1]} if now else None
        last_cp = max((cp for cp in dates if cp != "start" and cells.get(cp) and dates[cp] <= today),
                      key=lambda cp: dates[cp], default=None)
        latest = cells[last_cp] if last_cp and dates[last_cp] >= today - timedelta(days=1) else current
        start = cells.get("start")
        delta = (latest["value"] - start["value"]) if latest and start else None
        rows.append({"key": key, "name": d.get("name"), "unit": d.get("unit"), "better": d.get("better"),
                     "target": d.get("target_w8"), "how": d.get("how_to_measure"), "derived": d.get("derived"),
                     "pace": bool(d.get("pace_stored_as_seconds_per_km")), "auto": key in CALCULATORS,
                     "values": cells, "now": current, "delta": _r(delta, 2) if delta is not None else None,
                     "verdict": _verdict(d.get("better", "none"), start and start["value"],
                                         latest and latest["value"], d.get("target_w8"))})
    return {"plan": {"id": plan.id, "name": plan.name}, "today": today.isoformat(),
            "checkpoints": [{"key": cp, "date": day.isoformat(), "reached": day <= today} for cp, day in dates.items()],
            "metrics": rows}


def set_checkpoint(plan_id: str, checkpoint: str, key: str, value: float | None, estimated: bool = False) -> None:
    with Session(engine) as db:
        row = db.get(BikePlanCheckpoint, (plan_id, checkpoint, key))
        if value is None:
            if row:
                db.delete(row)
        elif row:
            row.value, row.estimated = value, estimated
            db.add(row)
        else:
            db.add(BikePlanCheckpoint(plan_id=plan_id, checkpoint=checkpoint, key=key, value=value, estimated=estimated))
        db.commit()
