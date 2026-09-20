# Fitness-Tracker — Architektur & Plan

## Übungsdetails: ein Diagramm je Messgröße (2026-09-20)

Standardzeitraum ist 3M; 1M/12M/Gesamt bleiben erreichbar. Ein `RunTrendChart` schaltet
zwischen e1RM, schwerstem Trainingsgewicht, bewegter Last und RPE um. Headline und
Vergleich beziehen sich auf den letzten bzw. ersten/letzten Trainingstag im Fenster;
fehlende RPE-Werte werden nicht ersetzt, ein einzelner Tag liefert keinen Vergleich.
Bestleistungen, Umfang und weitere Kennzahlen stehen im Detaildialog. Statuslabels
in der API beschreiben e1RM-/RPE-Verläufe ohne Ermüdungsdiagnose oder Deload-Empfehlung;
historische Statusschlüssel bleiben kompatibel. Der Status verwendet weiterhin die
jüngsten erfassten Trainingstage unabhängig vom gewählten Fenster und ist so beschriftet.

## Kraft: Entwicklung zuerst (2026-09-20)

Die Hauptseite zeigt Gesamtstärke mit einer geglätteten Wochenlinie, Zeitraumwahl
und den jeweils zwei größten steigenden/fallenden Beiträgen. Hauptwert und Δ bleiben
unverändert aus dem Monatsindex; Rohlinie, Monatsanker und Methodik liegen im Dialog.
Übungen sind standardmäßig auf die letzten 90 Kalendertage begrenzt; „Alle Übungen“
öffnet die gesamte Historie, die Suche arbeitet innerhalb dieser Auswahl. Letzter
Trainingstag und geschätztes 1RM ersetzen die dichte Peak-/Satzzahl-Zeile.
Der kompakte Umfang nennt ausdrücklich die letzte erfasste Trainingswoche mit Datum.
Tonnagehistorie, RPE und Stärke/Energiebilanz laden erst bei geöffnetem Detaildialog.
Backend, Coach und MCP beschreiben Zusammenhänge ohne Kausalitäts- oder Recomp-Urteil;
fehlende Korrelationen bleiben nicht berechenbar. Die Energiebilanz übernimmt die
in Q19 beschlossene gleiche Kalenderglättung (`tdee_avg - intake_avg`).

## Körpermodelle: Messabdeckung und gemeinsame Zeitfenster (2026-09-20)

Nach Vergleich der Varianten (Q19–21) mittelt `adaptive_tdee` die zugehörige Zufuhr
über dieselben Kalendertage wie TDEE; `tdee_trend.intake_avg` verwendet dieselbe
Glättung. `estimate_days` zählt Schätztage im Fenster, `provisional` markiert weniger
als die Hälfte der möglichen Tage (standardmäßig <7/14), keine Validitätsgarantie.
Fett-/fettfreie Masse nutzt ausschließlich gemeinsame Gewicht-/BIA-Messtage,
identische 7-Kalendertage-Fenster und mindestens drei Paare; fehlende Tage bleiben
null. Zusammenfassungen nennen reale Anfangs-/Enddaten und Messanzahl.
Gewichtsfortschreibung: EWMA nur beobachteter Tage, Neustart nach >7 fehlenden Tagen,
mindestens 14 Messtage und 21 verstrichene Tage im letzten maximal 30-Tage-Fenster.
Ohne Abdeckung liefert die API `available:false` mit Grund, keine Projektion.
Zusammensetzungsszenarien benötigen zusätzlich ausreichend gepaarte Messungen am
gleichen Ausgangstag. Ihr Ausgangsgewicht und Gewichtsziel entsprechen exakt der
Gewichtsfortschreibung; der BIA-Anteil teilt dieses Ausgangsgewicht auf.
Coach und UI respektieren die Pausen. Die Regeln sind Produktentscheidungen aus
dem Vergleich, kein belegter Genauigkeitsgewinn. Vergleichsprotokoll:
`docs/research/body-model-comparison.md`; persönliche Ergebnisse bleiben in `data/`.

