"""BISS import: the own food tracker, read live over its REST API (no auth, local Docker network).

GET /api/v1/days/{day} carries the entries with their macro snapshot, the totals and the goals of
that day. A BISS day runs from 04:00 to 04:00 (Europe/Berlin); Milon cuts days at midnight, so an
entry after midnight that BISS counts to the day before is stored at 23:59:59 of that day. Both
apps then show the same daily sums.

Each import replaces the last RECENT_DAYS days of source='biss' (entries get edited and deleted
during the day); `full` replaces everything from settings.biss_since on. Days before biss_since
are never imported: FDDB holds them.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete
from sqlmodel import Session

from ..config import settings
from ..db import count_rows, engine, upsert
from ..models import NutritionEntry, NutritionGoal, SyncState

SOURCE = "biss"
RECENT_DAYS = 3
# The published host port still answers when the api was recreated without the shared network.
FALLBACK_URL = "http://host.docker.internal:2478"


def _bases() -> list[str]:
    bases = [settings.biss_url.rstrip("/"), FALLBACK_URL]
    return [b for i, b in enumerate(bases) if b and b not in bases[:i]]


def fetch_days(days: list[date]) -> list[dict]:
    """Day summaries, in the order asked. The first base that answers serves all days."""
    error: Exception | None = None
    for base in _bases():
        try:
            with httpx.Client(base_url=base, timeout=10) as client:
                out = []
                for day in days:
                    r = client.get(f"/api/v1/days/{day.isoformat()}")
                    r.raise_for_status()
                    out.append(r.json())
                return out
        except httpx.HTTPError as e:
            error = e
    raise RuntimeError(f"BISS nicht erreichbar ({type(error).__name__})")


def biss_today(now: datetime | None = None) -> date:
    """Today as BISS counts it: until 04:00 the day before."""
    now = now or datetime.now(ZoneInfo(settings.timezone))
    return (now - timedelta(hours=4)).date()


def _rows(day_json: dict) -> list[dict]:
    tz = ZoneInfo(settings.timezone)
    rows = []
    for meal in day_json.get("meals", []):
        for e in meal.get("entries", []):
            day = date.fromisoformat(e["day"])
            local = datetime.fromisoformat(e["eaten_at"].replace("Z", "+00:00")).astimezone(tz).replace(tzinfo=None)
            if local.date() != day:
                local = datetime.combine(day, time(23, 59, 59))
            food, macros = e.get("food") or {}, e.get("macros") or {}
            rows.append(dict(
                eaten_at=local, description=food.get("name"), fddb_id=f"biss:{e['id']}",
                kcal=macros.get("kcal"), fat_g=macros.get("fat"), carb_g=macros.get("carbs"),
                protein_g=macros.get("protein"), source=SOURCE, grams=e.get("grams"), meal=e.get("meal"),
                food_ref=str(food["id"]) if food.get("id") is not None else None, brand=food.get("brand"),
                category=food.get("category"), group_name=e.get("group_name"),
            ))
    return rows


def _goal(day_json: dict) -> dict | None:
    t = day_json.get("targets")
    if not t:
        return None
    return dict(day=date.fromisoformat(day_json["date"]), kcal=t.get("kcal"), protein_g=t.get("protein"),
                carb_g=t.get("carbs"), fat_g=t.get("fat"), source=SOURCE)


def import_biss(full: bool = False, now: datetime | None = None) -> dict:
    today = biss_today(now)
    first = settings.biss_since if full else max(settings.biss_since, today - timedelta(days=RECENT_DAYS - 1))
    days = [first + timedelta(days=i) for i in range((today - first).days + 1)]
    if not days:  # biss_since lies in the future
        return {"mode": "not_started", "days": 0, "entries": 0, "total": 0, "changed": False}
    fetched = fetch_days(days)
    rows = [row for d in fetched for row in _rows(d)]
    goals = [g for g in (_goal(d) for d in fetched) if g]
    cursor = hashlib.sha1(json.dumps([rows, goals], default=str, sort_keys=True).encode()).hexdigest()

    with Session(engine) as s:
        state = s.get(SyncState, SOURCE)
        changed = full or state is None or state.cursor != cursor
        if changed:
            if full:
                s.execute(delete(NutritionEntry).where(NutritionEntry.source == SOURCE))
            else:
                s.execute(delete(NutritionEntry).where(
                    NutritionEntry.source == SOURCE, NutritionEntry.eaten_at >= datetime.combine(first, time.min)))
            upsert(s, NutritionEntry, rows, ["eaten_at", "fddb_id", "kcal"])
            upsert(s, NutritionGoal, goals, ["day"], update_cols=["kcal", "protein_g", "carb_g", "fat_g", "source"])
            s.commit()
        total = count_rows(s, NutritionEntry, SOURCE)

    return {"mode": "full" if full else "incremental", "days": len(days), "entries": len(rows),
            "total": total, "changed": changed, "cursor": cursor}
