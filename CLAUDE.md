# CLAUDE.md — Projekt-Memory: Milon

Persönliches, **lokal laufendes** Fitness-Dashboard mit LLM-Coach. Single-User, local-first.
Source of Truth für Architektur & Plan: **`ARCHITECTURE.md`** (lies sie bei größeren Schritten).
Phasen-Bootstrap: `CLAUDE_CODE_BOOTSTRAP.md`.

Drei Analysebereiche — **Körper · Laufen · Kraft** — plus **Coach**. Kernfrage:
„Wo werde ich besser, wo schlechter?" Bewusst schlank.

## Konventionen
- **UI deutsch, Code/Identifier englisch.**
- Kleine, lauffähige Schritte; nach jedem Schritt kurz zusammenfassen.
- Secrets nur in `.env` (gitignored). Gesundheitsdaten nie committen (`data/` ist gitignored).

## Struktur (weicht bewusst von ARCHITECTURE.md ab)
- **`client/`** (Next.js) und **`server/`** (FastAPI) statt frontend/backend; **kein** docker-compose.
- **Root `.env`** → nur `OPENAI_API_KEY` (Design-Asset-Generierung, gpt-image-2).
- **`server/.env`** → App-Secrets: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `HEVY_API_KEY`, `FDDB_USER/PW/COOKIE/PHPSESSID`, optional `DATABASE_URL`.
- **`client/.env`** → `NEXT_PUBLIC_API_URL`.
- **`data/`** (gitignored): `tracker.db` (App-DB) + `incoming/` (manuell abgelegte Quell-Exporte).
- **`design/`**: Design-Exploration (Playground + gewählte Studie). Siehe unten.

## Stack & Versionen (verifiziert 2026-06)
- Server: **FastAPI 0.138**, **SQLModel 0.0.38** (SQLite), **uvicorn 0.49**, **pandas 3.0** (CSV-Parser), **openai 2.43** (OpenRouter-Coach), pydantic-settings, tzdata.
- Client: **Next.js 16.2** (App Router, TS) + Tailwind + shadcn/ui + Tremor/Recharts (Phase-1-Frontend, noch nicht gebaut).

## Starten (VS Code → Task ausführen, siehe `.vscode/tasks.json`)
- „Server: FastAPI (Dev)" → `uvicorn app.main:app --reload` (cwd `server/`), Port 8000, Docs `/docs`.
- „Client: Next.js (Dev)" → `npm run dev` (cwd `client/`), Port 3000.
- „Start: Server + Client" (kombiniert) · „Design: HTML-Server" → Port 4321.
- DB liegt **immer** unter `<repo>/data/tracker.db` (cwd-unabhängig; relative `DATABASE_URL` wird an Root gebunden).

## Design-Entscheidung (fix)
**Klar & Klinisch** (UI) + **Sportler-Silhouette** (aus Neo-Sport), in klinischer Palette.
Referenz: `design/klar-klinisch.html`. Tokens: bg `#fbfcfc`, surface `#fff`, text `#14201f`,
muted `#4d5b5a`, border `#e2e7e8`, **accent Teal `#0a6e66`**, accent2 `#5cb8af`, bad `#b3261e`;
Fonts **Inter Tight** (Display) / **Inter** (Body); Radius ~6–8px. Silhouetten-Assets in
`design/assets/klar-sport/` (run-ink-slash = Hero, + teal-solid/monoline/duotone, kraft, koerper).
→ Beim Frontend-Bau diese Tokens als Tailwind-Theme + Assets nach `client/public/` übernehmen.