## Körper: klare Hauptansichten (2026-09-20)

Gewicht und BIA-Körperfett zeigen jeweils eine 7-Kalendertage-Linie mit optionalen
Rohwerten, Messdatum und neutraler Einordnung. Lange Messlücken erhalten null-Werte
statt ungültigem JSON oder einem aus alten Messungen fortgesetzten 7-Tage-Mittel.
Wochenwerte, abgeleitete Massen und Fortschreibungen laden erst im Detaildialog.
Fettfreie Masse wird nicht als Muskelmasse bezeichnet; Kompositionsszenarien sind
gleichrangige Rechenannahmen, keine Wahrscheinlichkeits- oder Unsicherheitsintervalle.
Das feste 15%-Szenario behält seinen API-Schlüssel `expected`, trägt aber einen
ausdrücklichen Annahme-Text. Modellrechnungen bleiben unverändert; offene methodische
Fragen und Evidenz stehen in `docs/research/body-composition-evidence.md`.
`EnergyBalance` zeigt auf Körper nur eine Zusammenfassung, unter Ernährung dagegen
die vollständige Bilanz und den TDEE-Verlauf. Die rückwirkende konstante TDEE-Linie
im Kalorienchart entfällt. TDEE und Kompositionsszenarien liefern ihren Ausgangstag.

## Übersicht: Entwicklung und Aktivität (2026-09-20)

Drei Entwicklungskarten zeigen das neutrale 7-Tage-Gewichtsmittel, standardisierten
Puls bei 6:00/km (Minute 30, VO₂eq ergänzend) und den Gesamtstärke-Index. Datenstände,
Messabdeckung und fehlende Vergleiche bleiben sichtbar; Karten laden unabhängig.
`body.summary` erhält Kalenderlücken im 7-Tage-Mittel und liefert Messdatum sowie
Messtage beider Vergleichsfenster. `/metrics/activity/overview` vergleicht die letzten
sieben lokalen Kalendertage inklusive heute mit den sieben davor: Laufkilometer,
Hevy-Workoutanzahl und Schrittmittel über erfasste Tage. Schrittveränderungen werden
nur bei vollständiger Abdeckung beider Fenster gezeigt. Mengenänderungen sind neutral.
Konsistenz zeigt 84 Tage, das Jahr lädt auf Anfrage; Aktivitäten und ein datierter
Coach-Auszug schließen die Seite ab. Ausführliche Analysen bleiben auf Fachseiten.

## Laufanalyse: kompakte Darstellung (2026-09-20)

Die Laufen-Seite gliedert sich in Training, Fitness und Bestleistungen. Der neue
Endpoint `/metrics/running/week-overview` liefert Kilometer, Laufanzahl und Minuten
der aktuellen Kalenderwoche bis jetzt sowie der gesamten Vorwoche; leere Wochen
bleiben null Läufe. Wochenkilometer zeigen zwölf Kalenderwochen inklusive Lücken.
Die beiden Fitnesskarten stehen auf großen Bildschirmen nebeneinander. Weitere
Analysen laden erst beim Öffnen ihres Dialogs; Rekorddetails und die vollständige
Erfolgssammlung sind ebenfalls separat zugänglich.

Beide Laufanalyse-Karten verwenden `RunTrendChart`: 300 px Höhe, adaptive Y-Skala
mit etwa sieben beschrifteten Markierungen, dezentes Bootstrap-Intervallband und
Wertanzeige per Hover, Antippen oder Tastatur. Lücken und Sensorwechsel bleiben
getrennt. Methodik und Tabellen öffnen über „Details“ einen Dialog;
`RunAnalysisSettings` bündelt Pulsreferenzen, Sensorwechsel und Lauf-Ausschlüsse
hinter „Laufanalyse einstellen“. Die Berechnung bleibt unverändert.

## Lauf-Fitness: rollierender eigener Trend (2026-09-19)

