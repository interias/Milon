"""Metrik-Endpunkte für das Dashboard. Dünne Wrapper über die reine metrics/-Schicht."""
from __future__ import annotations

from fastapi import APIRouter

from ..metrics import activity, body, health, nutrition, running, strength

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/overview")
def overview() -> dict:
    return {
        "body": body.summary(),
        "running": running.summary(),
        "strength": strength.summary(),
    }


# --- Körper ---
@router.get("/body/summary")
def body_summary() -> dict:
    return body.summary()


@router.get("/body/weight")
def body_weight(days: int = 180) -> list[dict]:
    return body.weight_trend(days)


@router.get("/body/bodyfat")
def body_bodyfat(days: int = 180) -> list[dict]:
    return body.body_fat_trend(days)


@router.get("/body/tdee")
def body_tdee(window_days: int = 14) -> dict:
    return body.adaptive_tdee(window_days)


@router.get("/body/tdee-trend")
def body_tdee_trend(window_days: int = 14, days: int = 180) -> list[dict]:
    return body.tdee_trend(window_days, days)


@router.get("/body/weight-weekly")
def body_weight_weekly(weeks: int = 12) -> list[dict]:
    return body.weekly_weight(weeks)


@router.get("/body/weight-forecast")
def body_weight_forecast(horizon: int = 30, fit_days: int = 30) -> dict:
    return body.weight_forecast(horizon, fit_days)


@router.get("/body/bodyfat-forecast")
def body_bodyfat_forecast(horizon: int = 30, fit_days: int = 30) -> dict:
    return body.bodyfat_forecast(horizon, fit_days)


@router.get("/body/composition-forecast")
def body_composition_forecast(horizon: int = 30, fit_days: int = 30) -> dict:
    return body.composition_forecast(horizon, fit_days)


@router.get("/body/lean-mass")
def body_lean_mass(days: int = 180) -> dict:
    return {"summary": body.lean_mass_summary(min(days, 90)), "trend": body.lean_mass_trend(days)}


# --- Ernährung (FDDB: kcal + Makros) ---
@router.get("/nutrition/summary")
def nutrition_summary() -> dict:
    return nutrition.summary()


@router.get("/nutrition/protein")
def nutrition_protein(days: int = 30) -> list[dict]:
    return nutrition.protein_trend(days)


@router.get("/nutrition/kcal")
def nutrition_kcal(days: int = 30) -> list[dict]:
    return nutrition.kcal_trend(days)


@router.get("/nutrition/daily")
def nutrition_daily(days: int = 30) -> list[dict]:
    return nutrition.daily(days)


@router.get("/body/steps")
def body_steps(days: int = 14) -> dict:
    return body.steps_recent(days)


@router.get("/activity/recent")
def activity_recent(limit: int = 8) -> list[dict]:
    return activity.recent(limit)


@router.get("/activity/consistency")
def activity_consistency(days: int = 140) -> dict:
    return activity.consistency(days)


@router.get("/activity/compare")
def activity_compare(days: int = 7) -> dict:
    return activity.compare(days)


# --- Gesundheit (Schritte + Radfahren) ---
@router.get("/health/overview")
def health_overview() -> dict:
    return health.overview()


@router.get("/health/steps")
def health_steps(days: int = 30) -> list[dict]:
    return health.steps_trend(days)


@router.get("/health/steps-weekly")
def health_steps_weekly(weeks: int = 12) -> list[dict]:
    return health.steps_weekly(weeks)


@router.get("/health/cycling")
def health_cycling(weeks: int = 12) -> list[dict]:
    return health.cycling_weekly(weeks)


@router.get("/health/cycling-recent")
def health_cycling_recent(limit: int = 8) -> list[dict]:
    return health.cycling_recent(limit)


# --- Laufen ---
@router.get("/running/summary")
def running_summary() -> dict:
    return running.summary()


@router.get("/running/volume")
def running_volume(weeks: int = 26) -> list[dict]:
    return running.weekly_volume(weeks)


@router.get("/running/pace")
def running_pace(weeks: int = 26) -> list[dict]:
    return running.pace_trend(weeks)


@router.get("/running/vo2")
def running_vo2(days: int = 365) -> list[dict]:
    return running.vo2_trend(days)


# --- Kraft ---
@router.get("/strength/summary")
def strength_summary() -> dict:
    return strength.summary()


@router.get("/strength/tonnage")
def strength_tonnage(weeks: int = 26) -> list[dict]:
    return strength.weekly_tonnage(weeks)


@router.get("/strength/rpe")
def strength_rpe(weeks: int = 26) -> list[dict]:
    return strength.rpe_trend(weeks)


@router.get("/strength/e1rm")
def strength_e1rm(exercise: str, weeks: int = 26) -> list[dict]:
    return strength.e1rm_trend(exercise, weeks)


@router.get("/strength/exercises")
def strength_exercises() -> list[dict]:
    return strength.all_exercises()


@router.get("/strength/exercise")
def strength_exercise(name: str, period: str = "all") -> dict:
    return strength.exercise_detail(name, period)


@router.get("/strength/records")
def strength_records(days: int = 120, limit: int = 25) -> list[dict]:
    return strength.personal_records(days, limit)


@router.get("/strength/index")
def strength_index(period: str = "3m") -> dict:
    return strength.strength_index(period)


@router.get("/strength/energy")
def strength_energy() -> dict:
    return strength.strength_energy()
