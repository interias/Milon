"""Garmin GPS geometry, stored independently of imported training metrics."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert
from sqlmodel import Field, Session, SQLModel, select

from .config import settings
from .db import engine
from .models import ExerciseSession


MAX_GPX_BYTES = 10 * 1024 * 1024
MAX_ROUTE_POINTS = 100_000


class GarminRoute(SQLModel, table=True):
    __tablename__ = "garmin_routes"

    activity_id: str = Field(primary_key=True)
    title: str
    started_at: datetime = Field(index=True)
    started_at_utc: str | None = None
    distance_km: float | None = None
    duration_seconds: float | None = None
    elapsed_duration_seconds: float | None = None
    elevation_gain_m: float | None = None
    point_count: int
    segments_json: str
    synced_at: datetime


class _NoDoctype(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError("GPX-Dateien mit DTD sind nicht erlaubt.")


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _gpx_number(value: str | None) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _gpx_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def parse_gpx(content: bytes) -> list[list[dict]]:
    """Retain track boundaries; invalid coordinates also break the drawn line."""
    if not isinstance(content, bytes) or not content or len(content) > MAX_GPX_BYTES:
        raise ValueError("GPX muss eine Datei mit höchstens 10 MiB sein.")
    # Removing NULs also catches declarations in UTF-16/32 before parsing.
    declarations = content.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
        raise ValueError("GPX-Dateien mit DTD oder Entitäten sind nicht erlaubt.")
    try:
        root = ET.fromstring(content, parser=ET.XMLParser(target=_NoDoctype()))
    except ET.ParseError as failure:
        raise ValueError("Die GPX-Datei enthält ungültiges XML.") from failure
    if _tag(root) != "gpx":
        raise ValueError("Die Datei ist kein GPX-Dokument.")

    segments = []
    points_seen = 0
    for container in root.iter():
        container_tag = _tag(container)
        if container_tag not in {"trkseg", "rte"}:
            continue
        point_tag = "trkpt" if container_tag == "trkseg" else "rtept"
        segment = []
        for point in container:
            if _tag(point) != point_tag:
                continue
            points_seen += 1
            if points_seen > MAX_ROUTE_POINTS:
                raise ValueError("Die GPX-Datei enthält zu viele Routenpunkte.")
            lat, lon = _gpx_number(point.get("lat")), _gpx_number(point.get("lon"))
            if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                if segment:
                    segments.append(segment)
                    segment = []
                continue
            fields = {_tag(child): child.text for child in point}
            segment.append({"lat": lat, "lon": lon,
                            "altitude_m": _gpx_number(fields.get("ele")),
                            "time": _gpx_time(fields.get("time"))})
        if segment:
            segments.append(segment)
    if not segments:
        raise ValueError("Die GPX-Datei enthält keine gültigen Routenpunkte.")
    return segments


def _number(value, name: str, *, nonnegative: bool = False) -> float | None:
    if value is None:
        return None
    try:
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        number = float(value) if valid else float("nan")
    except OverflowError:
        number = float("nan")
    if not math.isfinite(number) or (nonnegative and number < 0):
        raise ValueError(f"Ungültiger Zahlenwert für {name}.")
    return number


def _datetime(value, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime):
            raise ValueError
        return parsed
    except ValueError as failure:
        raise ValueError(f"Ungültiger Zeitpunkt für {name}.") from failure


def _validated_segments(segments: list) -> list[list[dict]]:
    if not isinstance(segments, list) or not segments:
        raise ValueError("Die Route benötigt mindestens einen Routenpunkt.")
    cleaned = []
    count = 0
    for segment in segments:
        if not isinstance(segment, list):
            raise ValueError("Ungültiges Routensegment.")
        points = []
        for point in segment:
            count += 1
            if count > MAX_ROUTE_POINTS:
                raise ValueError("Die Route enthält zu viele Routenpunkte.")
            if not isinstance(point, dict):
                raise ValueError("Ungültiger Routenpunkt.")
            lat, lon = _number(point.get("lat"), "lat"), _number(point.get("lon"), "lon")
            if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError("Ungültige Routenkoordinaten.")
            recorded_at = point.get("time")
            if recorded_at is not None:
                if not isinstance(recorded_at, str) or _gpx_time(recorded_at) is None:
                    raise ValueError("Ungültiger Zeitpunkt eines Routenpunkts.")
                recorded_at = _gpx_time(recorded_at)
            points.append({"lat": lat, "lon": lon,
                           "altitude_m": _number(point.get("altitude_m"), "altitude_m"),
                           "time": recorded_at})
        if points:
            cleaned.append(points)
    if not cleaned:
        raise ValueError("Die Route benötigt mindestens einen Routenpunkt.")
    return cleaned


def save_route(summary: dict, segments: list) -> dict:
    """Upsert a route by Garmin ID without creating or changing exercise sessions."""
    activity_id = summary.get("activity_id")
    if not isinstance(activity_id, str) or not activity_id.strip() or len(activity_id) > 128:
        raise ValueError("Eine gültige Garmin-Aktivitäts-ID ist erforderlich.")
    title = summary.get("title") or "Lauf"
    if not isinstance(title, str):
        raise ValueError("Ungültiger Aktivitätstitel.")
    started_at = _datetime(summary.get("started_at"), "started_at")
    if started_at.tzinfo:
        started_at = started_at.astimezone(ZoneInfo(settings.timezone)).replace(tzinfo=None)
    started_at_utc = summary.get("started_at_utc")
    if started_at_utc is not None:
        utc = _datetime(started_at_utc, "started_at_utc")
        if utc.tzinfo is None:
            raise ValueError("started_at_utc benötigt eine Zeitzone.")
        started_at_utc = utc.astimezone(timezone.utc).isoformat()
    segments = _validated_segments(segments)
    values = {"activity_id": activity_id.strip(), "title": title, "started_at": started_at,
              "started_at_utc": started_at_utc,
              "point_count": sum(len(segment) for segment in segments),
              "segments_json": json.dumps(segments, separators=(",", ":"), allow_nan=False),
              "synced_at": datetime.now(timezone.utc).replace(tzinfo=None)}
    for field in ("distance_km", "duration_seconds", "elapsed_duration_seconds", "elevation_gain_m"):
        values[field] = _number(summary.get(field), field, nonnegative=True)
    statement = insert(GarminRoute).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=["activity_id"],
        set_={key: getattr(statement.excluded, key) for key in values if key != "activity_id"})
    with Session(engine) as session:
        session.execute(statement)
        session.commit()
        return _summary(session.get(GarminRoute, values["activity_id"]), session)


def _matched_external_id(route: GarminRoute, session: Session) -> str | None:
    elapsed = route.elapsed_duration_seconds
    if elapsed is None:
        elapsed = route.duration_seconds
    if route.distance_km is None or route.distance_km <= 0 or elapsed is None or elapsed <= 0:
        return None
    candidates = session.exec(select(ExerciseSession).where(
        ExerciseSession.exercise_type == 33,
        ExerciseSession.started_at >= route.started_at - timedelta(seconds=120),
        ExerciseSession.started_at <= route.started_at + timedelta(seconds=120))).all()
    matches = []
    for candidate in candidates:
        if candidate.distance_km is None or candidate.ended_at is None:
            continue
        duration = (candidate.ended_at - candidate.started_at).total_seconds()
        if (duration > 0 and candidate.distance_km > 0
                and abs(candidate.distance_km - route.distance_km) <= max(0.3, route.distance_km * 0.1)
                and abs(duration - elapsed) <= max(120, elapsed * 0.1)):
            matches.append(candidate.external_id)
    return matches[0] if len(matches) == 1 and matches[0] else None


def _summary(route: GarminRoute, session: Session) -> dict:
    return {"activity_id": route.activity_id, "title": route.title,
            "started_at": route.started_at.isoformat(), "distance_km": route.distance_km,
            "duration_seconds": route.duration_seconds, "elevation_gain_m": route.elevation_gain_m,
            "point_count": route.point_count, "matched_external_id": _matched_external_id(route, session)}


def list_routes(limit: int = 30, offset: int = 0) -> dict:
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Ungültige Seiteneinteilung.")
    with Session(engine) as session:
        total = session.exec(select(func.count()).select_from(GarminRoute)).one()
        routes = session.exec(select(GarminRoute).order_by(
            GarminRoute.started_at.desc(), GarminRoute.activity_id.desc()).offset(offset).limit(limit)).all()
        return {"items": [_summary(route, session) for route in routes], "total": total}


def route_detail(activity_id: str) -> dict | None:
    with Session(engine) as session:
        route = session.get(GarminRoute, activity_id)
        if route is None:
            return None
        return {**_summary(route, session), "segments": json.loads(route.segments_json)}
