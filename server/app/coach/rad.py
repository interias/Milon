"""Rad-Kontext für den Coach (Epic #75, #74): Tool/MCP-Übersicht, Snapshot-Zeilen, Zwift-Vorschlag, Wochenzeilen.

Eine Stelle für alles, was der Coach über Indoor-Rad und Form (TSB) liest — Tool, MCP, Snapshot, Morgenbriefing
und Wochenbericht rufen dieselben Funktionen. Der Coach liest nur und schlägt vor.
Regeln: Urteile nur bei significant=true; Form ist pulsbasiert (TRIMP über Lauf + Rad), Watt-TSS wird nie mit
Lauflast verrechnet; im Prompt stehen nie Koordinaten (Fahrten haben ohnehin keine, Welt/Route sind Zwift-Namen).
"""
from __future__ import annotations

import logging
from datetime import date

from ..metrics import cycling, endurance

log = logging.getLogger(__name__)

# Zwift-Vorschlag bei schlechtem Laufwetter (Schwellen aus dem Ticket).
FROST_C = 0.0
WET_COLD_C = 5.0
WIND_KMH = 30

HINT = ("Urteile (hr_at_power.trend, efficiency.trend) nur bei significant=true als echten Trend deuten, sonst als "
        "Rauschen benennen. Form (TSB) ist pulsbasiert über Lauf + Rad (TRIMP, HFmax aus dem Setting) und nicht "
        "direkt mit TRIMP aus get_run_fitness_trends vergleichbar (anderes HFmax); Watt-TSS nie mit Lauflast "
        "verrechnen. Rad erhält die aerobe Basis, ersetzt aber weder Laufökonomie noch die Belastbarkeit von "
        "Sehnen und Knochen.")


def _verdict(trend: dict | None) -> str:
    """Urteil als Text: Richtung nur bei Signifikanz."""
    trend = trend or {}
    if trend.get("significant"):
        return f"{trend.get('verdict')} (signifikant, n={trend.get('n')})"
    if trend.get("verdict") == "wenig_daten":
        return "zu wenig Daten"
    return "kein belastbarer Trend"


def form(today: date | None = None) -> dict | None:
    """Heutige Form-Zeile aus `endurance.fitness` (`today`-Block) oder None ohne bewertete Einheit."""
    return endurance.fitness(days=28, today=today).get("today")


def form_text(f: dict | None) -> str | None:
    if not f:
        return None
    return (f"Form (TSB) {f['tsb']:+.0f} ({f['form']}), Fitness CTL {f['ctl']:.0f}, Ermüdung ATL {f['atl']:.0f}"
            " (TRIMP-Skala, Lauf + Rad)")


def intensity_for_form(tsb: float) -> str:
    """Setzung: Form → Coggan-Zone für den Ersatztag. Sehr müde → Z1/Ruhe, müde → Z2, neutral → Z2 mit
    Tempo-Anteil, frisch → Z3–Z4 möglich."""
    if tsb <= -25:
        return "Z1 oder Ruhetag"
    if tsb < -10:
        return "Z2"
    if tsb <= 5:
        return "Z2 mit kurzen Z3-Blöcken"
    return "Z2 bis Z4 (Qualität möglich)"


def zone_watts(zone: int, ftp: float | None) -> str:
    """Wattbereich einer Coggan-Zone, z. B. "110–150 W" (leer ohne eFTP)."""
    if not ftp:
        return ""
    edges = (0.0, *cycling.COGGAN, None)
    lo, hi = edges[zone - 1], edges[zone]
    return f"{round(lo * ftp)}–{round(hi * ftp)} W" if hi is not None else f"> {round(lo * ftp)} W"


def zwift_reasons(window: dict | None) -> list[str]:
    """Gründe für einen Zwift-Tag im Morgenlauf-Fenster (leer = Laufen ist ok)."""
    if not window:
        return []
    temp, wind = window.get("temp"), window.get("wind_kmh") or 0
    reasons = []
    if temp is not None and temp < FROST_C:
        reasons.append(f"Frost ({temp} °C)")
    if window.get("icy"):
        reasons.append("Glätte (Schnee oder gefrierender Niederschlag)")
    if window.get("wet") and temp is not None and temp < WET_COLD_C:
        reasons.append(f"Regen bei {temp} °C")
    if wind >= WIND_KMH:
        reasons.append(f"Wind {wind} km/h")
    return reasons


