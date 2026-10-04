"""Manual tape measurements and display preferences, independent of imports."""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, Session, SQLModel, select

from .config import settings
from .db import engine


DEFINITION_VERSION = "v1"
DEFINITIONS = [
    {"key": "abdomen_navel", "name": "Bauch", "site": "Nabelhöhe", "color": "#0a6e66",
     "definition": "Waagerecht auf Nabelhöhe messen. Aufrecht stehen, Bauch locker lassen und nach normalem Ausatmen ablesen.",
     "guide": [187, 289, 105, 15]},
    {"key": "waist_narrowest", "name": "Taille", "site": "Schmalste Stelle", "color": "#496f9e",
     "definition": "An der schmalsten Stelle zwischen unterem Rippenbogen und Beckenkamm waagerecht messen. Bauch entspannt, nach normalem Ausatmen ablesen. Diese Stelle beibehalten; nicht mit Nabelhöhe verwechseln.",
     "guide": [188, 264, 103, 14]},
    {"key": "hip_widest", "name": "Hüfte", "site": "Stärkste Stelle des Gesäßes", "color": "#a27635",
     "definition": "Füße zusammen, Gewicht gleichmäßig verteilt. Das Band waagerecht um die stärkste Stelle des Gesäßes führen.",
     "guide": [164, 374, 149, 19]},
    {"key": "upper_arm_right", "name": "Oberarm", "site": "Rechts · entspannt", "color": "#85649b",
     "definition": "Am rechten Oberarm die Mitte zwischen Schulter und Ellenbogen markieren. Den Arm locker hängen lassen und an dieser Stelle rechtwinklig zur Armachse messen. Nicht anspannen.",
     "guide": [133, 228, 40, 15]},
    {"key": "chest_nipple", "name": "Brust", "site": "Brustwarzenhöhe", "color": "#477e8d",
     "definition": "Das Band waagerecht auf Brustwarzenhöhe um den Brustkorb legen. Arme anschließend locker hängen lassen, nach normalem Ausatmen ablesen.",
     "guide": [167, 206, 144, 17]},
    {"key": "thigh_right_mid", "name": "Oberschenkel", "site": "Rechts · Mitte", "color": "#aa6850",
     "definition": "Die Mitte zwischen Leistenfalte und Oberkante der Kniescheibe am rechten Bein markieren; dieselbe Höhe beibehalten. Rechtes Bein etwas nach vorn stellen, leicht beugen und entlasten. Band rechtwinklig zur Beinachse anlegen.",
     "guide": [163, 450, 60, 16]},
    {"key": "calf_right_max", "name": "Wade", "site": "Rechts · sitzend", "color": "#698154",
     "definition": "Im Sitzen an der stärksten Stelle der rechten Wade messen. Fuß flach aufstellen, Unterschenkel entspannt halten. Band rechtwinklig zur Beinachse führen und jedes Mal dieselbe Sitzposition verwenden.",
     "guide": [154, 556, 53, 17]},
    {"key": "shoulders_deltoid", "name": "Schultern", "site": "Um beide Schulterkappen", "color": "#a77785",
     "definition": "Um die stärksten seitlichen Stellen beider Schultermuskeln messen, Arme locker am Körper. Möglichst von derselben zweiten Person messen lassen: Beim Selbstanlegen verändert sich leicht die Armhaltung.",
     "guide": [143, 164, 194, 19]},
]
MEASURE_KEYS = frozenset(item["key"] for item in DEFINITIONS)
DEFAULT_VISIBLE_KEYS = [item["key"] for item in DEFINITIONS[:4]]


class CircumferenceEntry(SQLModel, table=True):
    __tablename__ = "body_circumference_entries"
    __table_args__ = (UniqueConstraint("measured_on", "protocol", name="uq_circumference_date_protocol"),)

    id: int | None = Field(default=None, primary_key=True)
    measured_on: date = Field(index=True)
    protocol: str
    definition_version: str = DEFINITION_VERSION
    values_json: str


class CircumferencePreferences(SQLModel, table=True):
    __tablename__ = "body_circumference_preferences"

    id: int = Field(default=1, primary_key=True)
    visible_keys_json: str
    layout: str = "rows"
    period: str = "6m"


class DuplicateEntry(ValueError):
    pass


class EntryNotFound(LookupError):
    pass


