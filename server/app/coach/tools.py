"""Tool-Definitionen + Dispatcher fuer den Tool-Calling-Coach (ARCHITECTURE.md §6.2b).
Dieselbe metrics/-Schicht wie REST/Snapshot - das LLM ruft gezielt, was es fuer eine Frage braucht."""
from __future__ import annotations

from ..metrics import achievements, body, health, nutrition, run_analysis, run_fitness_service, running, strength


def _thin(items: list, n: int = 16) -> list:
    """Lange Reihen ausduennen, damit Tool-Ergebnisse token-sparsam bleiben."""
    if len(items) <= n:
        return items
    if n < 2:
        return items[-1:] if n == 1 else []
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


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
    _fn("get_personal_run_vo2", "Eigener VO2-Aequivalent-Trend bei 6:00/km, rollierende 8 Wochen. "
        "Feste beobachtete Belastungsreferenz (keine gemessene HFmax), Ruhepuls ggf. ausdrueckliche Annahme. "
        "Kalibrierung, Datenalter, Luecken und sensitive-Status nennen. Keine gemessene VO2max; "
        "ueberlappende Fenster sind keine unabhaengige Evidenz. Sensorwechsel trennen Zeitabschnitte."),
    _fn("get_standardized_run_hr", "Experimentelle standardisierte Lauf-HF bei Minute 30, "
        "automatisch belegte Pace-Stufen in 30 Sekunden/km. Rollierende 8-Wochen-Werte mit Lauf-Bootstrap-Intervall, "
        "Datenluecken und Begruendungen. Nur hr/ci-Felder freigegeben, exploratory_hr ist keine "
        "belastbare Aussage. Vergleichsmonate und Datenalter immer nennen. Temperatur und Terrain "
        "unkontrolliert; weder VO2max-Messung noch Nachweis physiologischen Fitnessfortschritts."),
    _fn("get_overview", "Kompakte Zusammenfassung aller drei Bereiche (Koerper, Laufen, Kraft) mit den aktuellen Kennzahlen."),
    _fn("get_weight_trend", "Gewichtsverlauf (Tageswerte + 7-Tage-EWMA) der letzten N Tage.",
        {"days": {"type": "integer", "description": "Zeitraum in Tagen (Default 90)"}}),
    _fn("get_tdee", "Geschaetzter Energieverbrauch und Energiebilanz. Datenstand, Erfassung und Vorlaeufigkeit beachten.",
        {"window_days": {"type": "integer", "minimum": 1, "description": "Default 14 Tage"}}),
    _fn("get_nutrition_summary", "Ernaehrung: Protein, Kalorien (bereits kcal), Makros und Protein-Referenzziel. "
        "Fenster window_start bis last_day und Erfassungstage beachten; *_today bezeichnet den letzten "
        "erfassten Tag, nicht zwingend heute. Eintragstage belegen keine vollstaendige Tageserfassung. "
        "tdee und kcal_avg7 haben unterschiedliche Fenster: fuer Energiebilanz get_tdee verwenden. "
        "protein_target ist ein Referenzwert, kein individuell verordnetes Ziel."),
    _fn("get_bodyfat_trend", "Koerperfett-Trend (Bioimpedanz, nur Trend) der letzten N Tage.",
        {"days": {"type": "integer"}}),
    _fn("get_running_volume", "Wochen-Laufvolumen (km) + Anzahl Laeufe der letzten N Wochen.",
        {"weeks": {"type": "integer", "description": "Default 12"}}),
    _fn("get_pace_trend", "Pace-Trend (min/km) je Woche (niedriger = schneller).",
        {"weeks": {"type": "integer"}}),
    _fn("get_vo2_trend", "VO2max-Verlauf (Uhr-Schaetzung, Trend zaehlt).",
        {"days": {"type": "integer"}}),
    _fn("get_run_heart_rate", "Herzfrequenz je Woche ueber alle Laeufe mit HF: Oe-HF, Max-HF, "
        "aerobe Effizienz ef (Meter pro Herzschlag, hoeher = fitter — gleiche Pace bei "
        "niedrigerer HF), Oe-Drift (HF 2. vs. 1. Haelfte in %, hoch = Ausdauerdefizit/Hitze).",
        {"weeks": {"type": "integer", "description": "Default 12"}}),
    _fn("get_run_zones", "Fuenf Lauf-Pulszonen in %HFmax mit gespeichertem Referenzwert; "
        "keine gemessene HFmax, keine Laktatschwellen und kein Import der Garmin-Zonen. "
        "Schema, Datenfenster und Quelle je Zone nennen. Aktuelle Uhr hat Vorrang; "
        "historical-Fallback ausdruecklich als fruehere Uhr vor Wechsel kennzeichnen und getrennt halten. "
        "Tempo aus beobachteten Laufminuten, P10–P90 ist kein Konfidenzintervall; "
        "null und reason bedeuten keine unterstuetzte Pace. "
        "Keine fehlenden Paces extrapolieren oder als Trainingsvorgabe darstellen; caveat beachten."),
    _fn("get_run_fitness_trends", "Lauf-Fitness-Entwicklung mit Signifikanz-Urteil (95%-CI, "
        "Lauf-Level-Regression): pace_at_hr (Pace bei Referenzpuls — schneller bei gleichem "
        "Puls = fitter), easy_hr (Oe-HF im Locker-Pace-Korridor — niedriger = fitter), "
        "trimp (Wochen-Trainingslast Banister), pace_by_zone (Oe-Pace je physiologischer "
        "Puls-Zone Z1-Z4 in %HFmax: Z1<70/Z2 70-80/Z3 80-90/Z4>=90 %, "
        "sec_per_km_per_month = Punkt-Schaetzer OHNE Signifikanz; ACHTUNG Zonen-Wanderung: "
        "fittere Laeufe rutschen in tiefere Zonen, Zonen-Slopes unterschaetzen den Fortschritt "
        "systematisch — nie als 'wo verbessere ich mich am meisten' deuten), resting_hr "
        "(Ruhepuls-Trend). Jedes trend-Objekt hat verdict (besser/schlechter/unklar/wenig_daten) "
        "— NUR bei significant=true als echten Trend deuten, sonst als Rauschen benennen."),
    _fn("get_run_records", "Lauf-Bestzeiten: Top-3 Best-Effort-Splits je Standard-Distanz "
        "(1/5/10/15/20 km = schnellstes zusammenhaengendes Fenster INNERHALB eines Laufs, nicht "
        "die Gesamtzeit) + weitere Rekorde (laengster Lauf, groesste Wochendistanz, beste aerobe "
        "Effizienz). Distanzen ohne qualifizierten Lauf haben eine leere Liste (nie so weit gelaufen)."),
    _fn("get_run_achievements", "Lauf-Achievements (sammelbare Trophaeen, WoW-Style): summary "
        "(Gesamtpunkte, erreichte/gesamte Trophaeen, Laeufer-Level+Titel), Liste der erreichten "
        "Erfolge und 'almost' (fast geschafft, hoechster Fortschritt) — gut zum Motivieren."),
    _fn("get_strength_summary", "Kraft-Ueberblick: Hauptuebungen mit e1RM/Peak/Saetzen, Wochen-Tonnage, Durchschnitts-RPE."),
    _fn("get_tonnage", "Wochen-Tonnage (kg) der letzten N Wochen.", {"weeks": {"type": "integer"}}),
    _fn("get_rpe_trend", "Woechentlicher Durchschnitts-RPE (Ermuedungssignal).", {"weeks": {"type": "integer"}}),
    _fn("get_e1rm_trend", "e1RM-Verlauf einer bestimmten Uebung.",
        {"exercise": {"type": "string", "description": "genauer Uebungsname, z. B. 'Squat (Langhantel)'"},
         "weeks": {"type": "integer"}}, ["exercise"]),
    _fn("get_health_overview", "Allgemeine Gesundheitswerte: Schritte (letzter erfasster Tag/Oe7T/Oe30T) + Radfahren. Datenstand und Erfassungstage beachten."),
    _fn("get_garmin_recovery", "Direkte Garmin-Erholungsdaten mit Messdatum: nächtliche HRV, Garmin-Ruhepuls, "
        "Body Battery und Trainingsbereitschaft. Fehlende HRV-Baseline ist unbekannt. Garmin-Scores "
        "enthalten bereits Schlaf/HRV; keine unabhängige Bestätigung und keine Trainingsfreigabe.",
        {"days": {"type": "integer", "minimum": 1, "maximum": 90, "description": "Default 14"}}),
    _fn("get_sleep_overview", "Schlafdauer und Erfassungstage der ausgewählten Uhr. Hauptschlaf ohne Wachphasen; "
        "Nickerchen separat. Datenstand, Quelle und fehlende Naechte nennen, Schlafstadien sind Uhr-Schaetzungen.",
        {"days": {"type": "integer", "minimum": 1, "maximum": 365, "description": "Default 90"}}),
    _fn("get_sleep_performance", "Vorherige Nacht und folgende Trainingsleistung: Lauf-Effizienz oder "
        "Aenderung des Uebungs-e1RM im Gym. Gruppen je Uhr getrennt, nicht zu einer Korrelation zusammenfassen. "
        "r erst ab zehn Paaren, Konfidenzintervall und Status beachten. Freiwillige Erfassung und "
        "Wetter/Trainingsplan erzeugen Verzerrung; niemals Ursache oder gesicherte Erholung ableiten.",
        {"kind": {"type": "string", "enum": ["run", "strength"], "description": "Default run"},
         "source": {"type": "string", "enum": ["current", "legacy", "all"], "description": "Default current"},
         "days": {"type": "integer", "minimum": 1, "maximum": 365, "description": "Default 180"}}),
    _fn("get_checkin_summary", "Freiwillige Check-ins: Energie, empfundene Trainingsbelastung und Notizen. "
        "Fehlende Antworten bleiben unbekannt. Anzahl und Erfassungstage immer nennen; "
        "Auswahlverzerrung verhindert allgemeine Aussagen ueber alle Tage oder Trainingseinheiten.",
        {"days": {"type": "integer", "minimum": 1, "maximum": 365, "description": "Default 30"}}),
    _fn("get_steps", "Tagesschritte + 7-Tage-Mittel der letzten N Tage (Health Connect).",
        {"days": {"type": "integer", "description": "Default 30"}}),
    _fn("get_cycling_volume", "Wochen-Radvolumen (km) + Anzahl Fahrten der letzten N Wochen (exercise_type 4).",
        {"weeks": {"type": "integer", "description": "Default 12"}}),
    _fn("get_forecast", "30-Tage-Gewichtsprognose aus linearem Trend; Körperfett als abgeleitetes "
        "Szenario mit 15%-Magermasseverlust-Annahme, keine eigenstaendige KFA-Prognose. Datenstand beachten."),
    _fn("get_strength_index", "Gesamtstärke-Index (wöchentlich aufgelöst, driftfrei am Monats-Backbone "
        "verankert, Basis 100 = Trainingsstart): aktueller Wert, Δ über den Zeitraum, Trend "
        "(steigt/stagniert/faellt) + Treiber-/Bremse-Übungen.",
        {"period": {"type": "string", "description": "1m|3m|6m|12m, Default 3m"}}),
    _fn("get_strength_energy", "Zusammenhang Gesamtstärke ↔ Energiebilanz (TDEE/Defizit), wöchentlich "
        "aligned. corr_index_deficit beschreibt den Zusammenhang der Niveaus; corr_change_deficit "
        "den der Indexänderung gegenüber der vorherigen verfügbaren Woche mit der Energiebilanz. "
        "Beide sind beschreibend, kein Kausalitätsnachweis. Keine feste Korrelation voraussetzen; "
        "null bedeutet nicht berechenbar. recent_* und phase_label beschreiben die jüngsten Wochen. "
        "Historische phase-Schlüssel wie recomp belegen keine Recomposition. 'caveat' beachten."),
]