`metrics/run_fitness.py` ergänzt die frühere Monatsanalyse durch feste, nachlaufende
56-Tage-Fenster. Referenz für das persönliche VO₂-Äquivalent: 6:00 min/km bei Minute
20, aus geeigneten Minuten 10–30. Laufgewichtete lineare Regression mit mindestens
fünf Läufen, davon drei nahe der Referenz, positiver Tempo-Steigung und gemeinsamer
Tempo-/Zeitabdeckung. Minute-30-Reihen entdecken belegte Paces in 30-Sekunden-Schritten.
Die Monatsimplementierung bleibt als Vergleichsverfahren erhalten; REST/UI verwenden
die rollierende Variante. Überlappende Punkte sind keine unabhängigen Beobachtungen.

Run-Level-Bootstrap erhält Ziehungsmultiplizität; die Mindestzahl lokaler Läufe gilt
für die Originalstichprobe, nicht jede Ziehung. Numerisch fehlgeschlagene Ziehungen
werden nicht als vollständiges Intervall ausgegeben. Einfluss einzelner Läufe über
3 bpm wird als empfindlich markiert. Angezeigte Einzelpunkte sind gemessene Mediane
nahe der Referenz, keine exakt standardisierten Beobachtungen. Frühe/späte Abschnitte
bei ähnlichem Tempo werden separat als Pulsänderung ausgewiesen. Der Vergleich an
zurückgehaltenen Läufen belegt keine bessere Vorhersagegenauigkeit als einfache
Abschnittsmittel; die Vorteile sind feste Referenzen und zeitliche Abdeckung.

`run_references.py` sucht quellengleiche, dicht gemessene hohe Pulsabschnitte über
60 Sekunden, bestätigt an zwei Tagen. Dies ergibt eine beobachtete Belastungsreferenz,
keine gemessene oder validiert geschätzte HFmax. `run_fitness_service.py` speichert
Referenzrevisionen append-only in `run_fitness_references`. Die anfängliche Ruhepuls-
Referenz 60 bpm ist ausdrücklich eine vorläufige Modellannahme; die UI erlaubt eine
belegte wache Ruhemessung. Höhere bestätigte Belastungsreferenzen werden vorgeschlagen,
erst bei Übernahme geändert. Jede Referenzrevision berechnet die gesamte Historie
einheitlich neu. VO₂eq verwendet die Laufkosten-/Reserve-Näherung, keine Samsung-Werte.
Parameter-Szenarien (beide Pulsreferenzen ±10 bpm) sind kein Konfidenzintervall.

Sensorwechsel werden mit Datum/Bezeichnung gespeichert und trennen Modellfenster
und Diagrammlinien. GET `/metrics/running/fitness`, PUT `/metrics/running/fitness-reference`,
Coach/MCP `get_personal_run_vo2`. Cache berücksichtigt Eingangsdaten, Tags, Referenzrevision,
Rohdatenkandidat, Modellversion und Datum. Gesundheitsdaten und Vergleichsberichte bleiben
unter `data/run-analysis/`; allgemeine Evidenz unter `docs/research/`.

> Persönliches, lokal laufendes Trainings-/Ernährungs-Dashboard mit LLM-Coach.
> Single-User. Local-first, später Cloudflare-fähig. „One source of truth", bewusst schlank.

---

## 0. Leitprinzipien

1. **Local-first, Single-User.** Läuft komplett auf deiner Maschine. Architektur verbaut den späteren Cloudflare-Schritt nicht.
2. **One source of truth = SQLite.** Eine typisierte Query-/Metrik-Schicht darüber, **dreifach exponiert**: REST (Dashboard), LLM-Tools (Coach), MCP (Claude Desktop). Einmal schreiben, dreifach nutzen.
3. **Schlank.** Drei Analyse-Bereiche — **Körper, Laufen, Kraft** — mit Kernmetriken statt Werte-Explosion. Kernfrage: „Wo werde ich besser, wo schlechter?"
4. **Prototyp-first.** Phase 1 ist lauffähig und klein. Automatik, Tool-Calling und MCP kommen inkrementell.

---

## 1. Tech-Stack

