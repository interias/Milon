"""Health-Connect-Import: liest die exportierte SQLite-DB (Vollabzug) und
schreibt Körper-, Lauf-/Cardio-, VO2max- und Schritt-Daten in die App-DB.

Verifizierte Format-Notizen (siehe CLAUDE.md / ARCHITECTURE.md §3):
- Zeitstempel = epoch-Millisekunden (UTC) + *_zone_offset in Sekunden (lokale Wandzeit = utc+offset).
- Gewicht in GRAMM (-> /1000 kg). Körperfett als percentage. VO2 = ml/min/kg.
- Distanz in METERN als feingranulare Segmente -> pro Session im Zeitfenster summieren,
  aber JE APP (mehrere Apps spiegeln dieselbe Strecke): Watch bevorzugt, sonst Max je App.
- exercise_type (android.health.connect ExerciseSessionType): 4=Radfahren, 33=Laufen, 45=Kraft,
  53=Gehen, 58=Laufband. Höhenmeter nicht vorhanden.
- Herzfrequenz: Einzelwerte liegen in heart_rate_record_series_table (epoch_millis /
  beats_per_minute, parent_key -> heart_rate_record_table.row_id). Pro Session im Zeitfenster
  aggregieren (Ø/Max + Drift 2. vs. 1. Hälfte). Quelle bevorzugt die Watch-App
  (date-aware configured source), legacy fallback = all apps.
- HC-Export ist ein Vollabzug -> idempotent durch Ersetzen aller source='health_connect'-Zeilen.
"""
from __future__ import annotations

import bisect
import logging
import math
import sqlite3
from array import array
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

from sqlalchemy import delete, select
from sqlmodel import Session

from ..config import settings, watch_source_for
from ..db import count_rows, engine, upsert
from ..models import (BodyMeasurement, ExerciseSession, RestingHrDaily, RunBestEffort,
                      RunMinute, SleepSession, StepsDaily, Vo2Max)
from .run_windows import read_run_windows

SOURCE = "health_connect"
BIKE, RUN, STRENGTH, WALK = 4, 33, 45, 53
EPOCH = date(1970, 1, 1)
HR_MIN_BPM, HR_MAX_BPM = 25, 250  # Sanity-Grenzen fuer HF-Samples
HR_MIN_SAMPLES = 5  # Mindest-Samples, bevor Ø/Max/Drift berechnet werden
# Standard-Distanzen (m) für Best-Effort-Splits (schnellste X km innerhalb eines Laufs).
BEST_EFFORT_DISTANCES = (1000, 5000, 10000, 15000, 20000)


def _read_hr_series(cur: sqlite3.Cursor, source_package: str | None = None, fallback: bool = True) -> tuple[array, array]:
    """Laedt die komplette HF-Serie (epoch_millis aufsteigend, bpm) als kompakte Arrays.
    Defensive gegen Schema-Abweichungen (Tabelle/Spalten fehlen -> leere Serie, nur Warnung).
    Bevorzugt Samples der Watch-App (settings.steps_source_package via parent-Record),
    faellt bei 0 Treffern auf alle Apps zurueck."""
    source_package = settings.steps_source_package if source_package is None else source_package
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
    if (source_package and "parent_key" in cols
            and "heart_rate_record_table" in tables):
        app_ids = [row[0] for row in cur.execute(
            "SELECT row_id FROM application_info_table WHERE package_name = ?",
            (source_package,))]
        if app_ids:
            ph = ",".join("?" * len(app_ids))
            queries.append((base.format(
                join=" JOIN heart_rate_record_table p ON s.parent_key = p.row_id"
                     f" AND p.app_info_id IN ({ph})"), tuple(app_ids)))
    if fallback:
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