def zwift_line(run: dict | None, today: date | None = None) -> str | None:
    """Zeile ZWIFT-VORSCHLAG fürs Morgenbriefing oder None, wenn das Wetter zum Laufen taugt."""
    window = (run or {}).get("morning") or (run or {}).get("best")
    reasons = zwift_reasons(window)
    if not reasons:
        return None
    parts = ["ZWIFT-VORSCHLAG (nur Hinweis, Lauf-Ersatz an schlechten Tagen): Laufwetter im Fenster "
             f"{window['start'][11:16]}–{window['end'][11:16]} ungünstig: {', '.join(reasons)}."]
    try:
        f = form(today)
    except Exception:  # noqa: BLE001 -- fehlende Rad-Daten kürzen nur den Vorschlag
        log.warning("Briefing: Form nicht verfügbar", exc_info=True)
        f = None
    try:
        ftp = cycling.eftp(today=today)["value"]
    except Exception:  # noqa: BLE001
        log.warning("Briefing: eFTP nicht verfügbar", exc_info=True)
        ftp = None
    if f:
        intensity = intensity_for_form(f["tsb"])
        zone = {"Z1": 1, "Z2": 2}.get(intensity[:2])
        watts = f" ({zone_watts(zone, ftp)} bei eFTP {round(ftp)} W)" if zone and ftp else ""
        parts.append(f"Form {f['tsb']:+.0f} ({f['form']}) → {intensity}{watts}; Dauer 45–60 min. "
                     "Rad erhält die aerobe Basis, ersetzt Laufökonomie und Sehnen-/Knochenbelastbarkeit nicht.")
    else:
        parts.append("Form unbekannt (keine bewertete Einheit mit Puls) → locker Z2, Dauer 45–60 min. "
                     "Rad erhält die aerobe Basis, ersetzt Laufökonomie und Sehnen-/Knochenbelastbarkeit nicht.")
    return " ".join(parts)


def power_overview(today: date | None = None) -> dict:
    """Ergebnis des Tools/MCP `get_cycling_power`: eFTP, W/kg, ausgedünnte Leistungskurve, Urteile, letzte Fahrten."""
    summary, eftp = cycling.summary(today), cycling.eftp(today=today)
    curve = cycling.power_curve(today)["durations"]
    if len(curve) > 10:  # token-sparsam: gleichmäßig auswählen, kürzeste und längste Dauer bleiben
        curve = [curve[round(i * (len(curve) - 1) / 9)] for i in range(10)]
    hp, eff = cycling.hr_at_power(), cycling.efficiency()
    recent = [{k: r.get(k) for k in ("date", "title", "world", "route", "minutes", "avg_power", "np", "avg_hr", "hr_valid",
                                     "if", "tss", "kj")} for r in cycling.rides(5)]
    try:
        f = form(today)
    except Exception:  # noqa: BLE001
        log.warning("Rad-Tool: Form nicht verfügbar", exc_info=True)
        f = None
    return {
        "hinweis": HINT,
        "summary": {k: summary.get(k) for k in ("rides", "rides_with_power", "rides_30d", "hours_30d", "tss_7d", "tss_28d",
                                                 "hr_valid_rides")},
        "eftp": {"value": eftp["value"], "source": eftp["source"], "wkg": eftp["wkg"], "weight_kg": eftp["weight_kg"],
                 "garmin_ftp": eftp["garmin_ftp"], "caveat": eftp["caveat"]},
        "power_curve": curve,
        "hr_at_power": {"ref_power": hp.get("ref_power"), "current_bpm": hp.get("current"), "trend": hp.get("trend"),
                        "caveat": hp.get("caveat")},
        "efficiency": {"current_np_per_hr": eff.get("current"), "rides": eff.get("rides"), "trend": eff.get("trend"),
                       "decoupling_last": eff.get("decoupling", [])[-3:], "caveat": eff.get("caveat")},
        "form": f,
        "recent_rides": recent,
    }


