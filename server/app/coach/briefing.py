"""Morgenbriefing: liegt morgens fertig da, bevor gelaufen wird (Epic #54, #52).

Auslöser (einmal je Tag, idempotent): ab 04:00 beim ersten Durchlauf, sobald die Hauptnacht der
vergangenen Nacht synchronisiert ist; ohne Schlaf spätestens 1 h vor Sonnenaufgang, dann mit Hinweis.
Der Coach liest nur und schlägt vor. Im Prompt stehen Ortsnamen, gerundete Entfernung und
Himmelsrichtung — nie Koordinaten (weder lat/lon noch Meter relativ zur Heimat).
"""
from __future__ import annotations

import json
import logging
import math
import threading
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from ..config import settings
from ..db import engine
from ..models import CoachReport
from . import client, prompts, snapshot

KIND = "briefing"
EARLIEST = time(4, 0)             # vorher wird nichts erzeugt, auch wenn der Schlaf schon da ist
BEFORE_SUNRISE = timedelta(hours=1)
# Ohne Sonnenaufgang (kein Wetterort, Open-Meteo ohne Altstand) gilt eine Ersatzfrist; sie liegt vor
# dem frühesten Sommerlauf (~6:30), damit das Briefing auch dann rechtzeitig daliegt.
FALLBACK_DEADLINE = time(6, 0)
DIRECTIONS = ["Norden", "Nordosten", "Osten", "Südosten", "Süden", "Südwesten", "Westen", "Nordwesten"]
_lock = threading.Lock()  # Scheduler-Job und Garmin-Sync laufen in verschiedenen Threads
log = logging.getLogger(__name__)

INSTRUCTIONS = """Erstelle mein Morgenbriefing für heute; ich lese es vor dem Laufen.
Du liest nur und schlägst vor: du änderst keine Daten und triffst keine Spielentscheidungen.
Format (Markdown, höchstens 150 Wörter):
Erste Zeile genau: **Heute:** <Empfehlung in höchstens 12 Wörtern>
- **Schlaf & Erholung:** die vergangene Nacht und die Erholungswerte.
- **Empfehlung:** Lauf, Kraft oder Ruhe mit Intensität und Dauer; stütze sie auf Fitness-Trends, Belastung und Check-in.
- **Laufwetter:** das Fenster ab Sonnenaufgang mit Kleidung aus LAUFWETTER übernehmen, nicht neu berechnen.
- **Route:** das Verlies aus ROUTE als Vorschlag mit Name, Entfernung und Richtung.
Fehlen Schlafdaten, sag das in einem Halbsatz und stütze dich auf die übrigen Daten.
Fehlt Wetter oder Route, lass den Punkt kurz weg."""


def _now() -> datetime:
    return datetime.now(ZoneInfo(settings.timezone))


def _local(now: datetime) -> datetime:
    zone = ZoneInfo(settings.timezone)
    return now.replace(tzinfo=zone) if now.tzinfo is None else now.astimezone(zone)


def report_for(day: date) -> CoachReport | None:
    start = datetime.combine(day, time())
    with Session(engine) as s:
        return s.exec(select(CoachReport).where(CoachReport.kind == KIND, CoachReport.created_at >= start,
                                                CoachReport.created_at < start + timedelta(days=1))
                      .order_by(CoachReport.created_at.desc())).first()


def as_dict(r: CoachReport) -> dict:
    return {"id": r.id, "kind": r.kind, "content": r.content, "created_at": r.created_at.isoformat(),
            "model": r.model, "provider": r.provider, "fallback_reason": r.fallback_reason, "cost_usd": r.cost_usd}


def main_night(day: date) -> dict | None:
    """Hauptnacht mit Aufwachdatum `day`: Garmin zuerst, sonst Health Connect (aktuelle Uhr)."""
    from ..garmin_daily import GarminDaily
    from ..metrics import garmin_nights, sleep
    with Session(engine) as s:
        row = s.get(GarminDaily, day)
    value = garmin_nights._night(row) if row else None
    if value:
        return {"source": "Garmin", "started_at": value["started_at"], "ended_at": value["ended_at"],
                "asleep_minutes": value["asleep_minutes"], "window_minutes": value["window_minutes"],
                "awake_minutes": value["awake_minutes"]}
    main = sleep._main_by_day(sleep._sleep_rows(1, day)).get(day)
    if main:
        return {"source": "Health Connect", "started_at": main.started_at.isoformat(), "ended_at": main.ended_at.isoformat(),
                "asleep_minutes": main.asleep_minutes, "window_minutes": main.duration_window_minutes,
                "awake_minutes": main.awake_minutes}
    return None


