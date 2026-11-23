# Waagen-Empfänger („draufstellen, fertig“)

Läuft auf dem Windows-PC neben dem Laufband-Recorder, nicht in Docker (Docker Desktop hat kein Bluetooth).
Er wartet auf die Arboleaf-Waage (Name beginnt mit `QN`). Wer sich draufstellt, weckt sie; der Empfänger verbindet sich,
holt die Messung ab und schickt sie an Milon (`POST /api/scale/measurements`, derselbe Endpunkt wie das Handy).
Protokoll wie im Browser-Treiber, als Python in `qn.py` (Tests: `server/tests/test_scale_receiver.py`).

- **Ablauf:** Handshake, dann alle 3 s den Speicher der Waage abfragen, bis die Wiegung da ist (live `0x10` oder gespeichert `0x23`),
  höchstens 2 min je Verbindung. Danach 30 s Pause, weil die Waage noch eine Weile sendet.
- **Ältere Messungen** aus dem Speicher der Waage gehen mit ihrer eigenen Uhrzeit an Milon. Die Waage löscht sie nach dem Senden.
- **Milon nicht erreichbar:** Messungen warten in `%LOCALAPPDATA%\milon-scale\spool\`. Abgelehnte (422) landen in `rejected\`.
- **Log:** `%LOCALAPPDATA%\milon-scale\receiver.log`, mit jedem Bluetooth-Paket als Hex.
- **Nur eine Verbindung:** Solange der Empfänger mit der Waage verbunden ist, kann das Handy („Wiegen“) nicht verbinden.
- **Reichweite:** Der PC muss die Waage per Bluetooth erreichen. Sonst läuft dasselbe Skript auf einem Gerät näher am Bad (z. B. Raspberry Pi; `SCALE_URL` auf Milon zeigen lassen).

## Einrichten

1. Eigene venv:

   ```bash
   py -3 -m venv tools/scale/.venv
   ```

   ```bash
   tools/scale/.venv/Scripts/pip install -r tools/scale/requirements.txt
   ```

2. Optional `tools/scale/.env.example` nach `tools/scale/.env` kopieren (URL, Name, MAC).
3. Testlauf mit Ausgabe im Terminal:

   ```bash
   tools/scale/.venv/Scripts/python tools/scale/receiver.py
   ```

4. Autostart bei Anmeldung, ohne Fenster: Verknüpfung „Milon Waage“ im Autostart-Ordner
   (`shell:startup`) auf `tools\scale\.venv\Scripts\pythonw.exe "<Repo>\tools\scale\receiver.py"`.
