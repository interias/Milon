# Walking-Pad-Recorder

Läuft auf dem Windows-PC, nicht in Docker, denn Docker Desktop hat kein Bluetooth. Er verbindet sich mit dem Pad
(FTMS-Dienst `0x1826`, getestet mit Sportstech sWalk Lite) und hört nur mit (Treadmill Data `0x2ACD`). Er schreibt nie an den
Control Point. Jede beendete Session schickt er an Milon (`POST /api/walkpad/sessions`).

- **Ende einer Session:** Zähler-Reset am Pad, 5 min Stillstand oder 3 min ohne Verbindung. Kürzer als 2 min oder 100 m wird verworfen.
- **Pause ohne Reset (> 5 min):** Danach beginnt eine neue Session, die nur den Teil nach der Pause zählt.
- **Server nicht erreichbar:** Sessions warten in `%LOCALAPPDATA%\milon-walkpad\spool\` und werden später gesendet.
  Das Log liegt in `recorder.log` im selben Ordner.
- **Nur eine Verbindung gleichzeitig:** Solange der Recorder verbunden ist, kann die Sportstech-App das Pad nicht verbinden.
  Bedient wird das Pad über die Fernbedienung.

## Einrichten

1. In `server/.env` `WALKPAD_TOKEN=<zufälliger Wert>` setzen und den Server neu starten (`docker compose up -d`).
2. `tools/walkpad/.env.example` nach `tools/walkpad/.env` kopieren und denselben Token eintragen.
3. Eigene venv anlegen:

   ```bash
   py -3 -m venv tools/walkpad/.venv
   ```

   ```bash
   tools/walkpad/.venv/Scripts/pip install -r tools/walkpad/requirements.txt
   ```

4. Testlauf, Ausgabe im Terminal:

   ```bash
   tools/walkpad/.venv/Scripts/python tools/walkpad/recorder.py
   ```

5. Autostart bei Anmeldung, ohne Fenster (Pfad anpassen):

   ```bash
   schtasks /Create /TN "Milon Walkpad" /SC ONLOGON /RL LIMITED /TR "\"<Repo>\tools\walkpad\.venv\Scripts\pythonw.exe\" \"<Repo>\tools\walkpad\recorder.py\""
   ```

Schrittlänge, Standard-Steigung und Garmin-Upload stellst du in Milon unter Einstellungen → Laufband ein.