def _sleep_minutes(start: int, end: int, stages: list[tuple]) -> dict:
    """Union stage windows, rejecting conflicting states and incomplete known coverage.

    Android stages: 0 unknown, 1/3/7 awake, 2/4/5/6 sleeping. Only measured
    sleeping stages contribute; unknown intervals never become sleep by subtraction.
    """
    sleeping, awake = {2, 4, 5, 6}, {1, 3, 7}
    events: dict[int, list[tuple[int, int]]] = {}
    for a, b, stage in stages:
        if a is None or b is None or stage not in sleeping | awake:
            continue
        a, b = max(start, int(a)), min(end, int(b))
        if b <= a:
            continue
        events.setdefault(a, []).append((int(stage), 1))
        events.setdefault(b, []).append((int(stage), -1))
    active: dict[int, int] = {}
    previous, sleep_ms, awake_ms, conflict = start, 0, 0, False
    for t in sorted(events):
        types = {stage for stage, count in active.items() if count > 0}
        is_sleeping, is_awake = bool(types & sleeping), bool(types & awake)
        if is_sleeping and is_awake:
            conflict = True
        elif is_sleeping:
            sleep_ms += t - previous
        elif is_awake:
            awake_ms += t - previous
        for stage, delta in events[t]:
            active[stage] = active.get(stage, 0) + delta
        previous = t
    coverage = (sleep_ms + awake_ms) / (end - start)
    valid = coverage >= 0.98 and not conflict
    return {"asleep_minutes": round(sleep_ms / 60_000, 2) if valid else None,
            "awake_minutes": round(awake_ms / 60_000, 2) if valid else None,
            "stage_coverage": round(coverage, 4)}


