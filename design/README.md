# Milon · Design-Exploration

Spielwiese, um vor dem eigentlichen Bau Designrichtungen zu vergleichen und
„weiterzudrehen". Eine Referenz-Oberfläche (Übersichts-Dashboard mit Körper /
Laufen / Kraft + Coach), die sich live in **11 Richtungen** umskinnen lässt.

## Starten

- **VS Code:** `Terminal → Task ausführen…` → **„Design: HTML-Server"**
- **oder:** `python design/serve.py`
- Browser: <http://localhost:4321>

Reload (F5) genügt nach Änderungen — kein Build. Der Server schickt No-Cache-Header.

## Bedienen

- **Richtung** oben wählen oder mit **← / →** durchblättern.
- **Dichte:** Kompakt / Normal / Luftig.
- **Galerie:** alle 11 Richtungen nebeneinander (klick öffnet die Einzelansicht).
- **Generierte Assets:** blendet die gpt-image-2-Grafiken aus/ein (reine Farb-/Typo-Wirkung prüfen).

## Dateien

| Datei | Zweck |
|---|---|
| `index.html` | Struktur + Bedienelemente |
| `styles.css` | token-getriebenes Layout (jede Richtung setzt nur CSS-Variablen) |
| `themes.js` | die 11 Richtungen (Tokens, Fonts, Signatur-Prompts) — aus dem Design-Workflow |
| `app.js` | Theme-Switcher, Mock-Dashboard, Mini-Charts |
| `serve.py` | kleiner No-Cache-Dev-Server (Port 4321) |
| `assets/` | generierte transparente PNGs (Signaturen je Richtung + 4 Domain-Icons) |

## Assets neu generieren

Voraussetzung: `OPENAI_API_KEY` in der Root-`.env`, einmalig `npm i openai sharp`.

```bash
# Standard-Batch (grüner Chroma-Key) – 9 Signaturen + 4 Icons
npm run assets        # == node --env-file=.env <skill>/generate-transparent.mjs design/assets.json
```

**Sonderfall – zwei neon-grüne Motive** (`dark-athletic`, `terminal-local-first`):
Der grüne Standard-Keyer würde sie ausstanzen. Darum auf **Magenta-Hintergrund**
generieren und mit dem eigenen Magenta-Keyer freistellen:

```bash
CHROMA_HEX='#FF00E5' node --env-file=.env "$HOME/.claude/skills/transparent-images/scripts/generate-transparent.mjs" design/assets-magenta-chroma.json
node design/tools/key-magenta.mjs
```

Bereits erzeugte Bilder werden bei Re-Runs übersprungen (Rohdaten in `assets/.raw/`,
gitignored). Zum Neuerzeugen die jeweilige Datei in `assets/.raw/` löschen.

Kosten: `1024×1024` / `quality:low` ≈ **$0,007/Bild** (alle 15 zusammen ≈ $0,10).

## Gewählte Richtung: Klar & Klinisch ✕ Sport

`klar-klinisch.html` (verlinkt oben in `index.html`) entwickelt die gewählte
Richtung als nahezu echtes Produkt: **Klar-&-Klinisch-Stil** + die **Sport-Silhouette**
aus Neo-Sport, übersetzt in die klinische Palette (Ink-Charcoal + ein Teal-Akzent).
Hero-Silhouette oben per Picker umschaltbar (Ink+Slash / Teal / Monoline / Duotone).

Assets dazu in `assets/klar-sport/` (Definition `assets-klar-sport.json`):
`run-ink-slash`, `run-teal-solid`, `run-monoline`, `run-duotone` (Lauf-Hero) sowie
`kraft-ink-slash` und `koerper-ink-arc` (Domänen-Begleiter, als Karten-Wasserzeichen).
Neu generieren: `node --env-file=.env "$HOME/.claude/skills/transparent-images/scripts/generate-transparent.mjs" design/assets-klar-sport.json`

## Bekannte Schwäche

`terminal-local-first.png`: die Bewegungs-Punkte gerieten leicht rosa statt phosphor-grün.
Brauchbar als Platzhalter; bei Wahl dieser Richtung neu generieren (Prompt schärfen).
