"""Gemeinsame Ausdauerlast über Lauf + Rad: TRIMP je Einheit, Fitness (CTL) / Ermüdung (ATL) / Form (TSB).

PULSBASIERT, EINE SKALA: Beide Sportarten laufen durch dieselbe Banister-Formel wie
`running.trimp_weekly` (Dauer × HFR × 0,64·e^(1,92·HFR)). Watt-TSS (`cycling._with_load`) fließt NIE
ein — auch nicht als Ersatz für Fahrten ohne gültigen Puls: solche Einheiten bekommen keine Last und
stehen unter `unrated` (Skalen von Watt-TSS und Puls-TRIMP sind nicht vergleichbar). Kraft bleibt außen vor.

Referenzen: HFmax wie beim Laufen (`running._resolved_hr_max`, Einstellung `run_hr_max`), Ruhepuls =
Median `resting_hr_daily` der letzten 90 Werte, sonst 60. (`trimp_weekly` nimmt als HFmax das beobachtete
Maximum — hier gilt bewusst die Einstellung, damit Lauf und Rad dieselbe feste Skala haben.)

CTL/ATL = exponentiell gewichtete Mittel der Tageslast (Zeitkonstanten 42/7 Tage, Tage ohne Einheit = 0):
    x_t = x_(t-1) + (Last_t − x_(t-1)) / τ
TSB (Form) eines Tages = CTL − ATL vom VORTAG-Abend (TrainingPeaks-Konvention: „wie frisch starte ich in
diesen Tag"), unabhängig von der Last des Tages selbst. CTL/ATL der Zeile gelten am Tagesende.

Reine Last-Kennzahlen — bewusst KEIN besser/schlechter-Urteil (wie TRIMP in stats.py/„Erweiterungen V“).
Ebenfalls hier: Fahrten als Trainingstage (`ride_sessions`) für Heatmap, Wochenvergleich, Aktivitätsliste."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ..config import settings
from . import cycling, health, running
from .cycling import _clean

CTL_DAYS = 42
ATL_DAYS = 7
BANISTER_A, BANISTER_B = 0.64, 1.92
MIN_OUTDOOR_RIDE_MIN = 20  # kürzere Outdoor-Fahrten (Pendelwege) sind kein Trainingstag


def _today(today: date | None) -> date:
    return today or datetime.now(ZoneInfo(settings.timezone)).date()


def _reference() -> dict:
    """HFmax (Einstellung vor Datenableitung) und Ruhepuls (Median 90 Werte, Fallback 60)."""
    hr_max, source = running._resolved_hr_max(running._runs())
    rest_df = running._read("SELECT bpm FROM resting_hr_daily ORDER BY day DESC LIMIT 90")
    hr_rest = float(rest_df["bpm"].median()) if not rest_df.empty else 60.0
    return {"hr_rest": hr_rest, "hr_max": float(hr_max), "hr_max_source": source}


def banister(minutes: float, avg_hr: float, hr_rest: float, hr_max: float) -> float:
    """Banister-TRIMP einer Einheit (Formel wie `running.trimp_weekly`)."""
    hrr = min(1.0, max(0.0, (avg_hr - hr_rest) / max(hr_max - hr_rest, 1.0)))
    return float(minutes * hrr * BANISTER_A * math.exp(BANISTER_B * hrr))


def _sessions(ref: dict) -> pd.DataFrame:
    """Lauf + Indoor-Fahrten als Zeilen {started_at, day, sport, minutes, avg_hr, trimp, activity_id, note}.
    trimp ist NaN ohne gültigen Puls (Läufe: kein Ø-HF; Fahrten: hr_valid false oder kein Ø-HF)."""
    rows: list[dict] = []
    for r in running._runs().itertuples():
        hr = r.avg_hr if pd.notna(r.avg_hr) and r.avg_hr > 0 else None
        rows.append({"started_at": r.started_at, "sport": "run", "minutes": float(r.dur_min), "avg_hr": hr,
                     "activity_id": None, "note": None if hr else "kein Puls"})
    for r in cycling.indoor_rides().itertuples():
        valid = bool(r.hr_valid) and pd.notna(r.avg_hr) and r.avg_hr > 0
        seconds = r.duration_seconds if pd.notna(r.duration_seconds) else r.elapsed_duration_seconds
        if pd.isna(seconds):
            continue
        rows.append({"started_at": r.started_at, "sport": "bike", "minutes": float(seconds) / 60,
                     "avg_hr": float(r.avg_hr) if valid else None, "activity_id": r.activity_id,
                     "note": None if valid else "kein gültiger Puls"})
    df = pd.DataFrame(rows, columns=["started_at", "sport", "minutes", "avg_hr", "activity_id", "note"])
    df["started_at"] = pd.to_datetime(df["started_at"])
    df["avg_hr"] = df["avg_hr"].astype(float)
    df["trimp"] = [banister(m, h, ref["hr_rest"], ref["hr_max"]) if pd.notna(h) else np.nan
                   for m, h in zip(df["minutes"], df["avg_hr"])]
    df["day"] = df["started_at"].dt.date
    return df.sort_values("started_at").reset_index(drop=True)


def _label(tsb: float | None) -> str | None:
    if tsb is None:
        return None
    return "ausgeruht" if tsb > 0 else "belastet" if tsb < 0 else "ausgeglichen"


def fitness(days: int = 180, today: date | None = None) -> dict:
    """CTL/ATL/TSB je Tag (letzte `days` Tage bis heute), Lauf/Rad-Anteil je Woche, Einheiten mit TRIMP.
    Die Berechnung startet am ersten Tag mit Last (Aufwärmphase: CTL braucht ~6 Wochen, `history_days`)."""
    today = _today(today)
    ref = _reference()
    df = _sessions(ref)
    df = df[df["day"] <= today] if not df.empty else df
    rated = df[df["trimp"].notna()] if not df.empty else df
    out = {"days": days, "ctl_days": CTL_DAYS, "atl_days": ATL_DAYS, "hr_rest": round(ref["hr_rest"]),
           "hr_max": round(ref["hr_max"]), "hr_max_source": ref["hr_max_source"], "history_days": 0,
           "today": None, "series": [], "weeks": [], "sessions": [],
           "unrated": {"runs": 0, "rides": 0},
           "caveat": "Pulsbasierte Last (Banister-TRIMP) über Lauf + Rad; Kraft und Watt-TSS zählen nicht. "
                     "Fahrten/Läufe ohne gültigen Puls haben keine Last. Reine Last-Kennzahl, kein Urteil. "
                     "CTL/ATL starten bei 0 am ersten Lasttag — die ersten ~6 Wochen sind unterschätzt."}
    if rated.empty:
        out["unrated"] = _unrated(df, today - timedelta(days=days - 1))
        return _clean(out)

    daily = rated.groupby("day")["trimp"].sum()
    first = min(daily.index)
    ctl = atl = 0.0
    rows: list[dict] = []
    for i in range((today - first).days + 1):
        d = first + timedelta(days=i)
        load = float(daily.get(d, 0.0))
        tsb = ctl - atl  # Vortag-Abend
        ctl += (load - ctl) / CTL_DAYS
        atl += (load - atl) / ATL_DAYS
        rows.append({"date": d.isoformat(), "load": round(load, 1), "ctl": round(ctl, 1),
                     "atl": round(atl, 1), "tsb": round(tsb, 1)})
    start = today - timedelta(days=days - 1)
    series = [r for r in rows if r["date"] >= start.isoformat()]
    last = rows[-1]
    out.update({
        "history_days": len(rows), "series": series,
        "today": {**last, "form": _label(last["tsb"]), "has_load_today": last["load"] > 0},
        "weeks": _weeks(df, start), "unrated": _unrated(df, start),
        "sessions": [{"date": r.started_at.isoformat(), "sport": r.sport, "minutes": round(r.minutes, 1),
                      "avg_hr": None if pd.isna(r.avg_hr) else round(float(r.avg_hr)),
                      "trimp": None if pd.isna(r.trimp) else round(float(r.trimp), 1),
                      "activity_id": r.activity_id, "note": r.note}
                     for r in df[df["day"] >= start].itertuples()],
    })
    return _clean(out)


def _unrated(df: pd.DataFrame, start: date) -> dict:
    if df.empty:
        return {"runs": 0, "rides": 0}
    window = df[(df["day"] >= start) & df["trimp"].isna()]
    return {"runs": int((window["sport"] == "run").sum()), "rides": int((window["sport"] == "bike").sum())}


def _weeks(df: pd.DataFrame, start: date) -> list[dict]:
    """Last je ISO-Woche (Mo–So) getrennt nach Lauf/Rad + Lauf-Anteil; Wochen ab der Woche von `start`."""
    window = df[df["day"] >= start].copy()
    if window.empty:
        return []
    window["week"] = window["started_at"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())
    out = []
    for week, grp in sorted(window.groupby("week"), key=lambda kv: kv[0]):
        run = float(grp.loc[grp["sport"] == "run", "trimp"].sum())
        bike = float(grp.loc[grp["sport"] == "bike", "trimp"].sum())
        total = run + bike
        out.append({"week": week.isoformat(), "run": round(run, 1), "bike": round(bike, 1),
                    "total": round(total, 1), "run_share": round(run / total * 100, 1) if total > 0 else None,
                    "runs": int(((grp["sport"] == "run") & grp["trimp"].notna()).sum()),
                    "rides": int(((grp["sport"] == "bike") & grp["trimp"].notna()).sum()),
                    "unrated": int(grp["trimp"].isna().sum())})
    return out


# ---------------- Fahrten als Trainingstage ----------------
def ride_sessions() -> pd.DataFrame:
    """Alle Fahrten, die als Training zählen: Indoor-Fahrten (alle) + Outdoor-Fahrten (HC/Garmin)
    ab MIN_OUTDOOR_RIDE_MIN Minuten. Spalten: started_at, day, minutes, kind (indoor|outdoor), title.
    Nur Zählung/Anzeige — mit Last hat das nichts zu tun (siehe `fitness`)."""
    rows: list[dict] = []
    for r in cycling.indoor_rides().itertuples():
        seconds = r.duration_seconds if pd.notna(r.duration_seconds) else r.elapsed_duration_seconds
        rows.append({"started_at": r.started_at, "minutes": float(seconds) / 60 if pd.notna(seconds) else 0.0,
                     "kind": "indoor", "title": r.title or "Rad"})
    outdoor = health._rides()
    if not outdoor.empty:
        for r in outdoor[outdoor["dur_min"] >= MIN_OUTDOOR_RIDE_MIN].itertuples():
            rows.append({"started_at": r.started_at, "minutes": float(r.dur_min), "kind": "outdoor", "title": "Rad"})
    df = pd.DataFrame(rows, columns=["started_at", "minutes", "kind", "title"])
    df["started_at"] = pd.to_datetime(df["started_at"])
    df["day"] = df["started_at"].dt.date
    return df.sort_values("started_at").reset_index(drop=True)


def ride_window(start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Fahrten und Minuten im Fenster [start, end)."""
    df = ride_sessions()
    part = df[(df["started_at"] >= start) & (df["started_at"] < end)] if not df.empty else df
    return {"sessions": int(len(part)), "minutes": round(float(part["minutes"].sum()), 0) if len(part) else 0.0}