| Schicht | Wahl | Begründung |
|---|---|---|
| Frontend | **Next.js** (App Router, TS) + Tailwind + **shadcn/ui** | moderne, schöne UI; du kennst es |
| Charts | **Tremon (Tremor)** + **Recharts** | fertige KPI-/Trend-Komponenten, schön & schnell |
| Backend | **FastAPI** (Python) | Analytik in Python; identisch zu unseren Analysen hier |
| ORM/DB | **SQLModel/SQLAlchemy** über **SQLite** | leichtgewichtig, lokal, migrierbar (libSQL/D1) |
| Parsing | **pandas** | HC-`.db`, Hevy-CSV, FDDB-CSV robust einlesen |
| Scheduler | **APScheduler** (im Backend) | Syncs + Reports (Phase 2+) |
| LLM | **OpenRouter** (OpenAI-kompatibel), Modell per `.env` | Modell-Tausch trivial; später Ollama-Swap |
| Lokal-Orchestrierung | **docker-compose** | frontend + backend + SQLite-Volume |

---

## 2. Repo-Layout

```
fitness-tracker/
├── docker-compose.yml
├── .env.example                  # alle Keys/Secrets (NIE echte Werte committen)
├── ARCHITECTURE.md               # dieses Dokument
├── CLAUDE.md                     # Projekt-Memory für Claude Code (legt CC an)
├── data/                         # SQLite-Volume (gitignored)
│   └── tracker.db
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── app/
│       ├── main.py               # FastAPI-App, Router-Mount
│       ├── db.py                 # Engine/Session, create_all
│       ├── models.py             # SQLModel-Tabellen (siehe §4)
│       ├── ingest/               # Parser pro Quelle (siehe §3)
│       │   ├── health_connect.py # .db (SQLite) -> Tabellen
│       │   ├── hevy.py           # API-Client + CSV-Fallback
│       │   └── fddb.py           # Login+Cookie -> CSV-Export -> Tabellen
│       ├── metrics/              # DAS HERZSTÜCK — reine Funktionen (siehe §5)
│       │   ├── body.py           # EWMA, adaptives TDEE
│       │   ├── running.py        # Volumen, Pace, VO2max
│       │   └── strength.py       # e1RM, Tonnage, RPE
│       ├── api/                  # REST-Router (nutzt metrics/)
│       ├── coach/                # LLM-Coach (siehe §6)
│       │   ├── snapshot.py       # baut Datensnapshot für Injection
│       │   ├── prompts.py        # System-Prompts
│       │   └── client.py         # OpenRouter (OpenAI-SDK)
│       └── mcp/                  # MCP-Server (Phase 3, nutzt metrics/)
└── frontend/
    ├── Dockerfile
    ├── package.json
    └── src/
        ├── app/                  # /, /body, /running, /strength, /coach
        ├── components/           # Charts, KPI-Karten (Tremor/Recharts)
        └── lib/api.ts            # Fetch-Client zum Backend
```

---

## 3. Datenquellen & Ingestion

Die Automatisierbarkeit ist **asymmetrisch** — ehrlich pro Quelle:

| Quelle | Methode | Automatik | Phase |
|---|---|---|---|
| **Hevy** (Kraft) | **Offizielle API** (Pro-Key) — `GET /v1/workouts` (paginiert) initial, `/v1/workouts/events` inkrementell. CSV-Fallback. | ✅ voll (Polling) | P1 Upload → P2 API |
| **FDDB** (Ernährung) | **Auth. CSV-Export** — Login → Session-Cookie → `GET fddb.info/db/i18n/exporter/?lang=de&action=diary&type=csv` → **komplette Historie als CSV**. | ⚙️ halb→voll | P1 Upload → P2 Auto-Login |
| **Health Connect** (Lauf/HR/VO2/Schritte/Gewicht) | **Kein Cloud-API.** Scheduled Export (`.db`-Zip) auf Ordner + Watcher, oder manueller Zip-Upload. | ⚙️ halb | P1 Upload → P2 Watcher |
| **Manuell** | Eingabeformular | — | P1 |