def _read_sleep(con: sqlite3.Connection) -> dict:
    """Read the verified AOSP sleep schema without treating missing stages as zero sleep."""
    cur = con.cursor()
    tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = {"row_id", "uuid", "start_time", "end_time", "app_info_id"}
    cols = {row[1] for row in cur.execute("PRAGMA table_info(sleep_session_record_table)")}
    if not required <= cols or "application_info_table" not in tables:
        return {"rows": [], "available": False, "stages_available": False}
    stage_cols = {row[1] for row in cur.execute("PRAGMA table_info(sleep_stages_table)")}
    stages_available = {"parent_key", "stage_start_time", "stage_end_time", "stage_type"} <= stage_cols
    stages: dict[int, list[tuple]] = {}
    if stages_available:
        for parent, a, b, stage in cur.execute(
                "SELECT parent_key, stage_start_time, stage_end_time, stage_type FROM sleep_stages_table"):
            stages.setdefault(parent, []).append((a, b, stage))
    packages = dict(cur.execute("SELECT row_id, package_name FROM application_info_table"))
    rows = []
    for record in cur.execute("SELECT * FROM sleep_session_record_table ORDER BY start_time"):
        start, end = record["start_time"], record["end_time"]
        if start is None or end is None or not 0 < end - start <= 24 * 3_600_000:
            continue
        start_offset = record["start_zone_offset"] if "start_zone_offset" in cols else None
        end_offset = record["end_zone_offset"] if "end_zone_offset" in cols else start_offset
        if end_offset is None:
            end_offset = start_offset
        local_start, local_end = _local(start, start_offset), _local(end, end_offset)
        package = packages.get(record["app_info_id"], "")
        if not package or package != watch_source_for(local_end.date(), settings):
            continue
        raw_id = record["uuid"]
        external_id = raw_id.hex() if isinstance(raw_id, (bytes, bytearray)) else str(raw_id)
        rows.append({"external_id": external_id, "started_at": local_start, "ended_at": local_end,
                     "day": local_end.date(), "duration_window_minutes": round((end - start) / 60_000, 2),
                     "main_sleep": end - start >= 120 * 60_000,
                     "source_package": package, "source": SOURCE,
                     **_sleep_minutes(start, end, stages.get(record["row_id"], []))})
    return {"rows": rows, "available": True, "stages_available": stages_available}


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
    rejected_times: set[datetime] = set()
    for r in cur.execute(f"SELECT time, zone_offset, weight FROM weight_record_table{where}", params):
        t = _local(r["time"], r["zone_offset"])
        if t is not None:
            weight = (r["weight"] or 0) / 1000.0
            if (not math.isfinite(weight) or weight <= 0
                    or (settings.body_weight_min_kg is not None and weight < settings.body_weight_min_kg)
                    or (settings.body_weight_max_kg is not None and weight > settings.body_weight_max_kg)):
                rejected_times.add(t)
                continue
            body.setdefault(t, {})["weight_kg"] = weight
    for r in cur.execute(f"SELECT time, zone_offset, percentage FROM body_fat_record_table{where}", params):
        t = _local(r["time"], r["zone_offset"])
        if t is not None:
            body.setdefault(t, {})["body_fat_pct"] = r["percentage"]

    # Reject the complete measurement so another person's paired body fat cannot leak through.
    for t in rejected_times:
        body.pop(t, None)
    if rejected_times:
        log.warning("%d Koerpermessungen ausserhalb der Gewichtsgrenzen uebersprungen", len(rejected_times))

    # --- Distanz-Segmente (Meter) je App, sortiert nach UTC-Start, für Fenster-Summe je Session.
    # WICHTIG (am echten Export 2026-07-10 verifiziert): Mehrere Apps spiegeln dieselbe Strecke
    # (Google Fit/Strava/Samsung schreiben parallel nahezu identische Segmente). NIE über alle
    # Apps summieren — das ergab im März/April 2026 die 2–3-fache Distanz (Pace 2:00–3:30 min/km).
    # Watch-App nach lokalem Datum wählen; nach einem Wechsel kein Quellen-Fallback. ---
    packages = {}
    for app_id, package in cur.execute("SELECT row_id, package_name FROM application_info_table"):
        packages.setdefault(package, set()).add(app_id)
    cutoff = getattr(settings, "watch_source_switch_date", None)
    legacy_ids = set(getattr(settings, "watch_source_legacy_session_ids", []))

    def session_source_day(external_id: str, day: date) -> date:
        return cutoff - timedelta(days=1) if cutoff is not None and external_id in legacy_ids else day

    def watch_ids_for(day: date) -> set[int]:
        return packages.get(watch_source_for(day, settings), set())

    def strict_day(day: date) -> bool:
        return cutoff is not None and day >= cutoff

    seg = [
        (_utc(r["start_time"]), _utc(r["end_time"]), r["distance"], r["app_info_id"])
        for r in cur.execute(
            "SELECT start_time, end_time, distance, app_info_id FROM distance_record_table")
    ]
    seg = [s for s in seg if s[0] is not None]
    seg.sort(key=lambda s: s[0])
    seg_starts = [s[0] for s in seg]

    def session_distance_m(start_utc: datetime | None, end_utc: datetime | None, day: date) -> float:
        if start_utc is None or end_utc is None:
            return 0.0
        per_app: dict[int | None, float] = {}
        i = bisect.bisect_left(seg_starts, start_utc)
        while i < len(seg) and seg[i][0] <= end_utc:
            s, e, d, app = seg[i]
            if d and (e is None or e <= end_utc):
                per_app[app] = per_app.get(app, 0.0) + d
            i += 1
        if not per_app:
            return 0.0
        watch = sum(v for a, v in per_app.items() if a in watch_ids_for(day))
        return watch if watch > 0 or strict_day(day) else max(per_app.values())

    invalid_best_effort_ids: set[str] = set()

    def session_best_efforts(start_utc: datetime | None, end_utc: datetime | None, day: date,
                             external_id: str) -> dict[int, float]:
        """Beste Zeit (s) für jede Standard-Distanz INNERHALB des Laufs (schnellstes
        zusammenhängendes X-km-Fenster). Nur Watch-Segmente (parallel schreibende Apps
        würden die Strecke doppeln); lineare Interpolation an den Fenster-Rändern für Präzision."""
        watch_ids = watch_ids_for(day)
        if start_utc is None or end_utc is None or not watch_ids:
            return {}
        i = bisect.bisect_left(seg_starts, start_utc)
        ts: list[datetime] = []
        cum: list[float] = []
        total = 0.0
        while i < len(seg) and seg[i][0] <= end_utc:
            s, e, d, app = seg[i]
            if d and e is not None and e <= end_utc and e > s and app in watch_ids:
                # Whole-session Garmin totals do not identify fastest intra-run splits.
                # Flag positive coarse evidence; absent raw data must retain prior splits.
                if strict_day(day) and (e - s).total_seconds() > 60:
                    invalid_best_effort_ids.add(external_id)
                    return {}
                if not ts:
                    ts.append(s); cum.append(0.0)
                total += d
                ts.append(e); cum.append(total)
            i += 1
        if total < BEST_EFFORT_DISTANCES[0] or len(cum) < 2:
            return {}
        out: dict[int, float] = {}
        for target in BEST_EFFORT_DISTANCES:
            if total < target:
                continue
            best: float | None = None
            a = 0
            for b in range(1, len(cum)):
                while cum[b] - cum[a] >= target:
                    # exakte Startzeit im Segment a..a+1, sodass genau `target` m im Fenster liegen
                    seg_d = cum[a + 1] - cum[a]
                    frac = 0.0 if seg_d <= 0 else (cum[b] - target - cum[a]) / seg_d
                    t_start = ts[a] + frac * (ts[a + 1] - ts[a])
                    dt = (ts[b] - t_start).total_seconds()
                    if best is None or dt < best:
                        best = dt
                    a += 1
            if best is not None and best > 0:
                out[target] = round(best, 1)
        return out

    # --- Herzfrequenz-Serie (epoch_millis + bpm), einmal sortiert laden -> Fenster je Session.
    # Bevorzugt die Watch-App des jeweiligen Datums, damit parallel
    # schreibende Apps (Handy-Sensoren o. ä.) Ø/Max nicht verfälschen; Fallback = alle Apps.
    hr_by_source = {}
    hr_packages = {settings.steps_source_package}
    if cutoff is not None:
        hr_packages.add(settings.watch_source_package)
    for package in hr_packages:
        hr_by_source[package] = _read_hr_series(cur, package, fallback=(cutoff is None or package == settings.steps_source_package))

    def session_hr(start_ms: int | None, end_ms: int | None, day: date) -> dict:
        """Ø-/Max-HF + Drift (Ø 2. Hälfte vs. Ø 1. Hälfte, %) im Session-Fenster."""
        hr_times, hr_bpm = hr_by_source[watch_source_for(day, settings)]
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

    # --- Sessions (Lauf/Kraft/Gehen/…). Duplikate entfernen: Strava/Google Fit spiegeln
    # Watch-Sessions als eigene Records (identisches Zeitfenster, eigene uuid) — im April 2026
    # lag jeder Lauf doppelt vor. Watch-Sessions gewinnen; weitere Sessions gleichen Typs mit
    # überlappendem Zeitfenster werden verworfen. ---
    raw_sessions = list(cur.execute(
        "SELECT uuid, start_time, start_zone_offset, end_time, exercise_type, app_info_id "
        "FROM exercise_session_record_table"
    ))
    raw_sessions.sort(key=lambda r: (r["app_info_id"] not in watch_ids_for(
        (_local(r["start_time"], r["start_zone_offset"]) or datetime.min).date()), r["start_time"] or 0))
    kept_windows: dict[int, list[tuple[int, int]]] = {}
    sessions = []
    best_efforts: list[dict] = []
    skipped_dupes = 0
    for r in raw_sessions:
        st, en = r["start_time"], r["end_time"]
        started_local = _local(st, r["start_zone_offset"])
        day = (started_local or datetime.min).date()
        uuid = r["uuid"]
        ext_id = uuid.hex() if isinstance(uuid, (bytes, bytearray)) else str(uuid)
        source_day = session_source_day(ext_id, day)
        if (strict_day(source_day) or ext_id in legacy_ids) and r["app_info_id"] not in watch_ids_for(source_day):
            continue
        if st is not None and en is not None:
            windows = kept_windows.setdefault(r["exercise_type"], [])
            if any(st < e and en > s for s, e in windows):
                skipped_dupes += 1
                continue
            windows.append((st, en))
        start_utc, end_utc = _utc(st), _utc(en)
        dist_m = session_distance_m(start_utc, end_utc, source_day)
        sessions.append(
            dict(
                external_id=ext_id,
                exercise_type=r["exercise_type"],
                started_at=started_local,
                ended_at=_local(en, r["start_zone_offset"]),
                distance_km=round(dist_m / 1000.0, 3) if dist_m else None,
                source=SOURCE,
                **session_hr(st, en, source_day),
            )
        )
        # Best-Effort-Splits nur für Läufe (exercise_type 33)
        if r["exercise_type"] == RUN and started_local is not None:
            for target, secs in session_best_efforts(start_utc, end_utc, source_day, ext_id).items():
                best_efforts.append(dict(external_id=ext_id, distance_m=target,
                                         seconds=secs, started_at=started_local, source=SOURCE))
    if skipped_dupes:
        log.info("%d doppelte Sessions (parallel schreibende Apps) übersprungen", skipped_dupes)

    # --- VO2max ---
    vo2 = [
        dict(measured_at=_local(r["time"], r["zone_offset"]),
             vo2=r["vo2_milliliters_per_minute_kilogram"], source=SOURCE)
        for r in cur.execute(
            "SELECT time, zone_offset, vo2_milliliters_per_minute_kilogram FROM vo2_max_record_table"
        )
    ]

    # --- Steps: sum only the date's selected watch; never add mirrored sources.
    # Preserve legacy maximum-per-app fallback only when no switch applies and the
    # configured application is absent entirely. Missing selected days remain gaps.
    step_totals: dict[date, dict[int, int]] = {}
    for r in cur.execute("SELECT local_date, app_info_id, SUM(count) c FROM steps_record_table "
                         "WHERE local_date IS NOT NULL GROUP BY local_date, app_info_id"):
        day = EPOCH + timedelta(days=r["local_date"])
        step_totals.setdefault(day, {})[r["app_info_id"]] = int(r["c"] or 0)
    steps = []
    for day, totals in step_totals.items():
        ids = watch_ids_for(day)
        if ids:
            selected = [v for app, v in totals.items() if app in ids]
            if not selected:
                continue
            value = sum(selected)
        elif strict_day(day):
            continue
        else:
            value = max(totals.values())
        steps.append(dict(day=day, steps=value, source=SOURCE))

    # --- Ruhepuls: resting_heart_rate_record_table (Instant-Record der Watch). Pro lokalem
    # Tag die NIEDRIGSTE Messung (= echter Ruhewert). Defensiv: Tabelle/Spalten koennen fehlen. ---
    resting: list[dict] = []
    tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "resting_heart_rate_record_table" in tables:
        rcols = {row[1] for row in cur.execute("PRAGMA table_info(resting_heart_rate_record_table)")}
        if {"time", "beats_per_minute"} <= rcols:
            sel_off = "zone_offset" if "zone_offset" in rcols else "NULL AS zone_offset"
            per_day: dict[date, float] = {}
            for r in cur.execute(
                f"SELECT time, {sel_off}, beats_per_minute, "
                f"{'app_info_id' if 'app_info_id' in rcols else 'NULL AS app_info_id'} "
                "FROM resting_heart_rate_record_table",
            ):
                t = _local(r["time"], r["zone_offset"])
                v = r["beats_per_minute"]
                if t is None or v is None or not (HR_MIN_BPM <= v <= HR_MAX_BPM):
                    continue
                d = t.date()
                ids = watch_ids_for(d)
                if (ids or strict_day(d)) and r["app_info_id"] not in ids:
                    continue
                per_day[d] = min(per_day.get(d, 999.0), float(v))
            resting = [{"day": d, "bpm": v, "source": SOURCE} for d, v in per_day.items()]
        else:
            log.warning("resting_heart_rate_record_table hat unerwartete Spalten %s", sorted(rcols))

    run_windows = {"rows": [], "session_ids": [], "available": False}
    for package in {watch_source_for(session_source_day(s["external_id"], s["started_at"].date()), settings)
                    for s in sessions if s["started_at"] is not None}:
        selected = [s for s in sessions if s["started_at"] is not None
                    and watch_source_for(session_source_day(s["external_id"], s["started_at"].date()), settings) == package]
        windows = read_run_windows(con, selected, package)
        run_windows["rows"].extend(windows["rows"])
        run_windows["session_ids"].extend(windows["session_ids"])
        run_windows["available"] |= windows["available"]
    sleep_data = _read_sleep(con)
    con.close()
    return {"body": body, "sessions": sessions, "best_efforts": best_efforts,
            "vo2": vo2, "steps": steps, "resting": resting,
            "skipped_body": len(rejected_times), "run_windows": run_windows,
            "best_efforts_invalid_ids": sorted(invalid_best_effort_ids), "sleep": sleep_data}


