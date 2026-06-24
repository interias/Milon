# Claude-Code-Bootstrap-Prompt

> So nutzt du das: Lege `ARCHITECTURE.md` und `docker-compose.yml` ins leere Projektverzeichnis,
> öffne dort Claude Code und füge den Block unten als **erste Nachricht** ein.
> Er ist bewusst auf **Phase 1 (MVP)** begrenzt — klein, lauffähig, prototypisch.

---

```
Wir bauen ein persönliches, lokal laufendes Fitness-Tracking-Dashboard mit LLM-Coach.
Die vollständige Architektur liegt in ARCHITECTURE.md — LIES SIE ZUERST und halte dich daran.

Stack: FastAPI + SQLite (SQLModel) im Backend, Next.js (App Router, TS) + Tailwind +
shadcn/ui + Tremor/Recharts im Frontend, docker-compose für lokal. Sprache der UI: Deutsch,
Code/Identifier auf Englisch.

ARBEITSWEISE:
- Arbeite in kleinen, lauffähigen Schritten. Nach jedem Schritt: kurz zusammenfassen, was
  läuft, dann erst weiter. Frag bei echten Architektur-Entscheidungen nach, rate nicht.
- Verifiziere zuerst die aktuellen stabilen Versionen von Next.js, FastAPI, SQLModel,
  shadcn/ui und Tremor, bevor du Abhängigkeiten festlegst (mein Trainingsstand kann veraltet sein).
- Lege als Erstes eine CLAUDE.md an (Projekt-Memory: Stack, Konventionen, Phasen-Status,
  Verweis auf ARCHITECTURE.md).

ZIEL DIESER SESSION = NUR PHASE 1 (MVP). NICHT mehr.

Reihenfolge:
1. Monorepo-Scaffold gemäß Repo-Layout in ARCHITECTURE.md (backend/, frontend/, data/,
   .env.example, .gitignore mit .env, data/, *.db). docker-compose.yml liegt schon bereit.
2. Backend-Grundgerüst: FastAPI-App, DB-Engine (SQLite unter /data), SQLModel-Tabellen
   exakt nach dem Datenmodell (§4), create_all beim Start.
3. File-Upload-Import + Parser für ALLE DREI Quellen (Upload-Endpoint je Quelle), strikt
   nach den Format-Notizen in §3:
   - Health Connect: hochgeladene .db (SQLite) lesen, Epoch-ms -> Europe/Berlin,
     exercise_type 33/45/53, in exercise_sessions/vo2max/steps_daily/body_measurements.
   - Hevy: CSV (set_type='normal' für Kraft) -> workouts/workout_sets.
   - FDDB: CSV (sep=';', decimal=',', UTF-8, kJ->kcal /4.184, pro Eintrag) -> nutrition_entries,
     Dedup über (eaten_at, fddb_id, kcal).
   Mach die Parser defensiv (Encoding, fehlende Felder, Dubletten) und schreib je einen
   kleinen Test mit Beispieldaten.
4. Metrik-Schicht (§5) als reine Funktionen in backend/app/metrics/:
   - body: 7-Tage-EWMA Gewicht, adaptives TDEE (Intake + Δ7d-avg-Gewicht×7700/Tage, Fenster ≥14 Tage).
   - running: Wochenvolumen km + Anzahl, Pace-Trend (plausible Distanzen), VO2max-Trend.
   - strength: e1RM (Epley w×(1+reps/30)) Top-Arbeitssatz/Session, Wochen-Tonnage, RPE-Trend.
5. REST-Router, der diese Metriken liefert (saubere JSON-Shapes fürs Frontend).
6. Frontend: vier Seiten — / (Übersicht), /body, /running, /strength — schlank gehalten,
   je 2-4 Kern-Charts (Tremor/Recharts). Kein überladenes Dashboard. Höhenmeter explizit als
   "nicht verfügbar" kennzeichnen (kommt nicht aus den Daten).
7. LLM-Coach Stufe (a) Context-Injection:
   - coach/snapshot.py baut einen kompakten Datensnapshot aus den Metriken.
   - coach/client.py spricht OpenRouter (OpenAI-SDK, base_url https://openrouter.ai/api/v1,
     Modell aus OPENROUTER_MODEL).
   - coach/prompts.py = System-Prompt aus ARCHITECTURE.md §6.4.
   - Endpunkte: täglicher Report, wöchentlicher Report, Chat. Ergebnisse in coach_reports.
   - Frontend-Seite /coach: Report anzeigen + einfacher Chat. Ton: ehrlich-motivierend.

NICHT in dieser Session bauen (spätere Phasen, nur als TODO/Stub vermerken):
- Automatische Syncs (Hevy-API-Polling, FDDB-Auto-Login, HC-Watcher, APScheduler) -> Phase 2
- Tool-Calling-Coach -> Phase 2
- MCP-Server (backend/app/mcp/) -> Phase 3
- Cloudflare-Hosting -> Phase 4

Beachte die Leitplanken aus §6.4 (keine medizinischen Diagnosen, Unsicherheit benennen,
keine erfundenen Werte) und §7 (Secrets nur in .env). Leg .env.example mit allen nötigen
Keys an: OPENROUTER_API_KEY, OPENROUTER_MODEL, HEVY_API_KEY (Phase 2), FDDB_USER/FDDB_PW/
FDDB_COOKIE (Phase 2).

Starte mit Schritt 0: lies ARCHITECTURE.md, dann schlag mir die konkreten Versionen/Abhängigkeiten
vor und das Scaffold, bevor du Code schreibst.
```

---

**Danach (in Folge-Sessions):** Phase 2 als neue Aufgabe starten („implementiere die automatischen Syncs + Tool-Calling-Coach gemäß ARCHITECTURE.md §3/§6.2"), dann Phase 3 (MCP), dann Phase 4 (Hosting). Jede Phase referenziert dasselbe `ARCHITECTURE.md` als Source of Truth.
