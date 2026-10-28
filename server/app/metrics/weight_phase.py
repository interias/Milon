"""Gewichtsphasen (Cut/Erhalt/Aufbau) mit Zielkorridor fürs Tempo in % Körpergewicht pro Woche.

Richtwerte: Cut 0,5–1 %/Woche (Helms, Aragon & Fitschen 2014), ~0,7 %/Woche erhielt in Garthe 2011
mehr fettfreie Masse als ~1 %/Woche; Aufbau Anfänger 1–2 %/Monat, Fortgeschrittene 0,5–1 %, Erfahrene
0,25–0,5 % (Helms, Muscle and Strength Pyramid; Iraki 2019: 0,25–0,5 %/Woche). Expertenkonsens, kein
hartes Gesetz → Korridor statt Grenze.

EHRLICHE STATISTIK: Das Tempo kommt aus der Regression über die Einzelwiegungen (stats.linear_trend),
nie aus dem 7-Tage-Mittel. Tagesrauschen ~±0,4 kg — unter ~3 Wochen gibt es kein Urteil."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlmodel import Field, Session, SQLModel, select

from ..config import settings
from ..db import engine
from . import stats

WEEKS_PER_MONTH = 30.44 / 7
WINDOW_DAYS = 28        # Tempo aus den letzten 4 Wochen
MIN_DAYS = 10           # Wiegungen im Fenster
MIN_SPAN = 14           # verstrichene Tage im Fenster
KCAL_PER_KG = 7700

# key → (Art, Name, Untergrenze, Obergrenze) in % Körpergewicht pro Woche (negativ = Abnahme)
PRESETS: dict[str, tuple[str, str, float, float]] = {
    "cut_gentle": ("cut", "Cut schonend", -0.5, -0.25),
    "cut_standard": ("cut", "Cut Standard", -1.0, -0.5),
    "maintain": ("maintain", "Erhalt", -0.25 / WEEKS_PER_MONTH, 0.25 / WEEKS_PER_MONTH),
    "bulk_beginner": ("bulk", "Aufbau Anfänger", 1.0 / WEEKS_PER_MONTH, 2.0 / WEEKS_PER_MONTH),
    "bulk_intermediate": ("bulk", "Aufbau Fortgeschritten", 0.5 / WEEKS_PER_MONTH, 1.0 / WEEKS_PER_MONTH),
    "bulk_advanced": ("bulk", "Aufbau Erfahren", 0.25 / WEEKS_PER_MONTH, 0.5 / WEEKS_PER_MONTH),
}

# Bereiche für den Rate-Schlauch (unabhängig von der gewählten Phase), Grenzen = die Voreinstellungen oben
_M = WEEKS_PER_MONTH
ZONES: list[tuple[float, float, str, str]] = [
    (float("-inf"), -1.0, "fast_loss", "schneller als 1 %/Woche ab"),
    (-1.0, -0.5, "cut", "Cut 0,5–1 %/Woche"),
    (-0.5, -0.25, "cut_gentle", "Cut schonend 0,25–0,5 %/Woche"),
    (-0.25, -0.25 / _M, "slight_loss", "leichte Abnahme"),
    (-0.25 / _M, 0.25 / _M, "stable", "stabil (±0,25 %/Monat)"),
    (0.25 / _M, 1.0 / _M, "bulk_slow", "Aufbau 0,25–1 %/Monat"),
    (1.0 / _M, 2.0 / _M, "bulk", "Aufbau 1–2 %/Monat"),
    (2.0 / _M, float("inf"), "fast_gain", "schneller als 2 %/Monat zu"),
]
TUBE_HALF = 14          # Rate je Tag: Regression über die Wiegungen ±14 Tage
TUBE_MIN_N = 8
TUBE_EDGE = 10          # weniger als 10 Tage Daten auf einer Seite = Rand (nur zurück bzw. nur voraus)


def zone_of(pct: float) -> dict:
    lo, hi, key, label = next(z for z in ZONES if z[0] <= pct < z[1])
    return {"key": key, "label": label}


def rate_series(s: pd.Series) -> dict[pd.Timestamp, dict]:
    """Lokale Rate je Kalendertag: OLS über die Einzelwiegungen ±14 Tage (mind. 8 über 14 Tage).
    `fit` = Mittellinie des Schlauchs, `sure` = 95-%-Spanne liegt in einem einzigen Bereich."""
    obs = s.dropna()
    if obs.empty:
        return {}
    day0 = obs.index[0]
    xs = np.asarray((obs.index - day0).days, float)
    ys = obs.to_numpy(float)
    out: dict[pd.Timestamp, dict] = {}
    for d in pd.date_range(obs.index[0], obs.index[-1], freq="D"):
        x = (d - day0).days
        m = (xs >= x - TUBE_HALF) & (xs <= x + TUBE_HALF)
        wx, wy = xs[m], ys[m]
        if len(wx) < TUBE_MIN_N or wx[-1] - wx[0] < 14:
            continue
        fit = stats.ols(np.column_stack([np.ones(len(wx)), wx - x]), wy)
        if fit is None:
            continue
        beta, se, df, _ = fit
        level, slope = float(beta[0]), float(beta[1])
        pct, ci = slope * 7 / level * 100, stats.t95(df) * float(se[1]) * 7 / level * 100
        out[d] = {"fit": round(level, 2), "rate_pct": round(pct, 3), "rate_ci": round(ci, 3),
                  "zone": zone_of(pct)["key"],
                  "sure": zone_of(pct - ci)["key"] == zone_of(pct + ci)["key"],
                  "edge": bool(x - wx[0] < TUBE_EDGE or wx[-1] - x < TUBE_EDGE)}
    return out


# Lage unter/über dem Korridor → Wortlaut je Art
_LABELS = {
    "cut": {"below": "zu schnell", "above": "zu langsam"},
    "maintain": {"below": "nimmt ab", "above": "nimmt zu"},
    "bulk": {"below": "zu langsam", "above": "zu schnell"},
}


class WeightPhase(SQLModel, table=True):
    """Eine Phase gilt ab `start` bis zum Start der nächsten."""
    __tablename__ = "weight_phases"

    id: int | None = Field(default=None, primary_key=True)
    start: date = Field(index=True, unique=True)
    preset: str


def _today() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def _row(p: WeightPhase, end: date | None) -> dict:
    kind, name, lo, hi = PRESETS[p.preset]
    return {"id": p.id, "start": p.start.isoformat(), "end": end.isoformat() if end else None,
            "preset": p.preset, "kind": kind, "name": name,
            "rate_min_pct": round(lo, 3), "rate_max_pct": round(hi, 3)}


def phases() -> list[dict]:
    """Alle Phasen chronologisch; `end` = Tag vor der nächsten (letzte offen)."""
    with Session(engine) as s:
        rows = [p for p in s.exec(select(WeightPhase).order_by(WeightPhase.start)) if p.preset in PRESETS]
    return [_row(p, rows[i + 1].start - timedelta(days=1) if i + 1 < len(rows) else None)
            for i, p in enumerate(rows)]


def set_phase(start: date, preset: str) -> dict:
    if preset not in PRESETS:
        raise ValueError(f"Unbekannte Phase: {preset}")
    with Session(engine) as s:
        p = s.exec(select(WeightPhase).where(WeightPhase.start == start)).first() or WeightPhase(start=start, preset=preset)
        p.preset = preset
        s.add(p)
        s.commit()
    return next(r for r in phases() if r["start"] == start.isoformat())


def delete_phase(phase_id: int) -> bool:
    with Session(engine) as s:
        p = s.get(WeightPhase, phase_id)
        if not p:
            return False
        s.delete(p)
        s.commit()
    return True


def _anchor(avg7: pd.Series, day: pd.Timestamp) -> float | None:
    """Startgewicht der Phase: 7-Tage-Mittel am Starttag, sonst das nächste gültige ±7 Tage."""
    near = avg7.dropna()
    near = near[(near.index >= day - pd.Timedelta(days=7)) & (near.index <= day + pd.Timedelta(days=7))]
    if near.empty:
        return None
    return float(near.iloc[abs((near.index - day).days).argmin()])


def corridor(avg7: pd.Series) -> dict[pd.Timestamp, tuple[float, float, str]]:
    """Zielkorridor je Tag ab Phasenstart: Startgewicht × (1 + Tempo · Wochen) für Unter- und Obergrenze."""
    out: dict[pd.Timestamp, tuple[float, float, str]] = {}
    if avg7.empty:
        return out
    for ph in phases():
        start = pd.Timestamp(ph["start"])
        end = pd.Timestamp(ph["end"]) if ph["end"] else avg7.index.max()
        anchor = _anchor(avg7, start)
        if anchor is None:
            continue
        for d in avg7.index[(avg7.index >= start) & (avg7.index <= end)]:
            weeks = (d - start).days / 7
            a, b = (anchor * (1 + r / 100 * weeks) for r in (ph["rate_min_pct"], ph["rate_max_pct"]))
            out[d] = (round(min(a, b), 2), round(max(a, b), 2), ph["name"])
    return out


def status(today: date | None = None) -> dict:
    """Tempo der letzten 4 Wochen (Regression über Einzelwiegungen) gegen den Korridor der aktuellen Phase."""
    from . import body
    today = today or _today()
    all_phases = phases()
    current = next((p for p in reversed(all_phases) if p["start"] <= today.isoformat()), None)
    out: dict = {"phase": current, "phases": all_phases, "window_days": WINDOW_DAYS,
                 "zones": [{"key": k, "label": lbl, "min_pct": None if lo == float("-inf") else round(lo, 3),
                            "max_pct": None if hi == float("inf") else round(hi, 3)} for lo, hi, k, lbl in ZONES],
                 "presets": [{"preset": k, "kind": v[0], "name": v[1], "rate_min_pct": round(v[2], 3),
                              "rate_max_pct": round(v[3], 3)} for k, v in PRESETS.items()]}
    s = body._weight_daily().dropna()
    lo_day = pd.Timestamp(today) - pd.Timedelta(days=WINDOW_DAYS - 1)
    if current:
        lo_day = max(lo_day, pd.Timestamp(current["start"]))
    win = s[(s.index >= lo_day) & (s.index <= pd.Timestamp(today))]
    span = (win.index[-1] - win.index[0]).days if len(win) else 0
    out.update(from_date=lo_day.date().isoformat(), n=len(win), span_days=span)
    if len(win) < MIN_DAYS or span < MIN_SPAN:
        out.update(rate=None, verdict="wenig_daten",
                   label=f"Noch kein Urteil: mindestens {MIN_DAYS} Wiegungen über {MIN_SPAN} Tage nötig")
        return out
    tr = stats.linear_trend([(d - win.index[0]).days for d in win.index], list(win.values))
    if tr is None:
        out.update(rate=None, verdict="wenig_daten", label="Noch kein Urteil")
        return out
    mean = float(win.mean())
    pct, ci = tr["slope_per_week"] / mean * 100, tr["ci_per_week"] / mean * 100
    out["rate"] = {"kg_per_week": round(tr["slope_per_week"], 3), "ci_kg": round(tr["ci_per_week"], 3),
                   "pct_per_week": round(pct, 3), "ci_pct": round(ci, 3),
                   "pct_per_month": round(pct * WEEKS_PER_MONTH, 2), "weight": round(mean, 2)}
    out["zone"] = zone_of(pct)
    if not current:
        out.update(verdict="keine_phase", label=out["zone"]["label"])
        return out
    lo, hi = current["rate_min_pct"], current["rate_max_pct"]
    if lo <= pct <= hi:
        verdict, certain = "im", lo <= pct - ci and pct + ci <= hi
    else:
        verdict = "below" if pct < lo else "above"
        certain = (pct + ci < lo) if verdict == "below" else (pct - ci > hi)
    words = _LABELS[current["kind"]]
    label = "im Korridor" if verdict == "im" else words[verdict]
    if not certain:
        label = f"{label} (noch unsicher)" if verdict == "im" else f"eher {label} (noch unsicher)"
    out.update(verdict=verdict, certain=bool(certain), label=label)
    if verdict != "im":
        # Kalorien-Hinweis: Abstand zur Korridormitte, 7.700 kcal je kg
        gap_kg = ((lo + hi) / 2 - pct) / 100 * mean
        out["kcal_per_day"] = int(round(gap_kg * KCAL_PER_KG / 7 / 10) * 10)
    return out
