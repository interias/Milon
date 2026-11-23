# Körperwaage per Web Bluetooth (Arboleaf CS20L)

Milon liest die Waage direkt im Handy-Browser aus. Die Arboleaf-App wird dafür nicht mehr gebraucht.

## Ablauf

1. Arboleaf-App schließen (sie hält sonst die Bluetooth-Verbindung).
2. Waage antippen – sie wacht auf und sendet.
3. In Milon „Wiegen“ tippen (Übersicht → „Wiegen“, `/wiegen` oder Körper → Gewicht → „Wiegen“).
4. Chrome zeigt den Gerätedialog → Waage wählen (meist `QN-Scale` / `QN-Scale1`).
5. Barfuß draufstellen. Das Live-Gewicht läuft mit; die stabile Messung wird automatisch gespeichert.

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

**Noch nicht an der echten Waage geprüft.** Die Tests nutzen synthetische Frames.

## Troubleshooting

- **Waage taucht im Dialog nicht auf:** Waage erneut antippen (sie sendet nur kurz). Dann „Alle Geräte anzeigen“ und das Gerät von Hand wählen.
  Meldet sie sich unter anderem Namen, das Debug-Log kopieren – der Name steht in der ersten Zeile.
- **Verbindet, aber kein Gewicht:** Debug-Log aufklappen, „Log kopieren“, in einen Chat oder ein Issue einfügen. Alle Pakete stehen
  dort als Hex (`←` empfangen, `→` gesendet). Häufigste Ursache: andere Protokollfamilie (dann fehlt `FFF2`/`FFE3`).
- **Verbindung bricht sofort ab / „NetworkError“:** Arboleaf-App ganz beenden (auch aus den zuletzt genutzten Apps wischen).
- **Kein Bluetooth-Dialog:** In Android Chrome Bluetooth- und Standort-Berechtigung erlauben (Android-Einstellungen → Apps → Chrome →
  Berechtigungen „Geräte in der Nähe“ und „Standort“), Bluetooth und Standort einschalten.
- **„Wiegen geht in diesem Browser nicht“:** Milon über die HTTPS-Adresse (Tailscale) in Chrome öffnen.
- **Falsche Messung (z. B. jemand anderes):** Unter „Letzte Wiegungen per Bluetooth“ löschen.
