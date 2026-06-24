"""Ernährungs-Metriken aus FDDB: Kalorien + Makros (Protein/Kohlenhydrate/Fett).
Protein-Ziel relativ zum Körpergewicht (g/kg). Reine Funktionen über die DB —
speisen REST + Coach + MCP. (Makros liegen vollständig in nutrition_entries vor.)"""
from __future__ import annotations

import pandas as pd

from ..db import engine
from . import body

PROTEIN_PER_KG = 1.8  # Standard-Zielwert (Muskelerhalt im Defizit)


def _read(sql: str, **kw) -> pd.DataFrame:
    with engine.connect() as con:
        return pd.read_sql(sql, con, **kw)


def _daily() -> pd.DataFrame:
    """Tagessummen je Makro + kcal (über alle Einträge eines Tages)."""
    df = _read(
        "SELECT eaten_at, kcal, protein_g, carb_g, fat_g FROM nutrition_entries",
        parse_dates=["eaten_at"],
    )
    if df.empty:
        return df
    g = df.groupby(df["eaten_at"].dt.floor("D"))[["kcal", "protein_g", "carb_g", "fat_g"]].sum()
    g.index.name = "day"
    return g.reset_index().sort_values("day")


def protein_target() -> float | None:
    """Protein-Zielmenge (g) = g/kg × stabiles Körpergewicht (7-Tage-Mittel)."""
    summ = body.summary()
    w = summ.get("weight_avg7") or summ.get("weight_kg")
    return round(float(w) * PROTEIN_PER_KG) if w else None


def daily(days: int = 30) -> list[dict]:
    df = _daily()
    if df.empty:
        return []
    cutoff = df["day"].max() - pd.Timedelta(days=days)
    df = df[df["day"] >= cutoff]
    return [
        {"date": d.date().isoformat(), "kcal": round(float(k)), "protein": round(float(p)),
         "carb": round(float(c)), "fat": round(float(f))}
        for d, k, p, c, f in zip(df["day"], df["kcal"], df["protein_g"], df["carb_g"], df["fat_g"])
    ]


def protein_trend(days: int = 30) -> list[dict]:
    """Protein je Tag + 7-Tage-Mittel (kalenderbasiert)."""
    df = _daily()
    if df.empty:
        return []
    s = df.set_index("day")["protein_g"].sort_index()
    avg = s.rolling("7D").mean()
    cutoff = s.index.max() - pd.Timedelta(days=days)
    return [
        {"date": d.date().isoformat(), "protein": round(float(v)), "avg7": round(float(a))}
        for d, v, a in zip(s.index, s.to_numpy(), avg.to_numpy()) if d >= cutoff
    ]


def kcal_trend(days: int = 30) -> list[dict]:
    """Kalorien je Tag + 7-Tage-Mittel."""
    df = _daily()
    if df.empty:
        return []
    s = df.set_index("day")["kcal"].sort_index()
    avg = s.rolling("7D").mean()
    cutoff = s.index.max() - pd.Timedelta(days=days)
    return [
        {"date": d.date().isoformat(), "kcal": round(float(v)), "avg7": round(float(a))}
        for d, v, a in zip(s.index, s.to_numpy(), avg.to_numpy()) if d >= cutoff
    ]


def summary() -> dict:
    df = _daily()
    if df.empty:
        return {"days": 0, "last_day": None, "kcal_today": None, "protein_today": None,
                "protein_avg7": None, "protein_target": None, "protein_per_kg": PROTEIN_PER_KG,
                "kcal_avg7": None, "tdee": None, "macro_split": None, "macro_g": None,
                "on_target_days_7": None}
    target = protein_target()
    s = df.set_index("day").sort_index()
    last_day = s.index.max()
    w7 = s[s.index > last_day - pd.Timedelta(days=7)]
    p, c, f = float(w7["protein_g"].mean()), float(w7["carb_g"].mean()), float(w7["fat_g"].mean())
    pk, ck, fk = p * 4, c * 4, f * 9
    tot = pk + ck + fk or 1.0
    last = s.iloc[-1]
    on_target = int((w7["protein_g"] >= target).sum()) if target else None
    return {
        "days": int(len(df)),
        "last_day": last_day.date().isoformat(),
        "kcal_today": round(float(last["kcal"])),
        "protein_today": round(float(last["protein_g"])),
        "protein_avg7": round(p),
        "protein_target": target,
        "protein_per_kg": PROTEIN_PER_KG,
        "kcal_avg7": round(float(w7["kcal"].mean())),
        "tdee": body.adaptive_tdee().get("tdee"),
        "macro_split": {"protein": round(pk / tot * 100), "carb": round(ck / tot * 100), "fat": round(fk / tot * 100)},
        "macro_g": {"protein": round(p), "carb": round(c), "fat": round(f)},
        "on_target_days_7": on_target,
    }
