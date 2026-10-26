"""Walking pad under the desk (FTMS treadmill, e.g. Sportstech sWalk): sessions from the host recorder.

The recorder (tools/walkpad, runs on the Windows host because Docker has no Bluetooth) posts one
finished session at a time. The pad reports speed, distance, energy and elapsed time — no steps and
no incline. Steps are estimated as distance / stride (WALKPAD_STRIDE_M, applied on read so a later
calibration fixes history); incline is a per-session setting (manual tilt, not reported over BLE).

Daily steps stay Garmin's truth (steps_daily). A pad session only adds the steps the watch did not
count in the same window (arms rest on the desk, the wrist barely moves): extra = max(0, pad − watch),
with the watch's 15-minute step buckets filled in on Garmin syncs. Until then extra is provisional.
Finished sessions are uploaded to Garmin Connect as an indoor-walking FIT activity (no effect on
Garmin's daily steps, which come from wellness monitoring only).

Energy: ACSM walking equation VO2 = 3.5 + 0.1·v + 1.8·v·grade (ml/kg/min, v in m/min) with the
7-day weight, 5 kcal per litre O2 — the grade term is the extra cost of the incline. Milon shows
active kcal only (net, without the 3.5 resting term; user decision). The FIT upload carries the gross
value: Garmin treats activity calories as total and subtracts resting itself, so net would be
counted short. The pad's own kcal (FTMS expended energy, no incline) is shown only as a second value.
Manual entries (source "manual") are replaced by a recorder session that overlaps them."""
from __future__ import annotations

import json
import logging
import struct
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import inspect
from sqlmodel import Field, Session, SQLModel, select

from .config import settings
from .db import engine
from .hero_export import _ENUM, _FIT_EPOCH, _U8, _U16, _U32, _U32Z, _Writer, fit_crc

log = logging.getLogger(__name__)

MIN_SECONDS = 120
MAX_SECONDS = 12 * 3600
MIN_DISTANCE_M = 100
MAX_SPEED_KMH = 8.0        # pad tops out at 6 km/h; anything above is a corrupt packet
MAX_SAMPLES = 50_000
SAMPLE_STEP_S = 5          # stored resolution (chart + FIT records)
WATCH_REFRESH = timedelta(hours=24)  # watch buckets keep updating until the watch has synced the day
WATCH_GIVE_UP = timedelta(days=7)    # no watch data by then → the estimate stays provisional
MAX_UPLOAD_ATTEMPTS = 5
SPORT_WALKING, SUB_SPORT_INDOOR_WALKING = 11, 27
KCAL_PER_L_O2 = 5.0


class WalkpadSession(SQLModel, table=True):
    __tablename__ = "walkpad_sessions"

    id: str = Field(primary_key=True)          # recorder session id, makes retries idempotent
    started_at: datetime = Field(index=True)    # naive local wall time like every other session table
    started_at_utc: float                       # epoch seconds
    ended_at_utc: float
    moving_s: float
    pad_elapsed_s: float | None = None
    distance_m: float
    kcal: float | None = None
    avg_speed_kmh: float | None = None
    max_speed_kmh: float | None = None
    avg_hr: float | None = None
    incline_pct: float = 0.0
    device: str | None = None
    source: str = "recorder"                    # recorder | manual
    samples_json: str = "[]"                    # [[t_s, speed_kmh, distance_m, hr|null], …] every 5 s
    watch_steps: int | None = None              # Garmin wrist steps inside the window (None = not yet known)
    watch_checked_at: datetime | None = None
    garmin_status: str | None = None            # None = pending, uploaded, duplicate, error, off
    garmin_activity_id: str | None = None
    garmin_attempts: int = 0
    created_at: datetime = Field(default_factory=datetime.now)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def _local(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, _tz()).replace(tzinfo=None)


def steps_of(distance_m: float, stride: float | None = None) -> int:
    stride = stride or settings.walkpad_stride_m
    return int(round(distance_m / stride)) if stride > 0 else 0


def _num(value, low: float, high: float, name: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} fehlt oder ist keine Zahl.") from None
    if not low <= x <= high:
        raise ValueError(f"{name} außerhalb des plausiblen Bereichs.")
    return x


