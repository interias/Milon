# Body model comparison protocol

Initial comparison: 2026-09-20, before production changes (commit d07e15e).
Q19–21 subsequently approved calendar alignment, paired composition windows and
coverage-gated forecasts. Implemented rules are recorded in ARCHITECTURE.md.
Scripts retain the pre-fix baseline formulas to reproduce the comparison.

Run from `server/`:

```powershell
python scripts/compare_body_gaps.py
python scripts/compare_tdee_windows.py
python -m pytest tests/test_body_gap_comparison.py -q
```

The scripts capture their input before comparing variants. Personal results are
written only to ignored `data/run-analysis/`; do not commit those outputs.

## Weight and composition

- Baseline: production interpolation, daily EWMA and 30-day linear extrapolation.
- Gap sensitivity: start a new segment after more than seven missing calendar
  days, run EWMA on observed days only, and fit those observations. This also changes
  smoothing weights; it is not an isolated test of interpolation alone.
- Alternative fit: linear regression on actual daily measurements within the last
  30 calendar days and current segment, using elapsed calendar time. Compare minimum
  10/14 observations, 14/21 elapsed days and maximum gaps of 3/7/14 missing days.
- Composition alternative: use only dates with both weight and BIA, average both
  over the same trailing seven calendar days, require at least three paired days,
  and calculate fat/FFM from these means. No interpolation, no muscle inference.
- Historical forecast comparison: weekly Sunday origins with observed weight,
  at least 60 days after history begins. Models receive no future measurements.
  Target is mean of at least three observed weights 27–33 days after origin;
  only completed target windows are scored. Compare identical eligible origins,
  including an unchanged-last-seven-day-mean baseline. Report coverage as well
  as mean absolute error and bias. Overlapping origins are not independent;
  these descriptive errors are not confidence intervals or external validation.

The current forecast is sensitive to how a long recent gap is treated. A raw-weight
regression does not establish an accuracy improvement. Keep any forecast optional
and separate from the observed trend. Coverage thresholds are transparent product
choices, not scientifically established reliability guarantees. The existing gap
sensitivity variant itself has no coverage guard; a proposed production replacement
would additionally require sufficient observations and calendar span.

## Energy balance

TDEE already uses non-interpolated seven-day weight averages at endpoints 14 days
apart. Its final smoothing averages estimates in 14 calendar days, whereas the
headline intake averages the last 14 available estimates. After gaps those sets
can differ. Aligning both to identical estimate dates repairs this mismatch without
changing TDEE itself. Intake means are themselves overlapping 14-day windows; this
is not the same as averaging raw intake over only the latest 14 days.

Sensitivity analysis varies recorded intake days per 14-day estimation window
(7/10/12/14) and the number of estimates in the 14-day smoothing window
(1/7/10/12/14). Missing entries are never zero-filled. A recorded day is not proof
that the entire day's intake was logged. Counts of overlapping estimates indicate
coverage, not independent sample size or physiological certainty.

Approved decisions: consistent calendar smoothing and visible coverage; gap-safe
derived mass; optional forecasts gated on coverage and anchored to a common date.
No change to the 7700 kcal/kg assumption or composition partition coefficients is
validated by this comparison. Source evidence and limitations remain in
`body-composition-evidence.md`.
