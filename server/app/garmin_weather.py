"""Optional station weather from Garmin; never store station coordinates."""
from datetime import datetime, timedelta, timezone
import json

from sqlmodel import Field, Session, SQLModel

from .db import engine
from .garmin_activity import _activity_id, _number


class GarminWeather(SQLModel, table=True):
    __tablename__ = "garmin_weather"
    activity_id: str = Field(primary_key=True)
    payload: str = "{}"
    status: str = "empty"
    attempted_at: datetime
    fetched_at: datetime | None = None


def normalize(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    result = {}
    # Activity weather uses Fahrenheit, regardless of profile units.
    for source, target in (("temp", "temperature_c"), ("apparentTemp", "feels_like_c")):
        value = _number(raw.get(source), -148, 140)
        if value is not None:
            result[target] = round((value - 32) * 5 / 9, 1)
    for source, target, high in (("relativeHumidity", "humidity_pct", 100),
                                 ("windDirection", "wind_from_degrees", 360)):
        value = _number(raw.get(source), 0, high)
        if value is not None:
            result[target] = value
    # windSpeed has no unit metadata in the observed response. Do not guess a unit.
    result["wind_speed_kmh"] = None
    stamp = raw.get("issueDate")
    if isinstance(stamp, str):
        try:
            observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if observed.tzinfo is not None:
                result["observed_at"] = observed.astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    return result if any(key in result for key in ("temperature_c", "humidity_pct", "wind_from_degrees")) else {}


def sync_weather(api, activities: list[dict], full: bool = False) -> dict:
    result = {"imported": 0, "skipped": 0, "empty": 0, "errors": 0}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    seen = set()
    for activity in activities:
        try:
            activity_id = _activity_id(activity.get("activityId"))
        except (ValueError, AttributeError):
            continue
        if activity_id in seen:
            continue
        seen.add(activity_id)
        with Session(engine) as session:
            row = session.get(GarminWeather, activity_id)
            if row and not full and (row.status == "available" or row.attempted_at > now - timedelta(days=1)):
                result["skipped"] += 1
                continue
            row = row or GarminWeather(activity_id=activity_id, attempted_at=now)
            try:
                payload = normalize(api.get_activity_weather(activity_id))
                row.status = "available" if payload else "empty"
                if payload:
                    row.payload = json.dumps(payload, allow_nan=False)
                    row.fetched_at = now
                result["imported" if payload else "empty"] += 1
            except Exception:
                row.status = "error"
                result["errors"] += 1
            row.attempted_at = now
            session.add(row)
            session.commit()
    return result


def weather_for(session: Session, activity_id: str, started_at_utc: str | None = None) -> dict:
    row = session.get(GarminWeather, activity_id)
    data = json.loads(row.payload) if row else {}
    offset = None
    if data.get("observed_at") and started_at_utc:
        try:
            offset = round((datetime.fromisoformat(data["observed_at"]) -
                            datetime.fromisoformat(started_at_utc.replace("Z", "+00:00"))).total_seconds() / 60)
        except (ValueError, TypeError):
            pass
    return {**data, "source": "garmin_activity_station", "available": bool(data),
            "status": row.status if row else "never", "offset_minutes": offset,
            "time_aligned": offset is not None and abs(offset) <= 180,
            "fetched_at": row.fetched_at.replace(tzinfo=timezone.utc).isoformat() if row and row.fetched_at else None}
