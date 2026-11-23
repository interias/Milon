# Körperwaage per Web Bluetooth (Arboleaf CS20L)

Milon liest die Waage direkt im Handy-Browser aus. Die Arboleaf-App wird dafür nicht mehr gebraucht.

## Ablauf

1. Arboleaf-App schließen (sie hält sonst die Bluetooth-Verbindung).
2. Waage antippen – sie wacht auf und sendet.
3. In Milon „Wiegen“ tippen (Karte ganz oben auf der Übersicht und auf der Körper-Seite, oder `/wiegen`).
4. Chrome zeigt den Gerätedialog → Waage wählen (meist `QN-Scale` / `QN-Scale1`).
5. **Erst wenn „Bereit – jetzt barfuß draufstellen“ erscheint**, draufstellen. Das Live-Gewicht läuft mit; die stabile Messung wird automatisch gespeichert.

Voraussetzungen: **Chrome auf Android** und **HTTPS** (Tailscale). Über `http://<IP>` gibt es kein Web Bluetooth;
Samsung Internet, Firefox und iOS können es gar nicht. Die Seite zeigt das statt eines Knopfs.

## Bausteine

| Teil | Datei |
|---|---|
| Treiber (QN-Protokoll) | `client/lib/scale/qnScale.ts` – Parser als reine Funktionen `parseInfoFrame`, `parseLiveFrame`, `parseStoredFrame`, `withChecksum` |
| Treiber-Tests | `client/tests/qn-scale.test.cjs` (`npm test`) |
| UI | `client/components/ScaleWeigh.tsx`, Seite `client/app/wiegen/page.tsx`, Einbindung in `client/app/koerper/page.tsx` |
| Backend | `server/app/scale.py`, API `server/app/api/scale.py` |
| Backend-Tests | `server/tests/test_scale.py` |

### API

- `POST /scale/measurements` (über den Proxy `/api/scale/measurements`) nimmt das `ScaleReading`-JSON des Treibers.
  201 = neu, 200 = Dublette (`duplicate: true`), 422 = unplausibel (außerhalb 20–250 kg, Zeit > 10 min in der Zukunft, falsche Felder).
- `GET /scale/measurements?days=90` – Verlauf, neueste zuerst.
- `DELETE /scale/measurements/{id}` – z. B. wenn jemand anderes auf der Waage stand. Löscht auch die Zeile in der Gewichtsreihe.

Kein eigener Zugangsschutz, wie die übrigen UI-Endpunkte (Milon ist nur im Heimnetz/Tailnet erreichbar).

### Speicherung

- `scale_measurements`: `measured_at` (UNIQUE, lokale Wandzeit, Sekunden), `weight_kg`, `r1`, `r2`, `source` (`live`|`stored`),
  `protocol_type`, `raw_hex`, `created_at`. Die Rohwiderstände bleiben für eine spätere eigene Körperfett-Rechnung, die gegen
  die alten Arboleaf-Werte kalibriert wird. Eine Formel gibt es bewusst noch nicht.
- Zusätzlich eine Zeile in `body_measurements` mit `source = 'scale_ble'`. Damit sehen Gewichtsverlauf, Änderungsrate,
  Verbrauchsmodell, Übersicht, Coach und Heldenreise die Messung ohne eigene Anpassung.

### Dubletten und mehrere Quellen

- Gleiche Messzeit → Dublette. Gleiches Gewicht (±0,05 kg) innerhalb von 2 Minuten → Dublette (Doppel-Tap, oder Live-Wert plus Waagenspeicher).
- Die Bluetooth-Messung gewinnt: Gewichtszeilen anderer Quellen (Arboleaf → Health Connect) innerhalb ±10 Minuten werden beim Speichern
  gelöscht, und der Health-Connect-Import übernimmt sie nicht mehr (`scale.shadowed`).

## Protokoll in Kürze

- GATT Typ 2: Service `0xFFF0`, Notify `0xFFF1`, Write `0xFFF2`. Typ 1: Service `0xFFE0`, Notify `0xFFE1`, Indicate `0xFFE2`,
  Config `0xFFE3`, Zeit `0xFFE4`. Batterie `0x180F/0x2A19`.
- Frame `[opcode, länge, protocolType, …, checksum]`, Checksumme = Summe aller Bytes davor `& 0xFF`.
- `0x12` Info (`byte[10] == 1` → Gewicht /100, sonst /10) → wir senden `0x13` Einheit + `0x02` Zeit.
- `0x14` Ack → `0x20` Zeit-Sync. `0x21` (neuere Firmware) → 2 × `0xA0` + `0x22` Abfrage gespeicherter Messungen.
- `0x10` Live-Gewicht: altes Layout `[3,4]` Gewicht, `[5]` stabil, `[6..9]` r1/r2; neues Layout (nur bei /10 und `[4] ≤ 2`)
  `[4]` Zustand, `[5,6]` Gewicht, `[7..10]` r1/r2. Liegt das Ergebnis ≤ 5 oder ≥ 250 kg, wird einmal durch 10 geteilt.
- `0x23` gespeicherte Messung (Fallback): Gewicht `[10,11]` /100, Zeit `[6..9]` little-endian, r1/r2 `[13..16]` little-endian.
- Zeit = Sekunden seit QN-Epoch (Unix − 946702800).

