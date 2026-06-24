"""Baut einen kompakten Datensnapshot aus der Metrik-Schicht für die Prompt-Injection (Coach-Stufe a)."""
from __future__ import annotations

from datetime import date

from ..metrics import body, health, running, strength


def _pace(p: float | None) -> str:
    if not p:
        return "–"
    m = int(p)
    s = round((p - m) * 60)
    return f"{m}:{s:02d} min/km"


def build_snapshot() -> dict:
    return {
        "stand": date.today().isoformat(),
        "koerper": body.summary(),
        "tdee": body.adaptive_tdee(),
        "laufen": running.summary(),
        "lauf_volumen_4w": running.weekly_volume(4),
        "kraft": strength.summary(),
        "kraft_tonnage_6w": strength.weekly_tonnage(6),
        "kraft_rpe_6w": strength.rpe_trend(6),
        "schritte": health.steps_summary(),
        "radfahren": health.cycling_summary(),
        "gewicht_prognose": body.weight_forecast(),
        "kfa_prognose": body.bodyfat_forecast(),
        "kraft_index": strength.strength_index("3m"),
    }


def snapshot_text() -> str:
    """Lesbare, kompakte Form des Snapshots (deutsch) zum Einsetzen in den Prompt."""
    snap = build_snapshot()
    b, t, r, k = snap["koerper"], snap["tdee"], snap["laufen"], snap["kraft"]
    st, rad = snap["schritte"], snap["radfahren"]
    gp, fp = snap["gewicht_prognose"], snap["kfa_prognose"]

    vol = " / ".join(f'{w["km"]:.0f}' for w in snap["lauf_volumen_4w"]) or "–"
    lifts = ", ".join(f'{m["exercise"]}: {m["e1rm"]:.0f} kg' for m in (k.get("main_lifts") or [])[:5]) or "–"
    ton = " / ".join(f'{w["tonnage_kg"]/1000:.1f}t' for w in snap["kraft_tonnage_6w"]) or "–"

    lines = [
        f"Stand: {snap['stand']}",
        "",
        f"KÖRPER: Gewicht {b.get('weight_kg')} kg (7-Tage-Mittel {b.get('weight_avg7')}, "
        f"Δ7T {b.get('weight_delta7')} kg), KFA-Trend {b.get('body_fat_pct')} %. "
        f"Adaptives TDEE ~{t.get('tdee')} kcal (Ø-Intake {t.get('avg_intake')}, "
        f"Defizit ~{t.get('deficit_per_day')} kcal/Tag über {t.get('window_days')} Tage).",
        "",
        f"LAUFEN: letzte Woche {r.get('week_km')} km / {r.get('week_runs')} Läufe, "
        f"Pace {_pace(r.get('pace'))}, VO2max {r.get('vo2max')}. "
        f"Wochenvolumen (4 Wo, km): {vol}. Höhenmeter: nicht verfügbar.",
        "",
        f"KRAFT: Top-e1RM {k.get('top_lift')} {k.get('top_e1rm')} kg; Wochen-Tonnage ~{(k.get('week_tonnage_kg') or 0)/1000:.1f} t; "
        f"RPE Ø {k.get('rpe')}. Tonnage (6 Wo): {ton}. e1RM-Hauptübungen: {lifts}.",
        (lambda ki: f"GESAMTSTÄRKE-Index: {ki.get('value')} (Basis 100), {ki.get('window_delta_pct')} % über 3 Monate → {ki.get('trend')}."
         if ki else "GESAMTSTÄRKE-Index: –")(snap.get("kraft_index") or {}),
        "",
        f"GESUNDHEIT: Schritte heute {st.get('last')}, Ø {st.get('avg7')}/Tag (7 T), Ø {st.get('avg30')}/Tag (30 T). "
        f"Radfahren: {rad.get('total_km')} km gesamt / {rad.get('rides')} Fahrten, "
        f"{rad.get('km_30d')} km in den letzten 30 T (heute-relativ), Ø {rad.get('avg_speed')} km/h, "
        f"zuletzt {rad.get('last_day')}.",
        "",
        "PROGNOSE (30 T, linearer Trend): "
        + (f"Gewicht {gp['current']}→{gp['projected']} kg ({gp['per_month']:+} kg/Monat)" if gp else "Gewicht –")
        + "; "
        + (f"KFA {fp['current']}→{fp['projected']} % ({fp['per_month']:+} %/Monat)" if fp else "KFA –")
        + ".",
    ]
    return "\n".join(lines)