def local_today(now: datetime | None = None) -> date:
    zone = ZoneInfo(settings.timezone)
    if now is None:
        return datetime.now(zone).date()
    return (now.replace(tzinfo=zone) if now.tzinfo is None else now.astimezone(zone)).date()


def entry_dict(entry: CircumferenceEntry) -> dict:
    return {"id": entry.id, "date": entry.measured_on.isoformat(),
            "protocol": entry.protocol, "values": json.loads(entry.values_json)}


def preferences_dict(row: CircumferencePreferences | None) -> dict:
    if row is None:
        return {"visible_keys": list(DEFAULT_VISIBLE_KEYS), "layout": "rows", "period": "6m"}
    return {"visible_keys": json.loads(row.visible_keys_json), "layout": row.layout, "period": row.period}


def overview() -> dict:
    with Session(engine) as session:
        entries = session.exec(select(CircumferenceEntry).order_by(
            CircumferenceEntry.measured_on.desc(), CircumferenceEntry.id.desc())).all()
        preferences = preferences_dict(session.get(CircumferencePreferences, 1))
        return {"today": local_today().isoformat(), "definitions": DEFINITIONS,
                "entries": [entry_dict(row) for row in entries], "preferences": preferences}


def validate_values(values: dict) -> dict[str, float]:
    if not values:
        raise ValueError("Bitte mindestens ein Körpermaß angeben.")
    if set(values) - MEASURE_KEYS:
        raise ValueError("Die Angaben enthalten eine unbekannte Messstelle.")
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Körpermaße müssen als Zahlen in Zentimetern angegeben werden.")
        if not 10 <= value <= 250 or not math.isfinite(value):
            name = next(item["name"] for item in DEFINITIONS if item["key"] == key)
            raise ValueError(f"{name}: Bitte einen endlichen Wert zwischen 10 und 250 cm angeben.")
    return {key: float(value) for key, value in values.items()}


def save_entry(day: date, protocol: str, values: dict, entry_id: int | None = None) -> dict:
    if day > local_today():
        raise ValueError("Das Messdatum darf nicht in der Zukunft liegen.")
    clean_values = validate_values(values)
    duplicate_message = "Für dieses Datum und diese Messstellen gibt es bereits einen Eintrag. Bitte den vorhandenen Eintrag bearbeiten."
    with Session(engine) as session:
        entry = session.get(CircumferenceEntry, entry_id) if entry_id is not None else None
        if entry_id is not None and entry is None:
            raise EntryNotFound("Messung nicht gefunden.")
        duplicate = session.exec(select(CircumferenceEntry).where(
            CircumferenceEntry.measured_on == day, CircumferenceEntry.protocol == protocol)).first()
        if duplicate is not None and duplicate.id != entry_id:
            raise DuplicateEntry(duplicate_message)
        if entry is None:
            entry = CircumferenceEntry(measured_on=day, protocol=protocol, values_json="{}")
        entry.measured_on = day
        entry.protocol = protocol
        entry.definition_version = DEFINITION_VERSION
        entry.values_json = json.dumps(clean_values, allow_nan=False)
        session.add(entry)
        try:
            session.commit()
        except IntegrityError as failure:
            session.rollback()
            raise DuplicateEntry(duplicate_message) from failure
        session.refresh(entry)
        return entry_dict(entry)


def delete_entry(entry_id: int) -> dict:
    with Session(engine) as session:
        entry = session.get(CircumferenceEntry, entry_id)
        if entry is None:
            raise EntryNotFound("Messung nicht gefunden.")
        session.delete(entry)
        session.commit()
    return {"deleted": entry_id}


def save_preferences(visible_keys: list[str], layout: str, period: str) -> dict:
    if not 1 <= len(visible_keys) <= 4 or len(set(visible_keys)) != len(visible_keys):
        raise ValueError("Bitte ein bis vier unterschiedliche Körpermaße auswählen.")
    if set(visible_keys) - MEASURE_KEYS:
        raise ValueError("Die Auswahl enthält eine unbekannte Messstelle.")
    with Session(engine) as session:
        row = session.get(CircumferencePreferences, 1)
        if row is None:
            row = CircumferencePreferences(visible_keys_json="[]")
        row.visible_keys_json = json.dumps(visible_keys)
        row.layout = layout
        row.period = period
        session.add(row)
        session.commit()
        session.refresh(row)
        return preferences_dict(row)
