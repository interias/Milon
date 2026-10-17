"""Heldenreise: Wochen-Saga — der Coach erzählt die Woche als kurze Heldengeschichte.

Nur auf Knopfdruck (LLM-Kosten); gespeichert als CoachReport kind='saga' inkl. Prompt und Kosten.
Die Fakten kommen ausschließlich aus der Heldenreise-Übersicht — das Modell soll nichts erfinden.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from .db import engine
from .models import CoachReport

SYSTEM = (
    "Du bist der Chronist einer Gilde in einer Welt wie World of Warcraft. Schreibe auf Deutsch eine kurze, "
    "lebendige Heldengeschichte (120–180 Wörter) über die vergangene Trainingswoche des Helden, in der zweiten "
    "Person („du“). Nutze AUSSCHLIESSLICH die gelieferten Fakten; erfinde keine Zahlen, Orte oder Ereignisse. "
    "Verwandle Läufe in Reisen, Krafttraining in Schmiedekunst, Bosse und Instanzen in Kämpfe, Beute in Schätze. "
    "Erwähne den Begleiter beim Namen. Krankheit ist eine ehrenvolle Rast, kein Versagen. Ende mit einem Satz "
    "Ausblick auf die nächste Woche. Gib nur den Text aus, mit einer Überschrift als erste Zeile (## …)."
)


def saga_week(today: date) -> date:
    """Montag der erzählten Woche: Mo/Di die abgeschlossene Vorwoche, sonst die laufende Woche."""
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(days=7) if today.weekday() < 2 else monday


def facts(o: dict, week: date, today: date) -> dict:
    end = min(week + timedelta(days=6), today)
    within = lambda iso: week.isoformat() <= iso[:10] <= end.isoformat()  # noqa: E731
    h = o["hero"]
    prog = next((p for p in o["progression"] if p["week"] == week.isoformat()), None)
    return {
        "zeitraum": f"{week.isoformat()} bis {end.isoformat()}",
        "held": {"klasse": h["class_label"], "spezialisierung": h["spec_label"], "stufe": h["level"],
                 "titel": h.get("title_chosen") or h["title"]},
        "begleiter": {"name": o["companion"]["name"], "art": o["companion"]["species"], "stimmung": o["companion"]["text"]},
        "ep_der_woche": prog and {k: v for k, v in prog.items() if k not in ("week", "xp", "level") and v},
        "ereignisse": [e["text"] for e in o["log"] if within(e["date"])][:25],
        "beute": [f"{it['name']} ({it['rarity_label']})" for it in o["inventory"] if within(it["date"])],
        "auftraege": [f"{q['title']}: {'erfüllt' if q['done'] else 'offen'}" for q in (o["quests"] or {}).get("quests", [])]
        if o["quests"] and o["quests"]["week"] == week.isoformat() else [],
        "bosse_des_monats": [f"{b['name']}: {'besiegt' if b['defeated'] else f'{round(b['hp'] * 100)} % Leben'}" for b in o["bosses"]],
        "saison_event": o["event"] and f"{o['event']['name']}: {o['event']['tokens']}/{o['event']['goal']} {o['event']['token']}",
        "tagesaufgaben_serie": (o["daily"] or {}).get("streak"),
        "buffs_heute": [b["name"] for b in o["buffs"]],
    }


def latest() -> dict | None:
    with Session(engine) as session:
        row = session.exec(select(CoachReport).where(CoachReport.kind == "saga")
                           .order_by(CoachReport.created_at.desc())).first()
    if row is None:
        return None
    week = None
    try:
        week = json.loads(row.prompt or "[]")[-1]["content"].split("ZEITRAUM: ", 1)[1][:10]
    except (IndexError, KeyError, ValueError):
        pass
    return {"created_at": row.created_at.isoformat(), "week": week, "content": row.content, "cost_usd": row.cost_usd}


def generate(overview: dict, today: date) -> dict:
    from .coach import client
    week = saga_week(today)
    data = facts(overview, week, today)
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"ZEITRAUM: {week.isoformat()}\nFAKTEN:\n" + json.dumps(data, ensure_ascii=False, indent=1)}]
    content, usage = client.complete(messages, temperature=0.8)
    with Session(engine) as session:
        session.add(CoachReport(created_at=datetime.now(), kind="saga", content=content,
                                prompt=json.dumps(messages, ensure_ascii=False), **client.report_fields(usage)))
        session.commit()
    return latest()