def _weather(now: datetime) -> dict | None:
    from .. import weather
    try:
        data = weather.today(0, now=now)
    except Exception:  # noqa: BLE001 -- Wetterausfall darf das Briefing nicht sperren
        log.warning("Briefing: Wetter nicht verfügbar", exc_info=True)
        return None
    return data if data.get("configured") else None


def _sunrise(w: dict | None) -> datetime | None:
    rise = ((w or {}).get("day") or {}).get("sunrise")
    try:
        return datetime.fromisoformat(rise) if rise else None
    except ValueError:
        return None


def due(now: datetime, has_sleep: bool, sunrise: datetime | None) -> str | None:
    """Grund zum Erzeugen ('sleep' | 'deadline') oder None. `now`/`sunrise` lokale Wandzeit."""
    now = now.replace(tzinfo=None)
    if now.time() < EARLIEST:
        return None
    if has_sleep:
        return "sleep"
    deadline = sunrise - BEFORE_SUNRISE if sunrise else datetime.combine(now.date(), FALLBACK_DEADLINE)
    return "deadline" if now >= deadline.replace(tzinfo=None) else None


def compass(x: float, y: float) -> str:
    """Himmelsrichtung aus der Lage relativ zur Heimat (x = Ost, y = Nord)."""
    angle = (math.degrees(math.atan2(x, y)) + 360) % 360
    return DIRECTIONS[round(angle / 45) % 8]


def nearest_dungeon() -> dict | None:
    """Nächstgelegenes offenes Verlies — nur Name, Entfernung, Richtung und Spielwerte, keine Koordinaten."""
    from .. import hero_world
    try:
        w = hero_world.world()
    except Exception:  # noqa: BLE001 -- Spiel-Ebene darf den Coach nie sperren
        log.warning("Briefing: Weltkarte nicht verfügbar", exc_info=True)
        return None
    open_ = [d for d in w.get("dungeons", []) if not d.get("cleared")]
    if not open_:
        return None
    d = min(open_, key=lambda d: d["km"])
    segs = d.get("segments") or []
    return {"name": d["name"], "type": d.get("type_label"), "km": round(d["km"], 1), "direction": compass(d["x"], d["y"]),
            "length_km": d.get("length_km"), "level": d.get("level"), "discovered": bool(d.get("discovered")),
            "sections_cleared": sum(1 for s in segs if s.get("cleared")), "sections": len(segs)}


def _hm(iso: str | None) -> str:
    return iso[11:16] if iso and len(iso) >= 16 else "–"


def _sleep_line(night: dict | None, now: datetime) -> str:
    if not night:
        return (f"SCHLAF LETZTE NACHT: keine Hauptnacht synchronisiert (Stand {now:%H:%M}). "
                "Briefing ohne Schlafdaten; Erholung nur aus den übrigen Werten.")
    asleep = night.get("asleep_minutes")
    return (f"SCHLAF LETZTE NACHT ({night['source']}): {_hm(night['started_at'])}–{_hm(night['ended_at'])}, "
            f"Schlafzeit {f'{asleep / 60:.1f} h' if asleep is not None else 'unbekannt (Phasen unvollständig)'}, "
            f"Fenster {night['window_minutes'] / 60:.1f} h"
            + (f", wach {night['awake_minutes']:.0f} min" if night.get("awake_minutes") is not None else "") + ".")


def _window(w: dict | None, label: str) -> str | None:
    if not w:
        return None
    c = w["clothing"]
    return (f"{label} {_hm(w['start'])}–{_hm(w['end'])}: {w['temp']} °C, Regen {w['rain_prob']} %, "
            f"Wind {w['wind_kmh']} km/h, {w['rating']}; Kleidung: {c['text']}"
            + (f" + {', '.join(c['extras'])}" if c.get("extras") else ""))


