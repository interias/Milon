"""Tool-Definitionen + Dispatcher fuer den Tool-Calling-Coach (ARCHITECTURE.md §6.2b).
Dieselbe metrics/-Schicht wie REST/Snapshot - das LLM ruft gezielt, was es fuer eine Frage braucht."""
from __future__ import annotations

from ..metrics import body, health, running, strength


def _thin(items: list, n: int = 16) -> list:
    """Lange Reihen ausduennen, damit Tool-Ergebnisse token-sparsam bleiben."""
    if len(items) <= n:
        return items
    step = len(items) / n
    return [items[min(len(items) - 1, int(i * step))] for i in range(n)]


def _fn(name: str, desc: str, props: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": required or []},
        },
    }


TOOLS = [
    _fn("get_overview", "Kompakte Zusammenfassung aller drei Bereiche (Koerper, Laufen, Kraft) mit den aktuellen Kennzahlen."),
    _fn("get_weight_trend", "Gewichtsverlauf (Tageswerte + 7-Tage-EWMA) der letzten N Tage.",
        {"days": {"type": "integer", "description": "Zeitraum in Tagen (Default 90)"}}),
    _fn("get_tdee", "Adaptives TDEE / echtes Defizit: Oe-Intake, Defizit pro Tag, Gewichtsaenderung ueber das Fenster."),
    _fn("get_bodyfat_trend", "Koerperfett-Trend (Bioimpedanz, nur Trend) der letzten N Tage.",
        {"days": {"type": "integer"}}),
    _fn("get_running_volume", "Wochen-Laufvolumen (km) + Anzahl Laeufe der letzten N Wochen.",
        {"weeks": {"type": "integer", "description": "Default 12"}}),
    _fn("get_pace_trend", "Pace-Trend (min/km) je Woche (niedriger = schneller).",
        {"weeks": {"type": "integer"}}),
    _fn("get_vo2_trend", "VO2max-Verlauf (Uhr-Schaetzung, Trend zaehlt).",
        {"days": {"type": "integer"}}),
    _fn("get_strength_summary", "Kraft-Ueberblick: Hauptuebungen mit e1RM/Peak/Saetzen, Wochen-Tonnage, Durchschnitts-RPE."),
    _fn("get_tonnage", "Wochen-Tonnage (kg) der letzten N Wochen.", {"weeks": {"type": "integer"}}),
    _fn("get_rpe_trend", "Woechentlicher Durchschnitts-RPE (Ermuedungssignal).", {"weeks": {"type": "integer"}}),
    _fn("get_e1rm_trend", "e1RM-Verlauf einer bestimmten Uebung.",
        {"exercise": {"type": "string", "description": "genauer Uebungsname, z. B. 'Squat (Langhantel)'"},
         "weeks": {"type": "integer"}}, ["exercise"]),
    _fn("get_health_overview", "Allgemeine Gesundheitswerte: Schritte (heute/Oe7T/Oe30T) + Radfahren (gesamt/30T/diese Woche/Oe-Speed)."),
    _fn("get_steps", "Tagesschritte + 7-Tage-Mittel der letzten N Tage (Health Connect).",
        {"days": {"type": "integer", "description": "Default 30"}}),
    _fn("get_cycling_volume", "Wochen-Radvolumen (km) + Anzahl Fahrten der letzten N Wochen (exercise_type 4).",
        {"weeks": {"type": "integer", "description": "Default 12"}}),
    _fn("get_forecast", "30-Tage-Prognose (linearer Trend) für Gewicht UND Körperfett: aktueller Wert, "
        "projizierter Wert in 30 Tagen, Änderung pro Woche/Monat."),
    _fn("get_strength_index", "Gesamtstärke-Index (wöchentlich aufgelöst, driftfrei am Monats-Backbone "
        "verankert, Basis 100 = Trainingsstart): aktueller Wert, Δ über den Zeitraum, Trend "
        "(steigt/stagniert/faellt) + Treiber-/Bremse-Übungen.",
        {"period": {"type": "string", "description": "1m|3m|6m|12m, Default 3m"}}),
    _fn("get_strength_energy", "Zusammenhang Gesamtstärke ↔ Energiebilanz (TDEE/Defizit), wöchentlich "
        "aligned. WICHTIG für die Deutung: corr_index_deficit ist die NIVEAU-Korrelation und "
        "trendgetrieben/scheinbar; corr_change_deficit (entkoppelt, Woche-zu-Woche) ist der belastbare "
        "Wert (~0 = kein Dauergesetz). 'phase'/'phase_label' + recent_* geben den Read der jüngsten "
        "Wochen (cut=Defizit kostet Kraft / recomp / aufbau / stabil). 'caveat' beachten."),
]


def dispatch(name: str, args: dict):
    if name == "get_overview":
        return {"body": body.summary(), "running": running.summary(), "strength": strength.summary()}
    if name == "get_weight_trend":
        return _thin(body.weight_trend(int(args.get("days", 90))))
    if name == "get_tdee":
        return body.adaptive_tdee(int(args.get("window_days", 14)))
    if name == "get_bodyfat_trend":
        return _thin(body.body_fat_trend(int(args.get("days", 180))))
    if name == "get_running_volume":
        return running.weekly_volume(int(args.get("weeks", 12)))
    if name == "get_pace_trend":
        return running.pace_trend(int(args.get("weeks", 12)))
    if name == "get_vo2_trend":
        return _thin(running.vo2_trend(int(args.get("days", 365))))
    if name == "get_strength_summary":
        return strength.summary()
    if name == "get_tonnage":
        return strength.weekly_tonnage(int(args.get("weeks", 12)))
    if name == "get_rpe_trend":
        return strength.rpe_trend(int(args.get("weeks", 12)))
    if name == "get_e1rm_trend":
        return strength.e1rm_trend(str(args.get("exercise", "")), int(args.get("weeks", 26)))
    if name == "get_health_overview":
        return health.overview()
    if name == "get_steps":
        return _thin(health.steps_trend(int(args.get("days", 30))))
    if name == "get_cycling_volume":
        return health.cycling_weekly(int(args.get("weeks", 12)))
    if name == "get_forecast":
        return {"weight": body.weight_forecast(), "bodyfat": body.bodyfat_forecast()}
    if name == "get_strength_index":
        return strength.strength_index(str(args.get("period", "3m")))
    if name == "get_strength_energy":
        r = strength.strength_energy()
        if r:  # Reihen für den Coach ausdünnen (token-sparsam), Kennzahlen behalten
            r = {**r, "series": _thin(r.get("series", []))}
        return r
    raise ValueError(f"Unbekanntes Tool: {name}")