def import_health_connect(db_path: str | Path, full: bool = False) -> dict:
    """Importiert die HC-DB idempotent (Append: nur neue Zeilen werden geschrieben).
    full=True macht eine Voll-Reconciliation (loescht source-Zeilen vorher -> spiegelt auch Loeschungen)."""
    from .. import garmin_activity, garmin_daily

    data = read_health_connect(db_path)
    models_ = (BodyMeasurement, ExerciseSession, RunBestEffort, Vo2Max, StepsDaily, RestingHrDaily, SleepSession)
    with Session(engine) as s:
        protected_ids = garmin_activity.protected_hc_ids(s, data["sessions"])
        if full:
            for m in models_:
                # Historien nie löschen, wenn der Import keine liefert (Fehlkonfiguration/leerer
                # Export bzw. Export ohne Distanz-Segmente) -> schützt vor versehentlichem Leeren.
                if m is StepsDaily and not data["steps"]:
                    continue
                if m is RestingHrDaily and not data["resting"]:
                    continue
                if m is RunBestEffort and not data["best_efforts"]:
                    continue
                if m is SleepSession and (not data["sleep"]["rows"] or not data["sleep"]["stages_available"]):
                    continue
                s.execute(delete(m).where(m.source == SOURCE))
        before = {m.__name__: count_rows(s, m, SOURCE) for m in models_}

        # einheitliche Spalten (sonst bricht der Bulk-INSERT bei gemischten Keys)
        body_rows = [
            {"measured_at": t, "source": SOURCE,
             "weight_kg": v.get("weight_kg"), "body_fat_pct": v.get("body_fat_pct")}
            for t, v in data["body"].items() if t is not None
        ]
        sess_rows = [d for d in data["sessions"]
                     if d["started_at"] is not None and d["external_id"] not in protected_ids]
        vo2_rows = [d for d in data["vo2"] if d["measured_at"] is not None]

        # HF kam spaeter dazu: liefert der Export HF, werden bestehende Sessions per
        # DO UPDATE retro-gefuellt; ohne HF bleibt der Upsert append-only. coalesce=True
        # haertet zusaetzlich pro Zeile: eine Session, die im aktuellen Export keine
        # Fenster-Samples hat, nullt nie einen frueher berechneten Wert (full=True ersetzt).
        sessions_with_hr = sum(1 for d in sess_rows if d.get("avg_hr") is not None)
        hr_update = ["avg_hr", "max_hr", "hr_drift_pct"] if sessions_with_hr else None

        upsert(s, BodyMeasurement, body_rows, ["measured_at", "source"])
        upsert(s, ExerciseSession, sess_rows, ["external_id"], update_cols=hr_update, coalesce=True)
        # Remove splits disproved by positively identified coarse replacement-watch data.
        invalid_ids = [key for key in data["best_efforts_invalid_ids"] if key not in protected_ids]
        for i in range(0, len(invalid_ids), 400):
            s.execute(delete(RunBestEffort).where(RunBestEffort.source == SOURCE,
                                                 RunBestEffort.external_id.in_(invalid_ids[i:i + 400])))
        # Best-Efforts kommen (wie HF) nachträglich rein: DO UPDATE retro-füllt bestehende Läufe,
        # sobald der Export Distanz-Segmente liefert (deterministisch aus den Segmenten neu berechnet).
        upsert(s, RunBestEffort, [row for row in data["best_efforts"]
                               if row["external_id"] not in protected_ids], ["external_id", "distance_m"],
               update_cols=["seconds", "started_at"])
        upsert(s, Vo2Max, vo2_rows, ["measured_at"])
        upsert(s, StepsDaily, data["steps"], ["day"], update_cols=["steps"])  # Schritte/Tag koennen wachsen
        upsert(s, RestingHrDaily, data["resting"], ["day"], update_cols=["bpm"])
        sleep_data = data["sleep"]
        sleep_updates = ["started_at", "ended_at", "day", "duration_window_minutes", "main_sleep"]
        if sleep_data["stages_available"]:
            sleep_updates += ["asleep_minutes", "awake_minutes", "stage_coverage"]
        upsert(s, SleepSession, sleep_data["rows"], ["external_id", "source_package"], update_cols=sleep_updates)
        minute_data = data["run_windows"]
        if minute_data["available"]:
            minute_ids = [key for key in minute_data["session_ids"] if key not in protected_ids]
            for i in range(0, len(minute_ids), 400):
                ids = minute_ids[i:i + 400]
                s.execute(delete(RunMinute).where(RunMinute.external_id.in_(ids)))
            upsert(s, RunMinute, [row for row in minute_data["rows"]
                                 if row["external_id"] not in protected_ids], ["external_id", "minute"])
        if full:
            # Partial raw series must not erase prior windows of retained sessions.
            retained = select(ExerciseSession.external_id).where(ExerciseSession.external_id.is_not(None))
            s.execute(delete(RunMinute).where(RunMinute.source == SOURCE,
                                              RunMinute.external_id.not_in(retained)))
        garmin_daily.apply_daily(s)
        s.commit()
        after = {m.__name__: count_rows(s, m, SOURCE) for m in models_}

    return {
        "mode": "full" if full else "incremental",
        "skipped_body": data["skipped_body"],
        "new_body": after["BodyMeasurement"] - before["BodyMeasurement"],
        "new_sessions": after["ExerciseSession"] - before["ExerciseSession"],
        "new_vo2max": after["Vo2Max"] - before["Vo2Max"],
        "new_steps_days": after["StepsDaily"] - before["StepsDaily"],
        "new_resting_hr_days": after["RestingHrDaily"] - before["RestingHrDaily"],
        "new_best_efforts": after["RunBestEffort"] - before["RunBestEffort"],
        "total_sessions": after["ExerciseSession"],
        "sessions_with_hr": sessions_with_hr,
        "run_minutes": len(data["run_windows"]["rows"]),
        "run_minutes_available": data["run_windows"]["available"],
        "new_sleep_sessions": after["SleepSession"] - before["SleepSession"],
        "sleep_sessions": len(data["sleep"]["rows"]),
        "sleep_available": data["sleep"]["available"],
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