Erster echter Test (2026-11-23, CS20L): Verbindung und Handshake laufen (`QN-Scale`, Service `FFF0`, protocolType `0xff`, Faktor /10,
neuere Firmware mit `0x21`). Die Waage antwortet auf `0xA0` mit `0xA1` und auf `0x22` mit einem leeren Speicher: `0x23` komplett 0, danach
`0x24`/`0x25` (ebenfalls 0, Bedeutung unbekannt). Leerer `0x23` → der Treiber fragt nicht weiter nach. Ein `0x10`-Live-Frame kam in diesem
Test nicht an (16 s Log) – die Reihenfolge entspricht openScale (`QNHandler.kt`), dort gibt es keinen eigenen Startbefehl.
Das Live-Gewicht ist also noch unbestätigt.

Zweiter Test (2026-11-23): Der Speicher lieferte die Wiegung aus dem ersten Versuch (`23 14 ff 01 01 f0 ea e6 96 32 1d fb …` = 76,75 kg,
Zeit `0x3296e6ea` = 16:58:34 UTC, r1/r2 = 0). Die Waage löscht einen Datensatz, sobald sie ihn gesendet hat. Deshalb gilt jetzt:
- Ältere Datensätze werden nie verworfen, sondern mit ihrer echten Uhrzeit nachgetragen (`onStoredRecord`; die Uhr der Waage stellen wir bei jeder Verbindung).
  Unplausible Waagenuhr (> 1 Jahr alt oder in der Zukunft) → Uhrzeit des Handys.
- Solange Milon auf eine Messung wartet, fragt es den Speicher alle 3 s ab (höchstens 40-mal, Wartezeit 2 min). Speichert die Waage die
  Wiegung, statt sie live zu senden, kommt sie so trotzdem in Sekunden an. Ein Datensatz, der höchstens 90 s alt ist, gilt als „diese Wiegung“.
- Die Log-Zeiten sind jetzt Ortszeit (vorher UTC).

## Bereitschaft: Seite offen, draufstellen, fertig

Am 2026-11-23 an der echten CS20L bestätigt (Handy, Bereitschaft).

Ein Tipp auf „Wiegen“ wählt die Waage (Chrome-Dialog). Danach ist die Karte **in Bereitschaft** (`watchScale` im Treiber):
Sie versucht alle 3 s, die Waage zu verbinden (mit `watchAdvertisements()`, falls Chrome es anbietet, erst beim Funksignal).
Wacht die Waage auf, weil man draufsteigt, verbindet sich die Seite, holt die Wiegung (live oder aus dem Speicher) und speichert sie.
Danach 30 s Pause, dann wieder Bereitschaft. Die Seite muss offen und sichtbar sein (im Hintergrund pausiert sie); solange hält
sie den Bildschirm wach (Wake Lock). „Bereitschaft aus“ beendet das.

- Ohne `getDevices()` braucht es einen Tipp pro Seitenaufruf (Chrome erlaubt den Gerätedialog nur nach einer Geste).
- Mit `getDevices()` (vermutlich nur mit dem Flag „Experimental Web Platform features“) startet die Bereitschaft beim Öffnen von selbst.
- Jede Verbindung bekommt eine Nummer: Das verzögerte Trennen nach einer Messung trifft nie eine neuere Verbindung
  (Test `client/tests/qn-scale-standby.test.cjs` mit simulierter Waage).

## Optional: Empfänger am PC

`tools/scale/receiver.py` (siehe `tools/scale/README.md`) wartet auf dem Windows-PC auf die Waage und holt jede Wiegung
automatisch ab. Das Handy braucht man dann nicht. Voraussetzung: Der PC erreicht die Waage per Bluetooth.

## Koppel-Dialog nur einmal?

Chrome merkt sich erlaubte Bluetooth-Geräte nur, wenn er `navigator.bluetooth.getDevices()` anbietet. Auf Android steht das laut
Implementierungsstand hinter „Experimental Web Platform features“ (`chrome://flags`); für die aktuelle Chrome-Version nicht bestätigt.
Gibt es die Funktion, verbindet Milon ohne Dialog mit der gemerkten Waage (Name beginnt mit „QN“); klappt das nicht, kommt der Dialog.
Ganz ohne Knopfdruck geht es im Browser nicht: eine geschlossene Seite kann nicht nach der Waage suchen.

## Troubleshooting

- **Waage taucht im Dialog nicht auf:** Waage erneut antippen (sie sendet nur kurz). Dann „Alle Geräte anzeigen“ und das Gerät von Hand wählen.
  Meldet sie sich unter anderem Namen, das Debug-Log kopieren – der Name steht in der ersten Zeile.
- **Verbindet, aber kein Gewicht:** Erst nach „Bereit“ draufstellen und 10–20 s stehen bleiben. Kommt nach 20 s nichts, zeigt die Karte einen Hinweis. Debug-Log aufklappen, „Log kopieren“, in einen Chat oder ein Issue einfügen. Alle Pakete stehen
  dort als Hex (`←` empfangen, `→` gesendet). Häufigste Ursache: andere Protokollfamilie (dann fehlt `FFF2`/`FFE3`).
- **Verbindung bricht sofort ab / „NetworkError“:** Arboleaf-App ganz beenden (auch aus den zuletzt genutzten Apps wischen).
- **Kein Bluetooth-Dialog:** In Android Chrome Bluetooth- und Standort-Berechtigung erlauben (Android-Einstellungen → Apps → Chrome →
  Berechtigungen „Geräte in der Nähe“ und „Standort“), Bluetooth und Standort einschalten.
- **„Wiegen geht in diesem Browser nicht“:** Milon über die HTTPS-Adresse (Tailscale) in Chrome öffnen.
- **Falsche Messung (z. B. jemand anderes):** Unter „Letzte Wiegungen per Bluetooth“ löschen.