def _clean_samples(raw, duration: float) -> list[list]:
    if not isinstance(raw, list) or len(raw) > MAX_SAMPLES:
        raise ValueError("samples fehlt oder ist zu lang.")
    out: list[list] = []
    last_t = -1.0
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        try:
            t, speed, dist = float(row[0]), float(row[1]), float(row[2])
            hr = float(row[3]) if len(row) > 3 and row[3] is not None else None
        except (TypeError, ValueError):
            continue
        if t <= last_t or not 0 <= t <= duration + 60 or not 0 <= speed <= MAX_SPEED_KMH or dist < 0:
            continue
        out.append([t, speed, dist, hr if hr and 30 <= hr <= 230 else None])
        last_t = t
    return out


def _downsample(samples: list[list]) -> list[list]:
    if not samples:
        return []
    kept, next_t = [], 0.0
    for row in samples:
        if row[0] >= next_t:
            kept.append([round(row[0]), round(row[1], 2), round(row[2], 1), row[3]])
            next_t = row[0] + SAMPLE_STEP_S
    if kept[-1][0] != round(samples[-1][0]):
        last = samples[-1]
        kept.append([round(last[0]), round(last[1], 2), round(last[2], 1), last[3]])
    return kept


def _moving_seconds(samples: list[list]) -> float:
    moving = 0.0
    for a, b in zip(samples, samples[1:]):
        dt = b[0] - a[0]
        if dt <= 10 and (a[1] > 0 or b[2] > a[2]):
            moving += dt
    return moving


def ingest(payload: dict, now: datetime | None = None) -> tuple[dict, bool]:
    """Store one finished session; (session, created). ValueError = message for humans (422)."""
    sid = str(payload.get("id") or "")
    if not 4 <= len(sid) <= 64 or not all(c.isalnum() or c in "-_" for c in sid):
        raise ValueError("id fehlt oder ist ungültig.")
    with Session(engine) as db:
        existing = db.get(WalkpadSession, sid)
        if existing is not None:
            return _row(existing), False
    now_utc = (now or datetime.now(timezone.utc)).timestamp()
    start = _num(payload.get("started_at"), 1_500_000_000, now_utc + 300, "started_at")
    end = _num(payload.get("ended_at"), start, now_utc + 300, "ended_at")
    duration = end - start
    if not MIN_SECONDS <= duration <= MAX_SECONDS:
        raise ValueError("Session zu kurz oder zu lang.")
    distance = _num(payload.get("distance_m"), 0, 100_000, "distance_m")
    if distance < MIN_DISTANCE_M:
        raise ValueError("Session zu kurz (unter 100 m).")
    samples = _clean_samples(payload.get("samples", []), duration)
    moving = _moving_seconds(samples) if len(samples) > 1 else 0.0
    if moving <= 0:
        elapsed = payload.get("elapsed_s")
        moving = float(elapsed) if isinstance(elapsed, (int, float)) and 0 < elapsed <= duration + 60 else duration
    moving = min(moving, duration)
    if distance / moving * 3.6 > MAX_SPEED_KMH:
        raise ValueError("Durchschnittstempo unplausibel.")
    speeds = [s[1] for s in samples if s[1] > 0]
    hrs = [s[3] for s in samples if s[3]]
    kcal = payload.get("kcal")
    incline = payload.get("incline_pct")
    row = WalkpadSession(
        id=sid, started_at=_local(start), started_at_utc=start, ended_at_utc=end, moving_s=round(moving, 1),
        pad_elapsed_s=payload.get("elapsed_s") if isinstance(payload.get("elapsed_s"), (int, float)) else None,
        distance_m=round(distance, 1),
        kcal=float(kcal) if isinstance(kcal, (int, float)) and 0 <= kcal <= 5000 else None,
        avg_speed_kmh=round(distance / moving * 3.6, 2),
        max_speed_kmh=round(max(speeds), 2) if speeds else None,
        avg_hr=round(sum(hrs) / len(hrs), 1) if hrs else None,
        incline_pct=float(incline) if isinstance(incline, (int, float)) and 0 <= incline <= 15
        else settings.walkpad_incline_pct,
        device=str(payload.get("device") or "")[:60] or None,
        samples_json=json.dumps(_downsample(samples), separators=(",", ":")),
        garmin_status=None if settings.walkpad_garmin_upload else "off",
    )
    with Session(engine) as db:
        for manual in db.exec(select(WalkpadSession).where(
                WalkpadSession.source == "manual", WalkpadSession.started_at_utc < end,
                WalkpadSession.ended_at_utc > start)):
            if manual.garmin_status in ("uploaded", "duplicate"):  # never a second activity for the same walk
                row.garmin_status, row.garmin_activity_id = manual.garmin_status, manual.garmin_activity_id
            db.delete(manual)
        db.add(row)
        db.commit()
        db.refresh(row)
        return _row(row), True


