"""Health-Connect-Import: liest die exportierte SQLite-DB (Vollabzug) und
schreibt Körper-, Lauf-/Cardio-, VO2max- und Schritt-Daten in die App-DB.

Verifizierte Format-Notizen (siehe CLAUDE.md / ARCHITECTURE.md §3):
- Zeitstempel = epoch-Millisekunden (UTC) + *_zone_offset in Sekunden (lokale Wandzeit = utc+offset).
- Gewicht in GRAMM (-> /1000 kg). Körperfett als percentage. VO2 = ml/min/kg.
- Distanz in METERN als feingranulare Segmente -> pro Session im Zeitfenster summieren.
- exercise_type (android.health.connect ExerciseSessionType): 4=Radfahren, 33=Laufen, 45=Kraft,
  53=Gehen, 58=Laufband. Höhenmeter nicht vorhanden.
- Herzfrequenz: Einzelwerte liegen in heart_rate_record_series_table (epoch_millis /
  beats_per_minute, parent_key -> heart_rate_record_table.row_id). Pro Session im Zeitfenster
  aggregieren (Ø/Max + Drift 2. vs. 1. Hälfte). Quelle bevorzugt die Watch-App
  (settings.steps_source_package), Fallback = alle Apps.
- HC-Export ist ein Vollabzug -> idempotent durch Ersetzen aller source='health_connect'-Zeilen.
"""
from __future__ import annotations

import bisect
import logging
import sqlite3
from array import array
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

from sqlalchemy import delete
from sqlmodel import Session

from ..config import settings
from ..db import count_rows, engine, upsert
from ..models import BodyMeasurement, ExerciseSession, RestingHrDaily, StepsDaily, Vo2Max

SOURCE = "health_connect"
BIKE, RUN, STRENGTH, WALK = 4, 33, 45, 53
EPOCH = date(1970, 1, 1)
HR_MIN_BPM, HR_MAX_BPM = 25, 250  # Sanity-Grenzen fuer HF-Samples
HR_MIN_SAMPLES = 5  # Mindest-Samples, bevor Ø/Max/Drift berechnet werden


