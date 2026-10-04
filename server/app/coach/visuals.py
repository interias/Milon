"""Saved metric charts and optional design illustrations for coach reports."""
from __future__ import annotations

import base64
import binascii
import io
import json
import logging
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.exc import SQLAlchemyError

from ..config import DATA_DIR, settings, watch_source_for
from ..metrics import body, running, strength

logger = logging.getLogger(__name__)
IMAGE_MODEL = "openai/gpt-image-2.5-flare"
IMAGE_DIR = DATA_DIR / "coach-images"


class ChartPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    date: str
    value: float | int | None = Field(allow_inf_nan=False)

    @field_validator("date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


class CoachVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: Literal["weight", "running", "strength", "sleep"]
    kind: Literal["line", "bars"]
    title: str = Field(max_length=120)
    unit: str = Field(max_length=20)
    description: str = Field(max_length=500)
    captured_at: str
    points: list[ChartPoint] = Field(max_length=400)

    @field_validator("captured_at")
    @classmethod
    def valid_timestamp(cls, value: str) -> str:
        datetime.fromisoformat(value)
        return value


def parse_visuals(stored: str | None) -> list[dict]:
    """Old or invalid reports stay readable without creating fresh chart values."""
    if not stored:
        return []
    try:
        decoded = json.loads(stored)
        if not isinstance(decoded, list) or len(decoded) > 4:
            return []
        return [CoachVisual.model_validate(item).model_dump() for item in decoded]
    except (ValidationError, ValueError, TypeError):
        return []


def build_visuals(kind: str, question: str = "", used: list[dict] | None = None) -> list[dict]:
    """Choose trusted chart datasets for the current topic; never execute model HTML."""
    text = question.casefold()
    names = " ".join(item.get("name", "") for item in (used or []))
    topics = []
    if any(word in text for word in ("körper", "gewicht", "abnehm", "kfa", "fett")) or any(
            word in names for word in ("weight", "body", "composition", "forecast")):
        topics.append("weight")
    if any(word in text for word in ("lauf", "pace", "puls", "ausdauer", "rennen")) or any(
            word in names for word in ("run", "pace", "vo2")):
        topics.append("running")
    if any(word in text for word in ("kraft", "gym", "stärke", "stärker", "muskel")) or "strength" in names:
        topics.append("strength")
    if any(word in text for word in ("schlaf", "erholung", "nacht")) or "sleep" in names:
        topics.append("sleep")
    if kind in ("daily", "weekly") or not topics:
        topics = ["weight", "running", "strength", "sleep"]
    now = datetime.now(ZoneInfo(settings.timezone))
    captured = now.isoformat()
    cards = []
    for topic in topics:
        try:
            if topic == "weight":
                points = [{"date": p["date"], "value": p["avg7"]} for p in body.weight_trend(90)]
                title, unit, style = "Gewicht · 7-Tage-Mittel", "kg", "line"
                description = "Mittel der erfassten Tage im Kalenderfenster; fehlende Messungen bleiben Lücken."
            elif topic == "running":
                points = [{"date": p["week"], "value": p["km"]} for p in running.weekly_volume(12)]
                title, unit, style = "Laufumfang · erfasste Wochen", "km", "bars"
                description = "Aufgezeichnete Kilometer je Kalenderwoche; die letzte Woche kann noch laufen. Wochen ohne Laufdaten fehlen."
            elif topic == "strength":
                index = strength.strength_index("3m")
                points = [{"date": p["week"], "value": p["smoothed"]} for p in index.get("series", [])[-14:]]
                title, unit, style = "Gesamtstärke · Wochenverlauf", "P", "line"
                description = "Geglättete Darstellung des Kraftindex; Basis 100 entspricht dem Trainingsstart."
            else:
                from ..metrics import sleep
                current_package = watch_source_for(now.date(), settings)
                rows = [row for row in sleep.overview(30).get("series", [])
                        if row.get("main_sleep") and row.get("source_package") == current_package]
                if not rows:
                    continue
                by_date = {row["date"]: row.get("asleep_hours") for row in rows}
                first, last = date.fromisoformat(min(by_date)), date.fromisoformat(max(by_date))
                points = [{"date": (first + timedelta(days=offset)).isoformat(),
                           "value": by_date.get((first + timedelta(days=offset)).isoformat())}
                          for offset in range((last - first).days + 1)]
                title, unit, style = "Schlafdauer · aktuelle Uhr", "h", "line"
                description = "Hauptschlaf ohne Wachphasen; nur die aktuelle Uhr. Fehlende Nächte und unbekannte Schlafphasen bleiben Lücken."
            if not any(p["value"] is not None for p in points):
                continue
            card = CoachVisual(id=topic, kind=style, title=title, unit=unit, description=description,
                               captured_at=captured, points=points)
            cards.append(card.model_dump())
        except (KeyError, ValueError, TypeError, RuntimeError, SQLAlchemyError):
            logger.exception("Could not capture coach chart %s", topic)
    return cards


def _store_image(payload: dict, directory: Path) -> dict:
    """Accept only bounded raster data and use a server-generated filename."""
    data = payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ValueError("Der Bildanbieter hat kein Bild geliefert.")
    encoded = data[0].get("b64_json")
    if not isinstance(encoded, str) or len(encoded) > 28_000_000:
        raise ValueError("Der Bildanbieter hat ungültige Bilddaten geliefert.")
    try:
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as original:
            if original.format not in ("PNG", "JPEG", "WEBP") or original.size != (1024, 1024):
                raise ValueError("Der Bildanbieter hat kein Rasterbild mit 1024 × 1024 Pixeln geliefert.")
            original.load()
            image = original.convert("RGB")
    except (binascii.Error, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Das generierte Bild konnte nicht gelesen werden.") from exc
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.png"
    image.save(directory / filename, format="PNG")
    usage = payload.get("usage")
    cost = usage.get("cost") if isinstance(usage, dict) else None
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
        cost = None
    return {"url": f"/media/coach-images/{filename}", "cost_usd": cost, "model": IMAGE_MODEL}


def generate_image(prompt: str) -> dict:
    """Explicit one-image request; no report, measurements or photos are attached."""
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY fehlt in den Einstellungen.")
    design_prompt = (
        "Create a square editorial fitness illustration for the Milon dashboard. "
        "Clinical, clean composition with plenty of negative space; charcoal ink silhouette "
        "and restrained teal accents (#0a6e66, #5cb8af) on an opaque off-white (#fbfcfc) background. "
        "No text, numbers, charts, logos or watermarks. Subject: " + prompt
    )
    with httpx.Client(timeout=110.0) as provider:
        response = provider.post(
            "https://openrouter.ai/api/v1/images",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}",
                     "HTTP-Referer": "http://localhost:3000", "X-Title": "Milon"},
            json={"model": IMAGE_MODEL, "prompt": design_prompt, "n": 1,
                  "size": "1024x1024", "quality": "low"},
        )
    if not response.is_success:
        raise ValueError(f"Bildgenerierung beim Anbieter fehlgeschlagen (HTTP {response.status_code}).")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("Der Bildanbieter hat keine gültige Antwort geliefert.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Der Bildanbieter hat keine gültige Antwort geliefert.")
    return _store_image(payload, IMAGE_DIR)
