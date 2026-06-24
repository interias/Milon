# Fitness-Tracker — Architektur & Plan

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