def _read_hr_series(cur: sqlite3.Cursor) -> tuple[array, array]:
    """Laedt die komplette HF-Serie (epoch_millis aufsteigend, bpm) als kompakte Arrays.
    Defensive gegen Schema-Abweichungen (Tabelle/Spalten fehlen -> leere Serie, nur Warnung).
    Bevorzugt Samples der Watch-App (settings.steps_source_package via parent-Record),
    faellt bei 0 Treffern auf alle Apps zurueck."""
    times, bpm = array("q"), array("d")
    tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "heart_rate_record_series_table" not in tables:
        log.warning("heart_rate_record_series_table fehlt im Export -> keine HF-Daten")
        return times, bpm
    cols = {row[1] for row in cur.execute("PRAGMA table_info(heart_rate_record_series_table)")}
    if not {"epoch_millis", "beats_per_minute"} <= cols:
        log.warning("HF-Serie hat unerwartete Spalten %s -> keine HF-Daten", sorted(cols))
        return times, bpm

    base = ("SELECT s.epoch_millis, s.beats_per_minute FROM heart_rate_record_series_table s{join} "
            "ORDER BY s.epoch_millis")
    queries: list[tuple[str, tuple]] = []
    if (settings.steps_source_package and "parent_key" in cols
            and "heart_rate_record_table" in tables):
        app_ids = [row[0] for row in cur.execute(
            "SELECT row_id FROM application_info_table WHERE package_name = ?",
            (settings.steps_source_package,))]
        if app_ids:
            ph = ",".join("?" * len(app_ids))
            queries.append((base.format(
                join=" JOIN heart_rate_record_table p ON s.parent_key = p.row_id"
                     f" AND p.app_info_id IN ({ph})"), tuple(app_ids)))
    queries.append((base.format(join=""), ()))

    for sql, params in queries:
        t_acc, b_acc = array("q"), array("d")
        try:
            for t, v in cur.execute(sql, params):
                if t is not None and v is not None and HR_MIN_BPM <= v <= HR_MAX_BPM:
                    t_acc.append(int(t))
                    b_acc.append(float(v))
        except sqlite3.Error as exc:  # z. B. abweichendes parent-Schema -> Fallback probieren
            log.warning("HF-Abfrage fehlgeschlagen (%s) -> Fallback", exc)
            continue
        if t_acc:
            times, bpm = t_acc, b_acc
            break
    return times, bpm


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

    # --- Herzfrequenz-Serie (epoch_millis + bpm), einmal sortiert laden -> Fenster je Session.
    # Bevorzugt die Watch-App (steps_source_package = Samsung Health), damit parallel
    # schreibende Apps (Handy-Sensoren o. ä.) Ø/Max nicht verfälschen; Fallback = alle Apps.
    hr_times, hr_bpm = _read_hr_series(cur)

    def session_hr(start_ms: int | None, end_ms: int | None) -> dict:
        """Ø-/Max-HF + Drift (Ø 2. Hälfte vs. Ø 1. Hälfte, %) im Session-Fenster."""
        out = {"avg_hr": None, "max_hr": None, "hr_drift_pct": None}
        if start_ms is None or end_ms is None or end_ms <= start_ms or not hr_times:
            return out
        i = bisect.bisect_left(hr_times, start_ms)
        j = bisect.bisect_right(hr_times, end_ms)
        window = hr_bpm[i:j]
        if len(window) < HR_MIN_SAMPLES:
            return out
        out["avg_hr"] = round(sum(window) / len(window), 1)
        out["max_hr"] = round(max(window), 0)
        # Drift nur für längere Einheiten (>= 15 min) mit genug Datenpunkten je Hälfte —
        # klassisches Decoupling-Signal bei Dauerläufen.
        if end_ms - start_ms >= 15 * 60_000:
            mid = bisect.bisect_right(hr_times, (start_ms + end_ms) // 2, i, j)
            first, second = hr_bpm[i:mid], hr_bpm[mid:j]
            if len(first) >= HR_MIN_SAMPLES and len(second) >= HR_MIN_SAMPLES:
                a1, a2 = sum(first) / len(first), sum(second) / len(second)
                if a1 > 0:
                    out["hr_drift_pct"] = round((a2 / a1 - 1) * 100, 1)
        return out

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
                **session_hr(r["start_time"], r["end_time"]),
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

    # --- Ruhepuls: resting_heart_rate_record_table (Instant-Record der Watch). Pro lokalem
    # Tag die NIEDRIGSTE Messung (= echter Ruhewert). Defensiv: Tabelle/Spalten koennen fehlen. ---
    resting: list[dict] = []
    tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "resting_heart_rate_record_table" in tables:
        rcols = {row[1] for row in cur.execute("PRAGMA table_info(resting_heart_rate_record_table)")}
        if {"time", "beats_per_minute"} <= rcols:
            rwhere, rparams = "", ()
            if step_ids and "app_info_id" in rcols:  # Watch bevorzugen (wie Schritte/HF)
                ph = ",".join("?" * len(step_ids))
                rwhere, rparams = f" WHERE app_info_id IN ({ph})", tuple(step_ids)
            sel_off = "zone_offset" if "zone_offset" in rcols else "NULL AS zone_offset"
            per_day: dict[date, float] = {}
            for r in cur.execute(
                f"SELECT time, {sel_off}, beats_per_minute FROM resting_heart_rate_record_table{rwhere}",
                rparams,
            ):
                t = _local(r["time"], r["zone_offset"])
                v = r["beats_per_minute"]
                if t is None or v is None or not (HR_MIN_BPM <= v <= HR_MAX_BPM):
                    continue
                d = t.date()
                per_day[d] = min(per_day.get(d, 999.0), float(v))
            resting = [{"day": d, "bpm": v, "source": SOURCE} for d, v in per_day.items()]
        else:
            log.warning("resting_heart_rate_record_table hat unerwartete Spalten %s", sorted(rcols))

    con.close()
    return {"body": body, "sessions": sessions, "vo2": vo2, "steps": steps, "resting": resting}


def import_health_connect(db_path: str | Path, full: bool = False) -> dict:
    """Importiert die HC-DB idempotent (Append: nur neue Zeilen werden geschrieben).
    full=True macht eine Voll-Reconciliation (loescht source-Zeilen vorher -> spiegelt auch Loeschungen)."""
    data = read_health_connect(db_path)
    models_ = (BodyMeasurement, ExerciseSession, Vo2Max, StepsDaily, RestingHrDaily)
    with Session(engine) as s:
        if full:
            for m in models_:
                # Tageswert-Historien nie löschen, wenn der Import keine liefert
                # (Fehlkonfiguration/leerer Export) -> schützt vor versehentlichem Leeren.
                if m is StepsDaily and not data["steps"]:
                    continue
                if m is RestingHrDaily and not data["resting"]:
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

        # HF kam spaeter dazu: liefert der Export HF, werden bestehende Sessions per
        # DO UPDATE retro-gefuellt; ohne HF bleibt der Upsert append-only. coalesce=True
        # haertet zusaetzlich pro Zeile: eine Session, die im aktuellen Export keine
        # Fenster-Samples hat, nullt nie einen frueher berechneten Wert (full=True ersetzt).
        sessions_with_hr = sum(1 for d in sess_rows if d.get("avg_hr") is not None)
        hr_update = ["avg_hr", "max_hr", "hr_drift_pct"] if sessions_with_hr else None

        upsert(s, BodyMeasurement, body_rows, ["measured_at", "source"])
        upsert(s, ExerciseSession, sess_rows, ["external_id"], update_cols=hr_update, coalesce=True)
        upsert(s, Vo2Max, vo2_rows, ["measured_at"])
        upsert(s, StepsDaily, data["steps"], ["day"], update_cols=["steps"])  # Schritte/Tag koennen wachsen
        upsert(s, RestingHrDaily, data["resting"], ["day"], update_cols=["bpm"])
        s.commit()
        after = {m.__name__: count_rows(s, m, SOURCE) for m in models_}

    return {
        "mode": "full" if full else "incremental",
        "new_body": after["BodyMeasurement"] - before["BodyMeasurement"],
        "new_sessions": after["ExerciseSession"] - before["ExerciseSession"],
        "new_vo2max": after["Vo2Max"] - before["Vo2Max"],
        "new_steps_days": after["StepsDaily"] - before["StepsDaily"],
        "new_resting_hr_days": after["RestingHrDaily"] - before["RestingHrDaily"],
        "total_sessions": after["ExerciseSession"],
        "sessions_with_hr": sessions_with_hr,
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

        n_hr = s.execute(
            select(func.count()).select_from(ExerciseSession).where(ExerciseSession.avg_hr.is_not(None))
        ).scalar_one()
        print(f"Sessions mit HF: {n_hr}")
        last_run_hr = s.execute(
            select(ExerciseSession.started_at, ExerciseSession.avg_hr,
                   ExerciseSession.max_hr, ExerciseSession.hr_drift_pct)
            .where(ExerciseSession.exercise_type == RUN, ExerciseSession.avg_hr.is_not(None))
            .order_by(ExerciseSession.started_at.desc()).limit(1)
        ).first()
        if last_run_hr:
            print(f"Letzter Lauf mit HF: {last_run_hr[0]:%Y-%m-%d} — Ø {last_run_hr[1]:.0f} / "
                  f"max {last_run_hr[2]:.0f} bpm, Drift {last_run_hr[3]}%")
