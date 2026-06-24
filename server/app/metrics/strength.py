"""Kraft-Metriken (ARCHITECTURE.md §5.3): e1RM (Epley), Wochen-Tonnage, RPE-Trend.
Nur Arbeitssätze (set_type='normal')."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..db import engine


def _read(sql: str, **kw) -> pd.DataFrame:
    with engine.connect() as con:
        return pd.read_sql(sql, con, **kw)


def _sets() -> pd.DataFrame:
    df = _read(
        "SELECT ws.exercise, ws.weight_kg, ws.reps, ws.rpe, w.started_at "
        "FROM workout_sets ws JOIN workouts w ON w.id = ws.workout_id "
        "WHERE ws.set_type = 'normal' AND ws.weight_kg IS NOT NULL AND ws.weight_kg > 0 "
        "AND ws.reps IS NOT NULL AND ws.reps > 0",
        parse_dates=["started_at"],
    )
    if not df.empty:
        df["e1rm"] = df["weight_kg"] * (1 + df["reps"] / 30.0)  # Epley
        df["tonnage"] = df["weight_kg"] * df["reps"]
        df["week"] = df["started_at"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())
        df["day"] = df["started_at"].dt.floor("D")
    return df


def main_lifts(limit: int = 6) -> list[dict]:
    """Häufigste Hauptübungen mit aktuellem Top-e1RM (bester Arbeitssatz der letzten Session)."""
    df = _sets()
    if df.empty:
        return []
    counts = df.groupby("exercise").size().sort_values(ascending=False).head(limit)
    out = []
    for ex in counts.index:
        sub = df[df["exercise"] == ex]
        last_day = sub["day"].max()
        cur = round(float(sub[sub["day"] == last_day]["e1rm"].max()), 1)
        peak = round(float(sub["e1rm"].max()), 1)
        out.append({"exercise": ex, "e1rm": cur, "peak": peak, "sets": int(counts[ex])})
    return out


def e1rm_trend(exercise: str, weeks: int = 26) -> list[dict]:
    df = _sets()
    if df.empty:
        return []
    sub = df[df["exercise"] == exercise]
    if sub.empty:
        return []
    g = sub.groupby("day")["e1rm"].max().reset_index().sort_values("day").tail(weeks * 3)
    return [{"date": d.date().isoformat(), "e1rm": round(float(v), 1)} for d, v in zip(g["day"], g["e1rm"])]


_PERIODS = {"1m": 1, "3m": 3, "12m": 12, "all": None}

_INDEX_MONTHS = {"1m": 1, "3m": 3, "6m": 6, "12m": 12}  # Fenster für Δ/Trend (aus dem Monats-Backbone)
_IDX_CLIP = 0.25     # Log-Return-Cap je Übung (Ausreißer-Schutz, = validierter Backbone)
_IDX_KAPPA = 1.0     # Skalierung der Intra-Monats-Auslenkung (1.0 = volle Amplitude)
_IDX_ALPHA = 0.25    # kausale EWMA-Glättung der Wochen-Anzeige (roughness ~1.0)


def _idx_weights(cohort: list, mg_of: dict) -> dict:
    """Muskelgruppen-balancierte Gewichte (1/G)*(1/n_g), renormiert auf Σ=1.
    Verhindert, dass viele Isolations-Übungen einer Gruppe die 'Gesamtstärke' dominieren."""
    groups: dict = {}
    for e in cohort:
        groups.setdefault(mg_of[e], []).append(e)
    G = len(groups)
    w = {e: (1.0 / G) * (1.0 / len(exs)) for exs in groups.values() for e in exs}
    tot = sum(w.values())
    return {e: x / tot for e, x in w.items()}


def _monthly_backbone(df: pd.DataFrame):
    """VALIDIERTE Monats-Verkettung (Endwert ~114) als drift-freies Rückgrat des Wochen-Index.
    Jeder Link = muskel-balanciertes geometrisches Mittel der e1RM-Log-Ratios über die in BEIDEN
    Monaten trainierten Übungen (löst Übungs-Rotation). 13 Links → kein Chain-Drift.
    Liefert (raw{Period:val}, basket{Period:{ex:(mg,e1rm)}}, months[list], contrib{Period:{ex:w*r}})."""
    sess = df.groupby(["exercise", "mg", "day", "month"])["e1rm_c"].max().reset_index()
    monthly = sess.groupby(["exercise", "mg", "month"])["e1rm_c"].max().reset_index()
    months = sorted(monthly["month"].unique())
    basket = {m: {r.exercise: (r.mg, float(r.e1rm_c)) for r in monthly[monthly["month"] == m].itertuples()}
              for m in months}
    raw = {months[0]: 100.0}
    contrib: dict = {}
    for a, b in zip(months[:-1], months[1:]):
        A, B = basket[a], basket[b]
        cohort = [e for e in B if e in A]
        if len(cohort) < 3:
            raw[b] = raw[a]; contrib[b] = {}; continue
        w = _idx_weights(cohort, {e: B[e][0] for e in cohort})
        c = {e: w[e] * max(-_IDX_CLIP, min(_IDX_CLIP, math.log(B[e][1] / A[e][1]))) for e in cohort}
        raw[b] = raw[a] * math.exp(sum(c.values())); contrib[b] = c
    return raw, basket, months, contrib


def strength_index(period: str = "3m") -> dict:
    """Gesamtstärke-Index (Basis 100 = Trainingsstart), WÖCHENTLICH aufgelöst & DRIFT-FREI.
    Hybrid (per Methoden-Panel an echten Daten validiert): der validierte monatliche Kettenindex
    bleibt unverändertes Rückgrat (13 Links, Endwert ~114). Wochenauflösung entsteht NICHT durch
    Woche-zu-Woche-Verkettung (das driftet auf ~168), sondern indem jede Woche DIREKT gegen ihren
    eigenen Monatskorb gemessen wird (kein zusätzlicher Ketten-Link → kein Pfad → kein Drift).
    Per-Monat-Re-Zentrierung pinnt den Monatsschnitt der Wochen auf den Backbone-Anker (killt den
    MAX-pro-Bucket-Bias). Δ%/Trend kommen aus dem Backbone über die Fenster-Monate (konsistent zur
    Basis 100, drift-frei); die Wochenkurve liefert die Auflösung. e1RM Epley
    rep-gekappt (≤12), Log-Returns auf ±0.25 geclippt, nur Übungen mit ≥3 Trainingstagen."""
    df = _sets()
    if df.empty:
        return {}
    df = df.copy()
    df["e1rm_c"] = df["weight_kg"] * (1 + df["reps"].clip(upper=12) / 30.0)  # Epley, rep-gekappt
    df["month"] = df["started_at"].dt.to_period("M")
    df["mg"] = df["exercise"].map(_muscle_group)

    elig = df.groupby("exercise")["day"].nunique()
    df = df[df["exercise"].isin(set(elig[elig >= 3].index))]
    if df.empty:
        return {}

    # --- 1) Monats-Backbone (UNVERÄNDERT validiert) ---
    raw_monthly, basket, months, m_contrib = _monthly_backbone(df)
    if len(months) < 2:
        return {}
    last_m = months[-1]

    # --- 2) Wochen-Best-e1RM + Anker-Monat (Wochenmitte = Donnerstag) ---
    wk = df.groupby(["exercise", "mg", "week"])["e1rm_c"].max().reset_index()
    weeks = sorted(wk["week"].unique())
    if len(weeks) < 2:
        return {}
    week_basket = {w: {r.exercise: (r.mg, float(r.e1rm_c)) for r in wk[wk["week"] == w].itertuples()}
                   for w in weeks}
    week_month = {w: pd.Period(pd.Timestamp(w) + pd.Timedelta(days=3), freq="M") for w in weeks}

    # Monatsanker linear aufs Wochenraster (laufender Monat flach geklemmt)
    an_dates = np.array([pd.Timestamp(year=m.start_time.year, month=m.start_time.month, day=15).toordinal()
                         for m in months], dtype=float)
    an_vals = np.array([raw_monthly[m] for m in months], dtype=float)
    wk_ord = np.array([pd.Timestamp(w).toordinal() for w in weeks], dtype=float)
    anchor_by_week = dict(zip(weeks, np.interp(wk_ord, an_dates, an_vals, left=an_vals[0], right=an_vals[-1])))

    # --- 3) Wochen-Offset DIREKT gegen den eigenen Monatskorb (keine Woche-zu-Woche-Verkettung) ---
    raw_offset: dict = {}
    for w in weeks:
        Bm = basket.get(week_month[w])
        Ww = week_basket[w]
        if Bm is None:
            raw_offset[w] = None
            continue
        cohort = [e for e in Ww if e in Bm]
        if len(cohort) < 3:
            raw_offset[w] = None
            continue
        wts = _idx_weights(cohort, {e: Ww[e][0] for e in cohort})
        raw_offset[w] = sum(wts[e] * max(-_IDX_CLIP, min(_IDX_CLIP, math.log(Ww[e][1] / Bm[e][1])))
                            for e in cohort)

    # --- 4) Re-Zentrierung pro Anker-Monat (Drift-Killer): Monatsschnitt der Wochen == Anker ---
    by_m: dict = {}
    for w in weeks:
        by_m.setdefault(week_month[w], []).append(w)
    weekly_raw: dict = {}
    for m, ws in by_m.items():
        offs = [raw_offset[w] for w in ws if raw_offset[w] is not None]
        mu = float(np.mean(offs)) if offs else 0.0
        for w in ws:
            weekly_raw[w] = (np.nan if raw_offset[w] is None
                             else anchor_by_week[w] * math.exp(_IDX_KAPPA * (raw_offset[w] - mu)))

    # --- 5) Lücken/thin: Interpolation im Log-Raum; kausale EWMA für die Anzeige ---
    s = pd.Series(weekly_raw).reindex(weeks).astype(float)
    s = np.exp(np.log(s).interpolate(limit=2)).ffill().bfill()
    smoothed = s.ewm(alpha=_IDX_ALPHA, adjust=False).mean()
    # Edge-Case: alle Wochen thin (cohort<3) → NaN-Kurve. Auf den Backbone-Anker zurückfallen
    # (nie HTTP 500); value/Δ kommen ohnehin aus dem Backbone.
    anchor_s = pd.Series(anchor_by_week)
    s = s.where(np.isfinite(s), anchor_s)
    smoothed = smoothed.where(np.isfinite(smoothed), anchor_s)

    # --- 6) value / Δ% / Trend / Treiber aus dem drift-freien Monats-Backbone (= validierter
    # Monatsindex, reproduziert dessen Zahlen exakt). Die Wochenkurve oben liefert nur die Auflösung;
    # so sind value, 'Basis 100' und Δ konsistent (kein 12M-Δ gegen die verrauschte erste Woche). ---
    rawv = [raw_monthly[m] for m in months]
    disp = [rawv[0]] + [(rawv[i] + rawv[i - 1]) / 2 for i in range(1, len(rawv))]  # 2-Pkt-Glättung
    n_mo = _INDEX_MONTHS.get(period, 3)
    target = last_m - n_mo
    base_i = 0
    for i, m in enumerate(months):
        if m <= target:
            base_i = i
    delta = (disp[-1] / disp[base_i] - 1) * 100 if disp[base_i] else 0.0
    trend = "steigt" if delta >= 3 else "faellt" if delta <= -3 else "stagniert"

    drv: dict = {}
    for i in range(base_i + 1, len(months)):
        for e, v in m_contrib.get(months[i], {}).items():
            drv[e] = drv.get(e, 0.0) + v
    ordered = sorted(drv.items(), key=lambda kv: kv[1], reverse=True)

    def as_driver(e: str, val: float) -> dict:
        return {"exercise": e, "muscle": _muscle_group(e), "pct": round((math.exp(val) - 1) * 100, 1)}

    # cohort/groups = aktiver Roster des letzten Monats (welche Übungen speisen den Index aktuell)
    active = basket.get(last_m, {})
    return {
        "value": round(disp[-1]),
        "base_week": str(pd.Timestamp(weeks[0]).date()),  # Trainingsstart (Basis 100)
        "period": period,
        "window_delta_pct": round(delta, 1),
        "trend": trend,
        "series": [{"week": str(pd.Timestamp(w).date()),
                    "raw": round(float(s.loc[w]), 1),
                    "smoothed": round(float(smoothed.loc[w]), 1),
                    "anchor": round(float(anchor_by_week[w]), 1)}
                   for w in weeks],
        "drivers_up": [as_driver(e, v) for e, v in ordered[:3] if v > 0],
        "drivers_down": [as_driver(e, v) for e, v in ordered[::-1][:3] if v < 0],
        "cohort_size": len(active),
        "groups": len({mg for mg, _ in active.values()}),
    }


def strength_energy() -> dict:
    """Verknüpft den wöchentlichen Gesamtstärke-Index mit TDEE & Defizit (body.tdee_trend),
    wöchentlich aligned. Liefert die Reihen für die Overlay-Grafik + EHRLICHE Kennzahlen:
    die NIVEAU-Korrelation ist trendgetrieben (beide laufen über die Zeit → scheinbar hoch),
    die ENTKOPPELTE Woche-zu-Woche-Korrelation ist der belastbare Wert (~0). Zusätzlich ein
    Phasen-Read der jüngsten Wochen (Cut-Tradeoff / Aufbau / Recomp)."""
    from . import body  # lazy: vermeidet Import-Zyklus

    idx = strength_index("12m")
    if not idx or not idx.get("series"):
        return {}
    si = pd.DataFrame(idx["series"])
    si["week"] = pd.to_datetime(si["week"])
    si = si.set_index("week")["smoothed"].rename("index")

    td = pd.DataFrame(body.tdee_trend(days=400))
    if td.empty:
        return {}
    td["date"] = pd.to_datetime(td["date"])
    td = td.set_index("date").sort_index()
    td["deficit"] = td["tdee_avg"] - td["intake"]            # >0 = Defizit, <0 = Überschuss
    wk = td[["tdee_avg", "deficit"]].resample("W-SUN").mean()
    wk.index = wk.index - pd.Timedelta(days=6)               # Wochenende(So) → Wochenstart(Mo), wie Index

    df = pd.concat([si, wk], axis=1, sort=True).dropna(subset=["index", "tdee_avg"])
    if len(df) < 6:
        return {}

    def _r(a: pd.Series, b: pd.Series):
        av, bv = a.to_numpy(float), b.to_numpy(float)
        m = np.isfinite(av) & np.isfinite(bv)
        if m.sum() < 4 or av[m].std() == 0 or bv[m].std() == 0:
            return None
        return round(float(np.corrcoef(av[m], bv[m])[0, 1]), 2)

    corr_level = _r(df["index"], df["deficit"])              # trendgetrieben (scheinbar)
    corr_change = _r(df["index"].diff(), df["deficit"])      # entkoppelt (belastbar) ~0
    corr_cum = _r(df["index"], (-df["deficit"]).cumsum())    # nur Transparenz (Schein-Trend)

    # Phasen-Read: letzte k Wochen vs. die k davor
    k = min(8, len(df) // 2)
    recent = df.tail(k)
    prior = df.iloc[-2 * k:-k] if len(df) >= 2 * k else df.iloc[:-k]
    idx_delta = round(float(recent["index"].iloc[-1] - recent["index"].iloc[0]), 1)
    def_now = round(float(recent["deficit"].mean()))
    def_prev = round(float(prior["deficit"].mean())) if len(prior) else None
    deepening = def_prev is not None and (def_now - def_prev) > 80

    if idx_delta <= -1.5 and def_now > 100:
        phase, phase_label = "cut", "Cut kostet Kraft"
    elif idx_delta >= 1.5 and def_now > 100:
        phase, phase_label = "recomp", "Recomp – Kraft hält trotz Defizit"
    elif idx_delta >= 1.5 and def_now < 0:
        phase, phase_label = "aufbau", "Aufbau – Überschuss, Kraft steigt"
    else:
        phase, phase_label = "stabil", "Stabil"

    return {
        "n_weeks": int(len(df)),
        "tdee_avg": round(float(df["tdee_avg"].mean())),
        "deficit_avg": round(float(df["deficit"].mean())),
        "corr_index_deficit": corr_level,
        "corr_change_deficit": corr_change,
        "corr_cumulative": corr_cum,
        "recent_weeks": int(k),
        "recent_index_delta": idx_delta,
        "recent_deficit_avg": def_now,
        "prior_deficit_avg": def_prev,
        "deficit_deepening": bool(deepening),
        "phase": phase,
        "phase_label": phase_label,
        "caveat": ("Die Niveau-Korrelation ist trendgetrieben (Index und Energiebilanz laufen beide "
                   "über die Zeit) und überzeichnet den Zusammenhang; entkoppelt (Woche-zu-Woche) ist "
                   "er ~0. Programmwechsel und Trainingsphasen verzerren zusätzlich. Belastbar ist nur "
                   "der Phasen-Read der jüngsten Wochen."),
        "series": [{"week": d.date().isoformat(),
                    "index": round(float(r["index"]), 1),
                    "tdee": round(float(r["tdee_avg"])),
                    "deficit": round(float(r["deficit"]))}
                   for d, r in df.iterrows()],
    }


def personal_records(days: int = 120, limit: int = 25) -> list[dict]:
    """Feed neuer Bestleistungen: je Übung ein PR, wenn der Tages-e1RM ODER das Top-Gewicht
    ein neues Allzeithoch übertrifft (erste Session = Baseline, kein PR). Neueste zuerst."""
    df = _sets()
    if df.empty:
        return []
    recs: list[dict] = []
    for ex, sub in df.groupby("exercise"):
        per_day = sub.groupby("day").agg(e1rm=("e1rm", "max"), top=("weight_kg", "max"),
                                         reps=("reps", "max")).sort_index()
        run_e = run_w = -1.0
        for i, (day, row) in enumerate(per_day.iterrows()):
            e_pr = float(row["e1rm"]) > run_e + 1e-9
            w_pr = float(row["top"]) > run_w + 1e-9
            if e_pr:
                run_e = float(row["e1rm"])
            if w_pr:
                run_w = float(row["top"])
            if i == 0:  # Baseline setzen, nicht als Rekord werten
                continue
            if e_pr or w_pr:
                recs.append({
                    "date": day.date().isoformat(), "exercise": ex, "muscle": _muscle_group(ex),
                    "e1rm": round(float(row["e1rm"]), 1), "top_weight": round(float(row["top"]), 1),
                    "kind": "both" if (e_pr and w_pr) else ("e1rm" if e_pr else "weight"),
                })
    if not recs:
        return []
    cutoff = (pd.Timestamp.now() - pd.Timedelta(days=days)).date().isoformat()
    recs = [r for r in recs if r["date"] >= cutoff]
    recs.sort(key=lambda r: r["date"], reverse=True)
    return recs[:limit]


def exercise_status(exercise: str, lookback: int = 6) -> dict:
    """Algorithmischer Status einer Übung über die letzten `lookback` Sessions:
    progress / stall / regress / deload (e1RM-Steigung + RPE-Steigung)."""
    df = _sets()
    sub = df[df["exercise"] == exercise]
    if sub.empty:
        return {"status": "unknown", "label": "—", "detail": "keine Daten"}
    per_day = sub.groupby("day").agg(e1rm=("e1rm", "max"), rpe=("rpe", "mean")).sort_index()
    n = len(per_day)
    is_pr = float(per_day["e1rm"].iloc[-1]) >= float(per_day["e1rm"].max()) - 1e-9
    if n < 3:
        return {"status": "new", "label": "Zu wenig Daten", "detail": f"erst {n} Session(s)",
                "sessions": n, "is_pr": bool(is_pr)}
    recent = per_day.tail(lookback)
    e_slope = float(np.polyfit(np.arange(len(recent), dtype=float), recent["e1rm"].to_numpy(dtype=float), 1)[0])
    rpe = recent["rpe"].dropna()
    rpe_slope = (float(np.polyfit(np.arange(len(rpe), dtype=float), rpe.to_numpy(dtype=float), 1)[0])
                 if len(rpe) >= 3 else None)

    if is_pr or e_slope > 0.3:
        status, label = "progress", "Im Aufwärtstrend"
    elif e_slope < -0.3:
        status, label = "regress", "Rückläufig"
    else:
        status, label = "stall", "Stagniert"
    detail = f"e1RM {'+' if e_slope >= 0 else ''}{round(e_slope, 2)} kg/Session über {len(recent)} Sessions"
    if status in ("stall", "regress") and rpe_slope is not None and rpe_slope > 0.1:
        status, label = "deload", "Ermüdung – Deload erwägen"
        detail += f", RPE steigt (+{round(rpe_slope, 2)}/Session)"
    return {"status": status, "label": label, "detail": detail,
            "e1rm_slope": round(e_slope, 2), "rpe_slope": round(rpe_slope, 2) if rpe_slope is not None else None,
            "is_pr": bool(is_pr), "sessions": int(n)}


def exercise_detail(exercise: str, period: str = "all") -> dict:
    """Detail-Auswertung EINER Übung über den gewählten Zeitraum (1m/3m/12m/all):
    Eckdaten, Entwicklung (erste vs. letzte Session) und Tagesreihen für Charts
    (e1RM, Top-Gewicht, Tonnage, Wiederholungen, RPE)."""
    df = _sets()
    muscle = _muscle_group(exercise)
    if df.empty:
        return {}
    sub = df[df["exercise"] == exercise].copy()
    if sub.empty:
        return {}
    months = _PERIODS.get(period)
    if months is not None:
        sub = sub[sub["started_at"] >= pd.Timestamp.now() - pd.DateOffset(months=months)]
    if sub.empty:
        return {"exercise": exercise, "muscle": muscle, "period": period,
                "stats": None, "deltas": None, "series": []}

    per_day = sub.groupby("day").agg(
        e1rm=("e1rm", "max"),
        top_weight=("weight_kg", "max"),
        tonnage=("tonnage", "sum"),
        reps=("reps", "sum"),
        sets=("reps", "size"),
        rpe=("rpe", "mean"),
    ).reset_index().sort_values("day")

    series = [
        {"date": d.date().isoformat(),
         "e1rm": round(float(e), 1), "top_weight": round(float(tw), 1),
         "tonnage": round(float(t)), "reps": int(rp), "sets": int(st),
         "rpe": None if pd.isna(rp_e) else round(float(rp_e), 1)}
        for d, e, tw, t, rp, st, rp_e in zip(
            per_day["day"], per_day["e1rm"], per_day["top_weight"], per_day["tonnage"],
            per_day["reps"], per_day["sets"], per_day["rpe"])
    ]

    best = sub.loc[sub["e1rm"].idxmax()]
    rpe_vals = sub["rpe"].dropna()
    stats = {
        "sessions": int(per_day.shape[0]),
        "sets": int(len(sub)),
        "reps": int(sub["reps"].sum()),
        "tonnage_kg": round(float(sub["tonnage"].sum())),
        "top_weight": round(float(sub["weight_kg"].max()), 1),
        "best_e1rm": round(float(sub["e1rm"].max()), 1),
        "best_e1rm_date": best["day"].date().isoformat(),
        "best_set": f'{best["weight_kg"]:.1f} kg × {int(best["reps"])}',
        "avg_reps": round(float(sub["reps"].mean()), 1),
        "avg_rpe": round(float(rpe_vals.mean()), 1) if not rpe_vals.empty else None,
        "first_date": per_day["day"].min().date().isoformat(),
        "last_date": per_day["day"].max().date().isoformat(),
    }

    deltas = None
    if len(series) >= 2:
        a, b = series[0], series[-1]
        deltas = {
            "e1rm": round(b["e1rm"] - a["e1rm"], 1),
            "top_weight": round(b["top_weight"] - a["top_weight"], 1),
            "tonnage": b["tonnage"] - a["tonnage"],
            "rpe": (round(b["rpe"] - a["rpe"], 1) if (a["rpe"] is not None and b["rpe"] is not None) else None),
        }

    return {"exercise": exercise, "muscle": muscle, "period": period,
            "stats": stats, "deltas": deltas, "series": series, "status": exercise_status(exercise)}


def weekly_tonnage(weeks: int = 26) -> list[dict]:
    df = _sets()
    if df.empty:
        return []
    g = df.groupby("week")["tonnage"].sum().reset_index().sort_values("week").tail(weeks)
    return [{"week": w.isoformat(), "tonnage_kg": round(float(t))} for w, t in zip(g["week"], g["tonnage"])]


def tonnage_window(days: int = 7) -> dict:
    """Tonnage der letzten `days` Tage vs. der `days` Tage davor (rollend, heute-relativ)."""
    df = _sets()
    if df.empty:
        return {"current_kg": 0.0, "previous_kg": 0.0, "days": days}
    now = pd.Timestamp.now()
    cur_start = now - pd.Timedelta(days=days)
    prev_start = now - pd.Timedelta(days=2 * days)
    cur = df[df["started_at"] > cur_start]
    prev = df[(df["started_at"] > prev_start) & (df["started_at"] <= cur_start)]
    return {
        "current_kg": round(float(cur["tonnage"].sum())),
        "previous_kg": round(float(prev["tonnage"].sum())),
        "days": days,
    }


def rpe_trend(weeks: int = 26) -> list[dict]:
    df = _sets()
    if df.empty or df["rpe"].notna().sum() == 0:
        return []
    sub = df[df["rpe"].notna()]
    g = sub.groupby("week")["rpe"].mean().reset_index().sort_values("week").tail(weeks)
    return [{"week": w.isoformat(), "rpe": round(float(r), 1)} for w, r in zip(g["week"], g["rpe"])]


def summary() -> dict:
    lifts = main_lifts(limit=6)
    ton = weekly_tonnage(weeks=1)
    rpe = rpe_trend(weeks=1)
    top = max(lifts, key=lambda x: x["e1rm"]) if lifts else None
    return {
        "top_lift": top["exercise"] if top else None,
        "top_e1rm": top["e1rm"] if top else None,
        "week_tonnage_kg": ton[-1]["tonnage_kg"] if ton else None,
        "rpe": rpe[-1]["rpe"] if rpe else None,
        "main_lifts": lifts,
    }


# Muskelgruppen-Heuristik (Reihenfolge wichtig: Spezifisches zuerst). DE + EN Stichworte.
_GROUPS = [
    ("Beine", ["squat", "kniebeuge", "lunge", "ausfall", "wade", "calf", "beinpresse", "leg press",
               "leg curl", "leg extension", "beinbeuger", "beinstrecker", "hip thrust", "glute",
               "gesäß", "rdl", "rumänisch", "romanian", "hamstring", "quad", "bein"]),
    ("Brust", ["bench", "bankdrücken", "bankdruecken", "chest", "brust", "butterfly", "pec",
               "fliegende", "dips", "liegestütz", "push-up", "push up"]),
    ("Schultern", ["shoulder", "schulter", "overhead press", "ohp", "military", "seitheben",
                   "frontheben", "lateral raise", "front raise", "rear delt", "reverse fly",
                   "reverse pec", "delt", "arnold", "nackendrücken", "face pull", "shrug", "nacken"]),
    ("Rücken", ["row", "rudern", "lat", "pull-up", "pullup", "klimmzug", "pulldown", "latzug",
                "zug", "rücken", "ruecken", "back", "überzug", "pullover", "deadlift", "kreuzheb",
                "hyperext", "rückenstrecker", "good morning"]),
    ("Bizeps", ["curl", "bizeps", "biceps", "hammer", "preacher", "scott"]),
    ("Trizeps", ["triceps", "trizeps", "pushdown", "kickback", "french", "stirndrücken", "skull", "dip "]),
    ("Core", ["crunch", "plank", "planke", "bauch", "core", "sit-up", "situp", "leg raise",
              "beinheben", "russian twist", "ab wheel", "mountain climber", "hollow"]),
]


def _muscle_group(name: str) -> str:
    n = (name or "").lower()
    for group, kws in _GROUPS:
        if any(k in n for k in kws):
            return group
    return "Sonstige"


def all_exercises() -> list[dict]:
    """Alle Übungen mit aktuellem e1RM, Peak, Satzzahl und Muskelgruppe (für Suche/Gruppierung)."""
    df = _sets()
    if df.empty:
        return []
    out = []
    for ex, sub in df.groupby("exercise"):
        last_day = sub["day"].max()
        out.append({
            "exercise": ex,
            "muscle": _muscle_group(ex),
            "e1rm": round(float(sub[sub["day"] == last_day]["e1rm"].max()), 1),
            "peak": round(float(sub["e1rm"].max()), 1),
            "sets": int(len(sub)),
            "last": last_day.date().isoformat(),
        })
    return sorted(out, key=lambda r: (r["muscle"], -r["sets"]))