**Format-Notizen (verifiziert an echten Exports):**

- **FDDB-CSV:** `;`-getrennt, **`,` als Dezimaltrenner**, UTF-8. Spalten: `datum_tag_monat_jahr_stunde_minute` (`DD.MM.YYYY HH:MM`), `bezeichnung`, `interne_id`, `kj`, `kj_aktivitaeten`, `fett_g`, `kh_g`, `protein_g`. **Energie in kJ → kcal = kj / 4.184.** Daten sind **pro Eintrag** (Zeitstempel + Produkt) → Tagessummen selbst aggregieren. `kj_aktivitaeten` meist 0 (Aktivität kommt aus HC/Hevy). Dedup-Key: `(datetime, interne_id, kj)` oder Zeilen-Hash.
  - *MVP-Login:* Session-Cookie aus DevTools in `.env`, Backend nutzt es für den GET. *Ziel:* programmatischer Login (Login-POST nachbauen → Cookie selbst holen).
  - *Caveat:* reine KI-FoodScan-Einträge fehlen lt. FDDB evtl. im Export — einmal stichprobenartig prüfen.
- **Hevy-CSV/API:** Felder `title, start_time, exercise_title, set_type (normal/warmup), weight_kg, reps, rpe`. Für Kraft-Metriken nur `set_type='normal'`.
- **Health-Connect-`.db`:** SQLite. Zeitstempel = **Epoch-Millisekunden** (UTC → `Europe/Berlin` konvertieren). Relevante Tabellen: `exercise_session_record_table`, `distance_record_table`, `vo2_max_record_table`, `steps_record_table`, `heart_rate_record_*`, `weight_record_table`, `body_fat_record_table`. `exercise_type` ist ein Integer-Code (**an deinen Daten verifiziert: 33 = Laufen, 45 = Kraft, 53 = Gehen** — vor Produktion gegenchecken). `energy` in `total_calories_burned` ist in **cal → /1000 für kcal** (und dort unvollständig/aktiv-only → **nicht** als TDEE nutzen). `elevation_gained_record_table` ist bei dir leer → **keine Höhenmeter** (siehe §5.2).
  - **Herzfrequenz:** Einzelwerte in `heart_rate_record_series_table` (`parent_key` → `heart_rate_record_table.row_id`, `epoch_millis`, `beats_per_minute`). Pro Session im Zeitfenster aggregiert (Ø/Max + Drift 2. vs. 1. Hälfte); Quelle bevorzugt die Watch-App (`steps_source_package`), Fallback alle Apps; Sanity 25–250 bpm.

---

## 4. Datenmodell (SQLite)

DDL als Source of Truth; SQLModel spiegelt das 1:1. `source` überall, damit Mehrfachquellen (z. B. Gewicht aus Arboleaf *und* HC) unterscheidbar sind.