def add_manual(start: datetime, minutes: float, speed_kmh: float, incline_pct: float | None = None,
               now: datetime | None = None) -> dict:
    """Walk entered by hand (before the recorder ran, or without it): constant speed from a local start."""
    if not 2 <= minutes <= MAX_SECONDS / 60 or not 0.5 <= speed_kmh <= MAX_SPEED_KMH:
        raise ValueError("Dauer oder Tempo unplausibel.")
    t0 = start.replace(tzinfo=_tz()).timestamp()
    end = t0 + minutes * 60
    if end > (now or datetime.now(timezone.utc)).timestamp() + 300:
        raise ValueError("Der Walk liegt in der Zukunft.")
    with Session(engine) as db:
        overlap = db.exec(select(WalkpadSession).where(WalkpadSession.started_at_utc < end,
                                                       WalkpadSession.ended_at_utc > t0)).first()
    if overlap is not None:
        raise ValueError("In diesem Zeitraum ist schon ein Walk erfasst.")
    v = speed_kmh / 3.6
    samples = [[t, speed_kmh, round(v * t, 1), None] for t in range(0, int(minutes * 60), SAMPLE_STEP_S)]
    samples.append([round(minutes * 60), speed_kmh, round(v * minutes * 60, 1), None])
    row = WalkpadSession(
        id=f"manual-{int(t0)}", started_at=start.replace(tzinfo=None), started_at_utc=t0, ended_at_utc=end,
        moving_s=minutes * 60, distance_m=round(v * minutes * 60, 1), avg_speed_kmh=speed_kmh,
        max_speed_kmh=speed_kmh, source="manual",
        incline_pct=settings.walkpad_incline_pct if incline_pct is None else incline_pct,
        samples_json=json.dumps(samples, separators=(",", ":")),
        garmin_status=None if settings.walkpad_garmin_upload else "off",
    )
    with Session(engine) as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        return _row(row)


def delete_manual(sid: str) -> bool | None:
    """None = unknown, False = recorder session (kept), True = deleted."""
    with Session(engine) as db:
        row = db.get(WalkpadSession, sid)
        if row is None:
            return None
        if row.source != "manual":
            return False
        db.delete(row)
        db.commit()
        return True


def _weights():
    try:
        from .metrics import cycling
        return cycling._weights()
    except Exception:  # noqa: BLE001 -- no weight → no ACSM estimate, pad kcal only
        return None


def energy(distance_m: float, moving_s: float, incline_pct: float, weight_kg: float | None) -> dict:
    """ACSM walking equation: active kcal (net), its flat-ground part and the incline's extra cost;
    kcal_gross adds the resting term for the Garmin upload."""
    if not weight_kg or moving_s <= 0:
        return {"kcal": None, "kcal_flat": None, "kcal_incline": None, "kcal_gross": None, "weight_kg": None}
    minutes = moving_s / 60
    v = distance_m / minutes  # m/min
    per_ml = weight_kg * minutes / 1000 * KCAL_PER_L_O2
    flat = 0.1 * v * per_ml
    incline = 1.8 * v * incline_pct / 100 * per_ml
    rest = 3.5 * per_ml
    return {"kcal": round(flat + incline), "kcal_flat": round(flat), "kcal_incline": round(incline),
            "kcal_gross": round(rest + flat + incline), "weight_kg": round(weight_kg, 1)}


