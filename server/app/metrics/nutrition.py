"""Ernährungs-Metriken aus FDDB: Kalorien + Makros (Protein/Kohlenhydrate/Fett).
Protein-Ziel relativ zum Körpergewicht (g/kg). Reine Funktionen über die DB —
speisen REST + Coach + MCP."""
from __future__ import annotations

import pandas as pd

from ..db import engine
from . import body

PROTEIN_PER_KG = 1.8  # Existing reference target, not an individual prescription.


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
    g = df.groupby(df["eaten_at"].dt.floor("D"))[["kcal", "protein_g", "carb_g", "fat_g"]].sum(min_count=1)
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
        {"date": d.date().isoformat(), "kcal": _rounded(k), "protein": _rounded(p),
         "carb": _rounded(c), "fat": _rounded(f)}
        for d, k, p, c, f in zip(df["day"], df["kcal"], df["protein_g"], df["carb_g"], df["fat_g"])
    ]


def _rounded(value: float) -> int | None:
    return round(float(value)) if pd.notna(value) else None


def _trend(column: str, key: str, days: int) -> list[dict]:
    df = _daily()
    if df.empty:
        return []
    s = df.set_index("day")[column].sort_index().asfreq("D")
    avg = s.rolling("7D").mean()
    counts = s.rolling("7D").count()
    cutoff = s.index.max() - pd.Timedelta(days=days)
    return [
        {"date": d.date().isoformat(), key: _rounded(v), "avg7": _rounded(a), "days7": int(n)}
        for d, v, a, n in zip(s.index, s.to_numpy(), avg.to_numpy(), counts.to_numpy()) if d >= cutoff
    ]


def protein_trend(days: int = 30) -> list[dict]:
    """Protein je Kalendertag + Mittel der erfassten Werte im 7-Tage-Fenster."""
    return _trend("protein_g", "protein", days)


def kcal_trend(days: int = 30) -> list[dict]:
    """Kalorien je Kalendertag + Mittel der erfassten Werte im 7-Tage-Fenster."""
    return _trend("kcal", "kcal", days)


def summary() -> dict:
    df = _daily()
    if df.empty:
        return {"days": 0, "last_day": None, "kcal_today": None, "protein_today": None,
                "protein_avg7": None, "protein_target": None, "protein_per_kg": PROTEIN_PER_KG,
                "kcal_avg7": None, "tdee": None, "macro_split": None, "macro_g": None,
                "on_target_days_7": None, "window_start": None,
                "recorded_days_7": 0, "protein_days_7": 0, "kcal_days_7": 0}
    target = protein_target()
    s = df.set_index("day").sort_index()
    last_day = s.index.max()
    w7 = s[s.index > last_day - pd.Timedelta(days=7)]
    p, c, f = float(w7["protein_g"].mean()), float(w7["carb_g"].mean()), float(w7["fat_g"].mean())
    macro_split = None
    if all(pd.notna(value) for value in (p, c, f)):
        pk, ck, fk = p * 4, c * 4, f * 9
        tot = pk + ck + fk
        if tot > 0:
            macro_split = {"protein": round(pk / tot * 100), "carb": round(ck / tot * 100), "fat": round(fk / tot * 100)}
    last = s.iloc[-1]
    on_target = int((w7["protein_g"] >= target).sum()) if target and w7["protein_g"].count() else None
    return {
        "days": int(len(df)),
        "last_day": last_day.date().isoformat(),
        "window_start": (last_day - pd.Timedelta(days=6)).date().isoformat(),
        "recorded_days_7": int(len(w7)),
        "protein_days_7": int(w7["protein_g"].count()),
        "kcal_days_7": int(w7["kcal"].count()),
        "kcal_today": _rounded(last["kcal"]),
        "protein_today": _rounded(last["protein_g"]),
        "protein_avg7": _rounded(p),
        "protein_target": target,
        "protein_per_kg": PROTEIN_PER_KG,
        "kcal_avg7": _rounded(w7["kcal"].mean()),
        "tdee": body.adaptive_tdee().get("tdee"),
        "macro_split": macro_split,
        "macro_g": {"protein": _rounded(p), "carb": _rounded(c), "fat": _rounded(f)},
        "on_target_days_7": on_target,
    }