```sql
-- Körper (Arboleaf-Export / Health Connect)
CREATE TABLE body_measurements (
  id INTEGER PRIMARY KEY,
  measured_at TIMESTAMP NOT NULL,
  weight_kg REAL, body_fat_pct REAL, muscle_kg REAL,
  ffm_kg REAL, visceral REAL, water_pct REAL,
  source TEXT NOT NULL,                      -- 'arboleaf' | 'health_connect' | 'manual'
  UNIQUE(measured_at, source)
);

-- Ernährung (FDDB) — pro Eintrag
CREATE TABLE nutrition_entries (
  id INTEGER PRIMARY KEY,
  eaten_at TIMESTAMP NOT NULL,
  description TEXT, fddb_id TEXT,
  kcal REAL, fat_g REAL, carb_g REAL, protein_g REAL,
  source TEXT NOT NULL DEFAULT 'fddb',
  UNIQUE(eaten_at, fddb_id, kcal)            -- Dedup
);

-- Kraft (Hevy)
CREATE TABLE workouts (
  id INTEGER PRIMARY KEY,
  external_id TEXT UNIQUE,                    -- Hevy-Workout-ID (für inkrement. Sync)
  title TEXT, started_at TIMESTAMP, ended_at TIMESTAMP,
  source TEXT NOT NULL DEFAULT 'hevy'
);
CREATE TABLE workout_sets (
  id INTEGER PRIMARY KEY,
  workout_id INTEGER REFERENCES workouts(id),
  exercise TEXT NOT NULL, set_index INTEGER,
  set_type TEXT,                             -- 'normal' | 'warmup' | ...
  weight_kg REAL, reps INTEGER, rpe REAL
);

-- Cardio/Schritte/VO2 (Health Connect)
CREATE TABLE exercise_sessions (
  id INTEGER PRIMARY KEY,
  external_id TEXT UNIQUE,
  exercise_type INTEGER,                      -- 33 run / 45 strength / 53 walk
  started_at TIMESTAMP, ended_at TIMESTAMP,
  distance_km REAL, avg_hr REAL,
  max_hr REAL, hr_drift_pct REAL,             -- HF je Session (aus heart_rate_record_series_table)
  source TEXT NOT NULL DEFAULT 'health_connect'
);
CREATE TABLE vo2max (
  id INTEGER PRIMARY KEY,
  measured_at TIMESTAMP UNIQUE, vo2 REAL,
  source TEXT NOT NULL DEFAULT 'health_connect'
);
CREATE TABLE steps_daily (
  day DATE PRIMARY KEY, steps INTEGER,
  source TEXT NOT NULL DEFAULT 'health_connect'
);

-- LLM-Coach-Ausgaben
CREATE TABLE coach_reports (
  id INTEGER PRIMARY KEY,
  created_at TIMESTAMP NOT NULL,
  kind TEXT NOT NULL,                         -- 'daily' | 'weekly' | 'chat'
  content TEXT NOT NULL, model TEXT
);

-- Sync-Status pro Quelle (Cursor/letzter Stand)
CREATE TABLE sync_state (
  source TEXT PRIMARY KEY,
  last_sync TIMESTAMP, cursor TEXT
);
```

Tagessummen (Intake/Tonnage) werden **berechnet**, nicht gespeichert (Views/Funktionen in `metrics/`), damit keine Redundanz entsteht.

---

## 5. Metrik-Schicht — das Herzstück

`backend/app/metrics/` = reine Funktionen über die DB (kein Web, keine LLM-Abhängigkeit). Genau diese Funktionen speisen **REST + Coach + MCP**.

### 5.1 Körper (`body.py`)
- **Gewicht:** `ewma(span=10)` bzw. 7-Tage-rolling — filtert Wasser-Rauschen. (Tageswerte nie roh interpretieren.)
- **Körperfett-Trend** (Bioimpedanz, nur Trend, nicht Absolutwert).
- **Adaptives TDEE / echtes Defizit:**
  `TDEE ≈ Ø_Intake + (Δ(7d-avg-Gewicht_kg) × 7700) / Tage`
  Rollendes Fenster **≥ 14 Tage** (Einzelwochen sind durch Wasser unbrauchbar — Lektion aus den Analysen). Intake aus `nutrition_entries`, Gewicht aus `body_measurements`.
  *Benötigt:* tägl. Intake + tägl. Gewicht.

