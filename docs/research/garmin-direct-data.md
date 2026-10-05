# Direct Garmin data: replacement and enrichment plan

Verified 2026-10-05 against the installed `garminconnect==0.3.17`, its [versioned source](https://github.com/cyberjunky/python-garminconnect/blob/0.3.17/garminconnect/__init__.py), and Garmin documentation. Interface research was followed by a separate, read-only account audit. Method availability is distinct from successful retrieval or populated fields; the final section records qualitative audit findings without personal measurements.

## Recommendation

Make Garmin the primary source for Garmin-recorded activities and watch metrics from the configured watch-switch date onward. Start with complete running records, then sleep, HRV and steps; keep Garmin resting HR separately attributed until its discrepancy is resolved. Keep Health Connect for historical Samsung data and Arboleaf body measurements; keep Hevy for gym sets and FDDB for nutrition. The implementation following this research now applies this source policy; see the final section and [current architecture](../../ARCHITECTURE.md).

The current library uses Garmin Connect's consumer services. It is an unofficial integration, not the approved Garmin developer program, and endpoint behavior can change. Garmin's official program targets approved business integrations. Faster reads still require the watch to have synchronized to Garmin Connect; server polling cannot retrieve an unsynchronized watch recording. [Library project](https://pypi.org/project/garminconnect/0.3.17/) · [Garmin program FAQ](https://developer.garmin.com/gc-developer-program/program-faq/)

## Available interfaces

Names below were checked in the installed, MIT-licensed 0.3.17 implementation. The wrapper generally passes Garmin payloads through; do not infer a stable field schema or guaranteed data coverage from the method name. [Versioned implementation](https://github.com/cyberjunky/python-garminconnect/blob/0.3.17/garminconnect/__init__.py)

| Data | Exact library entry points | Milon priority |
| --- | --- | --- |
| Activities and summaries | `get_activities`, `get_activity` | Replace mirrored watch sessions after reconciliation |
| Activity series | `get_activity_details(activity_id, maxchart=2000, maxpoly=4000)` | HR, speed, elevation, cadence and other available descriptors |
| Original recording | `download_activity(id, ActivityDownloadFormat.ORIGINAL)` | ZIP containing original activity file; inspect format before parsing |
| Laps and splits | `get_activity_splits`, `get_activity_typed_splits`, `get_activity_split_summaries` | Compact kilometer/lap comparison |
| HR zones | `get_activity_hr_in_timezones`, `get_heart_rate_zones` | Recorded zone duration and configured sport profiles |
| Steps | `get_daily_steps`, `get_steps_data`, `get_user_summary` | Replace Garmin HC daily/interval values |
| Daily HR and resting HR | `get_heart_rates`, `get_rhr_day`, `get_rhr_daily` | Recovery context; distinguish daily series from workout samples |
| Sleep | `get_sleep_data`, `get_sleep_daily` | Duration, timing and available stage/score fields |
| HRV | `get_hrv_data`, `get_hrv_data_range` | Overnight measurements and available baseline/status |
| VO2max estimates | `get_max_metrics`, `get_max_metrics_range` | Separate Garmin estimate alongside Milon's trend |
| Recovery and load | `get_training_readiness`, `get_morning_training_readiness`, `get_training_status`, `get_daily_training_status`, `get_training_four_week_load_balance` | Optional contextual panel |
| Body Battery and stress | `get_body_battery`, `get_body_battery_events`, `get_stress_data` | Secondary recovery context |
| Further candidates | `get_lactate_threshold`, `get_running_tolerance`, `get_endurance_score`, `get_hill_score`, `get_race_predictions`, `get_respiration_data`, `get_spo2_data` | Inspect only after higher-value imports |

## Running: prefer synchronized sensor records

The strongest immediate improvement is a run detail with one shared time/distance axis and selectable HR, pace and elevation, plus laps. Activity records offer a better starting point for matching HR to speed than joining independently exported HC streams. Preserve missing samples and pauses instead of interpolating across them. The activity-detail request defaults to **2,000 chart points**, so it must not silently be treated as the full recording. Raising the request limit is not proof that Garmin returned every sample. [Library activity methods](https://github.com/cyberjunky/python-garminconnect/blob/0.3.17/garminconnect/__init__.py#L3260-L3390)

For analytical ingestion, use the detail JSON when its returned descriptors, timestamps, coverage and reported counts establish adequate completeness for that recording; equality of returned/total chart counts is useful evidence, not proof of raw sensor frequency. Otherwise use the original FIT, also useful for archival and sensor metadata. Garmin's own SDK examples explicitly support timestamped HR, distance, speed, altitude, cadence, power, coordinates, timer events, laps and session totals. These are format capabilities, not guarantees for every recording. Decode units/scales through a FIT decoder. Validate active versus elapsed time, enhanced versus legacy fields, cadence convention and coverage against Garmin's summary. [Garmin FIT SDK activity example](https://github.com/garmin/fit-python-sdk/blob/main/tests/test_encode_activity_recipe.py)

GPX remains useful for the route display. It is not sufficient evidence that HR or other sensor fields exist: Milon's current GPX parser stores position, elevation and time, and optional vendor extensions require explicit support. Keep a chart-resolution series for the browser and the fullest available recording for analysis. [Current route parser](../../server/app/garmin_routes.py)

Useful derived views, in order:

1. **Run detail:** HR/pace over the same axis, elevation context, pauses, laps and time in zones. Show the zone definition used; do not silently replace Milon's configured HR reference with Garmin's current zones.
2. **Comparable sections:** pace at similar HR on repeated routes or similar flat sections; separate warm-up, hills and intervals. More samples do not create more independent runs.
3. **Drift and durability:** compare equivalent early/late steady sections at similar speed/grade. Distinguish a rising HR at constant workload from simply running faster later.

These are design recommendations, not new physiological estimators. Existing model checks, minimum-run requirements and the sensor-change boundary remain necessary. [Existing model evidence](running-vo2-evidence.md)

## Recovery: valuable data, overlapping algorithms

Sleep timing/duration, resting HR and overnight HRV are the most useful next inputs for the existing sleep/performance work. Persist date, sampling context and coverage. Garmin's overnight HRV comes from wrist measurements during sleep; it is not the same measurement context as chest-strap HRV during exercise. The Forerunner 970 requires approximately **three weeks of consistent sleep data** for its HRV status. Missing baseline/status during initial use is therefore different from a failed sync. [Forerunner 970 manual, HRV status](https://www8.garmin.com/manuals/webhelp/GUID-025D75CF-3445-49E1-8D81-1AA74AB4E00F/EN-US/Forerunner_970_OM_EN-US.pdf)

Training Readiness incorporates sleep, HRV status, recovery time, acute load and recent stress/sleep history. Body Battery also incorporates HRV, stress, sleep and activity. Consequently, correlating these scores with their own inputs mostly rediscovers their construction. Use them as **Garmin estimates**, with timestamps, alongside an independent optional energy check-in and subsequent performance; do not combine several overlapping scores into a supposedly stronger independent signal. [Garmin Training Readiness](https://www8.garmin.com/manuals/webhelp/GUID-025D75CF-3445-49E1-8D81-1AA74AB4E00F/EN-US/GUID-C21BE0C8-A08E-4DA1-B6C6-2E0E2DDDB372.html) · [Garmin Body Battery](https://www8.garmin.com/manuals-apac/webhelp/forerunner970/EN-SG/GUID-F2046174-6E88-4330-84F6-BE7881CB7E80-9121.html)

For sleep-to-training associations, pair the preceding night with the following workout; compare within similar workouts and account for duration/intensity and time trends. Use raw session/day observations for inference, not overlapping smoothed windows. A handful of nights can populate the chart but cannot establish a robust personal relationship. The software's morning-readiness helper can fall back to the first available snapshot when the wake-up marker is absent; retain that uncertainty rather than labeling any returned value as a verified morning measurement. [Library readiness implementation](https://github.com/cyberjunky/python-garminconnect/blob/0.3.17/garminconnect/__init__.py#L2290-L2343)

## Forerunner 970 and HRM 600 extras

The combination supports cadence, stride length, vertical oscillation/ratio, ground-contact time/balance and **step speed loss**. Garmin specifically requires a secure Bluetooth connection for the HRM 600's complete running-dynamics path. Their availability in this account's JSON/FIT must still be checked; owning the devices does not prove the relevant fields were recorded. Compare mechanics at similar speed and terrain, rather than treating every lower value as better. [Garmin running dynamics](https://www8.garmin.com/manuals/webhelp/GUID-025D75CF-3445-49E1-8D81-1AA74AB4E00F/EN-US/GUID-62A09512-518A-424A-8491-FE2B80CD2091.html)

Garmin's Running Economy is a separate algorithmic estimate, not Milon's meters-per-heartbeat efficiency. Garmin describes approximately 5–7 qualifying runs before an initial estimate, using a compatible step-speed-loss sensor; indoor/trail runs are excluded. There is no dedicated `get_running_economy` method in the inspected 0.3.17 wrapper. Treat retrieval of that estimate as unverified until a supported response field is observed; do not promise it based only on the watch feature. [Garmin Running Economy](https://www.garmin.com/en-US/garmin-technology/running-science/physiological-measurements/running-economy/) · [Library source](https://github.com/cyberjunky/python-garminconnect/blob/0.3.17/garminconnect/__init__.py)

## Migration without duplicates or rewritten history

Proposed implementation sequence, inferred from Milon's existing source policy:

1. **Shadow import:** store normalized Garmin activities/samples and daily metrics with source, Garmin ID/date, retrieval time and parser version. Backfill from the configured watch switch. Keep private originals under ignored `data/`, never in reports or Git.
2. **Reconcile:** map one Garmin activity to one canonical session using stable IDs plus start/type/distance/duration checks. Ambiguous cases remain unresolved. Link HC aliases to that canonical session; never sum the two sources. Keep selected source per metric/day as well as source-level originals.
3. **Switch running:** after comparing totals, time semantics and sample coverage, let direct Garmin supply new runs and supported summaries/series. An HC full reimport must neither remove direct records nor recreate their aliases. Preserve earlier Samsung history and sensor provenance.
4. **Switch daily watch metrics:** steps, sleep, RHR and HRV after overlapping comparisons. Treat today's values as provisional; reread recent days for late device sync and edited sleep. Use GMT instants and the configured timezone instead of assuming returned local timestamps are reliable. Distinguish missing data, partial day, genuine zero, unsupported metric and request failure.
5. **Enrich selectively:** add a compact recovery panel and optional running-dynamics detail. Retain Hevy/FDDB/Arboleaf ownership; Garmin calorie estimates do not replace food logging or Milon's observed energy-balance model.

Use the existing serialized Garmin sync and token persistence. Fetch new/changed activities frequently, daily metrics on a slower cadence, and recent days again after new data arrives. Keep last successful values with a visible stale/error state; do not silently switch to a different sensor after a failed request. Reconcile explicit remote edits/deletions through a bounded full-history procedure, not by deleting records absent from the latest page. Rate limits and undocumented response changes require bounded retries/backoff; no fixed guaranteed quota was established by this research.

Concrete migration constraints in the current code:

- `RunMinute` is unique by `(external_id, minute)`, while a normal HC import deletes minute rows for affected IDs without a source condition. Direct writes into that table alone would therefore be overwritten. Introduce source-owned staging plus canonical selection, or update both importers together. [Models](../../server/app/models.py) · [HC import](../../server/app/ingest/health_connect.py)
- `StepsDaily` and `RestingHrDaily` use the day as their primary key; HC upserts their values without source precedence. Apply a tested selection policy before updating canonical daily values, and change provenance with the selected value. [HC import](../../server/app/ingest/health_connect.py)
- Sleep selection filters `source_package` through `watch_source_for(day)`. Keep device/app provenance distinct from transport (`garmin_direct` versus `health_connect`) and reconcile equivalent nights before selecting one. [Sleep metrics](../../server/app/metrics/sleep.py)
- Preserve existing session aliases, annotations and historical Samsung data. Version the source-selection/parser policy and include it in derived-cache fingerprints, so changing the transport or underlying samples actually recomputes dependent analyses. Acceptance tests must cover direct-first, HC-first, repeated imports, partial failures and HC full reimport; direct priority applies only with adequate coverage for the relevant metric.

## Account audit

Bounded authenticated reads and read-only comparison with the local HC export confirmed the following. Private audit artifacts remain under ignored `data/qa/`; no personal values or recordings are included here. These findings describe the sampled records, not guaranteed coverage of every activity or date.

- A running detail response requested with `maxchart=20000, maxpoly=0` returned matching `metricsCount` and `totalMetricsCount`. Its timestamps were substantially denser than the corresponding HC HR/speed streams, with nearly complete HR coverage. HR, speed, altitude, cadence, running power, ground-contact time, stride length and stamina channels were populated. Units, pauses and sensor attribution still need normalized importer tests.
- Summary comparisons showed that distance, duration and speed values were already in consistent units despite descriptor `unit.factor` metadata. Do not apply those factors blindly. In this response, `directDoubleCadence` matched the session's total-step cadence, whereas `directRunCadence` represented half that rate. Verify each channel against summary values before normalization.
- Sleep records were available across the sampled watch-use period. Sampled sleep duration and awake time matched HC, as did the compared daily step total. The primary benefit here is freshness and additional fields rather than a demonstrated correction to those HC values.
- Resting-HR readings differed between the direct and HC paths. Resolve their definitions and day assignment before switching that metric; do not splice them into one supposedly homogeneous series.
- Overnight HRV readings were available while baseline/status remained unset. Treat baseline warm-up separately from missing measurements.
- A VO2max estimate was populated on a running day but not on the subsequent non-record day, while the HC series lacked the newer estimate. Import measurement dates/ranges; an empty response for a day must not erase the last valid value.
- Training readiness, recovery time, stress and Body Battery data were retrievable; the sampled SpO2 response was empty. Advanced score semantics and longitudinal usefulness still require validation.

The audit initially enabled no additional production paths. The subsequent implementation now imports sufficiently complete running series into canonical activity metrics, plus direct steps, sleep and VO2max. Recovery observations remain source-attributed and Garmin resting HR is kept distinct. See [current architecture](../../ARCHITECTURE.md) for synchronization, completeness guards and HC reconciliation; owning a device still does not guarantee every optional field is populated.
