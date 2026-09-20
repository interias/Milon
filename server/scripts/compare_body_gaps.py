"""Offline sensitivity analysis; writes personal results only to ignored data/.

Run from server/: python scripts/compare_body_gaps.py
Candidate thresholds are engineering choices for comparison, not validated cutoffs.
"""
from pathlib import Path
import json
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.metrics import body


def latest_segment(series, gap_days=7):
    observed = series.dropna()
    groups = observed.index.to_series().diff().dt.days.gt(gap_days + 1).cumsum()
    return observed.loc[groups == groups.iloc[-1]] if len(observed) else observed


def candidate(series, gap_days=7, min_days=14, min_span=21):
    """Fit observed daily weights only, within 30 days and the current segment."""
    observed = latest_segment(series, gap_days)
    if observed.empty:
        return {}
    end = observed.index[-1]
    window = observed.loc[observed.index > end - pd.Timedelta(days=30)]
    span = int((window.index[-1] - window.index[0]).days)
    metadata = {"from_date": str(end.date()), "observed_days": len(window), "span_days": span}
    if len(window) < min_days or span < min_span:
        return {**metadata, "available": False}
    x = (window.index - end).days.to_numpy(float)
    slope, intercept = np.polyfit(x, window.to_numpy(float), 1)
    return {**metadata, "available": True, "current": float(intercept),
            "per_month": float(slope * 30), "projected": float(intercept + slope * 30)}


def gap_ranges(series):
    result = []
    for _, chunk in series.groupby(series.notna().cumsum()):
        missing = chunk[chunk.isna()]
        if len(missing):
            result.append({"start": str(missing.index[0].date()),
                           "end": str(missing.index[-1].date()), "days": len(missing)})
    return result


def composition_observed(weight, bf):
    # Both rolling averages use the same observed measurement dates and >=3 pairs.
    pairs = pd.concat({"weight": weight, "bf": bf}, axis=1).dropna()
    means = pairs.rolling("7D", min_periods=3).mean()
    means["ffm"] = means.weight * (1 - means.bf / 100)
    means["fat"] = means.weight - means.ffm
    return means.dropna()


def comparison():
    # Capture all body input in one query; production functions use this snapshot.
    frame = body._read("SELECT measured_at, weight_kg, body_fat_pct FROM body_measurements",
                       parse_dates=["measured_at"])
    daily = frame.groupby(frame.measured_at.dt.floor("D"))[["weight_kg", "body_fat_pct"]].mean().sort_index()
    weight = daily.weight_kg.dropna().asfreq("D")
    bf = daily.body_fat_pct.dropna().asfreq("D")
    with patch.object(body, "_weight_daily", return_value=weight), patch.object(body, "_bodyfat_daily", return_value=bf):
        current = body.weight_forecast()
        old_mass = pd.DataFrame(body.lean_mass_trend(180)).set_index("date")
        old_composition = body.composition_forecast()
    new_mass = composition_observed(weight, bf)
    last = weight.index[-1]
    cutoff = last - pd.Timedelta(days=180)
    recent_mass = new_mass.loc[new_mass.index >= cutoff]
    old_mass.index = pd.to_datetime(old_mass.index)
    common = old_mass.index.intersection(recent_mass.index)
    gaps = gap_ranges(weight)
    # A causal ablation changes only interpolation: reset EWMA after long gaps,
    # give missing days no observation weight, and fit only real measurement dates.
    segment = latest_segment(weight)
    ablation = body._forecast(segment.ewm(span=10).mean(), 30, 30, 2)
    records = []
    # Weekly origins, target actual weight 30 days later (+/-3 calendar days).
    # Backtest future rows are never supplied to the fitting functions.
    for origin in weight.dropna().index:
        if origin.dayofweek != 6 or origin < weight.index[0] + pd.Timedelta(days=60):
            continue
        future = weight.loc[origin + pd.Timedelta(days=27):origin + pd.Timedelta(days=33)].dropna()
        if len(future) < 3 or origin + pd.Timedelta(days=33) > last:
            continue
        history = weight.loc[:origin]
        baseline = body._forecast(history.interpolate().ewm(span=10).mean(), 30, 30, 2)
        gap_only = body._forecast(latest_segment(history).ewm(span=10).mean(), 30, 30, 2)
        proposed = candidate(history)
        if not baseline:
            continue
        actual = float(future.mean())
        no_change = float(history.loc[origin - pd.Timedelta(days=6):].mean())
        records.append({"date": str(origin.date()), "actual": actual,
                        "baseline": baseline["projected"], "no_change": no_change,
                        "gap_only": gap_only.get("projected"),
                        "candidate": proposed.get("projected")})
    paired = [row for row in records if row["candidate"] is not None]
    scores = {key: {"mae_kg": float(np.mean([abs(row[key] - row["actual"]) for row in paired])),
                    "bias_kg": float(np.mean([row[key] - row["actual"] for row in paired]))}
              for key in ("baseline", "gap_only", "candidate", "no_change")} if paired else {}
    return {
        "data": {"start": str(weight.index[0].date()), "end": str(last.date()),
                 "weight_days": int(weight.count()), "calendar_days": len(weight),
                 "gaps_over_7_days": [g for g in gaps if g["days"] > 7]},
        "weight": {"baseline": {k: v for k, v in current.items() if k not in ("history", "points")},
                   "gap_only_ablation": {k: v for k, v in ablation.items() if k not in ("history", "points")},
                   "candidate": candidate(weight),
                   "sensitivity": [{"max_gap_days": gap, "minimum_days": count, "minimum_span": span,
                                    **candidate(weight, gap, count, span)} for gap in (3, 7, 14)
                                   for count in (10, 14) for span in (14, 21)]},
        "composition": {"baseline_anchor": old_composition.get("anchor"),
                        "baseline_date": old_composition.get("from_date"),
                        "candidate_date": str(new_mass.index[-1].date()),
                        "candidate_anchor": new_mass.iloc[-1].to_dict(),
                        "baseline_points_180d": len(old_mass), "candidate_points_180d": len(recent_mass),
                        "paired_points": len(common),
                        "ffm_mean_absolute_difference": float((old_mass.loc[common].ffm - recent_mass.loc[common].ffm).abs().mean())},
        "backtest": {"eligible_origins": len(records), "paired_origins": len(paired),
                     "scores_same_origins": scores, "records": records,
                     "caveat": "Overlapping weekly origins; descriptive errors, not independent validation or confidence intervals. Target is mean of >=3 observed weights at horizon +/-3 days."},
    }


if __name__ == "__main__":
    result = comparison()
    destination = Path(__file__).resolve().parents[2] / "data/run-analysis/body-gap-comparison.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(destination)
