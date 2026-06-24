"""Health-Connect-Auto-Pull aus Google Drive (Phase 2).

WICHTIG: „Jeder mit dem Link"-Inhalte sind über einen anonymen API-Key NICHT erreichbar
(Google blockt Listing UND Get → 404). Der zuverlässige no-OAuth-Weg ist daher der
**keylose Download per fester Datei-ID** (gdown nutzt den uc-Download-Pfad und handhabt auch
große Dateien + die Viren-Scan-Bestätigung). Aus dem Datei-Freigabelink
`https://drive.google.com/file/d/<ID>/view` die `<ID>` als `HC_DRIVE_FILE_ID` in server/.env.

Funktioniert dauerhaft, solange der Export dieselbe Datei *überschreibt* (stabile ID). Legt das
Export-Tool die Datei täglich neu an (neue ID), bricht der Link → dann auf ein Service-Account
(robust, name-basiert) umstellen.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from ..config import INCOMING_DIR, settings

HC_DB = INCOMING_DIR / "health_connect_export.db"


def _file_id() -> str:
    """Datei-ID aus der Config — akzeptiert auch einen vollen Freigabelink."""
    raw = (settings.hc_drive_file_id or "").strip()
    if not raw:
        raise RuntimeError("HC_DRIVE_FILE_ID fehlt in server/.env (Datei-Freigabelink → ID).")
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", raw) or re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", raw)
    return m.group(1) if m else raw


def _download_zip(dest: Path) -> int:
    """Lädt die HC-Zip keylos per Datei-ID nach `dest`. Gibt die Byte-Anzahl zurück."""
    import gdown  # lazy: nur nötig, wenn der Drive-Pull tatsächlich läuft

    fid = _file_id()
    out = gdown.download(id=fid, output=str(dest), quiet=True)
    if not out or not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(
            "Download per Datei-ID fehlgeschlagen — ist die Datei auf 'Jeder mit dem Link' "
            f"freigegeben und die ID korrekt? (id={fid[:12]}…)")
    return dest.stat().st_size


def pull(full: bool = False) -> dict:
    """Zieht die HC-Zip aus Drive, entpackt `health_connect_export.db` nach data/incoming/
    (atomar) und importiert sie. full=True erzwingt eine Voll-Reconciliation."""
    from . import health_connect  # lazy, vermeidet Import-Zyklus

    with tempfile.TemporaryDirectory() as td:
        zpath = Path(td) / "hc.zip"
        size = _download_zip(zpath)
        try:
            with zipfile.ZipFile(zpath) as z:
                member = next((n for n in z.namelist() if n.endswith("health_connect_export.db")), None)
                if not member:
                    raise RuntimeError(
                        f"Zip enthält keine health_connect_export.db (Inhalt: {z.namelist()[:10]})")
                extracted = Path(z.extract(member, td))
        except zipfile.BadZipFile:
            raise RuntimeError(f"Heruntergeladene Datei ist keine gültige Zip ({size} Bytes)")
        INCOMING_DIR.mkdir(parents=True, exist_ok=True)
        tmp_db = HC_DB.with_name(HC_DB.name + ".tmp")
        shutil.copyfile(extracted, tmp_db)
        tmp_db.replace(HC_DB)  # atomares Ersetzen der gestageten DB

    counts = health_connect.import_health_connect(HC_DB, full=full)
    return {"file_id": _file_id(), "zip_bytes": size, **counts}
