# Independent running VO2-equivalent trend: evidence and design implications

Research date: 2026-09-19. Scope: published primary evidence and mathematical implications; no personal health data or application changes. This is a design note, not a validated estimator.

## Main finding

An independent heart-rate/speed trend is feasible, but an interpretable VO2-equivalent is a more defensible target than claiming measured VO2max. Standardized running heart rate, a VO2-equivalent derived from it, and a running performance score answer related but different questions. Agreement of a commercial method with laboratory values cannot be transferred to a new implementation.

## What supports the reserve model, and what does not

Swain et al. (1998) tested 50 adults with a Bruce treadmill protocol. Percentage heart-rate reserve was closer to percentage oxygen-uptake reserve than to percentage VO2max. However, even the reserve-to-reserve regression differed statistically from identity. This supports a working approximation, not an individual physiological equality. [Original abstract](https://pubmed.ncbi.nlm.nih.gov/9502363/)

A particularly relevant counterpoint is Ferri Marini et al. (2022): eight physically active men completed treadmill exercise at 60%/80% HR reserve for 15/45 minutes. HR reserve and oxygen-uptake reserve were similar at 15 minutes; at 45 minutes the former exceeded the latter by a mean 6.7 percentage points. The small sample limits generalization, but duration matters even under controlled conditions. Standardizing at minute 30 improves comparisons; it does not establish that the reserve equality is exact at that minute. [Original study](https://pmc.ncbi.nlm.nih.gov/articles/PMC9048681/)

The proposed model is:

```text
estimated oxygen demand = 3.5 + 0.2 * speed_m_per_min
HRR = (standardized_HR - resting_HR) / (maximum_HR - resting_HR)
VO2_equivalent = 3.5 + 0.2 * speed_m_per_min / HRR
```

Its assumptions include level running, a representative oxygen-cost equation, sufficiently steady exercise, an applicable reserve relationship, and valid HR references. It is not a direct measurement of either running economy or maximal oxygen uptake.

## ACSM equations are useful approximations, not personal calibration

Koutlianos et al. found that the ACSM running equation should not simply be applied to maximal graded tests as though it measured VO2max; the equation's intended steady-state use matters. [Original study](https://pmc.ncbi.nlm.nih.gov/articles/PMC3743617/)

A 2023 comparison in 99 active adults (mean laboratory VO2max 47.4 ml/kg/min) reported mean overestimation of 9.8 for maximal ACSM estimates and 3.4/3.8 ml/kg/min for submaximal estimates using age-predicted/measured HRmax respectively. Those protocols are not identical to our proposed minute-level model, so these errors cannot be adopted as Milon's error bars or bias correction. [Original abstract](https://pubmed.ncbi.nlm.nih.gov/38133102/)

## What wearable validations actually show

Firstbeat's manufacturer white paper describes selecting reliable heart-rate/speed periods. It reports approximately 5% mean absolute percentage error from 2,690 runs by 79 runners, with four laboratory tests over 6–9 months. This is manufacturer evidence for its own method, not independent validation of a simple reserve formula. The paper itself emphasizes standardized conditions, since surface, wind and altitude affect speed. [Manufacturer white paper](https://assets.firstbeat.com/firstbeat/uploads/2015/10/white_paper_VO2max_11-11-2014.pdf)

Parak et al. (2017) studied 24 healthy volunteers using wrist optical HR and phone GPS during self-paced outdoor running. Reported VO2max MAPE was 5.2% with measured HRmax. This supports technical feasibility, but the device/model-specific result is not proof that any speed/HR estimator has this accuracy, nor proof of sensitivity to small month-to-month change. This study involved commercial technology; it should not be presented as wholly independent validation. [Original publication](https://doi.org/10.2196/mhealth.7437) · [Abstract](https://pubmed.ncbi.nlm.nih.gov/28743682/)

A 2025 Garmin Forerunner 245 study in 35 endurance athletes (mean laboratory VO2max 60.1) reported mean underestimation of 4.73 and 4.05 ml/kg/min across two submaximal runs. This is another method/population, illustrating why a single advertised accuracy is not universal. [Original abstract](https://pubmed.ncbi.nlm.nih.gov/40770433/)

Longitudinal validation must assess changes, not just cross-sectional ranking. Spathis et al. studied 11,059 participants, a 2,675-person follow-up after seven years, and an external maximal-testing cohort of 181. Their complex wearable model offers evidence that longitudinal inference is possible. The main Fenland reference was a submaximal exercise estimate; it does not establish monthly responsiveness for a personal running model. [Original study](https://pmc.ncbi.nlm.nih.gov/articles/PMC9718831/)

## Reference parameters and uncertainty

Maximum HR predicted from age is a population estimate. Tanaka et al. developed the widely used alternative to 220 minus age; that does not turn it into an individual measurement. A separate college-age validation reported a 9.3 bpm standard error for the Tanaka equation. [Tanaka study](https://pubmed.ncbi.nlm.nih.gov/11153730/) · [Validation](https://pubmed.ncbi.nlm.nih.gov/21691228/)

Design implications, derived from the proposed formula:

- At 6:00/km, HR=150, HRmax=190 and resting HR=50, VO2-equivalent is 50.17. Increasing HRmax to 200 changes it to 53.50 with no change in the run. A changing reference can therefore manufacture a trend.
- A low everyday HR sample is not automatically a standardized resting measurement. Do not silently equate a minimum, sleeping value and waking-rest value.
- Persist source/date/method for HR references. A correction should allow recalculating comparable history with a consistent reference version; real long-term physiological changes need an explicit separate policy.
- A run-level bootstrap estimates sampling variability conditional on the model and chosen references. It does not include uncertainty in oxygen cost, HR references, sensor bias or environment. Display these limitations separately, or add an explicitly labeled sensitivity range. Do not claim a physiologically calibrated 95% interval from the bootstrap alone.
- At fixed speed and fixed references, VO2-equivalent is a monotonic transformation of standardized HR. It is another scale for the same signal, not independent corroboration.
- Three reference paces from one fitted curve are correlated. If a median is taken over whichever paces happen to pass each month, changing that set can cause a composition artifact. Keep the aggregation reference set fixed, or compare over a stable shared support and disclose changes.

## Practical alternatives and calibration

VDOT is a running-performance index. Its own provider explicitly distinguishes it from VO2max because runners with the same VO2max can achieve different results. Existing race results can be a useful independent performance anchor, but should not be treated as laboratory oxygen measurements. [Provider explanation](https://support.vdoto2.com/v-o2-faq/)

Cooper's original 12-minute field-test study involved 115 male US Air Force personnel and reported correlation 0.897 with laboratory oxygen uptake. That establishes historical prediction evidence in a specific population; correlation is not individual agreement, and casual training runs are not equivalent to the test protocol. This note does not recommend conducting a maximal test. [Original study](https://doi.org/10.1001/JAMA.1968.03140030033008)

Preferred product direction, as a design inference from the evidence:

1. Keep standardized HR/pace as the auditable primary observation.
2. Add a clearly named personal VO2-equivalent trend based on the same quality-controlled data, with reference assumptions visible and no Samsung value as a required input.
3. Favor repeatable submaximal route/section comparisons and stable duration over merely accumulating more unrelated minutes. Compare an early steady section with a later section separately to distinguish fresh efficiency from durability/drift; do not collapse both into one claim about VO2max.
4. Use matched repeated runs to estimate ordinary test–retest variability. Validate any trend against held-out runs and, when already available, independent performance or laboratory results.
5. An optional laboratory anchor can adjust the absolute scale at one time, but a single calibration does not validate future slopes. Historical race results can validate running performance, not supply equivalent physiological calibration.

Open decisions for the user: whether an honest VO2-equivalent label meets the goal; availability of trustworthy HR references or existing laboratory/race results; willingness to repeat comparable easy running sections occasionally; preference for a responsive rolling trend versus non-overlapping monthly estimates. Exact thresholds such as 5/3 runs remain engineering choices to validate on the data, not scientific constants from these studies.
