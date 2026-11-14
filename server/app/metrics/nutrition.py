"""Ernährungs-Metriken aus dem Ernährungstagebuch (BISS, davor FDDB): Kalorien + Makros.
Protein-Ziel relativ zum Körpergewicht (g/kg). Reine Funktionen über die DB —
speisen REST + Coach + MCP."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import text

from ..config import settings
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


# ---- Makros heute, Lieblingslebensmittel, Mahlzeiten -------------------------------------------

MACROS = {"protein": "protein_g", "carb": "carb_g", "fat": "fat_g"}
MEALS = (("breakfast", "Frühstück"), ("lunch", "Mittag"), ("snack", "Snack"), ("dinner", "Abend"))
# FDDB writes the amount in front of the name ("25 g Corny Big", "1 Portion Cappuccino").
_AMOUNT = re.compile(r"^[\d.,/]+\s*(?:g|ml|kg|l|Portion\w*|Stück\w*|Scheiben?|Becher|Glas|Gläser|Tassen?|EL|TL|"
                     r"Riegel|Dosen?|Flaschen?|Packung\w*|Tafeln?|Kugeln?)\s+", re.IGNORECASE)
_COLS = ["kcal", "protein_g", "carb_g", "fat_g"]


def macro_trend(macro: str, days: int = 30) -> list[dict]:
    """Protein, Kohlenhydrate oder Fett je Kalendertag + 7-Tage-Mittel."""
    return _trend(MACROS[macro], "value", days)


def _now() -> datetime:
    return datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None)


def _entries(days: int) -> pd.DataFrame:
    cutoff = (_now() - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    df = _read(text("SELECT eaten_at, description, kcal, protein_g, carb_g, fat_g, source, meal, brand "
                    "FROM nutrition_entries WHERE eaten_at >= :cutoff"),
               params={"cutoff": cutoff}, parse_dates=["eaten_at"])
    df["day"] = pd.to_datetime(df["eaten_at"]).dt.floor("D")  # to_datetime: an empty result has no dtype
    return df


def _food_name(description, source) -> str:
    name = (description or "").strip() or "Ohne Namen"
    return _AMOUNT.sub("", name, count=1) if source == "fddb" else name


def _pack(values) -> dict:
    return {"kcal": _rounded(values["kcal"]), "protein": _rounded(values["protein_g"]),
            "carb": _rounded(values["carb_g"]), "fat": _rounded(values["fat_g"])}


def today() -> dict:
    """Makros des laufenden Tages gegen die Ziele des Tagebuchs, dazu das Mittel der 7 Tage davor.
    Mit BISS endet der Tag wie dort erst um 04:00 Uhr."""
    now = _now() - timedelta(hours=4 if settings.nutrition_source == "biss" else 0)
    day = pd.Timestamp(now.date())
    df = _entries(7)
    cur = df[df["day"] == day]
    tot = {c: float(cur[c].sum()) for c in _COLS}
    prev = df[df["day"] < day].groupby("day")[_COLS].sum()
    goal = _read(text("SELECT kcal, protein_g, carb_g, fat_g FROM nutrition_goals WHERE day <= :d "
                      "ORDER BY day DESC LIMIT 1"), params={"d": day.date().isoformat()})
    energy = {"protein": tot["protein_g"] * 4, "carb": tot["carb_g"] * 4, "fat": tot["fat_g"] * 9}
    total = sum(energy.values())
    return {
        "date": day.date().isoformat(),
        "source": settings.nutrition_source,
        "entries": int(len(cur)),
        "last_entry": cur["eaten_at"].max().strftime("%H:%M") if not cur.empty else None,
        **_pack(tot),
        "goal": _pack(goal.iloc[0]) if not goal.empty else None,
        "protein_target": protein_target(),
        "avg7": _pack(prev.mean()) if not prev.empty else None,
        "avg7_days": int(len(prev)),
        "split": {k: round(v / total * 100) for k, v in energy.items()} if total > 0 else None,
    }


def foods(days: int = 30, limit: int = 8) -> dict:
    """Was am häufigsten gegessen wird und woher Protein, Kohlenhydrate, Fett und Kalorien kommen."""
    df = _entries(days)
    if df.empty:
        return {"days": days, "recorded_days": 0, "favorites": [], "protein": [], "carb": [], "fat": [], "kcal": []}
    df["name"] = [_food_name(d, s) for d, s in zip(df["description"], df["source"])]
    g = df.groupby("name").agg(count=("name", "size"), days=("day", "nunique"), brand=("brand", "first"),
                               **{c: (c, "sum") for c in _COLS}).reset_index()
    totals = {c: float(df[c].sum()) for c in _COLS}

    def top(column: str | None) -> list[dict]:
        order = g.sort_values(["count", "kcal"] if column is None else [column], ascending=False).head(limit)
        return [{
            "name": r["name"], "brand": r["brand"] if isinstance(r["brand"], str) else None,
            "count": int(r["count"]), "days": int(r["days"]), **_pack(r),
            "share": round(float(r[column]) / totals[column] * 100) if column and totals[column] > 0 else None,
        } for _, r in order.iterrows() if column is None or r[column] > 0]

    return {"days": days, "recorded_days": int(df["day"].nunique()), "favorites": top(None),
            "protein": top("protein_g"), "carb": top("carb_g"), "fat": top("fat_g"), "kcal": top("kcal")}


def meals(days: int = 30) -> dict:
    """Ø je Mahlzeit und erfasstem Tag (nur BISS kennt die Mahlzeit)."""
    df = _entries(days)
    df = df[df["meal"].notna()]
    if df.empty:
        return {"days": days, "recorded_days": 0, "meals": []}
    n = int(df["day"].nunique())
    g = df.groupby("meal")[_COLS].sum()
    protein_total = float(g["protein_g"].sum())
    return {"days": days, "recorded_days": n, "meals": [
        {"meal": key, "label": label, **_pack(g.loc[key] / n),
         "protein_share": round(float(g.loc[key, "protein_g"]) / protein_total * 100) if protein_total > 0 else None}
        for key, label in MEALS if key in g.index]}