def snapshot_lines() -> list[str]:
    """AUSDAUER- (Form) und RAD-Zeile für den Snapshot; leer ohne Rad-Daten. Fehler kürzen nur den Snapshot."""
    lines: list[str] = []
    try:
        fit = endurance.fitness(days=28)
        text = form_text(fit.get("today"))
        if text:
            week = fit["weeks"][-1] if fit.get("weeks") else None
            share = (f"; letzte Woche Lauf-Anteil an der Last {week['run_share']:.0f} % ({week['runs']} Läufe, "
                     f"{week['rides']} Fahrten mit Puls)" if week and week.get("run_share") is not None else "")
            un = fit.get("unrated") or {}
            miss = (f"; ohne Puls unbewertet: {un.get('runs', 0)} Läufe, {un.get('rides', 0)} Fahrten"
                    if un.get("runs") or un.get("rides") else "")
            lines.append(f"AUSDAUER: {text}{share}{miss}. Reine Last-Kennzahl ohne besser/schlechter-Urteil.")
        s = cycling.summary()
        if not s["rides"]:
            return lines
        hp, eff = cycling.hr_at_power(), cycling.efficiency()
        last = s.get("last_ride") or {}
        hr_part = (f"Puls bei {hp['ref_power']} W: {hp.get('current')} bpm" if hp.get("ref_power") is not None
                   else "Puls bei Referenzleistung")
        eff_part = f"Effizienz NP/HF {eff['current']}" if eff.get("current") is not None else "Effizienz NP/HF"
        lines.append(
            f"RAD (Zwift/Rolle): {s['rides']} Fahrten gesamt, {s['rides_30d']} in 30 T ({s['hours_30d']} h), "
            f"eFTP {s['eftp']} W ({s['eftp_source']}), {s['wkg']} W/kg, Watt-TSS 7 T {s['tss_7d']} / 28 T {s['tss_28d']}. "
            f"{hr_part} → {_verdict(hp.get('trend'))}; "
            f"{eff_part} → {_verdict(eff.get('trend'))}. "
            f"Letzte Fahrt {str(last.get('date'))[:10]}: {last.get('minutes')} min, NP {last.get('np')} W."
            " Watt-TSS nicht mit Lauflast vergleichen.")
    except Exception:  # noqa: BLE001
        log.warning("Snapshot: Rad-Zeilen nicht verfügbar", exc_info=True)
    return lines


def week_lines(first: date, last: date) -> list[str]:
    """Wochenbericht: Lauf/Rad-Anteil, Form-Verlauf Mo–So, Rad-Urteile. Leer, wenn es keine Rad-/Lastdaten gibt."""
    lines: list[str] = []
    try:
        fit = endurance.fitness(days=60, today=last)
        days = [r for r in fit.get("series", []) if first.isoformat() <= r["date"] <= last.isoformat()]
        week = next((w for w in fit.get("weeks", []) if w["week"] == first.isoformat()), None)
        if week:
            share = f"{week['run_share']:.0f} %" if week.get("run_share") is not None else "unbekannt"
            lines.append(f"AUSDAUER DER WOCHE: Last Lauf {week['run']:.0f} / Rad {week['bike']:.0f} (TRIMP), Lauf-Anteil {share}, "
                         f"{week['runs']} Läufe und {week['rides']} Fahrten mit Puls, {week['unrated']} Einheiten ohne gültigen Puls "
                         "(unbewertet).")
        if days:
            a, b = days[0], days[-1]
            lines.append(f"FORM-VERLAUF DER WOCHE: TSB {a['tsb']:+.0f} (Mo) → {b['tsb']:+.0f} (So); Fitness CTL {a['ctl']:.0f} → "
                         f"{b['ctl']:.0f}, Ermüdung ATL {a['atl']:.0f} → {b['atl']:.0f}. Reine Last-Kennzahl ohne Urteil.")
        week_rides = [r for r in cycling.rides(0)
                      if first.isoformat() <= str(r["date"])[:10] <= last.isoformat()]
        if week_rides:
            lines.append("RAD DER WOCHE: " + "; ".join(
                f"{str(r['date'])[:10]} {r['minutes']} min, NP {r['np']} W, Watt-TSS {r['tss']}" for r in week_rides)
                + ". Watt-TSS nicht mit Lauflast vergleichen.")
        if cycling.summary(last)["rides"]:
            hp, eff = cycling.hr_at_power(), cycling.efficiency()
            ref = f"{hp['ref_power']} W" if hp.get("ref_power") is not None else "Referenzleistung"
            lines.append(f"RAD-URTEILE (nur bei Signifikanz belastbar): Puls bei {ref} → "
                         f"{_verdict(hp.get('trend'))}; Effizienz NP/HF → {_verdict(eff.get('trend'))}.")
    except Exception:  # noqa: BLE001
        log.warning("Wochenbericht: Rad nicht verfügbar", exc_info=True)
    return lines
