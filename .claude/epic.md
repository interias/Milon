---
# Projektadapter für /epic, /epic-nacharbeit und /epic-aufraeumen (angelegt 2026-10-17 mit dem Expeditionen-Epic).
forge: github                      # interias/Milon (öffentlich), Zugriff über die angemeldete `gh`-CLI
push_remote: origin
base_branch: main
main_branch: main                  # nie Ziel eines Merges durch den Lauf

issue_form: tickets
ready_label: ready-for-agent
epic_label: epic
dependency_source: [api, body]     # api = GitHub-Sub-Issues des Epics, body = `## Blocked by`
acceptance_section: "## Abnahmekriterien"
verification_section: "## Verifikationsweg"
modules_section: "## Betroffene Module"

must_read: [CLAUDE.md]
# glossary / adr_dir: keine im Projekt

test_commands:
  server: >-
    cd <worktree>/server &&
    <repo>/server/.venv/Scripts/python -m pytest -q -p no:cacheprovider --basetemp=<scratchpad>/pytest-<name>
  client: >-
    cd <worktree>/client && npx tsc --noEmit
known_red: keine                   # Stand 2026-10-17: 638 Server-Tests grün, tsc sauber

window: 1
max_rounds: 3
exclusive_paths:
  - server/pyproject.toml
  - client/package.json
  - client/package-lock.json
  - server/app/db.py               # Migrationen
  - docker-compose.yml
always_collide:
  - CLAUDE.md                      # jede Etappe hängt ihren Abschnitt an
writers:
  - server/app/ingest
  - server/app/sync
  - server/app/db.py

worktree_root: ../Milon-worktrees
env_files:
  - server/.env
  - .env
link_dirs:
  - client/node_modules
always_link:
  - client/node_modules            # tsc braucht es in jedem Paket

commit_style: plain                # englischer Imperativsatz ohne Präfix, z. B. "Add route GPX export"
commit_language: en
commit_umlauts: keep
plan_artifact: publish
---

# Projektregeln

**Sprache.** UI deutsch, Code, Kommentare an Identifiern und Commits englisch (Bestandskommentare
im Code sind teils deutsch – im Stil der Datei bleiben).

**Gesundheitsdaten.** `data/` ist gitignoriert und wird nie committet. Tests laufen gegen temporäre
SQLite-Datenbanken (`tmp_path`), nie gegen `data/tracker.db`.

**Echte Spielentscheidungen.** Truhenwahl, Spec, Talente, Ausrüstung, Käufe, Reittier usw. des Nutzers
werden beim Testen nie verändert. Manuelle Prüfungen mit schreibenden Aktionen laufen auf einer
Kopie der Datenbank (`DATABASE_URL` auf eine Kopie im Scratchpad).

**Keine absoluten Koordinaten in API-Antworten.** Die Weltkarte liefert nur Meter relativ zur Heimat.
Ausnahme ist ein ausdrücklich angeforderter Routen-Export (GPX/FIT) öffentlicher Strecken. Live-Positionen
liegen nur auf dem eigenen Server und werden gelöscht, sobald die Garmin-Spur da ist.

**Externe Dienste.** Ein neuer externer Dienst, der zur Laufzeit Daten mit Ortsbezug erhält, ist ein
Tor-Punkt. Bereits genutzt: Open-Meteo, OSM-Kacheln (serverseitig, gecacht), Garmin über `garminconnect`.

**Doku-Pflicht.** Jedes Paket ergänzt `CLAUDE.md` um einen kurzen Abschnitt (was, wo, wichtige Befunde).

**Downloads und Installationen** (SDKs, Werkzeuge, Pakete außerhalb der Projektabhängigkeiten) nur mit
Zustimmung des Nutzers im Chat.