## Datenquellen — verifizierte Format-Notizen
Siehe ARCHITECTURE.md §3. **An echtem Export verifiziert (2026-06-23, `data/incoming/health_connect_export.db`):**
- HC-Export = **eine** SQLite-DB `health_connect_export.db` in der täglichen Zip (Vollabzug → idempotenter Import durch „HC-Zeilen ersetzen").
- Zeitstempel: **epoch-Millisekunden (UTC)** + Spalte `*_zone_offset` in **Sekunden** (7200 = Europe/Berlin). Lokale Wandzeit = utc + offset.
- **Gewicht in GRAMM** (`weight_record_table.weight`, z. B. 73150 → 73,15 kg) → `/1000`. Quelle Arboleaf (app_info_id 5).
- Körperfett: `body_fat_record_table.percentage` (direkt). Mit Gewicht über denselben Zeitstempel zu einer `body_measurements`-Zeile mergen.
- **WICHTIG – Datenqualität:** Mehrere Apps schreiben Körper-Werte in HC (Arboleaf, Google Fit, Samsung Health, …). Google Fit/Samsung liefern Ausreißer (z. B. 0,0 % / 22,6 % KFA → Trend-Spikes). Der Parser filtert Gewicht **und** KFA auf die Waagen-App über `application_info_table.package_name` = `settings.body_source_package` (Default **`com.qingniu.arboleaf`**; leer = alle Quellen). Nach Änderung HC-Import `full=True` laufen lassen, um Alt-Werte zu ersetzen.
- VO2max: `vo2_max_record_table.vo2_milliliters_per_minute_kilogram`.
- Distanz: `distance_record_table.distance` in **METERN**, als feingranulare **Segmente** → pro Session im Zeitfenster summieren, `/1000` → km (Sanity-Filter beachten, §5.2).
- Schritte: `steps_record_table.count`, Tagessumme über `local_date` (= epoch-Tag-Nummer). **WICHTIG – Quelle:** Galaxy Watch (Samsung Health) **und** Google Fit tracken parallel. **Maßgeblich = nur die Watch** (`settings.steps_source_package`, Default `com.sec.android.app.shealth`): Google Fit zählt das Handy und untertreibt an Tagen ohne Handy (Niedrig-Schritt-Tage von 949–4500). Verifiziert: 116 von 448 Tagen sind nur-Google-Fit (= watch-lose Tage) und fallen bewusst weg → 332 echte Watch-Tage, `best` 27.162 statt 30.874. Leerer Config-Wert = Fallback `MAX(SUM(count) per app_info_id)` je Tag (entdoppelt, aber inkl. Handy-Tage). Nach Änderung HC-Import `full=True`.
- `exercise_type` = **android.health.connect ExerciseSessionType** (alphabetisch): **4=Radfahren (BIKING)**, **33=Laufen**, **45=Kraft**, **53=Gehen**, **58=Laufband** (verifiziert via App-Attribution + Distanz/Speed). Rad-Sessions kommen aus Samsung Health (kurze Pendelfahrten 2–3 km @ ~10–15 km/h). Codes 34/49 = noch ungenutzt (Gehen-Varianten/ohne Distanz).
- **Höhenmeter:** `elevation_gained_record_table` **leer** → bestätigt „nicht verfügbar".
- **Herzfrequenz-Werte** liegen in `heart_rate_record_series_table` (1,2 Mio Zeilen), NICHT in `heart_rate_record_table` → avg_hr vorerst zurückstellen.

## Phasen
- **Phase 1 (jetzt):** Scaffold; SQLite-Schema (§4); Upload-Import + Parser (HC/Hevy/FDDB); 3 Dashboards; Context-Injection-Coach.
- **Phase 2:** Auto-Syncs (Hevy-API, FDDB-Login, **HC via rclone/Drive-Watcher** — Zip kommt täglich aus Drive), Tool-Calling-Coach.
- **Phase 3:** MCP-Server. **Phase 4:** Cloudflare-Hosting.

## Status (2026-06-23)
Design abgenommen. **Backend Phase 1 weit:** alle 3 Quellen ingesten live in die DB —
Health Connect (`data/incoming/health_connect_export.db`), **Hevy via API** (`/ingest/hevy`),
**FDDB via Cookie `fddb`** (`/ingest/fddb`), plus `/ingest/refresh`. Metrik-Schicht
(`app/metrics/` body/running/strength) + REST (`/metrics/*`) fertig & an echten Daten verifiziert
(TestClient, alle 200). **Coach (Context-Injection) fertig & live getestet** (`/coach/daily|weekly|chat|reports|reports/{id}|snapshot`,
OpenRouter `deepseek/deepseek-v4-flash`) — speichert **Prompt (Messages als JSON) + Antwort** in `coach_reports`
(Spalte `prompt`; leichte Migration in `db._run_migrations`).
**Phase 1 KOMPLETT:** Frontend `client/` (Next 16 + Tailwind v4, Inline-SVG-Charts) mit 5 Seiten —
Übersicht/Körper/Laufen/Kraft/Coach — im Klar-&-Klinisch-Design, live gegen die API, verifiziert.
Design-Tokens in `client/app/globals.css` (@theme), Komponenten in `client/components/`, API-Client `client/lib/api.ts`.
Backend-CORS erlaubt jeden localhost-Port (`allow_origin_regex`). Start: Task „Server: FastAPI (Dev)" + „Client: Next.js (Dev)".
FDDB-Auth-Detail: Login-Cookie heißt **`fddb`** (Wert = `userid,token`); PHPSESSID optional.

**Phase 2 (Automatik) – Kern fertig:** `app/sync/scheduler.py` (APScheduler, startet in `main.lifespan`).
Jobs: Hevy-Polling (alle 6 h), FDDB täglich 04:30, HC-Ordner-Scan (alle 10 min → importiert `data/incoming/health_connect_export.db` bei neuer Datei via mtime-Cursor). Status/Detail je Quelle in `sync_state`;
`GET /ingest/status`. **FDDB-Auto-Login** ersetzt den ablaufenden Cookie: POST `account/?action=login`
(`loginemailorusername`/`loginpassword`) → frischer `fddb`-Cookie (Fallback auf gespeicherten Cookie).
Manuelle `/ingest/{hevy,fddb,health-connect,refresh}` protokollieren ebenfalls in `sync_state`.
Toggle: `SCHEDULER_ENABLED` (Default true).
**Imports sind inkrementell/idempotent** (kein Full-Replace mehr): HC/FDDB append-only via `db.upsert`
(SQLite ON CONFLICT, nur neue Zeilen; FDDB-Dedup mit Surrogat-Hash-Key bei fehlender `interne_id`;
StepsDaily = DO UPDATE), **Hevy echt inkrementell** via `/v1/workouts/events` + Cursor in `sync_state`
(inkl. Updates/Löschungen, Detail je Workout über `/v1/workouts/{id}`). `?full=true` erzwingt eine Voll-Reconciliation.
Frontend-Charts (`client/components/charts.tsx`) haben Y-Werteskala + X-Zeitachse (Pace als m:ss).
**Tool-Calling-Coach (§6.2b) fertig:** `POST /coach/ask` — das LLM ruft die metrics-Tools selbst auf
(`coach/tools.py` = Tool-Schemas + Dispatcher, `client.complete_with_tools` = Tool-Loop), Frontend-Chat
nutzt `/coach/ask`; Prompt inkl. vollständigem Tool-Trace + Antwort in `coach_reports` (kind `chat-tools`).
**UX-Politur:** Coach-Antworten als **Markdown** (`marked` + `client/components/Markdown.tsx` + `.md`-Styles in globals.css);
**Coach-Kosten/Token-Statistik** (`GET /coach/stats`; OpenRouter `usage.include` → `coach_reports.cost_usd/prompt_tokens/completion_tokens`, oben auf der Coach-Seite);
**manueller Refresh-Button** im Menü (`Shell` → `/ingest/refresh` + `/ingest/status`, zeigt „zuletzt").
**Reiter-Ausbau (1/2):** Kraft = **alle Übungen** (`GET /metrics/strength/exercises`) mit **Suchfeld** + Gruppierung nach **Muskelgruppe** (Heuristik `strength._muscle_group`, DE+EN-Stichworte); Körper = **Mehr-Linien-Chart** (roh/7-Tage/EWMA via `MultiTrend` in charts.tsx) + **Wochenmittel** (`GET /metrics/body/weight-weekly`).
**Fortschritts-/Optik-Seite** (`/fortschritt`): Foto-Timeline, je Eintrag Datum + Notiz + bis zu 5 Ansichten (Vorne/Seite/Hinten + 2 Posen).
Crop (Pan/Zoom auf 3:4) + Rescale + JPEG-Compression im Browser (`client/components/PhotoPicker.tsx`, Canvas); Server vereinheitlicht via **Pillow**
(EXIF-Transpose, max. Kante 1080, JPEG q85), speichert in **`data/progress/`** (gitignored), liefert über **`/media/progress/<datei>`** (StaticFiles).
DB-Tabelle `progress_entries`; API `app/api/progress.py` (`GET/POST-multipart/DELETE /progress`).
**Settings-Seite** (`/einstellungen`): `GET/PUT /settings` (`app/api/settings.py`) — Keys maskiert (last-4-Hint), Modell + Scheduler-Toggle.
PUT aktualisiert **live** (`settings.*` mutiert, Scheduler wird gestartet/gestoppt) UND persistiert via `config.update_env_file` in **server/.env** (Kommentare bleiben). Nur übergebene/nicht-leere Felder werden geändert.
**Übersicht v2 + Grafiken:** Übersicht zeigt Wochenvergleich (km/Tonnage/Schritte/Gewicht vs. Vorwoche), „Letzte Aktivitäten"
(`GET /metrics/activity/recent`, Läufe+Workouts), Schritte (`GET /metrics/body/steps`) und einen Coach-Snippet (letzter Report).
7 **Muskelgruppen-Icons** (gpt-image-2, Ink+Teal) in `client/public/img/muscle/` → Kraft-Gruppen-Header; Empty-State-Grafik `client/public/img/empty.png`.
**Damit ist die gesamte Reiter-/Feature-Roadmap des Users abgearbeitet.**

**Phase 3 (MCP) fertig:** `server/app/mcp/server.py` (FastMCP, stdio) exponiert **15 Tools** über dieselbe `metrics/`-Schicht
(get_overview/snapshot/weight_trend/tdee/bodyfat/steps/running_volume/pace/vo2max/strength_summary/exercises/tonnage/rpe/e1rm/recent_activity) —
liest dieselbe `data/tracker.db`. Start: `python -m app.mcp.server` (stdio). **`.mcp.json`** im Repo-Root registriert ihn für **Claude Code**;
für **Claude Desktop** den `mcpServers.milon`-Block aus `server/app/mcp/claude_desktop_config.example.json` in
`%APPDATA%/Claude/claude_desktop_config.json` einfügen (PYTHONPATH=server, kein cwd-Bedarf). Verifiziert per echtem stdio-Handshake (15 Tools, echte Daten).
Damit sind **Phase 1–3** umgesetzt; offen nur noch **Phase 4** (Cloudflare-Hosting) + optional rclone-Drive-Pull.

**Mobil-Optimierung:** `Shell.tsx` ist responsive — Desktop = feste Sidebar, Handy = sticky Top-Bar + Slide-in-Drawer (schließt bei Routenwechsel);
`viewport`-Export in `layout.tsx`. Per Workflow-Audit (8 Agents) entzerrt: responsive Padding (`p-4 sm:p-5`), schmalerer Chart-Y-Gutter (`w-10 sm:w-14`),
Bars-Label-Ausdünnung (max ~7 Labels), Truncation langer Übungs-/Werte-Namen, Markdown-Coach-Tabellen horizontal scrollbar (`.md table` display:block+overflow-x),
StatRow als Grid auf Mobile, 16px-Inputs (`text-base sm:text-sm`) gegen iOS-Auto-Zoom. Verifiziert auf 375px (Drawer, Charts, Listen).
**HC-Drive-Pull (2026-06-24, Phase 2 erledigt):** `app/ingest/drive.py` zieht die tägliche HC-Export-Zip aus Google Drive, entpackt `health_connect_export.db` atomar nach `data/incoming/` und importiert. Scheduler-Job `sync_hc_drive` (täglich 05:00, nur wenn `HC_DRIVE_FILE_ID` gesetzt) + Endpoint `POST /ingest/health-connect-pull` + in `/ingest/refresh` integriert. **Wichtiger Befund:** „Jeder mit dem Link"-Inhalte sind über einen anonymen Drive-**API-Key NICHT erreichbar** (verifiziert: Ordner-Listing → leer, files.get(folderId) → 404; embeddedfolderview → 401, auch das was gdown nutzt). Der einzige no-OAuth-Weg ist daher der **keylose Download per fester Datei-ID** (`gdown.download(id=…, fuzzy=True)` → handhabt uc-Confirm-Token + große Dateien). Config: **`HC_DRIVE_FILE_ID`** (aus dem Datei-Freigabelink `…/file/d/<ID>/view`; akzeptiert auch vollen Link). `GOOGLE_API_KEY`/`HC_DRIVE_FOLDER_ID`/`HC_DRIVE_FILENAME` bleiben optional/Legacy (nur für einen *wirklich* öffentlichen Ordner). gdown ist jetzt Dependency. **Funktioniert dauerhaft, solange der Export dieselbe Datei *überschreibt* (stabile ID); legt das Tool sie täglich neu an, bricht der Link → dann Service-Account (robust, name-basiert).**

## Erweiterungen (2026-06-23, nach Phase 1–3)
- **Gesundheit-Seite** (`/gesundheit`, Nav nach Körper): allgemeine Gesundheitswerte aus HC — Schritte (Trend 30 T + Wochenschritte) + **Radfahren** (`exercise_type 4` = BIKING, Samsung Health). `app/metrics/health.py` (steps_*/cycling_*), `/metrics/health/*`, Coach-Tools/-Snapshot + MCP. Übersicht-Karte zeigt Schritte+Rad. **Schritte jetzt watch-only** (s. o.).
- **Gewichts-/Komposition-Prognose** (Körper-Seite, kompakt — keine großen Charts mehr): `body.weight_forecast()` = lineare EWMA-Regression (30 T), als +7T/+30T-Werte. **KFA NICHT mehr eigenständig extrapoliert** (verrauschtes Bioimpedanz-Signal implizierte unplausiblen Muskelverlust). Stattdessen `body.composition_forecast()` (per Methoden-Panel-Workflow 2026-06-24): am Gewichtstrend verankert, Abnahme über Magerverlust-Anteil p in Fett/FFM gesplittet, KFA=Fett/Gewicht abgeleitet → 3 Szenarien (p=0 „Magermasse erhalten"/p=0,15 „Erwartet" Headline/p=p_obs „Waagentrend") als KFA-Spanne + Bioimpedanz-Caveat. `/metrics/body/{weight,bodyfat,composition}-forecast`; `bodyfat_forecast()`=Erwartet-Szenario für Coach/Snapshot/MCP (`get_forecast`).
- **Fortschritt-Workflow neu:** kein Dauerformular mehr — „+ Neuer Eintrag" öffnet eine Draft-Karte (`components/EntryEditor.tsx`, Datum/Notiz/5 Slots), Speichern legt an + schließt sie, Abbrechen verwirft; Karten chronologisch (taken_on desc). **Drag-and-drop** im `PhotoPicker` (Foto in Slot/Canvas ziehen).
- **PhotoPicker-Bugfix (wichtig):** alter Stale-Closure-Bug (`setTimeout(exportBlob)` las `img`-State = null beim 1. Foto → `onChange(null)`, Upload still kaputt außer man zoomte vorher). Jetzt `exportFrom(image, zoom, center)` direkt aus dem frisch geladenen Bild (kein setTimeout), objectURL-revoke, dragleave-Guard. E2E verifiziert (Drop → Save legt Foto an).
- **Übungs-Detailseiten:** Kraft-Zeilen sind Links → `/kraft/[exercise]` (`strength.exercise_detail(name, period)`, `/metrics/strength/exercise`). Zeitraum-Toggle **1M/3M/12M/Gesamt**, KPIs (best e1RM, Top-Gewicht, Tonnage, Ø RPE), **Entwicklung erste→letzte Session** (e1RM/Gewicht/Tonnage/RPE-Δ) + Charts (e1RM/Top-Gewicht/Tonnage/RPE je Session). `exercise_type`-Codes: 84 Übungen, keine Slashes → `encodeURIComponent` sicher.

## Erweiterungen II (2026-06-23)
- **Mobil-Zugriff via Next-Proxy:** Frontend nutzt relativen `/api`-Pfad (`api.ts` BASE), `next.config.ts` `rewrites` proxien `/api/:path*` → `http://127.0.0.1:8000`. Damit erreicht das Handy (`http://<PC-IP>:3000`) das Backend **ohne CORS und ohne Firewall-Freigabe für :8000** (nur Node/:3000 muss erreichbar sein). Hintergrund: Netzwerkprofil **Public**, venv-`python.exe` hat keine Inbound-Regel. CORS-Regex (LAN-IPs) bleibt als Fallback. `mediaUrl` ist jetzt `/api/media/progress/...` (proxied, verifiziert). Backend-Task bindet `0.0.0.0`.
  - **Coach-Lade-Animation (2026-06-24):** Während der Coach rechnet (`/coach/ask|daily|weekly`, 20–40 s) zeigt `components/CoachThinking.tsx` ein zentriertes Overlay-Modal mit **einer zufälligen von vier Sport-Animationen** (Inline-SVG + scoped CSS, `prefers-reduced-motion`-sicher) + **rotierenden Gags** aus `lib/quips.ts` (100 Sprüche, alle 2,8 s zufällig, Fade). Esc/Klick blendet aus (Request läuft weiter), „läuft seit Xs". Eingehängt in `app/coach/page.tsx` via `busy`-State. Die vier Animationen (#5 Wiederholungen, #9 EKG-Linie, #15 Trend-Linie, #20 Stoppuhr) wurden per **6-Agenten-Workflow** generiert (24 Kandidaten) und in der Galerie `design/coach-animations.html` (Design-Server :4321) ausgewählt; der erste Versuch mit einer animierten Strichfigur wirkte „gruselig" → verworfen zugunsten clean-geometrischer Motive. E2E verifiziert.
  - **WICHTIG – Proxy-Timeout (2026-06-24):** Der Next-Rewrite-Proxy hat per Default nur **30 s** Timeout (`proxyTimeout || 30000` in `proxy-request.js`). Der Tool-Calling-Coach `/coach/ask` braucht bei vielen Tool-Aufrufen 20–40 s → Proxy antwortete mit **500**, obwohl das Backend sauber 200 lieferte (direkt :8000 = 200, durch :3000 = 500 @ exakt 30 s — so diagnostiziert). Fix: `experimental: { proxyTimeout: 120_000 }` in `next.config.ts` (kein HMR → Client-Dev-Server neu starten). Verifiziert: derselbe Call durch den Proxy jetzt 200 @ 30,4 s.
- **Ernährungs-Cockpit** (`/ernaehrung`, Nav nach Körper): `metrics/nutrition.py` aus FDDB (kcal **+ Makros Protein/KH/Fett — waren 494 Tage ungenutzt!**). Protein Ø/Tag vs **Ziel** (`PROTEIN_PER_KG=1.8` × 7-Tage-Gewicht), kcal Ø vs TDEE (Defizit), Makro-Split, Ziel-Tage. `/metrics/nutrition/{summary,protein,kcal,daily}`.
- **Recomp/Magermasse** (Körper-Seite): `body.lean_mass_trend/summary` = geglättetes Gewicht × (1 − KFA%) → FFM + Fettmasse + Δ über 90 T („behalte ich die Muskeln?"). `/metrics/body/lean-mass`.
- **PR-Trophäen + Stagnations-Detektor:** `strength.personal_records` (Allzeit-PR je Übung, erste Session = Baseline) → Übersicht-Feed (klickbar). `strength.exercise_status` (np.polyfit e1RM-/RPE-Steigung über letzte 6 Sessions → progress/stall/regress/**deload** wenn e1RM flach + RPE↑) → Badge auf Detailseite + in `exercise_detail`. `/metrics/strength/records`.
- **Trainings-Heatmap & Streak** (Übersicht): `activity.consistency` (Tages-Level 0–3 aus Kraft/Lauf/Schritten, Streak überspringt leeres „heute"). `components/Heatmap.tsx` (GitHub-Style), `/metrics/activity/consistency`. Konsistenz-Karte zeigt **letztes Jahr** (365 T).

## Erweiterungen III (2026-06-24)
- **Gesamtstärke-Index** (Kraft-Seite, oben): **ein** Wert „werde ich insgesamt stärker?". `strength.strength_index(period=1m|3m|6m|12m)` — **WÖCHENTLICH aufgelöst & drift-frei** (2026-06-24, per Methoden-Panel validiert). **Wichtiger Befund:** naive Umstellung von Monats- auf Wochen-Buckets treibt den Index durch **Chain-Drift** (pfadabhängige Verkettung mit wechselndem Übungs-Basket) von ~114 auf ~168 hoch — je mehr Verkettungs-Links, desto mehr Drift (53 Wochen-Links statt 13 Monats-Links). **Lösung (Hybrid):** der validierte **Monats-Backbone bleibt unverändert** (`_monthly_backbone()`: verkettete Monats-e1RM-Links, muskel-balanciert `1/G·1/n_g`, clip ±0,25, Endwert ~114) = drift-freies Rückgrat. Wochenauflösung entsteht NICHT durch Woche-zu-Woche-Verkettung, sondern indem **jede ISO-Woche (W-SUN) DIREKT gegen ihren Anker-Monat** (Monat der Wochenmitte) gemessen wird (`offset_w` = muskel-balanciertes clip-Log-Ratio Wochen- vs. Monats-Best-e1RM) → **0 zusätzliche Ketten-Links → kein Drift**. **Per-Monat-Re-Zentrierung** (μ_m abziehen) pinnt den Monatsschnitt der Wochen exakt auf den Backbone-Anker (killt den MAX-pro-Bucket-Bias). Monatsanker linear aufs Wochenraster interpoliert (laufender Monat geklemmt); `weekly_raw = anchor·exp(κ·(offset−μ))`, κ=1,0; thin/leere Wochen (cohort<3) interpoliert (log-Raum, limit 2), NaN-Fallback auf Anker (nie 500); kausale **EWMA α=0,25** (roughness ~1,0) = die **Wochenkurve** (`series`, reine Auflösung/Anzeige). **`value`/Δ%/Trend/Treiber kommen aus dem drift-freien Monats-Backbone** (`disp` = 2-Pkt-geglättet, Fenster-Monate `<= target`, ±3 %) — reproduziert exakt die validierten Monatszahlen und hält value/„Basis 100"/Δ konsistent (so misst der 12M-Δ NICHT gegen die verrauschte erste Woche). `cohort_size`/`groups` = aktiver Roster des letzten Monats. Liefert `value`, `base_week` (Trainingsstart), `window_delta_pct`, `trend`, `series[{week,raw,smoothed,anchor}]`, `drivers_up/down`, `cohort_size`, `groups`. **An echten Daten verifiziert (+ adversarialer Review, 6 Funde gefixt):** value=115 (== Backbone, drift_ok), 53 Wochenpunkte, roughness 1,02; 3M −5,8 % fällt, 12M +14,5 % steigt, 1M −3,4 % (Treiber nie leer); cohort 15/6; Treiber Leg Press/Shrug, Bremse Triceps/Lateral-Raise — identisch zum validierten Backbone. (Eligibility weiter global ≥3 Trainingstage; **Volumen-Gewichtung** nach Satz-Anteil getestet → verschiebt Endwert 114→117, ändert Treiber aber kaum → vorerst Gleichgewichtung; Daten zeigen fast vollständigen **Programmwechsel** vor ~6 Mon., deutsch→englisch benannte Übungen, 18 aktiv/16 Staples.) `/metrics/strength/index?period=`; Coach-Tool `get_strength_index` + MCP-Tool (16 MCP-Tools) + Snapshot-Zeile. UI: `client/app/kraft/page.tsx` Karte „Gesamtstärke" (Headline 4xl + Trend-Badge + 1M/3M/6M/12M-Toggle + `MultiTrend` Woche-roh/Monats-Anker/Index, X-Labels adaptiv Tag bzw. Monat + Treiber/Bremse-Links + Caveat).
- **Stärke ↔ Energiebilanz** (Kraft-Seite, Karte unter „Gesamtstärke"): verknüpft den Wochen-Index mit TDEE/Defizit (`strength.strength_energy()`, lazy `from . import body`; aligned `strength_index('12m').series` ↔ `body.tdee_trend(days=400)` wöchentlich, Defizit = `tdee_avg − intake`). **EHRLICHE Statistik (wichtig gegen Fehldeutung):** `corr_index_deficit` = NIVEAU-Korrelation ist **trendgetrieben/scheinbar** (beide laufen als Zeittrend; an echten Daten −0,49, kumuliert −0,88), `corr_change_deficit` = **entkoppelt** (Woche-zu-Woche-Δ, ~0,01 = kein Dauergesetz) ist der belastbare Wert. Confounder: Programmwechsel + Trainingsphasen. Liefert zusätzlich **Phasen-Read** der jüngsten ~8 Wochen (`phase`/`phase_label`: cut „Cut kostet Kraft"/recomp/aufbau/stabil; `recent_index_delta`, `recent_deficit_avg`) — an echten Daten: Phase „cut", Index −5,1 bei Ø +151 kcal Defizit. `/metrics/strength/energy`; **Coach-Tool `get_strength_energy`** (Serie ausgedünnt) + **MCP-Tool** (jetzt 20) — beide mit Deutungs-Hinweis im Tool-Text. UI: neue `DualAxisTrend`-Komponente (`charts.tsx`, zwei Y-Skalen links/rechts + Defizit-Nulllinie) zeigt Index (Teal) vs. Defizit (Amber, gestrichelt) über 52 Wochen; Karte mit Phasen-Badge + beiden Korrelationen (Niveau „scheinbar" vs. Woche-zu-Woche „belastbar") + Caveat. Card-Guards `&& .series &&` (kein Crash bei `{}`).
- **Nav-Icons + Chart-X-Achsen (2026-06-24):** `Shell.tsx` hat pro Nav-Eintrag ein **Inline-SVG-Icon** (`ICON`-Map, lucide-Pfade, `currentColor` — keine Icon-Lib). `MultiTrend` + neue `DualAxisTrend` zeigen jetzt **verteilte X-Achsen-Labels** (`pickTicks`→5, `flex justify-between`, gutter-aligned) statt nur Start–Ende-Range (Gesamtstärke 3M=Tagesdaten/12M=Monate; `AreaTrend`/`Bars` hatten das schon).
- **RIR/Volumen im Gesamtstärke-Index — geprüft, BEWUSST NICHT geändert (2026-06-24):** User fragte, ob RIR (Reps in Reserve = 10−RPE) und Volumen einfließen. Index nutzt **reinen e1RM** (Epley `weight·(1+min(reps,12)/30)`, Peak je Übung) — **kein RIR, kein Volumen** (bewusst ein Maximalkraft-Index). RIR-Korrektur (effektive Reps = reps + (10−RPE)) an Daten getestet: (a) User trainiert **am Versagen** (Median-RPE 10, Ø-Korrektur nur +0,6 Reps) → Effekt winzig; (b) **RPE existiert erst ab Okt 2025** (vorher 0 %, dann 95–100 %) → Korrektur nur der zweiten Hälfte würde einen **Schein-Sprung** erzeugen (12M-Δ 14,5 %→17,1 %, Endwert 115→117, Kurvendiff Ø +0,7/max 2,6 P) = Abdeckungs-Artefakt; (c) Index ist **ratio-basiert**, konstanter RIR-Bias kürzt sich ohnehin. → **raw e1RM bleibt**. Volumen wird separat getrackt (Wochen-Tonnage-Chart + Tonnage auf Übungs-Detailseiten); kein Volumen in den Stärke-Index mischen (sonst nicht mehr „werde ich stärker").