def _weather_line(w: dict | None) -> str:
    run = (w or {}).get("run")
    if not run:
        return "LAUFWETTER: nicht verfügbar."
    parts = [f"LAUFWETTER {w['place']} ({run['day']}, {run['date']}): Sonnenaufgang {_hm(run['sunrise'])}, "
             f"Sonnenuntergang {_hm(run['sunset'])}."]
    parts += [line for line in (_window(run.get("morning"), "Morgenlauf ab Sonnenaufgang"),
                                _window(run.get("best"), "Bestes Fenster")) if line]
    parts += run.get("notes") or []
    return " ".join(parts)


def _route_line(d: dict | None) -> str:
    if not d:
        return "ROUTE: kein offenes Verlies."
    return (f"ROUTE: nächstes offenes Verlies „{d['name']}“ ({d['type']}, Stufe {d['level']}), "
            f"{str(d['km']).replace('.', ',')} km im {d['direction']} von zu Hause, Streckenlänge {str(d['length_km']).replace('.', ',')} km, "
            f"{d['sections_cleared']}/{d['sections']} Abschnitte bezwungen"
            + ("" if d["discovered"] else ", Strecke noch im Nebel") + ".")


def _context_lines(day: date) -> list[str]:
    """Check-in, letzte Einheiten, Fitness-Trends und Belastung — vorhandene Kennzahlen, nichts Neues."""
    from .. import checkins
    from ..metrics import activity, running
    lines = []
    entries = checkins.list_entries(2, day)
    lines.append("CHECK-IN (heute/gestern, freiwillig): "
                 + (json.dumps([{k: e.get(k) for k in ("day", "energy", "training_effort", "sick", "note")} for e in entries],
                               ensure_ascii=False) if entries else "keine Einträge"))
    try:
        lines.append("LETZTE EINHEITEN: " + json.dumps(activity.recent(4), ensure_ascii=False, default=str))
        pah, easy, trimp = running.pace_at_hr(), running.easy_hr_trend(), running.trimp_weekly(4)
        verdict = lambda t: {k: (t or {}).get(k) for k in ("verdict", "label", "n")}  # noqa: E731
        lines.append("FITNESS-TRENDS (Urteil nur bei verdict besser/schlechter belastbar): " + json.dumps({
            "pace_bei_referenzpuls": {"ref_hr": pah.get("ref_hr"), "aktuell_min_km": pah.get("current"),
                                      **verdict(pah.get("trend"))} if pah else None,
            "puls_im_locker_korridor": verdict(easy.get("trend")) if easy else None,
            "trimp_letzte_wochen": [s["trimp"] for s in (trimp or {}).get("series", [])],
        }, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001 -- fehlende Teilmetriken kürzen nur den Kontext
        log.warning("Briefing: Trainingskontext unvollständig", exc_info=True)
    return lines


def build_messages(now: datetime, night: dict | None, w: dict | None, dungeon: dict | None,
                   snap: str, context: list[str]) -> list[dict]:
    facts = [f"JETZT: {now:%Y-%m-%d %H:%M} ({settings.timezone})", _sleep_line(night, now), *context,
             _weather_line(w), _route_line(dungeon)]
    return [{"role": "system", "content": prompts.system_prompt()},
            {"role": "system", "content": f"Aktueller Datensnapshot:\n{snap}"},  # letzter System-Block = Cache-Breakpoint
            {"role": "user", "content": INSTRUCTIONS + "\n\n" + "\n".join(facts)}]


def generate(now: datetime, night: dict | None, w: dict | None = None) -> dict:
    now = _local(now)
    w = w if w is not None else _weather(now)
    messages = build_messages(now, night, w, nearest_dungeon(), snapshot.snapshot_text(), _context_lines(now.date()))
    content, usage = client.complete(messages)
    with Session(engine) as s:
        report = CoachReport(created_at=now.replace(tzinfo=None), kind=KIND, content=content,
                             prompt=json.dumps(messages, ensure_ascii=False), **client.report_fields(usage))
        s.add(report)
        s.commit()
        s.refresh(report)
        return as_dict(report)


def maybe_run(now: datetime | None = None) -> dict | None:
    """Prüft den Auslöser und erzeugt das heutige Briefing höchstens einmal. None = nichts zu tun."""
    if not _lock.acquire(blocking=False):
        return None
    try:
        now = _local(now or _now())
        if now.time() < EARLIEST or report_for(now.date()):
            return None
        night = main_night(now.date())
        w = None if night else _weather(now)
        if not due(now, night is not None, _sunrise(w)):
            return None
        return generate(now, night, w)
    finally:
        _lock.release()
