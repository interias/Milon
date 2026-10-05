# Health Connect synchronization options

Verified 2026-10-04 against primary documentation. This is a design recommendation; no Android bridge or additional server has been installed.

Health Connect already has a native Android API. Its SDK accesses the datastore on the user's phone; the official integration documented by Google is not a cloud REST endpoint that Milon's Python server can call directly. Faster synchronization therefore needs a phone component that forwards records to Milon. [Android platform overview](https://developer.android.com/health-and-fitness/health-connect)

## Native Android bridge

An Android companion can read permitted record types in the foreground and, where the feature is available, request `READ_HEALTH_DATA_IN_BACKGROUND`. Google's example schedules hourly WorkManager reads. Older history requires the additional history permission; ordinary access starts 30 days before the initial permission grant. Reads must paginate. For Milon, retain source attribution and the configured Garmin/Samsung cutoff rather than summing mirrored records from all apps. [Reading data](https://developer.android.com/health-and-fitness/health-connect/read-data)

Incremental reads use `getChangesToken` and `getChanges`, including upserts and deletions. Keep stable record IDs and separate tokens per type; drain all change pages and persist the next token after successful ingestion. Unused tokens expire within 30 days, so recovery needs a bounded reread and deduplication. Background reads still require permission, and Health Connect does not provide a new-record notification to replace polling. [Synchronization guide](https://developer.android.com/health-and-fitness/health-connect/sync-data)

Recommended Milon implementation, inferred from those capabilities:

1. A small Android app with read-only Health Connect access, a manual sync button, and a periodic background job.
2. A paired, authenticated Milon ingest endpoint reachable over the home network or a private VPN, with an on-phone retry queue. Preserve UTC instants, zone offsets, record IDs, source packages, updates, and deletions.
3. Reuse the existing source selection and metric layer; show the last successful transfer and per-type coverage. Keep ZIP import as a recovery path and reconcile IDs before enabling both inputs together.

This removes the export cadence as the bottleneck. It does not make Garmin write to Health Connect sooner, and actual phone scheduling and end-to-end freshness require a device test.

## Existing ZIP export

Google's native backup on Android 14+ offers daily, weekly, or monthly ZIP exports. Daily is the shortest documented built-in schedule. [Android backup help](https://support.google.com/android/answer/15323271?hl=en)

Milon currently checks its incoming directory every ten minutes and pulls the Drive file at 05:00 (`server/app/sync/scheduler.py`). A manual refresh can download a newer existing file; increasing polling cannot create a fresh phone export. Keep this functioning route until a phone bridge is tested.

## HCGateway alternative

[HCGateway's own README](https://github.com/ShuchirJ/HCGateway) describes an Android APK plus a REST server, with customizable two-hour transfers and an in-app force-sync option. It supports self-hosting and relevant data types, including sleep, steps, heart rate, weight, and body fat. The author explicitly describes both API and app as still under development. Its server adds MongoDB; custom server-triggered push needs a custom mobile build/Firebase configuration.

It could shorten prototyping, but a backend deployment alone is insufficient: install the APK, grant phone permissions, connect it to the private instance, and verify record identities, updates/deletions, sleep stages, and background behavior. Do not use the public hosted instance for this local-first project. Those checks have not been performed. A purpose-built companion would fit Milon's existing FastAPI/SQLite stack more directly, at the cost of building and maintaining Android code.

## Direct Garmin API

Garmin's official Connect developer program is for business/enterprise use and requires application approval; it is not an immediately available personal-account API. Garmin documents OAuth 2.0 and typical integration of one to four weeks after the application process. [Garmin program FAQ](https://developer.garmin.com/gc-developer-program/program-faq/)

Update, 2026-10-05: Milon now imports GPS routes, verified running sensor series, steps, sleep and VO2max directly through the unofficial `garminconnect==0.3.17` client and a locally stored authenticated session. Recovery observations supplement the dashboard. Source reconciliation protects direct records from subsequent HC imports; Arboleaf and historical Samsung data retain their existing route. Capabilities and limitations are documented in [Garmin direct-data research](garmin-direct-data.md). This is separate from Garmin's official developer program and depends on Connect's private interfaces. [Client source](https://github.com/cyberjunky/python-garminconnect/tree/0.3.17)