def _row(r: WalkpadSession, weights=None) -> dict:
    from .metrics import cycling
    weights = _weights() if weights is None else weights
    kg = cycling._weight_at(weights, r.started_at.date()) if weights is not None else None
    steps = steps_of(r.distance_m)
    extra = max(0, steps - (r.watch_steps or 0))
    return {
        "id": r.id, "started_at": r.started_at.isoformat(timespec="seconds"),
        "date": r.started_at.date().isoformat(),
        "ended_at": _local(r.ended_at_utc).isoformat(timespec="seconds"),
        "minutes": round(r.moving_s / 60, 1), "distance_km": round(r.distance_m / 1000, 2),
        "avg_speed_kmh": r.avg_speed_kmh, "max_speed_kmh": r.max_speed_kmh, "kcal_pad": r.kcal, "avg_hr": r.avg_hr,
        **energy(r.distance_m, r.moving_s, r.incline_pct, kg), "source": r.source,
        "incline_pct": r.incline_pct, "elevation_m": round(r.distance_m * r.incline_pct / 100),
        "steps": steps, "watch_steps": r.watch_steps, "extra_steps": extra,
        "steps_provisional": r.watch_steps is None, "garmin_status": r.garmin_status,
        "garmin_activity_id": r.garmin_activity_id,
    }


def set_incline(sid: str, pct: float) -> dict | None:
    with Session(engine) as db:
        row = db.get(WalkpadSession, sid)
        if row is None:
            return None
        row.incline_pct = pct
        db.add(row)
        db.commit()
        db.refresh(row)
        return _row(row)


# ---------------- readers for other modules (take the caller's connection) ----------------
def _rows(con) -> list[tuple]:
    if not inspect(con).has_table("walkpad_sessions"):
        return []
    return con.exec_driver_sql(
        "SELECT started_at, started_at_utc, ended_at_utc, moving_s, distance_m, watch_steps FROM walkpad_sessions"
    ).fetchall()


def extra_steps(con) -> dict[date, int]:
    """Pad steps the watch did not count, per local day (added on top of steps_daily)."""
    out: dict[date, int] = {}
    for started, _, _, _, dist, watch in _rows(con):
        day = datetime.fromisoformat(str(started)).date()
        out[day] = out.get(day, 0) + max(0, steps_of(dist) - (watch or 0))
    return out


def with_extra_steps(df, con):
    """steps_daily frame (day as datetime, steps) plus pad extra steps; adds days the watch missed."""
    import pandas as pd

    extra = extra_steps(con)
    if not extra:
        return df
    df = df.copy()
    known = {d.date() for d in df["day"]} if not df.empty else set()
    for day, n in extra.items():
        if day in known:
            df.loc[df["day"].dt.date == day, "steps"] += n
    missing = [{"day": pd.Timestamp(d), "steps": n} for d, n in extra.items() if d not in known and n > 0]
    if missing:
        df = pd.concat([df, pd.DataFrame(missing)], ignore_index=True) if not df.empty else pd.DataFrame(missing)
        if "source" in df:
            df["source"] = df["source"].fillna("walkpad")
    return df.sort_values("day").reset_index(drop=True)


def active_kcal_by_day() -> dict[date, float]:
    """Active (net) ACSM kcal of all walks per local day; days without a weight have none."""
    weights = _weights()
    with Session(engine) as db:
        rows = list(db.exec(select(WalkpadSession)))
    out: dict[date, float] = {}
    for r in rows:
        kcal = _row(r, weights)["kcal"]
        if kcal:
            out[r.started_at.date()] = out.get(r.started_at.date(), 0.0) + kcal
    return out


def minutes_by_day(con) -> dict[date, float]:
    out: dict[date, float] = {}
    for started, _, _, moving, _, _ in _rows(con):
        day = datetime.fromisoformat(str(started)).date()
        out[day] = out.get(day, 0.0) + moving / 60
    return out


def windows(con) -> list[tuple[datetime, datetime]]:
    """Local wall-time windows; HC/Garmin mirrors of a pad walk overlapping them are dropped."""
    return [(_local(s), _local(e)) for _, s, e, *_ in _rows(con)]


