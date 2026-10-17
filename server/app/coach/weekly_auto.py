"""Automatischer Wochenbericht: liegt Montag früh fertig da (Epic #54, #53).

Auslöser (einmal je ISO-Woche, idempotent): ab Sonntag 23:30 (Ortszeit) für die gerade endende Woche.
Wurde der Zeitpunkt verpasst (Server aus), holt der nächste Durchlauf den Bericht nach, solange die neue
Woche läuft — bis zum nächsten Sonntag 23:30. Der Coach liest nur und schlägt vor.
Im Prompt stehen nur Kennzahlen der Woche, keine Orts- oder Koordinatendaten.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlmodel import Session, select

from ..config import settings
from ..db import engine
from ..models import CoachReport
from . import briefing, client, prompts, snapshot

KIND = "weekly-auto"
CUTOFF = time(23, 30)             # Sonntag, nach dem letzten Sync des Tages
_lock = threading.Lock()          # Scheduler-Job und manueller Aufruf laufen in verschiedenen Threads
log = logging.getLogger(__name__)

INSTRUCTIONS = """Erstelle meinen Wochenbericht für die abgelaufene Woche; ich lese ihn am Montagmorgen.
Du liest nur und schlägst vor: du änderst keine Daten und triffst keine Spielentscheidungen.
Format (Markdown, höchstens 220 Wörter):
Erste Zeile genau: **Woche:** <Fazit in höchstens 12 Wörtern>
- **Körper:** Gewicht (7-Tage-Mittel) und Trend der Woche.
- **Laufen:** Umfang und Fitness-Trends; Urteil nur bei verdict besser/schlechter als belastbar behandeln.
- **Kraft:** Einheiten, Tonnage und Stärke-Index.
- **Ernährung:** Protein und Energie mit den erfassten Tagen; Einträge belegen keine vollständige Tageserfassung.
- **Schlaf:** Schlafzeit der Woche und bekannte Nächte.
**Für die kommende Woche:** Höchstens drei Vorschläge für die kommende Woche als nummerierte Liste, jeder konkret
mit Datenbeleg und überprüfbarem Ziel; der erste ist die Hauptmaßnahme.
Die Heldenreise erwähnst du höchstens mit einem Halbsatz. Fehlen Daten eines Bereichs, sag das in einem Halbsatz."""


def last_cutoff(now: datetime) -> datetime:
    """Letzter Sonntag 23:30 vor/gleich `now` (lokale Wandzeit, naiv)."""
    n = now.replace(tzinfo=None)
    sunday = n.date() - timedelta(days=(n.weekday() + 1) % 7)
    cutoff = datetime.combine(sunday, CUTOFF)
    return cutoff - timedelta(days=7) if cutoff > n else cutoff


def week_of(cutoff: datetime) -> tuple[date, date]:
    """Montag und Sonntag der Woche, die zu `cutoff` endet."""
    sunday = cutoff.date()
    return sunday - timedelta(days=6), sunday


def report_between(start: datetime, end: datetime) -> CoachReport | None:
    with Session(engine) as s:
        return s.exec(select(CoachReport).where(CoachReport.kind == KIND, CoachReport.created_at >= start,
                                                CoachReport.created_at < end)
                      .order_by(CoachReport.created_at.desc())).first()


def latest() -> CoachReport | None:
    with Session(engine) as s:
        return s.exec(select(CoachReport).where(CoachReport.kind == KIND)
                      .order_by(CoachReport.created_at.desc())).first()


def current(now: datetime | None = None) -> dict:
    """Bericht zur zuletzt beendeten Woche, solange die neue Woche läuft; sonst `report` = None."""
    cutoff = last_cutoff(briefing._local(now or briefing._now()))
    report = report_between(cutoff, cutoff + timedelta(days=7))
    first, last = week_of(cutoff)
    return {"week_from": first.isoformat(), "week_to": last.isoformat(),
            "report": briefing.as_dict(report) if report else None}


def _nutrition_line(first: date, last: date) -> str:
    from ..metrics import nutrition
    df = nutrition._daily()
    if not df.empty:
        df = df[(df["day"] >= pd.Timestamp(first)) & (df["day"] <= pd.Timestamp(last))]
    if df.empty:
        return "ERNÄHRUNG DER WOCHE: keine Einträge erfasst."
    avg = lambda c: None if df[c].count() == 0 else round(float(df[c].mean()))  # noqa: E731
    return ("ERNÄHRUNG DER WOCHE: " + json.dumps({
        "erfasste_tage": int(len(df)), "protein_avg_g": avg("protein_g"), "kcal_avg": avg("kcal"),
        "carb_avg_g": avg("carb_g"), "fat_avg_g": avg("fat_g"), "protein_referenzziel_g": nutrition.protein_target()},
        ensure_ascii=False) + " (Referenzziel ist eine Annahme, kein individuelles Ziel)")


def _week_lines(first: date, last: date) -> list[str]:
    """Kennzahlen der Woche Montag–Sonntag aus den vorhandenen Metriken; Ausfälle kürzen nur den Kontext."""
    from ..metrics import activity, running
    lines = [f"BERICHTSWOCHE: {first.isoformat()} (Mo) bis {last.isoformat()} (So)"]
    end_of_week = datetime.combine(last + timedelta(days=1), time(), tzinfo=ZoneInfo(settings.timezone))
    try:
        review = activity.weekly_review(end_of_week)  # die sieben abgeschlossenen Tage = Mo–So
        lines.append("WOCHE (Körper, Laufen, Kraft, Schritte, Schlaf, Check-in): "
                     + json.dumps(review, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        log.warning("Wochenbericht: Wochenübersicht nicht verfügbar", exc_info=True)
    try:
        lines.append(_nutrition_line(first, last))
    except Exception:  # noqa: BLE001
        log.warning("Wochenbericht: Ernährung nicht verfügbar", exc_info=True)
    try:
        pah, easy = running.pace_at_hr(), running.easy_hr_trend()
        verdict = lambda t: {k: (t or {}).get(k) for k in ("verdict", "label", "n")}  # noqa: E731
        lines.append("FITNESS-TRENDS (Urteil nur bei verdict besser/schlechter belastbar): " + json.dumps({
            "pace_bei_referenzpuls": {"ref_hr": pah.get("ref_hr"), "aktuell_min_km": pah.get("current"),
                                      **verdict(pah.get("trend"))} if pah else None,
            "puls_im_locker_korridor": verdict(easy.get("trend")) if easy else None}, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        log.warning("Wochenbericht: Fitness-Trends nicht verfügbar", exc_info=True)
    return lines


def build_messages(snap: str, facts: list[str]) -> list[dict]:
    return [{"role": "system", "content": prompts.system_prompt()},
            {"role": "system", "content": f"Aktueller Datensnapshot:\n{snap}"},  # letzter System-Block = Cache-Breakpoint
            {"role": "user", "content": INSTRUCTIONS + "\n\n" + "\n".join(facts)}]


def generate(now: datetime, cutoff: datetime) -> dict:
    now = briefing._local(now)
    first, last = week_of(cutoff)
    messages = build_messages(snapshot.snapshot_text(), _week_lines(first, last))
    content, usage = client.complete(messages)
    with Session(engine) as s:
        report = CoachReport(created_at=now.replace(tzinfo=None), kind=KIND, content=content,
                             prompt=json.dumps(messages, ensure_ascii=False), **client.report_fields(usage))
        s.add(report)
        s.commit()
        s.refresh(report)
        return briefing.as_dict(report)


def maybe_run(now: datetime | None = None) -> dict | None:
    """Erzeugt den Bericht der zuletzt beendeten Woche höchstens einmal. None = nichts zu tun."""
    if not _lock.acquire(blocking=False):
        return None
    try:
        now = briefing._local(now or briefing._now())
        cutoff = last_cutoff(now)
        if report_between(cutoff, cutoff + timedelta(days=7)):
            return None
        return generate(now, cutoff)
    finally:
        _lock.release()
