"""Hevy-Import über die offizielle API (Pro-Key in server/.env: HEVY_API_KEY).
GET /v1/workouts (paginiert) -> workouts / workout_sets. Vollabzug -> ersetzt source='hevy'.
Zeiten kommen als ISO-UTC -> in Europe/Berlin (naive Wandzeit) gewandelt."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, func, select
from sqlmodel import Session

from ..config import settings
from ..db import count_rows, engine
from ..models import SyncState, Workout, WorkoutSet

SOURCE = "hevy"
BASE = "https://api.hevyapp.com/v1"
TZ = ZoneInfo("Europe/Berlin")


def _local(iso: str | None) -> datetime | None:
    if not iso:
        return None
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is not None:
        dt = dt.astimezone(TZ).replace(tzinfo=None)
    return dt


def fetch_workouts(api_key: str, page_size: int = 10) -> list[dict]:
    headers = {"api-key": api_key, "Accept": "application/json"}
    out: list[dict] = []
    with httpx.Client(timeout=30, headers=headers) as c:
        page = 1
        while True:
            r = c.get(f"{BASE}/workouts", params={"page": page, "pageSize": page_size})
            r.raise_for_status()
            d = r.json()
            out.extend(d.get("workouts", []))
            if page >= int(d.get("page_count", 1)):
                break
            page += 1
    return out


def fetch_events(api_key: str, since: str, page_size: int = 10) -> list[dict]:
    """Inkrementelle Aenderungen seit `since` (ISO-UTC): events mit type updated/deleted."""
    headers = {"api-key": api_key, "Accept": "application/json"}
    out: list[dict] = []
    with httpx.Client(timeout=30, headers=headers) as c:
        page = 1
        while True:
            r = c.get(f"{BASE}/workouts/events", params={"since": since, "page": page, "pageSize": page_size})
            r.raise_for_status()
            d = r.json()
            out.extend(d.get("events", []))
            if page >= int(d.get("page_count", 1)):
                break
            page += 1
    return out


def fetch_workout(api_key: str, workout_id: str) -> dict | None:
    """Einzelnes Workout inkl. Saetze (events liefern nur Metadaten)."""
    headers = {"api-key": api_key, "Accept": "application/json"}
    r = httpx.get(f"{BASE}/workouts/{workout_id}", headers=headers, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _upsert_workout(s: Session, w: dict) -> bool:
    """Workout neu anlegen oder aktualisieren; Saetze je Workout neu setzen. True wenn neu."""
    wo = s.execute(select(Workout).where(Workout.external_id == w.get("id"))).scalar_one_or_none()
    is_new = wo is None
    if wo is None:
        wo = Workout(external_id=w.get("id"), source=SOURCE)
        s.add(wo)
    wo.title = w.get("title")
    wo.started_at = _local(w.get("start_time"))
    wo.ended_at = _local(w.get("end_time"))
    s.flush()  # wo.id
    s.execute(delete(WorkoutSet).where(WorkoutSet.workout_id == wo.id))
    for ex in w.get("exercises", []):
        title = ex.get("title")
        for st in ex.get("sets", []):
            s.add(WorkoutSet(
                workout_id=wo.id, exercise=title,
                set_index=st.get("index"), set_type=st.get("type"),
                weight_kg=st.get("weight_kg"), reps=st.get("reps"), rpe=st.get("rpe"),
            ))
    return is_new


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def import_hevy(full: bool = False) -> dict:
    """Inkrementeller Hevy-Sync.
    - Erstlauf (kein Cursor) oder full=True: kompletter Pull aller Workouts.
    - Sonst: nur Aenderungen seit dem letzten Cursor (events) -> neu/aktualisiert/geloescht.
    Cursor (Zeitpunkt) lebt in sync_state(source='hevy').cursor."""
    if not settings.hevy_api_key:
        raise RuntimeError("HEVY_API_KEY fehlt in server/.env")
    key = settings.hevy_api_key
    now_iso = _now_iso()

    with Session(engine) as s:
        st = s.get(SyncState, SOURCE)
        cursor = None if full else (st.cursor if st else None)

    if cursor:
        events = fetch_events(key, cursor)
        added = updated = deleted = 0
        with Session(engine) as s:
            for ev in events:
                w = ev.get("workout") or {}
                wid = w.get("id")
                if not wid:
                    continue
                if ev.get("type") == "deleted":
                    wo = s.execute(select(Workout).where(Workout.external_id == wid)).scalar_one_or_none()
                    if wo:
                        s.execute(delete(WorkoutSet).where(WorkoutSet.workout_id == wo.id))
                        s.delete(wo)
                        deleted += 1
                else:  # created / updated -> Detail mit Saetzen holen
                    detail = fetch_workout(key, wid)
                    if detail and _upsert_workout(s, detail):
                        added += 1
                    elif detail:
                        updated += 1
            st = s.get(SyncState, SOURCE) or SyncState(source=SOURCE)
            st.cursor = now_iso
            s.merge(st)
            s.commit()
        return {"mode": "incremental", "events": len(events),
                "added": added, "updated": updated, "deleted": deleted}

    # Voll-/Erstlauf (setzt zugleich den Cursor)
    raw = fetch_workouts(key)
    with Session(engine) as s:
        if full:
            ids = s.execute(select(Workout.id).where(Workout.source == SOURCE)).scalars().all()
            if ids:
                s.execute(delete(WorkoutSet).where(WorkoutSet.workout_id.in_(ids)))
            s.execute(delete(Workout).where(Workout.source == SOURCE))
            s.flush()
        before = count_rows(s, Workout, SOURCE)
        for w in raw:
            _upsert_workout(s, w)
        st = s.get(SyncState, SOURCE) or SyncState(source=SOURCE)
        st.cursor = now_iso
        s.merge(st)
        s.commit()
        after = count_rows(s, Workout, SOURCE)
    return {"mode": "full" if full else "initial", "workouts_fetched": len(raw), "new": after - before}


if __name__ == "__main__":
    from ..db import init_db

    init_db()
    print("Hevy-Import:", import_hevy())
    with Session(engine) as s:
        nw = s.execute(select(func.count()).select_from(Workout).where(Workout.source == SOURCE)).scalar_one()
        ns = s.execute(select(func.count()).select_from(WorkoutSet)).scalar_one()
        rng = s.execute(select(func.min(Workout.started_at), func.max(Workout.started_at)).where(Workout.source == SOURCE)).first()
        print(f"workouts={nw}  sets={ns}  zeitraum={rng[0]} .. {rng[1]}")
        print("Top-Übungen (Arbeitssätze):")
        rows = s.execute(
            select(WorkoutSet.exercise, func.count())
            .where(WorkoutSet.set_type == "normal")
            .group_by(WorkoutSet.exercise).order_by(func.count().desc()).limit(6)
        ).all()
        for ex, n in rows:
            print(f"  {n:>4}  {ex}")
