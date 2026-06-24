"""Health-Connect-Import: liest die exportierte SQLite-DB (Vollabzug) und
schreibt Körper-, Lauf-/Cardio-, VO2max- und Schritt-Daten in die App-DB.

Verifizierte Format-Notizen (siehe CLAUDE.md / ARCHITECTURE.md §3):
- Zeitstempel = epoch-Millisekunden (UTC) + *_zone_offset in Sekunden (lokale Wandzeit = utc+offset).
- Gewicht in GRAMM (-> /1000 kg). Körperfett als percentage. VO2 = ml/min/kg.
- Distanz in METERN als feingranulare Segmente -> pro Session im Zeitfenster summieren.
- exercise_type (android.health.connect ExerciseSessionType): 4=Radfahren, 33=Laufen, 45=Kraft,
  53=Gehen, 58=Laufband. Höhenmeter nicht vorhanden.
- HC-Export ist ein Vollabzug -> idempotent durch Ersetzen aller source='health_connect'-Zeilen.
"""
from __future__ import annotations

import bisect
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

from sqlalchemy import delete
from sqlmodel import Session

from ..config import settings
from ..db import count_rows, engine, upsert
from ..models import BodyMeasurement, ExerciseSession, StepsDaily, Vo2Max

SOURCE = "health_connect"
BIKE, RUN, STRENGTH, WALK = 4, 33, 45, 53
EPOCH = date(1970, 1, 1)


