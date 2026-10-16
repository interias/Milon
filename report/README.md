# Bericht: Heldenreise

Statische Seite (`index.html` + `img/`), ohne Build-Schritt.

## Lokal ansehen
Läuft als Container `report` im Docker-Stack auf Port 8090:

    docker compose up -d report

→ http://localhost:8090

## Auf Cloudflare Pages veröffentlichen
Einmalig anmelden (oder `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` setzen), dann aus dem Repo-Root:

    npx wrangler pages deploy report --project-name milon-heldenreise

Beim ersten Mal legt Wrangler das Projekt an. Die Seite ist danach unter `https://milon-heldenreise.pages.dev` erreichbar.
`_headers` setzt Caching für die Bilder.

## Screenshots
Aufgenommen per Headless-Chrome von der Live-Version. Entfernungs- und Richtungsangaben zu Orten
sind ausgeblendet („··· km“), damit sich der Startpunkt nicht zurückrechnen lässt.
Die Verlies-Vorschau (Auesee) stammt aus einem simulierten Lauf auf einer Datenbank-Kopie.