def dispatch(name: str, args: dict):
    if name == "get_standardized_run_hr":
        return run_fitness_service.standardized_hr()
    if name == "get_personal_run_vo2":
        return run_fitness_service.fitness()
    if name == "get_overview":
        return {"body": body.summary(), "running": running.summary(), "strength": strength.summary()}
    if name == "get_weight_trend":
        return _thin(body.weight_trend(int(args.get("days", 90))))
    if name == "get_tdee":
        return body.adaptive_tdee(int(args.get("window_days", 14)))
    if name == "get_nutrition_summary":
        return nutrition.summary()
    if name == "get_bodyfat_trend":
        return _thin(body.body_fat_trend(int(args.get("days", 180))))
    if name == "get_running_volume":
        return running.weekly_volume(int(args.get("weeks", 12)))
    if name == "get_pace_trend":
        return running.pace_trend(int(args.get("weeks", 12)))
    if name == "get_vo2_trend":
        return _thin(running.vo2_trend(int(args.get("days", 365))))
    if name == "get_run_heart_rate":
        return running.heart_rate_trend(int(args.get("weeks", 12)))
    if name == "get_run_zones":
        from ..metrics import run_zones
        return run_zones.zones()
    if name == "get_run_records":
        return running.best_efforts()
    if name == "get_run_achievements":
        r = achievements.evaluate()
        earned = [{"name": a["name"], "points": a["points"], "date": a["earned_date"]}
                  for a in r["achievements"] if a["earned"]]
        almost = sorted((a for a in r["achievements"] if not a["earned"]),
                        key=lambda a: -a["progress"])[:6]
        almost = [{"name": a["name"], "progress": a["progress"], "status": a["progress_label"]}
                  for a in almost]
        return {"summary": r["summary"], "earned": earned, "almost": almost}
    if name == "get_run_fitness_trends":
        pah = running.pace_at_hr()
        easy = running.easy_hr_trend()
        trimp = running.trimp_weekly()
        zones = running.pace_by_hr_zone()
        resting = health.resting_hr_trend()
        return {  # Serien ausduennen, Kennzahlen/Urteile komplett behalten
            "pace_at_hr": {**pah, "series": _thin(pah.get("series", []))} if pah else {},
            "easy_hr": {**easy, "series": _thin(easy.get("series", []))} if easy else {},
            "trimp": {**trimp, "series": trimp.get("series", [])[-8:]} if trimp else {},
            "pace_by_zone": ({**zones, "weeks": None,
                              "zones": [{k: v for k, v in z.items() if k != "series"}
                                        for z in zones.get("zones", [])]} if zones else {}),
            "resting_hr": ({k: v for k, v in resting.items() if k != "series"} if resting else {}),
        }
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
    if name == "get_garmin_recovery":
        from .. import garmin_daily
        return garmin_daily.coach_summary(max(1, min(90, int(args.get("days", 14)))))
    if name == "get_sleep_overview":
        from ..metrics import sleep
        result = sleep.overview(max(1, min(365, int(args.get("days", 90)))))
        return {**result, "series": _thin(result.get("series", []))}
    if name == "get_sleep_performance":
        from ..metrics import sleep
        kind, source = args.get("kind", "run"), args.get("source", "current")
        if kind not in ("run", "strength") or source not in ("current", "legacy", "all"):
            raise ValueError("Invalid sleep performance kind or source")
        result = sleep.performance(kind, source, max(1, min(365, int(args.get("days", 180)))))
        return {**result, "groups": [{**group, "points": _thin(group.get("points", []), 12)}
                                    for group in result.get("groups", [])]}
    if name == "get_checkin_summary":
        from .. import checkins
        return checkins.summary(max(1, min(365, int(args.get("days", 30)))))
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
