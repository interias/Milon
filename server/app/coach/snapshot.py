"""Baut einen kompakten Datensnapshot aus der Metrik-Schicht für die Prompt-Injection (Coach-Stufe a)."""
from __future__ import annotations

from datetime import datetime
import json
from zoneinfo import ZoneInfo

from ..config import settings
from .. import checkins, coach_actions
from ..metrics import body, health, nutrition, running, sleep, strength


def _pace(p: float | None) -> str:
    if not p:
        return "–"
    m = int(p)
    s = round((p - m) * 60)
    return f"{m}:{s:02d} min/km"


def build_snapshot() -> dict:
    from .. import garmin_daily

    return {
        "stand": datetime.now(ZoneInfo(settings.timezone)).date().isoformat(),
        "ernaehrung": nutrition.summary(),
        "koerper": body.summary(),
        "tdee": body.adaptive_tdee(),
        "laufen": running.summary(),
        "lauf_volumen_4w": running.weekly_volume(4),
        "kraft": strength.summary(),
        "kraft_tonnage_6w": strength.weekly_tonnage(6),
        "kraft_rpe_6w": strength.rpe_trend(6),
        "schritte": health.steps_summary(),
        "radfahren": health.cycling_summary(),
        "ruhepuls": health.resting_hr_trend(days=30),
        "gewicht_prognose": body.weight_forecast(),
        "kfa_prognose": body.bodyfat_forecast(),
        "kraft_index": strength.strength_index("3m"),
        "schlaf": sleep.overview(30)["summary"],
        "checkins": checkins.summary(30),
        "wochenmassnahmen": coach_actions.coach_context(),
        "garmin_erholung": garmin_daily.coach_summary(14),
    }


