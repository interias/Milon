# Milon · Design

Die **gewählte** Designrichtung als Referenz plus die Asset-Studien. Die ursprüngliche
Explorations-Galerie (11 verworfene Richtungen, Theme-Switcher) wurde entfernt — die
Entscheidung ist gefallen: **Klar & Klinisch ✕ Sport**.

## Starten

- **VS Code:** `Terminal → Task ausführen…` → **„Design: HTML-Server"**
- **oder:** `python design/serve.py` → <http://localhost:4321>

Reload (F5) genügt — kein Build, der Server schickt No-Cache-Header.

## Dateien

| Datei | Zweck |
|---|---|
| `index.html` | schlanke Landing → verlinkt die beiden Studien |
| `klar-klinisch.html` | Near-Product-Studie der gewählten UI (Tokens, Sport-Silhouette, klinische Palette) |
| `silhouette.html` | Foto-Schablonen: Silhouetten- & Pose-Overlays für die Fortschritts-Fotos |
| `serve.py` | kleiner No-Cache-Dev-Server (Port 4321) |
| `assets/klar-sport/` | Lauf-Hero (`run-*`) + Domänen-Begleiter (`kraft-ink-slash`, `koerper-ink-arc`) |
| `assets/silhouette/` | freigestellte Silhouetten + Posen (`poses/`) inkl. `*.prompt` (Generierungs-Protokoll) |
| `assets/icons/` | Muskelgruppen-Icons (Quelle für `client/public/img/muscle/`) |
| `tools/key-silhouette.mjs` | Magenta-Keyer (gpt-image-2 kann kein transparentes BG) |

## Gewählte Richtung: Klar & Klinisch ✕ Sport

`klar-klinisch.html` entwickelt die Richtung als nahezu echtes Produkt: **Klar-&-Klinisch-Stil**
+ die **Sport-Silhouette**, übersetzt in die klinische Palette (Ink-Charcoal + ein Teal-Akzent).
Tokens: bg `#fbfcfc`, surface `#fff`, text `#14201f`, muted `#4d5b5a`, border `#e2e7e8`,
**accent Teal `#0a6e66`**, accent2 `#5cb8af`; Fonts **Inter Tight** (Display) / **Inter** (Body).

## Assets generieren

Voraussetzung: `OPENAI_API_KEY` in der Root-`.env` (gpt-image-2). Generierung läuft über die
`transparent-images`-Skill (grüner bzw. Magenta-Chroma-Key → freigestellt). Definitionen:
`assets-klar-sport.json` (Lauf-Hero + Domänen) und `assets-graphics.json` (Icons, Coach-Motiv).

```bash
npm run assets   # Root-Skript: node --env-file=.env <skill>/generate-transparent.mjs design/assets.json
```

Für die **Silhouetten** (auf Magenta generiert, dann freigestellt): siehe `tools/key-silhouette.mjs`.
Rohdaten landen in `assets/.raw/` (gitignored); zum Neuerzeugen die jeweilige `.raw`-Datei löschen.
Kosten: `1024²` / `quality:low` ≈ **$0,007/Bild**.
