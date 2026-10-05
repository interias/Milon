# Garmin resting HR and the Health Connect discrepancy

Checked 2026-10-05 using official documentation, the installed `garminconnect==0.3.17` implementation, the read-only local Health Connect export, and cached Garmin responses. No additional authenticated provider requests were made. Personal values and the comparison output remain under ignored `data/qa/`.

## Finding

Keep the direct Garmin resting-HR series separate from the existing Health Connect series. The overlap is not consistently identical. Neither Milon's daily minimum aggregation nor a simple one-day offset explains the observed difference. An export/update-timing difference remains possible, but the cached evidence cannot establish its cause.

## Definitions and transport

Garmin's current English support article defines daily resting HR as the lowest 30-minute average within a 24-hour period. Its seven-day resting HR is a separate rolling average of daily values. This is a provider-derived measure, not the lowest individual pulse sample. The public article does not provide enough implementation detail to reproduce all device processing or export timing. [Garmin resting-HR definition](https://support.garmin.com/en-US/?faq=F8YKCB4CJd5PG0DR9ICV3A)

Health Connect's `RestingHeartRateRecord` stores an instantaneous resting-HR record with an `Instant` and zone offset. It supports min, max and average aggregation over such records; it does not specify Garmin's calculation or the semantics of Garmin's chosen export timestamp. The record type must not be confused with individual samples in `HeartRateRecord`. [Android record reference](https://developer.android.com/reference/android/health/connect/datatypes/RestingHeartRateRecord) · [Builder and zone offset](https://developer.android.com/reference/android/health/connect/datatypes/RestingHeartRateRecord.Builder) · [AOSP internal representation](https://android.googlesource.com/platform/prebuilts/fullsdk/sources/+/refs/heads/androidx-constraintlayout-release/android-35/android/health/connect/internal/datatypes/RestingHeartRateRecordInternal.java)

The library exposes consumer-service responses rather than calculating a new RHR. Milon's direct path takes `restingHeartRate` from the daily summary keyed by `calendarDate`. Distinct fields such as `minHeartRate`, `minAvgHeartRate` and `lastSevenDaysAvgRestingHeartRate` are not substitutes for that field. [Versioned library implementation](https://github.com/cyberjunky/python-garminconnect/blob/0.3.17/garminconnect/__init__.py) · [Milon normalization](../../server/app/garmin_daily.py)

Milon's HC parser reads `resting_heart_rate_record_table`, selects the configured watch app for the local date and takes the minimum of the day's **resting-HR records**. It does not derive that number from the complete all-day pulse stream. The UI phrase “HC daily minimum” therefore needs this qualification. [HC importer](../../server/app/ingest/health_connect.py) · [Stored daily model](../../server/app/models.py)

## Local comparison

The offline audit compared Garmin-attributed HC resting-HR records with cached direct daily summaries on overlapping dates. It also checked record timestamps, stored zone offsets, HC `local_date`, and direct dates shifted by one day in either direction.

- Each compared HC day contained only one distinct resting-HR value. Taking its minimum cannot explain the differing direct values in this sample.
- Some dates matched direct `restingHeartRate`, while others differed. A fixed source correction would overwrite already matching days.
- HC values did not match the direct daily `minHeartRate` or `minAvgHeartRate` fields in this overlap. A blanket relabeling as an all-day pulse minimum is unsupported.
- The parser's local dates agreed with HC's own stored local dates. The sampled timestamps were not ambiguous midnight records, and shifting the direct series by either one day did not resolve the discrepancy.
- The two paths were captured at different times. The cached responses do not reveal which internal Garmin calculation or revision produced each exported HC value. A difference between an earlier exported estimate and a revised daily value remains a hypothesis, not a verified explanation.

These findings concern the inspected overlap only. They do not establish Garmin's behavior across firmware versions, other devices, travel, or future exports. The private reproducible comparison is saved as `data/qa/garmin-rhr-comparison.json`; no personal measurements are included here.

## Product behavior

Use “Garmin-Ruhepuls” for the direct daily series and explain the prior HC path as the smallest transmitted resting-HR entry per day. Do not splice the two series, apply an estimated correction, or use their difference as a fitness change. Label current-day readings as provisional.

The compact source-status panel separates the last successful retrieval/import from the newest measurement or journal date. A successful Hevy poll without a new workout remains current. Category-level Garmin failures remain visible even if other daily categories succeeded. Error payloads, cookies, provider identifiers and raw health values are excluded from the status endpoint.

A conclusive future check would compare repeated, synchronized captures of a closed Garmin day and the corresponding HC record revisions, including last-modified times. Until then, preserving source identity is the defensible behavior.