def snapshot_text() -> str:
    """Lesbare, kompakte Form des Snapshots (deutsch) zum Einsetzen in den Prompt."""
    snap = build_snapshot()
    b, t, r, k = snap["koerper"], snap["tdee"], snap["laufen"], snap["kraft"]
    st, rad = snap["schritte"], snap["radfahren"]
    gp, fp = snap["gewicht_prognose"], snap["kfa_prognose"]
    food = snap["ernaehrung"]

    vol = " / ".join(f'{w["week"]}: {w["km"]:.0f}' for w in snap["lauf_volumen_4w"]) or "–"
    lifts = ", ".join(f'{m["exercise"]}: {m["e1rm"]:.0f} kg' for m in (k.get("main_lifts") or [])[:5]) or "–"
    ton = " / ".join(f'{w["week"]}: {w["tonnage_kg"]/1000:.1f}t' for w in snap["kraft_tonnage_6w"]) or "–"

    # HF-Werte stammen aus der letzten Woche MIT HF-Läufen — ist die älter als die letzte
    # Lauf-Woche (Watch nicht getragen), explizit kennzeichnen statt "letzte Woche" zu suggerieren.
    cur_week = snap["lauf_volumen_4w"][-1]["week"] if snap["lauf_volumen_4w"] else None
    hr_week = r.get("hr_week")
    hr_note = f" (Werte aus Woche vom {hr_week}, seitdem keine HF-Läufe)" if hr_week and hr_week != cur_week else ""

    lines = [
        f"Abfragedatum: {snap['stand']}; einzelne Messdaten können älter sein. None = nicht verfügbar.",
        "",
        f"KÖRPER: Gewicht {b.get('weight_kg')} kg (7-Tage-Mittel {b.get('weight_avg7')}, "
        f"Δ7T {b.get('weight_delta7')} kg; letzter Messtag {b.get('weight_date')}, "
        f"{b.get('weight_days7')}/7 Messtage), KFA-Trend {b.get('body_fat_pct')} %. "
        f"Adaptives TDEE ~{t.get('tdee')} kcal (Ø-Intake {t.get('avg_intake')}, "
        f"Defizit ~{t.get('deficit_per_day')} kcal/Tag; Stand {t.get('from_date')}, "
        f"{t.get('estimate_days')} Schätztage in {t.get('smooth_days')} Kalendertagen"
        + (", vorläufig" if t.get("provisional") else "") + ").",
        "",
        f"LAUFEN: letzte erfasste Woche ({cur_week}) {r.get('week_km')} km / {r.get('week_runs')} Läufe, "
        f"Pace {_pace(r.get('pace'))}, VO2max {r.get('vo2max')}. "
        f"Ø-HF {r.get('avg_hr') or '–'} bpm (max {r.get('max_hr') or '–'}), "
        f"aerobe Effizienz {r.get('ef') or '–'} m/Herzschlag, HF-Drift {r.get('hr_drift') if r.get('hr_drift') is not None else '–'} %{hr_note}. "
        f"Wochenvolumen (4 Wo, km): {vol}. Höhenmeter sind gegebenenfalls in einzelnen Garmin-Laufdetails vorhanden.",
        "",
        f"KRAFT: Top-e1RM {k.get('top_lift')} {k.get('top_e1rm')} kg; Wochen-Tonnage ~{(k.get('week_tonnage_kg') or 0)/1000:.1f} t; "
        f"RPE Ø {k.get('rpe')}. Tonnage (6 Wo): {ton}. e1RM-Hauptübungen: {lifts}.",
        (lambda ki: f"GESAMTSTÄRKE-Index: {ki.get('value')} (Basis 100), {ki.get('window_delta_pct')} % über 3 Monate → {ki.get('trend')}."
         if ki else "GESAMTSTÄRKE-Index: –")(snap.get("kraft_index") or {}),
        "",
        f"GESUNDHEIT: Schritte zuletzt {st.get('last')} am {st.get('last_day')}, "
        f"Ø {st.get('avg7')}/Tag ({st.get('days7')}/7 erfasste Tage), "
        f"Ø {st.get('avg30')}/Tag ({st.get('days30')}/30 erfasste Tage). "
        f"Radfahren: {rad.get('total_km')} km gesamt / {rad.get('rides')} Fahrten, "
        f"{rad.get('km_30d')} km in den letzten 30 T (heute-relativ), Ø {rad.get('avg_speed')} km/h, "
        f"zuletzt {rad.get('last_day')}."
        + (lambda rp: f" Ruhepuls {rp.get('last'):.0f} bpm (Ø7 {rp.get('avg7')})."
           if rp and rp.get("last") is not None else "")(snap.get("ruhepuls") or {}),
        "",
        f"ERNÄHRUNG: Fenster {food.get('window_start')} bis {food.get('last_day')}: "
        f"Protein Ø {food.get('protein_avg7')} g ({food.get('protein_days_7')}/7 erfasste Tage), "
        f"Referenzziel {food.get('protein_target')} g ({food.get('protein_per_kg')} g/kg, kein individuelles Ziel); "
        f"Energie Ø {food.get('kcal_avg7')} kcal ({food.get('kcal_days_7')}/7 erfasste Tage). "
        f"Makros Ø in g: {food.get('macro_g')}. Einträge belegen keine vollständige Tageserfassung.",
        "",
        (lambda sl: f"SCHLAF: letzte Hauptnacht {sl.get('latest_date')}, Schlafzeit {sl.get('latest_asleep_hours')} h "
         f"(Schlaffenster {sl.get('latest_window_hours')} h, nicht gleich Schlafzeit); aktuelle Uhr "
         f"Ø7 {sl.get('avg_asleep_hours_7d')} h aus {sl.get('known_asleep_nights_7d')}/7 bekannten Nächten. "
         "Fehlende Phasen und Nächte bleiben unbekannt.")(snap["schlaf"]),
        (lambda ci: f"CHECK-IN (freiwillig): {ci['count']}/{ci['days']} Tage erfasst, "
         f"Energie Ø {ci['energy_avg']}/5 ({ci['energy_days']} Tage), Trainingsanstrengung "
         f"Ø {ci['training_effort_avg']}/5 ({ci['training_effort_days']} Tage). "
         "Auswahl kann verzerrt sein; keine Einträge bedeuten keine Aussage über Befinden.")(snap["checkins"]),
        "",
        "PROGNOSE (30 T, linearer Trend): "
        + (f"Gewicht {gp['current']}→{gp['projected']} kg ({gp['per_month']:+} kg/Monat)" if gp.get("projected") is not None else f"Gewicht: {gp.get('reason', 'nicht verfügbar')}")
        + "; "
        + (f"KFA-Szenario (15%-Annahme) {fp['current']}→{fp['projected']} % ({fp['per_month']:+} %/Monat)" if fp.get("projected") is not None else f"KFA: {fp.get('reason', 'nicht verfügbar')}")
        + ".",
    ]
    if snap.get("garmin_erholung"):
        lines.append("GARMIN ERHOLUNG (Schätzungen, Messdaten beachten): "
                     + json.dumps(snap["garmin_erholung"], ensure_ascii=False, allow_nan=False))
    if snap.get("wochenmassnahmen"):
        lines.append("ÜBERNOMMENE WOCHENMASSNAHMEN (Nutzerentscheidung und Rückmeldung; "
                     "beobachtete Unterschiede sind kein Wirkungsnachweis): "
                     + json.dumps(snap["wochenmassnahmen"], ensure_ascii=False, allow_nan=False))
    return "\n".join(lines)
