"""SQLModel-Tabellen — spiegelt das Datenmodell aus ARCHITECTURE.md §4.
`source` ueberall, damit Mehrfachquellen unterscheidbar bleiben."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class BodyMeasurement(SQLModel, table=True):
    __tablename__ = "body_measurements"
    __table_args__ = (UniqueConstraint("measured_at", "source", name="uq_body_measured_source"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    measured_at: datetime = Field(index=True)
    weight_kg: Optional[float] = None
    body_fat_pct: Optional[float] = None
    muscle_kg: Optional[float] = None
    ffm_kg: Optional[float] = None
    visceral: Optional[float] = None
    water_pct: Optional[float] = None
    source: str


class NutritionEntry(SQLModel, table=True):
    __tablename__ = "nutrition_entries"
    __table_args__ = (UniqueConstraint("eaten_at", "fddb_id", "kcal", name="uq_nutrition_dedup"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    eaten_at: datetime = Field(index=True)
    description: Optional[str] = None
    fddb_id: Optional[str] = None
    kcal: Optional[float] = None
    fat_g: Optional[float] = None
    carb_g: Optional[float] = None
    protein_g: Optional[float] = None
    source: str = "fddb"


class Workout(SQLModel, table=True):
    __tablename__ = "workouts"

    id: Optional[int] = Field(default=None, primary_key=True)
    external_id: Optional[str] = Field(default=None, index=True, unique=True)
    title: Optional[str] = None
    started_at: Optional[datetime] = Field(default=None, index=True)
    ended_at: Optional[datetime] = None
    source: str = "hevy"


class WorkoutSet(SQLModel, table=True):
    __tablename__ = "workout_sets"

    id: Optional[int] = Field(default=None, primary_key=True)
    workout_id: int = Field(foreign_key="workouts.id", index=True)
    exercise: str
    set_index: Optional[int] = None
    set_type: Optional[str] = None  # 'normal' | 'warmup' | ...
    weight_kg: Optional[float] = None
    reps: Optional[int] = None
    rpe: Optional[float] = None


class ExerciseSession(SQLModel, table=True):
    __tablename__ = "exercise_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    external_id: Optional[str] = Field(default=None, index=True, unique=True)
    exercise_type: Optional[int] = Field(default=None, index=True)  # 33 run / 45 strength / 53 walk
    started_at: datetime = Field(index=True)
    ended_at: Optional[datetime] = None
    distance_km: Optional[float] = None
    avg_hr: Optional[float] = None
    source: str = "health_connect"


class Vo2Max(SQLModel, table=True):
    __tablename__ = "vo2max"

    id: Optional[int] = Field(default=None, primary_key=True)
    measured_at: datetime = Field(index=True, unique=True)
    vo2: float
    source: str = "health_connect"


class StepsDaily(SQLModel, table=True):
    __tablename__ = "steps_daily"

    day: date = Field(primary_key=True)
    steps: int
    source: str = "health_connect"


class CoachReport(SQLModel, table=True):
    __tablename__ = "coach_reports"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(index=True)
    kind: str  # 'daily' | 'weekly' | 'chat'
    content: str  # LLM-Antwort
    prompt: Optional[str] = None  # gesendete Messages als JSON (fuer spaetere Analyse)
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost_usd: Optional[float] = None


class ProgressEntry(SQLModel, table=True):
    """Fortschritts-/Optik-Eintrag: Datum, Notiz + bis zu 5 Foto-Dateinamen."""
    __tablename__ = "progress_entries"

    id: Optional[int] = Field(default=None, primary_key=True)
    taken_on: date = Field(index=True)
    note: Optional[str] = None
    front: Optional[str] = None
    side: Optional[str] = None
    back: Optional[str] = None
    pose1: Optional[str] = None
    pose2: Optional[str] = None
    created_at: Optional[datetime] = None


class SyncState(SQLModel, table=True):
    __tablename__ = "sync_state"

    source: str = Field(primary_key=True)
    last_sync: Optional[datetime] = None
    cursor: Optional[str] = None
    status: Optional[str] = None  # 'ok' | 'error'
    detail: Optional[str] = None  # kurze Zusammenfassung / Fehlertext
