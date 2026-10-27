"""Körperzusammensetzung aus dem Taillenumfang — als Spanne, nie als Einzelwert.

Obergrenze = RFM nach Woolcott 2018 (Mann: 64 − 20 · Größe / Taille), mit der schmalsten Taille.
Untergrenze = RFM − PHOTO_OFFSET: die blinde Fotobewertung (2026-10-27, 7 Termine) lag im Schnitt so weit
unter RFM. Augenmaß unterschätzt eher, RFM ist eine Bevölkerungsformel (±4–5 Pkt. je Person) — die Wahrheit
liegt dazwischen; eine DEXA-Messung würde sie festlegen. Fettfreie Masse = Gewicht · (1 − KFA) für beide Grenzen.
Der Waagen-Körperfettwert wird bewusst nicht benutzt (Formel aus dem Gewicht, R² 0,998)."""
from __future__ import annotations

import json

import pandas as pd

from ..config import settings
from ..db import engine

PHOTO_OFFSET = 5.0      # Prozentpunkte zwischen RFM und blinder Fotobewertung
WEIGHT_WINDOW_DAYS = 7  # Gewicht = Mittel ±7 Tage um den Messtag (mindestens 3 Wiegungen)


def rfm(height_cm: float, waist_cm: float) -> float:
    return 64 - 20 * height_cm / waist_cm


def _waists() -> pd.Series:
    with engine.connect() as con:
        rows = con.exec_driver_sql(
            "SELECT measured_on, values_json FROM body_circumference_entries "
            "WHERE protocol = 'standard' ORDER BY measured_on").fetchall()
    waist = {pd.Timestamp(day): json.loads(raw).get("waist_narrowest") for day, raw in rows}
    return pd.Series({d: v for d, v in waist.items() if v is not None}, dtype=float)


def _weight_at(weight: pd.Series, day: pd.Timestamp) -> float | None:
    win = weight[(weight.index >= day - pd.Timedelta(days=WEIGHT_WINDOW_DAYS))
                 & (weight.index <= day + pd.Timedelta(days=WEIGHT_WINDOW_DAYS))]
    return float(win.mean()) if len(win) >= 3 else None


def estimate() -> dict:
    """Spanne je Taillenmessung + aktueller Stand (letzte Messung)."""
    from . import body
    height = settings.body_height_cm
    caveat = ("Spanne aus dem Taillenumfang: oben die Taillenformel (RFM), unten deine blinde Fotobewertung "
              f"(im Schnitt {PHOTO_OFFSET:.0f} Punkte tiefer). Keine Messung; eine DEXA-Messung würde den Wert festlegen.")
    if not height:
        return {"available": False, "reason": "Körpergröße fehlt (Einstellungen → Körper).", "series": [], "caveat": caveat}
    waists = _waists()
    if waists.empty:
        return {"available": False, "reason": "Noch keine Taillenmessung (schmalste Stelle).", "series": [], "caveat": caveat}
    weight = body._weight_daily().dropna()
    series = []
    for day, waist in waists.items():
        high = rfm(height, waist)
        low = high - PHOTO_OFFSET
        w = _weight_at(weight, day)
        row = {"date": day.date().isoformat(), "waist": round(waist, 1), "whtr": round(waist / height, 3),
               "bf_low": round(low, 1), "bf_high": round(high, 1), "bf_mid": round((low + high) / 2, 1),
               "weight": None if w is None else round(w, 1)}
        if w is not None:
            row.update(fat_low=round(w * low / 100, 1), fat_high=round(w * high / 100, 1),
                       ffm_low=round(w * (1 - high / 100), 1), ffm_high=round(w * (1 - low / 100), 1),
                       ffm_mid=round(w * (1 - (low + high) / 200), 1))
        series.append(row)
    first, last = series[0], series[-1]
    return {"available": True, "current": last, "first": first, "height_cm": height,
            "whtr_delta": round(last["whtr"] - first["whtr"], 3), "waist_delta": round(last["waist"] - first["waist"], 1),
            "series": series, "photo_offset": PHOTO_OFFSET, "caveat": caveat}


def current_ffm() -> float | None:
    """Mitte der fettfreien Masse aus der letzten Taillenmessung (für den Ruheumsatz)."""
    try:
        est = estimate()
    except Exception:  # noqa: BLE001 -- Anzeige-Zusatz darf den Verbrauch nie sperren
        return None
    return est.get("current", {}).get("ffm_mid") if est.get("available") else None