def _utc(ms: int | None) -> datetime | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _local(ms: int | None, offset_s: int | None) -> datetime | None:
    """Lokale Wandzeit als naive datetime (utc + zone_offset)."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000 + (offset_s or 0), tz=timezone.utc).replace(tzinfo=None)


def read_health_connect(db_path: str | Path) -> dict:
    """Liest die HC-DB read-only und liefert transformierte Datensätze (noch ohne Persistenz)."""
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # --- Körper: Gewicht (Gramm) + Körperfett (%) über denselben Zeitstempel mergen ---
    # Nur Messungen aus der konfigurierten Waagen-App übernehmen (z. B. Arboleaf) — andere
    # Quellen (Google Fit, Samsung Health) liefern Ausreißer/0-Werte und verfälschen den Trend.
    app_ids = []
    if settings.body_source_package:
        app_ids = [row[0] for row in cur.execute(
            "SELECT row_id FROM application_info_table WHERE package_name = ?",
            (settings.body_source_package,))]
    where = f" WHERE app_info_id IN ({','.join('?' * len(app_ids))})" if app_ids else ""
    params = tuple(app_ids)

    body: dict[datetime, dict] = {}
    for r in cur.execute(f"SELECT time, zone_offset, weight FROM weight_record_table{where}", params):
        t = _local(r["time"], r["zone_offset"])
        if t is not None:
            body.setdefault(t, {})["weight_kg"] = (r["weight"] or 0) / 1000.0
    for r in cur.execute(f"SELECT time, zone_offset, percentage FROM body_fat_record_table{where}", params):
        t = _local(r["time"], r["zone_offset"])
        if t is not None:
            body.setdefault(t, {})["body_fat_pct"] = r["percentage"]

    # --- Distanz-Segmente (Meter), sortiert nach UTC-Start, für Fenster-Summe je Session ---
    seg = [
        (_utc(r["start_time"]), _utc(r["end_time"]), r["distance"])
        for r in cur.execute("SELECT start_time, end_time, distance FROM distance_record_table")
    ]
    seg = [s for s in seg if s[0] is not None]
    seg.sort(key=lambda s: s[0])
    seg_starts = [s[0] for s in seg]

    def session_distance_m(start_utc: datetime | None, end_utc: datetime | None) -> float:
        if start_utc is None or end_utc is None:
            return 0.0
        total = 0.0
        i = bisect.bisect_left(seg_starts, start_utc)
        while i < len(seg) and seg[i][0] <= end_utc:
            s, e, d = seg[i]
            if d and (e is None or e <= end_utc):
                total += d
            i += 1
        return total

    # --- Sessions (Lauf/Kraft/Gehen/…) ---
    sessions = []
    for r in cur.execute(
        "SELECT uuid, start_time, start_zone_offset, end_time, exercise_type, title "
        "FROM exercise_session_record_table"
    ):
        start_utc, end_utc = _utc(r["start_time"]), _utc(r["end_time"])
        dist_m = session_distance_m(start_utc, end_utc)
        uuid = r["uuid"]
        sessions.append(
            dict(
                external_id=uuid.hex() if isinstance(uuid, (bytes, bytearray)) else str(uuid),
                exercise_type=r["exercise_type"],
                started_at=_local(r["start_time"], r["start_zone_offset"]),
                ended_at=_local(r["end_time"], r["start_zone_offset"]),
                distance_km=round(dist_m / 1000.0, 3) if dist_m else None,
                source=SOURCE,
            )
        )

    # --- VO2max ---
    vo2 = [
        dict(measured_at=_local(r["time"], r["zone_offset"]),
             vo2=r["vo2_milliliters_per_minute_kilogram"], source=SOURCE)
        for r in cur.execute(
            "SELECT time, zone_offset, vo2_milliliters_per_minute_kilogram FROM vo2_max_record_table"
        )
    ]

    # --- Schritte: Tagessumme über local_date (= epoch-Tag-Nummer). Mehrere Apps tracken
    # parallel (Galaxy Watch + Google Fit). Maßgeblich ist die Watch (Samsung Health) —
    # Google Fit zählt das Handy und untertreibt an Tagen ohne Handy (Niedrig-Schritt-Tage).
    # Default: nur die konfigurierte Schritt-App. Leer = Maximum je Tag über alle Apps
    # (entdoppelt: NICHT summieren, sonst 27k + 27k = 54k). ---
    # App-IDs der konfigurierten Schritt-App auflösen. Wird sie NICHT gefunden, KEIN
    # `IN (NULL)` bauen (liefert 0 Zeilen -> würde bei full=True die Schritt-Historie löschen),
    # sondern mit Warnung auf das Tages-Maximum über alle Apps zurückfallen.
    step_ids: list[int] = []
    if settings.steps_source_package:
        step_ids = [row[0] for row in cur.execute(
            "SELECT row_id FROM application_info_table WHERE package_name = ?",
            (settings.steps_source_package,))]
        if not step_ids:
            log.warning("steps_source_package %r nicht in application_info_table gefunden "
                        "-> Fallback: Maximum je Tag über alle Apps", settings.steps_source_package)
    if step_ids:
        placeholders = ",".join("?" * len(step_ids))
        steps_sql = (
            "SELECT local_date, SUM(count) c FROM steps_record_table "
            f"WHERE local_date IS NOT NULL AND app_info_id IN ({placeholders}) GROUP BY local_date"
        )
        steps_params: tuple = tuple(step_ids)
    else:
        steps_sql = (
            "SELECT local_date, MAX(per_app) c FROM ("
            "  SELECT local_date, app_info_id, SUM(count) per_app FROM steps_record_table"
            "  WHERE local_date IS NOT NULL GROUP BY local_date, app_info_id"
            ") GROUP BY local_date"
        )
        steps_params = ()
    steps = [
        dict(day=EPOCH + timedelta(days=r["local_date"]), steps=int(r["c"] or 0), source=SOURCE)
        for r in cur.execute(steps_sql, steps_params)
    ]

    con.close()
    return {"body": body, "sessions": sessions, "vo2": vo2, "steps": steps}


def import_health_connect(db_path: str | Path, full: bool = False) -> dict:
    """Importiert die HC-DB idempotent (Append: nur neue Zeilen werden geschrieben).
    full=True macht eine Voll-Reconciliation (loescht source-Zeilen vorher -> spiegelt auch Loeschungen)."""
    data = read_health_connect(db_path)
    models_ = (BodyMeasurement, ExerciseSession, Vo2Max, StepsDaily)
    with Session(engine) as s:
        if full:
            for m in models_:
                # Schritte nie löschen, wenn der Import keine liefert (Fehlkonfiguration/leer)
                # -> schützt die Schritt-Historie vor versehentlichem Leeren.
                if m is StepsDaily and not data["steps"]:
                    continue
                s.execute(delete(m).where(m.source == SOURCE))
        before = {m.__name__: count_rows(s, m, SOURCE) for m in models_}

        # einheitliche Spalten (sonst bricht der Bulk-INSERT bei gemischten Keys)
        body_rows = [
            {"measured_at": t, "source": SOURCE,
             "weight_kg": v.get("weight_kg"), "body_fat_pct": v.get("body_fat_pct")}
            for t, v in data["body"].items() if t is not None
        ]
        sess_rows = [d for d in data["sessions"] if d["started_at"] is not None]
        vo2_rows = [d for d in data["vo2"] if d["measured_at"] is not None]

        upsert(s, BodyMeasurement, body_rows, ["measured_at", "source"])
        upsert(s, ExerciseSession, sess_rows, ["external_id"])
        upsert(s, Vo2Max, vo2_rows, ["measured_at"])
        upsert(s, StepsDaily, data["steps"], ["day"], update_cols=["steps"])  # Schritte/Tag koennen wachsen
        s.commit()
        after = {m.__name__: count_rows(s, m, SOURCE) for m in models_}

    return {
        "mode": "full" if full else "incremental",
        "new_body": after["BodyMeasurement"] - before["BodyMeasurement"],
        "new_sessions": after["ExerciseSession"] - before["ExerciseSession"],
        "new_vo2max": after["Vo2Max"] - before["Vo2Max"],
        "new_steps_days": after["StepsDaily"] - before["StepsDaily"],
        "total_sessions": after["ExerciseSession"],
    }


if __name__ == "__main__":
    # Verifikationslauf:  python -m app.ingest.health_connect [pfad-zur-db]
    import sys

    from sqlalchemy import func, select

    from ..config import INCOMING_DIR
    from ..db import init_db

    path = sys.argv[1] if len(sys.argv) > 1 else str(INCOMING_DIR / "health_connect_export.db")
    init_db()
    print(f"Import aus: {path}")
    counts = import_health_connect(path)
    print("Importiert:", counts)

    with Session(engine) as s:
        print("\nSessions nach exercise_type:")
        rows = s.execute(
            select(ExerciseSession.exercise_type, func.count())
            .group_by(ExerciseSession.exercise_type)
            .order_by(func.count().desc())
        ).all()
        for et, n in rows:
            label = {BIKE: "Rad", RUN: "Laufen", STRENGTH: "Kraft", WALK: "Gehen"}.get(et, "—")
            print(f"  type {et:>4} ({label:<7}): {n}")

        for et, name in ((RUN, "Lauf"), (BIKE, "Rad")):
            km = s.execute(
                select(func.sum(ExerciseSession.distance_km)).where(ExerciseSession.exercise_type == et)
            ).scalar_one_or_none()
            print(f"{name}-Distanz gesamt (type {et}): {round(km or 0, 1)} km")

        latest = s.execute(
            select(BodyMeasurement.measured_at, BodyMeasurement.weight_kg)
            .where(BodyMeasurement.weight_kg.is_not(None))
            .order_by(BodyMeasurement.measured_at.desc()).limit(1)
        ).first()
        if latest:
            print(f"Letztes Gewicht: {latest[1]:.2f} kg am {latest[0]:%Y-%m-%d}")

        vo2_latest = s.execute(
            select(Vo2Max.measured_at, Vo2Max.vo2).order_by(Vo2Max.measured_at.desc()).limit(1)
        ).first()
        if vo2_latest:
            print(f"Letzter VO2max: {vo2_latest[1]:.1f} am {vo2_latest[0]:%Y-%m-%d}")
