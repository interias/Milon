"""Body scale read directly over Web Bluetooth (Arboleaf CS20L, Chipsea/Yolanda "QN" protocol).

The phone talks to the scale in Chrome (client/lib/scale/qnScale.ts) and posts one stable reading.
Stored twice on purpose:
- `scale_measurements` keeps the raw reading (r1/r2 resistances, protocol type, raw frame) for a
  later body-composition model calibrated against the old Arboleaf values. No formula here yet.
- `body_measurements` gets a row with source `scale_ble`, so every existing weight reader
  (trend, rate tube, expenditure model, overview, Heldenreise …) sees it without changes.

Same weighing from two sources (e.g. Arboleaf via Health Connect) → the BLE reading wins: other
weight rows within ±PREFER_WINDOW are deleted on save, and the Health Connect import skips them
(`shadowed`). Times are naive local wall time like every other table.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func
from sqlalchemy.exc import OperationalError
from sqlmodel import Field, Session, SQLModel, select

from .config import settings
from .db import engine, upsert
from .models import BodyMeasurement

SOURCE = "scale_ble"
MIN_KG, MAX_KG = 20.0, 250.0
DOUBLE_TAP = timedelta(minutes=2)    # same weight again within this → same weighing
DOUBLE_TAP_KG = 0.05
PREFER_WINDOW = timedelta(minutes=10)  # other sources this close to a BLE reading are the same weighing
FUTURE_SLACK = timedelta(minutes=10)
# Someone else (or a bag) on the scale: more than this off the median of the last 30 days is rejected.
OUTLIER_WINDOW = timedelta(days=30)
OUTLIER_SHARE = 0.15
OUTLIER_MIN_WEIGHINGS = 3


class ScaleMeasurement(SQLModel, table=True):
    __tablename__ = "scale_measurements"

    id: Optional[int] = Field(default=None, primary_key=True)
    measured_at: datetime = Field(index=True, unique=True)  # naive local wall time, second precision
    weight_kg: float
    r1: Optional[int] = None   # raw resistance, unit depends on firmware (Ohm or deci-Ohm)
    r2: Optional[int] = None
    source: str                # "live" | "stored" (scale history fallback)
    protocol_type: Optional[int] = None
    raw_hex: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


def to_local(ts: datetime) -> datetime:
    """Aware timestamps (the phone sends UTC ISO) → naive local wall time; naive = already local."""
    if ts.tzinfo is not None:
        ts = ts.astimezone(ZoneInfo(settings.timezone)).replace(tzinfo=None)
    return ts.replace(microsecond=0)


def _row(m: ScaleMeasurement) -> dict:
    return {"id": m.id, "measured_at": m.measured_at.isoformat(), "weight_kg": m.weight_kg,
            "r1": m.r1, "r2": m.r2, "source": m.source, "protocol_type": m.protocol_type,
            "raw_hex": m.raw_hex, "created_at": m.created_at.isoformat(timespec="seconds")}


def save(*, measured_at: datetime, weight_kg: float, r1: int | None, r2: int | None, source: str,
         protocol_type: int | None, raw_hex: str | None, now: datetime | None = None) -> tuple[dict, bool]:
    """Store one reading. Returns (row, created); created=False = duplicate of an existing reading.
    ValueError = implausible input (API → 422)."""
    if not MIN_KG <= weight_kg <= MAX_KG:
        raise ValueError(f"Gewicht {weight_kg:.2f} kg ist unplausibel (erlaubt {MIN_KG:.0f}–{MAX_KG:.0f} kg).")
    at = to_local(measured_at)
    now = now or datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None)
    if at > now + FUTURE_SLACK:
        raise ValueError("Messzeit liegt in der Zukunft – stimmt die Uhr des Handys?")
    weight_kg = round(weight_kg, 2)
    with Session(engine) as s:
        dup = s.exec(select(ScaleMeasurement).where(ScaleMeasurement.measured_at == at)).first()
        if dup is None:
            dup = s.exec(select(ScaleMeasurement).where(
                ScaleMeasurement.measured_at >= at - DOUBLE_TAP, ScaleMeasurement.measured_at <= at + DOUBLE_TAP,
                func.abs(ScaleMeasurement.weight_kg - weight_kg) <= DOUBLE_TAP_KG)).first()
        if dup is not None:
            return _row(dup), False
        _check_outlier(s, at, weight_kg)
        m = ScaleMeasurement(measured_at=at, weight_kg=weight_kg, r1=r1, r2=r2, source=source,
                             protocol_type=protocol_type, raw_hex=raw_hex, created_at=now)
        s.add(m)
        upsert(s, BodyMeasurement, [{"measured_at": at, "weight_kg": weight_kg, "source": SOURCE}],
               ["measured_at", "source"], update_cols=["weight_kg"])
        # BLE wins: the same weighing from another source (Arboleaf → Health Connect) goes away.
        s.execute(delete(BodyMeasurement).where(
            BodyMeasurement.source != SOURCE, BodyMeasurement.weight_kg.is_not(None),
            BodyMeasurement.measured_at >= at - PREFER_WINDOW, BodyMeasurement.measured_at <= at + PREFER_WINDOW))
        s.commit()
        s.refresh(m)
        return _row(m), True


def _check_outlier(s: Session, at: datetime, weight_kg: float) -> None:
    """ValueError if the weight is far from the own median of the 30 days before (any source)."""
    recent = sorted(s.exec(select(BodyMeasurement.weight_kg).where(
        BodyMeasurement.weight_kg.is_not(None), BodyMeasurement.measured_at >= at - OUTLIER_WINDOW,
        BodyMeasurement.measured_at < at - PREFER_WINDOW)).all())
    if len(recent) < OUTLIER_MIN_WEIGHINGS:
        return
    n = len(recent)
    median = recent[n // 2] if n % 2 else (recent[n // 2 - 1] + recent[n // 2]) / 2
    if abs(weight_kg - median) > OUTLIER_SHARE * median:
        raise ValueError(f"Gewicht {weight_kg:.2f} kg weicht stark von deinem Gewicht der letzten 30 Tage "
                         f"(um {median:.1f} kg) ab – stand jemand anderes auf der Waage? Nicht gespeichert.")


def remove(measurement_id: int) -> bool:
    """Delete a reading (e.g. someone else stood on the scale) and its weight row."""
    with Session(engine) as s:
        m = s.get(ScaleMeasurement, measurement_id)
        if m is None:
            return False
        s.execute(delete(BodyMeasurement).where(BodyMeasurement.source == SOURCE,
                                                BodyMeasurement.measured_at == m.measured_at))
        s.delete(m)
        s.commit()
        return True


def history(days: int = 90, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None)
    with Session(engine) as s:
        rows = s.exec(select(ScaleMeasurement).where(ScaleMeasurement.measured_at >= now - timedelta(days=days))
                      .order_by(ScaleMeasurement.measured_at.desc())).all()
        return [_row(m) for m in rows]


def shadowed(session: Session, times: list[datetime]) -> set[datetime]:
    """Of `times`, those within ±PREFER_WINDOW of a BLE reading (importers skip them)."""
    if not times:
        return set()
    lo, hi = min(times) - PREFER_WINDOW, max(times) + PREFER_WINDOW
    try:
        ble = session.exec(select(ScaleMeasurement.measured_at).where(
            ScaleMeasurement.measured_at >= lo, ScaleMeasurement.measured_at <= hi)).all()
    except OperationalError:  # old DB without the table (init_db not run yet)
        session.rollback()
        return set()
    if not ble:
        return set()
    return {t for t in times if any(abs(t - b) <= PREFER_WINDOW for b in ble)}