# ---------------- overview for the UI ----------------
def overview(weeks: int = 12, recent: int = 8, today: date | None = None) -> dict:
    today = today or datetime.now(_tz()).date()
    with Session(engine) as db:
        rows = list(db.exec(select(WalkpadSession).order_by(WalkpadSession.started_at.desc())))
    weights = _weights()
    items = [_row(r, weights) for r in rows]
    monday = today - timedelta(days=today.weekday())
    first = monday - timedelta(weeks=weeks - 1)
    series = []
    for i in range(weeks):
        w0 = first + timedelta(weeks=i)
        inside = [x for x in items if w0 <= date.fromisoformat(x["date"]) < w0 + timedelta(days=7)]
        series.append({"week": w0.isoformat(), "minutes": round(sum(x["minutes"] for x in inside)),
                       "km": round(sum(x["distance_km"] for x in inside), 1),
                       "steps": sum(x["steps"] for x in inside), "sessions": len(inside)})

    def total(pred) -> dict:
        sel = [x for x in items if pred(date.fromisoformat(x["date"]))]
        return {"sessions": len(sel), "minutes": round(sum(x["minutes"] for x in sel)),
                "km": round(sum(x["distance_km"] for x in sel), 2), "steps": sum(x["steps"] for x in sel),
                "extra_steps": sum(x["extra_steps"] for x in sel),
                "kcal": round(sum(x["kcal"] or 0 for x in sel)),
                "kcal_incline": round(sum(x["kcal_incline"] or 0 for x in sel)),
                "kcal_pad": round(sum(x["kcal_pad"] or 0 for x in sel)),
                "elevation_m": sum(x["elevation_m"] for x in sel)}

    return {
        "today": total(lambda d: d == today), "week": total(lambda d: d >= monday),
        "weeks": series, "recent": items[:recent], "total_sessions": len(items),
        "stride_m": settings.walkpad_stride_m, "incline_pct": settings.walkpad_incline_pct,
        "garmin_upload": settings.walkpad_garmin_upload, "recorder_enabled": bool(settings.walkpad_token),
    }


def detail(sid: str) -> dict | None:
    with Session(engine) as db:
        row = db.get(WalkpadSession, sid)
        if row is None:
            return None
        out = _row(row)
        out["samples"] = json.loads(row.samples_json or "[]")
        return out


# ---------------- FIT activity (indoor walking) ----------------
def fit_activity_bytes(row: WalkpadSession) -> bytes:
    """FIT activity file: file_id, timer start, records, timer stop, lap, session, activity."""
    samples = json.loads(row.samples_json or "[]")
    t0 = int(row.started_at_utc) - _FIT_EPOCH
    t_end = int(row.ended_at_utc) - _FIT_EPOCH
    elapsed_ms = round((row.ended_at_utc - row.started_at_utc) * 1000)
    timer_ms = round(row.moving_s * 1000)
    dist_cm = round(row.distance_m * 100)
    kcal = round(_row(row)["kcal_gross"] or row.kcal or 0)  # Garmin wants total kcal; pad value as fallback
    cycles = steps_of(row.distance_m) // 2  # walking/running: total_cycles counts strides (2 steps)
    avg = round((row.avg_speed_kmh or 0) / 3.6 * 1000)
    mx = round((row.max_speed_kmh or row.avg_speed_kmh or 0) / 3.6 * 1000)
    local_offset = round(datetime.fromtimestamp(row.started_at_utc, _tz()).utcoffset().total_seconds())
    w = _Writer()
    w.message(0, 0, [(0, _ENUM, 4, 0), (1, _U16, 255, 0), (2, _U16, 0, 0), (3, _U32Z, 1, 0), (4, _U32, t0, 0)])
    w.message(1, 21, [(253, _U32, t0, 0), (0, _ENUM, 0, 0), (1, _ENUM, 0, 0)])
    for t, speed, dist, hr in samples:
        fields = [(253, _U32, t0 + int(t), 0), (5, _U32, round(dist * 100), 0), (6, _U16, round(speed / 3.6 * 1000), 0)]
        if hr:
            fields.append((3, _U8, round(hr), 0))
        w.message(2 if hr else 3, 20, fields)
    w.message(1, 21, [(253, _U32, t_end, 0), (0, _ENUM, 0, 0), (1, _ENUM, 4, 0)])
    common = [(2, _U32, t0, 0), (7, _U32, elapsed_ms, 0), (8, _U32, timer_ms, 0), (9, _U32, dist_cm, 0),
              (10, _U32, cycles, 0), (11, _U16, kcal, 0), (14, _U16, avg, 0), (15, _U16, mx, 0)]
    w.message(4, 19, [(253, _U32, t_end, 0), (254, _U16, 0, 0), (0, _ENUM, 9, 0), (1, _ENUM, 1, 0), *common,
                      (25, _ENUM, SPORT_WALKING, 0)])
    w.message(5, 18, [(253, _U32, t_end, 0), (254, _U16, 0, 0), (0, _ENUM, 8, 0), (1, _ENUM, 1, 0), *common,
                      (5, _ENUM, SPORT_WALKING, 0), (6, _ENUM, SUB_SPORT_INDOOR_WALKING, 0),
                      (25, _U16, 0, 0), (26, _U16, 1, 0)])
    w.message(6, 34, [(253, _U32, t_end, 0), (0, _U32, timer_ms, 0), (1, _U16, 1, 0), (2, _ENUM, 0, 0),
                      (3, _ENUM, 26, 0), (4, _ENUM, 1, 0), (5, _U32, t_end + local_offset, 0)])
    head = struct.pack("<BBHI4s", 14, 0x20, 2132, len(w.buf), b".FIT")
    head += struct.pack("<H", fit_crc(head))
    body = head + bytes(w.buf)
    return body + struct.pack("<H", fit_crc(body))


