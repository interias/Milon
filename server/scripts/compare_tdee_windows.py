"""Compare TDEE window policies against one read-only SQLite snapshot.

Run from any directory with the server Python environment. Results contain health
data and default to the ignored data/run-analysis directory. Coverage thresholds
are sensitivity scenarios, not validated physiological reliability cutoffs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))

from app.metrics import body  # noqa: E402


def read_snapshot(path: Path) -> tuple[pd.Series, pd.Series, str]:
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(":memory:") as snapshot:
            source.backup(snapshot)
            weight = pd.read_sql_query(
                "SELECT measured_at, weight_kg FROM body_measurements "
                "WHERE weight_kg IS NOT NULL ORDER BY measured_at, weight_kg", snapshot,
                parse_dates=["measured_at"],
            )
            intake = pd.read_sql_query(
                "SELECT eaten_at, kcal FROM nutrition_entries "
                "WHERE kcal IS NOT NULL ORDER BY eaten_at, kcal", snapshot,
                parse_dates=["eaten_at"],
            )
    digest = hashlib.sha256(
        (weight.to_json(date_format="iso") + intake.to_json(date_format="iso")).encode()
    ).hexdigest()
    w = weight.groupby(weight.measured_at.dt.floor("D")).weight_kg.mean().sort_index().asfreq("D")
    i = intake.groupby(intake.eaten_at.dt.floor("D")).kcal.sum().sort_index()
    return w, i, digest


def summarize_differences(series: pd.Series) -> dict:
    series = series.dropna()
    return {
        "paired_days": len(series),
        "mean_delta": round(float(series.mean()), 2) if len(series) else None,
        "median_abs_delta": round(float(series.abs().median()), 2) if len(series) else None,
        "max_abs_delta": round(float(series.abs().max()), 2) if len(series) else None,
    }


def compare(weight: pd.Series, intake: pd.Series) -> dict:
    if weight.empty or intake.empty:
        return {"error": "Weight or intake missing"}
    anchor = weight.index.max()
    start = anchor - pd.Timedelta(days=179)
    calendar = pd.date_range(start, anchor, freq="D")
    with patch.object(body, "_weight_daily", return_value=weight), patch.object(
        body, "_intake_daily", return_value=intake
    ):
        baseline_rows = body.tdee_trend(days=len(weight) + 30)
        baseline_current = body.adaptive_tdee()
        threshold_rows = {n: body.tdee_trend(days=len(weight) + 30, min_intake_days=n)
                          for n in (7, 10, 12, 14)}
    if not baseline_rows:
        return {"error": "No eligible TDEE estimates", "current": baseline_current}

    baseline = pd.DataFrame(baseline_rows).set_index("date")
    baseline.index = pd.to_datetime(baseline.index)
    baseline["calendar_intake"] = baseline.intake.rolling("14D").mean().round()
    baseline["available_intake"] = baseline.intake.rolling(14, min_periods=1).mean().round()
    baseline["aligned_deficit"] = baseline.tdee_avg - baseline.calendar_intake
    baseline["legacy_deficit"] = baseline.tdee_avg - baseline.available_intake
    # Preserve the pre-alignment headline for reproducibility after production fixes.
    baseline_current["avg_intake"] = int(baseline.available_intake.iloc[-1])
    baseline_current["deficit_per_day"] = int(baseline.legacy_deficit.iloc[-1])
    baseline["smooth_estimate_days"] = baseline.tdee.rolling("14D").count()
    baseline["intake_recorded_days"] = intake.reindex(weight.index).rolling(14).count()
    recent = baseline.loc[baseline.index >= start]
    changed = recent[recent.aligned_deficit != recent.legacy_deficit]

    sensitivity = []
    for minimum, rows in threshold_rows.items():
        if not rows:
            sensitivity.append({"minimum_recorded_intake_days_per_14": minimum, "points": 0})
            continue
        frame = pd.DataFrame(rows).set_index("date")
        frame.index = pd.to_datetime(frame.index)
        frame["calendar_intake"] = frame.intake.rolling("14D").mean().round()
        frame["deficit"] = frame.tdee_avg - frame.calendar_intake
        frame["smooth_estimate_days"] = frame.tdee.rolling("14D").count()
        current = frame.iloc[-1]
        window = frame.loc[frame.index >= start]
        gates = []
        for smooth_minimum in (1, 7, 10, 12, 14):
            eligible = frame.loc[frame.smooth_estimate_days >= smooth_minimum]
            visible = eligible.loc[eligible.index >= start]
            gates.append({
                "minimum_estimates_per_14_calendar_days": smooth_minimum,
                "visible_days_of_180": len(visible),
                "latest_eligible_date": eligible.index[-1].date().isoformat() if len(eligible) else None,
                "latest_eligible_tdee": int(eligible.tdee_avg.iloc[-1]) if len(eligible) else None,
            })
        sensitivity.append({
            "minimum_recorded_intake_days_per_14": minimum,
            "points_last_180_calendar_days": len(window),
            "latest_date": frame.index[-1].date().isoformat(),
            "latest_age_days_from_weight_anchor": (anchor - frame.index[-1]).days,
            "latest_tdee": int(current.tdee_avg),
            "latest_aligned_intake": int(current.calendar_intake),
            "latest_aligned_deficit": int(current.deficit),
            "smoothing_count_distribution": {str(int(k)): int(v) for k, v in
                                             window.smooth_estimate_days.value_counts().sort_index().items()},
            "tdee_difference_on_same_dates": summarize_differences(
                window.tdee_avg - baseline.tdee_avg.reindex(window.index)),
            "smoothing_coverage_gates": gates,
        })

    recorded = intake.reindex(calendar).notna()
    coverage = intake.reindex(pd.date_range(weight.index.min(), max(anchor, intake.index.max())))
    coverage14 = coverage.rolling(14, min_periods=1).count().reindex(calendar)
    return {
        "historical_window": {"from": start.date().isoformat(), "through": anchor.date().isoformat(), "calendar_days": 180},
        "current_production": baseline_current,
        "current_aligned_intake": int(baseline.calendar_intake.iloc[-1]),
        "current_aligned_deficit": int(baseline.aligned_deficit.iloc[-1]),
        "current_window_details": {
            "legacy_intake_estimate_dates": [d.date().isoformat() for d in baseline.tail(14).index],
            "aligned_estimate_dates": [d.date().isoformat() for d in baseline.index
                                       if d > baseline.index[-1] - pd.Timedelta(days=14)],
            "smoothing_estimate_days": int(baseline.smooth_estimate_days.iloc[-1]),
            "latest_intake_recorded_days_per_14": int(baseline.intake_recorded_days.iloc[-1]),
            "latest_weight_recorded_days_per_7": int(weight.rolling(7).count().iloc[-1]),
            "reference_weight_recorded_days_per_7": int(weight.rolling(7).count().get(anchor - pd.Timedelta(days=14), 0)),
        },
        "raw_intake_coverage": {
            "latest_recorded_date": intake.index.max().date().isoformat(),
            "recorded_days_of_180": int(recorded.sum()),
            "days_with_no_intake_record": int((~recorded).sum()),
            "minimum_daily_kcal_on_recorded_days": round(float(intake.reindex(calendar).min())),
            "recorded_days_per_14_distribution": {str(int(k)): int(v) for k, v in coverage14.value_counts().sort_index().items()},
            "complete_intake_days": None,
            "completeness_note": "A recorded day contains at least one kcal entry; complete daily intake cannot be inferred from these records.",
        },
        "window_alignment": {
            "changed_deficit_days": len(changed),
            "deficit_difference": summarize_differences(recent.aligned_deficit - recent.legacy_deficit),
            "tdee_change": 0,
            "note": "Aligning headline intake to the same 14 calendar days changes the displayed deficit, not TDEE. Both are means of overlapping 14-day estimates; the underlying input span can extend to 27 days.",
            "changed_rows": json.loads(changed.reset_index().to_json(orient="records", date_format="iso")),
        },
        "coverage_sensitivity": sensitivity,
        "baseline_daily_last_180": json.loads(recent.reset_index().to_json(orient="records", date_format="iso")),
        "limits": [
            "The 7/10/12/14 coverage cutoffs are sensitivity scenarios, not physiological validity thresholds.",
            "Missing intake days are omitted, never treated as zero kcal; omitted days may still bias the recorded-day mean.",
            "No variant changes the 7700 kcal/kg assumption or short-term water and glycogen effects.",
            "Weight means still require three measured days in each seven-day endpoint window; TDEE does not interpolate weight gaps.",
            "A smoothing window can contain one estimate; stricter raw input coverage alone does not ensure dense smoothed output.",
            "Differences compare identical calendar dates; latest available values can be older under stricter policies.",
        ],
    }


def self_check() -> None:
    """Exercise the calendar/available-row distinction without personal data."""
    dates = pd.date_range("2020-01-01", periods=76)
    weight = pd.Series([80 - day / 100 for day in range(76)], index=dates)
    intake = pd.Series([2000 + day * 10 for day in range(76)], index=dates)
    weight.iloc[35:50] = float("nan")
    report = compare(weight, intake)
    details = report["current_window_details"]
    assert details["smoothing_estimate_days"] < 14
    assert report["current_aligned_intake"] != report["current_production"]["avg_intake"]
    assert report["current_aligned_deficit"] == (
        report["current_production"]["tdee"] - report["current_aligned_intake"]
    )
    assert len(details["aligned_estimate_dates"]) == details["smoothing_estimate_days"]
    # All intake days are present: changing intake coverage cannot change TDEE.
    for variant in report["coverage_sensitivity"]:
        assert variant["tdee_difference_on_same_dates"]["max_abs_delta"] == 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/tracker.db")
    parser.add_argument("--output", type=Path, default=ROOT / "data/run-analysis/tdee-comparison.json")
    parser.add_argument("--self-check", action="store_true", help="Run synthetic assertions only")
    args = parser.parse_args()
    if args.self_check:
        self_check()
        print("Synthetic calendar-window assertions passed")
        return
    weight, intake, digest = read_snapshot(args.database)
    report = {
        "snapshot_utc": datetime.now(timezone.utc).isoformat(),
        "input_sha256": digest,
        **compare(weight, intake),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"Saved private comparison to {args.output}")


if __name__ == "__main__":
    main()