### 5.2 Laufen (`running.py`)
- **Experimentelle standardisierte Lauf-HF** (`metrics/run_standardization.py`, Persistenz/Cache in
  `metrics/run_analysis.py`): zusätzliche Karte „Puls bei gleicher Pace“, Referenz immer **Laufminute 30**.
  Referenzpaces werden aus den verfügbaren Daten in **30 Sekunden/km** entdeckt; jede Pace erscheint
  erst, wenn mindestens ein Monatswert die Qualitätsprüfung besteht. Andere Monate bleiben Lücken.
  Basis sind echte, quellengebundene Speed-/HF-Minutenfenster (`ingest/run_windows.py`, `run_minutes`),
  keine interpolierten Gesamtdistanzen. Der normale HC-Import füllt bestehende Sessions nachträglich.
  Monatsmodell HF ~ Speed + verstrichene Laufzeit; gleiche Gesamtgewichte je Lauf, Huber-Fit,
  2.000 Lauf-Bootstrap-Ziehungen, lokale gemeinsame Abdeckung, Auslassungs- und Variantenprüfung.
  Vorläufige Produktgrenzen: ≥10 geeignete Läufe, ≥5 lokal unterstützende Läufe, maximal 3 bpm
  Einfluss eines einzelnen Laufs/Modellvariante. Keine universellen physiologischen Grenzwerte.
  Laufender Monat ist vorläufig; direkte Differenzintervalle vergleichen nur vollständige geeignete
  Monate. Wetter/Terrain bleiben unkontrolliert; kein automatischer physiologischer Fitnessnachweis.
  Manuelle Kategorien/Ausschlüsse liegen separat in `run_annotations` an der externen Session-ID
  und überstehen Vollimporte. Sie ändern weder Historie noch Trainingsvolumen.
  REST: `/metrics/running/standardized-hr`, GET/PUT `/metrics/running/analysis-sessions[/{external_id}]`;
  Coach/MCP: `get_standardized_run_hr`. Inhaltsbasierter SQLite-Cache (`run_analysis_cache`),
  neu berechnet nach Daten-/Markierungs-/Modell-/Kalendermonatsänderung. SR-VO₂eq bleibt ausstehend.
- **Wochenvolumen** (km) + Anzahl Läufe (`exercise_type=33`).
- **Pace-Trend** (min/km) — nur plausible Distanzen (HC-Distanzfelder können verrauscht sein → Sanity-Filter, z. B. max. Distanzrecord pro Session statt Summe).
- **VO2max-Trend** (HC, `vo2max`). Uhr-Schätzung → Trend zählt.
- *(optional)* **ACWR** = akute Last (7 d) / chronische Last (28 d) — Überlastungs-/Verletzungsindikator.
- **Lücke (bewusst):** **keine Höhenmeter** (HC liefert keine, Strava ist raus). Fürs Beast-Vert ist das die bekannte tote Stelle — im Dashboard als „nicht verfügbar" kennzeichnen, nicht faken.

### 5.3 Kraft (`strength.py`)
- **e1RM** je Hauptübung, Top-Arbeitssatz/Session — **Epley:** `e1RM = weight × (1 + reps/30)`.
- **Wochen-Tonnage** = Σ `weight × reps` über Arbeitssätze (`set_type='normal'`).
- **RPE-Trend** = Wochenschnitt RPE — Ermüdungssignal (steigt im Defizit bei gleicher Last).
  *Benötigt:* `workout_sets` mit `weight_kg, reps, rpe`.

---

## 6. LLM-Coach

### 6.1 Prinzip: eine Query-Schicht, drei Gesichter
Die `metrics/`-Funktionen werden gewrappt als (1) **REST** fürs Dashboard, (2) **LLM-Tools** für den Coach, (3) **MCP-Tools** für Claude Desktop/Code. Query-Logik existiert **genau einmal**.

### 6.2 Ausbaustufen (in dieser Reihenfolge bauen)
- **(a) Context-Injection — Phase 1 (Start hier).** Backend baut einen kompakten Datensnapshot (Gewicht/TDEE, e1RM, Laufvolumen, VO2max, RPE) → in den Prompt → OpenRouter → Report. Kein Tool-Loop, voll kontrollierbar, billig. ~80 % des Nutzens.
- **(b) Tool-Calling — Phase 2.** Die `metrics/`-Funktionen als Tools; das LLM ruft selbst, was es für eine Frage braucht. Skaliert ohne Prompt-Aufblähung. (Lern-Schwerpunkt: Function-Calling.)
- **(c) MCP-Server — Phase 3.** Dieselben Funktionen als MCP-Server → in Claude Desktop/Code einhängen und Daten dort befragen, außerhalb der App.

