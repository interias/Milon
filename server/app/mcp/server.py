"""Milon MCP-Server (Phase 3): dieselbe metrics-Schicht als MCP-Tools.
In Claude Desktop/Code einhängen (siehe .mcp.json im Repo-Root) und die Fitness-Daten
dort befragen — außerhalb der App. Liest dieselbe SQLite-DB (data/tracker.db).

Start (stdio):  python -m app.mcp.server
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..coach import snapshot
from ..metrics import activity, body, health, running, strength

mcp = FastMCP("Milon")


@mcp.tool()
def get_overview() -> dict:
    """Aktuelle Kennzahlen aller drei Bereiche: Körper, Laufen, Kraft."""
    return {"body": body.summary(), "running": running.summary(), "strength": strength.summary()}


@mcp.tool()
def get_snapshot() -> str:
    """Kompakter Text-Snapshot aller Kernmetriken (schnelle Gesamtlage)."""
    return snapshot.snapshot_text()


@mcp.tool()
def get_weight_trend(days: int = 90) -> list:
    """Gewichtsverlauf (Tageswert, 7-Tage-Mittel, EWMA) der letzten N Tage."""
    return body.weight_trend(days)


@mcp.tool()
def get_tdee() -> dict:
    """Adaptives TDEE / echtes Defizit: Ø-Intake, Defizit pro Tag, Gewichtsänderung im Fenster."""
    return body.adaptive_tdee()


@mcp.tool()
def get_bodyfat_trend(days: int = 180) -> list:
    """Körperfett-Trend (Bioimpedanz, nur Trend) der letzten N Tage."""
    return body.body_fat_trend(days)


@mcp.tool()
def get_steps(days: int = 14) -> dict:
    """Tagesschritte + 7-Tage-Schnitt."""
    return body.steps_recent(days)


@mcp.tool()
def get_running_volume(weeks: int = 12) -> list:
    """Wochen-Laufvolumen (km) + Anzahl Läufe."""
    return running.weekly_volume(weeks)


@mcp.tool()
def get_pace_trend(weeks: int = 12) -> list:
    """Pace-Trend (min/km) je Woche (niedriger = schneller)."""
    return running.pace_trend(weeks)


@mcp.tool()
def get_vo2max_trend(days: int = 365) -> list:
    """VO2max-Verlauf (Uhr-Schätzung, Trend zählt)."""
    return running.vo2_trend(days)


@mcp.tool()
def get_strength_summary() -> dict:
    """Kraft-Überblick: Hauptübungen (e1RM/Peak/Sätze), Wochen-Tonnage, Ø-RPE."""
    return strength.summary()


@mcp.tool()
def get_exercises() -> list:
    """Alle Kraftübungen mit e1RM/Peak/Sätzen, gruppiert nach Muskelgruppe (Feld 'muscle')."""
    return strength.all_exercises()


@mcp.tool()
def get_tonnage(weeks: int = 12) -> list:
    """Wochen-Tonnage (kg) der letzten N Wochen."""
    return strength.weekly_tonnage(weeks)


@mcp.tool()
def get_rpe_trend(weeks: int = 12) -> list:
    """Wöchentlicher Ø-RPE (Ermüdungssignal)."""
    return strength.rpe_trend(weeks)


@mcp.tool()
def get_e1rm_trend(exercise: str, weeks: int = 26) -> list:
    """e1RM-Verlauf einer bestimmten Übung (genauer Name, z. B. 'Squat (Langhantel)')."""
    return strength.e1rm_trend(exercise, weeks)


@mcp.tool()
def get_recent_activity(limit: int = 10) -> list:
    """Letzte Aktivitäten: Läufe + Kraft-Workouts, neueste zuerst."""
    return activity.recent(limit)


@mcp.tool()
def get_health_overview() -> dict:
    """Allgemeine Gesundheitswerte: Schritte (heute/Ø7T/Ø30T) + Radfahren (gesamt/30T/diese Woche/Ø-Speed)."""
    return health.overview()


@mcp.tool()
def get_cycling_volume(weeks: int = 12) -> list:
    """Wochen-Radvolumen (km) + Anzahl Fahrten der letzten N Wochen (exercise_type 4 = Radfahren)."""
    return health.cycling_weekly(weeks)


@mcp.tool()
def get_forecast() -> dict:
    """30-Tage-Prognose (linearer Trend) für Gewicht & Körperfett: aktuell -> projiziert, Δ/Woche, Δ/Monat."""
    return {"weight": body.weight_forecast(), "bodyfat": body.bodyfat_forecast()}


@mcp.tool()
def get_strength_index(period: str = "3m") -> dict:
    """Gesamtstärke-Index (wöchentlich aufgelöst, driftfrei am Monats-Backbone verankert,
    Basis 100 = Trainingsstart): Wert, Δ, Trend (steigt/stagniert/faellt) + Treiber-/Bremse-Übungen.
    period = 1m|3m|6m|12m."""
    return strength.strength_index(period)


@mcp.tool()
def get_strength_energy() -> dict:
    """Zusammenhang Gesamtstärke ↔ Energiebilanz (TDEE/Defizit), wöchentlich aligned.
    corr_index_deficit = NIVEAU-Korrelation (trendgetrieben/scheinbar); corr_change_deficit =
    entkoppelt (belastbar, ~0). 'phase'/'phase_label' + recent_* = Read der jüngsten Wochen
    (cut/recomp/aufbau/stabil). 'caveat' beachten — keine Kausalität aus der Niveau-Korrelation."""
    return strength.strength_energy()


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