# ---------------- Garmin: upload + watch steps in the window ----------------
def _upload_one(api, row: WalkpadSession) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"walkpad-{row.id}.fit"
        path.write_bytes(fit_activity_bytes(row))
        try:
            response = api.upload_activity(str(path))
        except Exception as e:  # noqa: BLE001 -- message only inspected for the duplicate marker
            text = str(e)
            if "409" in text or "uplicate" in text:
                row.garmin_status = "duplicate"
                return
            row.garmin_status, row.garmin_attempts = "error", row.garmin_attempts + 1
            return
    body = response.json() if hasattr(response, "json") else response
    result = (body or {}).get("detailedImportResult", {}) if isinstance(body, dict) else {}
    successes, failures = result.get("successes") or [], result.get("failures") or []
    if successes:
        row.garmin_status = "uploaded"
        internal = successes[0].get("internalId")
        row.garmin_activity_id = str(internal) if internal else None
    elif failures and "uplicate" in json.dumps(failures):
        row.garmin_status = "duplicate"
    elif failures:
        row.garmin_status, row.garmin_attempts = "error", row.garmin_attempts + 1
    else:  # accepted asynchronously (202) without an id yet
        row.garmin_status = "uploaded"


def _bucket_time(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "")).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def watch_steps_in(buckets: list[dict], start: float, end: float) -> int:
    """Wrist steps inside [start, end] from Garmin's 15-min buckets, overlap-weighted."""
    total = 0.0
    for b in buckets or []:
        b0, b1 = _bucket_time(b.get("startGMT")), _bucket_time(b.get("endGMT"))
        steps = b.get("steps")
        if b0 is None or b1 is None or b1 <= b0 or not isinstance(steps, (int, float)):
            continue
        overlap = min(end, b1) - max(start, b0)
        if overlap > 0:
            total += steps * overlap / (b1 - b0)
    return int(round(total))


def sync_garmin(api, now: datetime | None = None) -> dict:
    """Garmin category: upload pending sessions, refresh watch steps of recent sessions."""
    now = now or datetime.now()
    result = {"uploaded": 0, "upload_errors": 0, "watch_days": 0}
    with Session(engine) as db:
        pending = list(db.exec(select(WalkpadSession).where(
            (WalkpadSession.garmin_status.is_(None)) | ((WalkpadSession.garmin_status == "error")
                                                       & (WalkpadSession.garmin_attempts < MAX_UPLOAD_ATTEMPTS)))))
        if settings.walkpad_garmin_upload:
            for row in pending:
                _upload_one(api, row)
                result["uploaded" if row.garmin_status in ("uploaded", "duplicate") else "upload_errors"] += 1
                db.add(row)
            db.commit()
        rows = [r for r in db.exec(select(WalkpadSession))
                if now - _local(r.ended_at_utc) < (WATCH_GIVE_UP if r.watch_steps is None else WATCH_REFRESH)]
        by_day: dict[date, list[WalkpadSession]] = {}
        for r in rows:
            by_day.setdefault(r.started_at.date(), []).append(r)
        for day, items in by_day.items():
            if now - _local(max(r.ended_at_utc for r in items)) < timedelta(minutes=15):
                continue  # the watch has not synced the walk yet; zero would look final
            try:
                buckets = api.get_steps_data(day.isoformat())
            except Exception:  # noqa: BLE001 -- keep provisional, try again next sync
                continue
            for r in items:
                r.watch_steps = watch_steps_in(buckets, r.started_at_utc, r.ended_at_utc)
                r.watch_checked_at = now
                db.add(r)
            result["watch_days"] += 1
        db.commit()
    return result