### 6.3 Coach-Features
- **Täglicher Report:** kurz — gestern vs. Trend, ein Hinweis.
- **Wöchentlicher Report:** die 3 Bereiche; was gut lief, worauf achten, **genau eine** konkrete Anpassung.
- **Chat:** „frag deine Daten".
- **Ton:** ehrlich-motivierend — würdigt Fortschritt faktisch, **pusht statt zu validieren**.

### 6.4 System-Prompt (Startgerüst — anpassen)
```
Du bist mein persönlicher, evidenzbasierter Trainings- und Ernährungscoach.
Stil: direkt, prägnant, ehrlich. Du würdigst Fortschritt anhand der Zahlen,
aber beschönigst nichts und pushst statt zu validieren.

Mein Kontext:
- Ziel: Cut auf ~70 kg, Krafterhalt (3×/Woche), Spartan Beast am 12.09. (21 km, ~2000 Hm).
- Baselines: {wird zur Laufzeit eingesetzt}.

Datenzugang:
- {Phase 1: hier folgt ein Datensnapshot} / {Phase 2: nutze die bereitgestellten Tools}.
- Begriffe: Energie aus FDDB ist kJ (kcal = kJ/4.184); e1RM = Gewicht×(1+Wdh/30);
  Bioimpedanz-KFA nur als Trend; Gewicht immer als 7-Tage-Mittel lesen.

Ausgabeformat:
- "Wo werde ich besser / Wo schlechter / 1 konkrete Anpassung".
- Bei Wochenreport zusätzlich ein kurzer Motivationssatz zu dem, was gut lief.

Leitplanken:
- Keine medizinischen Diagnosen. Benenne Unsicherheit ehrlich.
- Bei gesundheitlichen Auffälligkeiten: auf Fachperson/Arzt verweisen.
- Erfinde keine Werte; wenn Daten fehlen (z. B. Höhenmeter), sag das.
```

### 6.5 OpenRouter-Anbindung
OpenAI-SDK mit anderer Base-URL; Modell als env. **Local-first-Bonus:** OpenAI-kompatibel → später per Endpoint-Tausch auf Ollama (lokales Modell) zeigbar.
```python
from openai import OpenAI
client = OpenAI(base_url="https://openrouter.ai/api/v1",
                api_key=os.environ["OPENROUTER_API_KEY"])
# Modell aus env, z.B. OPENROUTER_MODEL="deepseek/deepseek-chat"
```

---

## 7. Datenschutz (ehrlich markiert)
Mit einem Cloud-LLM **verlassen deine Gesundheitsdaten die Maschine** (OpenRouter + Modellanbieter). Für ein privates Experiment deine Entscheidung. Mitigation: OpenRouter-Provider mit No-Logging wählen, oder später lokales Modell (Ollama). Alle Keys in `.env`, **nie ins Repo**. `.env`, `data/` und `*.db` in `.gitignore`.

---

## 8. Roadmap

- **Phase 1 — MVP (klein, lauffähig):** Repo-Scaffold + docker-compose; SQLite-Schema; **File-Upload-Import** für alle drei Quellen + Parser; die **3 Dashboards** (Körper/Laufen/Kraft) mit Tremor/Recharts; **Context-Injection-Coach** (täglicher + wöchentlicher Report + einfacher Chat).
- **Phase 2 — Automatik & Tools:** Hevy-API-Polling, FDDB-Auto-Login, HC-Export-Watcher (APScheduler); **Tool-Calling-Coach**.
- **Phase 3 — MCP:** Metrik-Funktionen als MCP-Server, in Claude Desktop/Code nutzbar.
- **Phase 4 — Hosting:** Cloudflare Pages (Frontend) + containerisiertes FastAPI (CF Containers/Fly.io) + SQLite-Volume oder libSQL/Turso.

---

## 9. Offene Punkte (für später)
- HC `exercise_type`-Codes (33/45/53) final gegen deine Daten verifizieren.
- FDDB FoodScan-Einträge im Export stichprobenartig prüfen.
- Design-Feinschliff: Farbsystem & Typografie, Design-Assets via OpenAI Image (gpt-image-2) generieren und unter `frontend/public/` ablegen.
