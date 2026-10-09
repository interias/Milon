"""Konfiguration & Pfade. Liest server/.env (pydantic-settings)."""
import re
from datetime import date
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py -> app -> server -> <repo-root>
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
INCOMING_DIR = DATA_DIR / "incoming"
PROGRESS_DIR = DATA_DIR / "progress"  # Fortschritts-/Optik-Fotos (statisches Dateisystem)
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"  # server/.env


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        extra="ignore",
    )

    # Default: <repo>/data/tracker.db (absolut, cwd-unabhaengig)
    database_url: str = f"sqlite:///{(DATA_DIR / 'tracker.db').as_posix()}"
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-6-luna"
    coach_context: str = ""
    timezone: str = "Europe/Berlin"

    # Körper-Messungen (Gewicht/KFA) nur aus dieser Health-Connect-App (Waage) übernehmen;
    # leer = alle Quellen. Andere Apps (Google Fit, Samsung Health) erzeugen Ausreißer.
    body_source_package: str = "com.qingniu.arboleaf"
    # Personal import bounds; unset means no personal lower/upper limit.
    body_weight_min_kg: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    body_weight_max_kg: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_body_weight_bounds(self):
        if (self.body_weight_min_kg is not None and self.body_weight_max_kg is not None
                and self.body_weight_min_kg >= self.body_weight_max_kg):
            raise ValueError("BODY_WEIGHT_MIN_KG must be less than BODY_WEIGHT_MAX_KG")
        return self

    # Schritte nur aus dieser HC-App: maßgeblich die Galaxy Watch (Samsung Health). Google Fit
    # zählt das Handy und untertreibt an Tagen ohne Handy → wird ausgeschlossen.
    # Leer = Maximum je Tag über alle Apps (entdoppelt, aber inkl. Handy-Tage).
    steps_source_package: str = "com.sec.android.app.shealth"

    # Optional watch replacement: keep the historical source before the cutoff.
    watch_source_switch_date: date | None = None
    watch_source_package: str = ""
    # Explicit transition sessions retained until the handover time is clarified.
    watch_source_legacy_session_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_watch_switch(self):
        if self.watch_source_switch_date is not None and not self.watch_source_package:
            raise ValueError("WATCH_SOURCE_PACKAGE is required with WATCH_SOURCE_SWITCH_DATE")
        return self

    # Quell-Zugaenge (Hevy-API + FDDB-Login/Cookies)
    hevy_api_key: str = ""
    fddb_user: str = ""
    fddb_pw: str = ""
    fddb_cookie: str = ""
    fddb_phpsessid: str = ""

    # Health Connect via Google Drive: taegliche Export-Zip ziehen.
    # "Jeder mit dem Link"-Inhalte sind per anonymem API-Key NICHT erreichbar (Google blockt das) ->
    # der no-OAuth-Weg ist der keylose Download per DATEI-ID (gdown). Aus dem Datei-Freigabelink
    # https://drive.google.com/file/d/<ID>/view die <ID> nehmen.
    hc_drive_file_id: str = ""
    # Optional/Legacy (nur fuer einen WIRKLICH oeffentlichen Ordner per API-Key nutzbar):
    google_api_key: str = ""
    hc_drive_folder_id: str = ""
    hc_drive_filename: str = "Health Connect.zip"

    scheduler_enabled: bool = True

    # Maximalpuls für die Lauf-Puls-Zonen (%HFmax). Fester Wert ist robuster als die
    # Datenableitung (einzelne Sensor-Spikes verschieben das beobachtete Max). 0 = aus
    # den Daten ableiten (robustes 95.-Perzentil der max_hr, Boden 180).
    run_hr_max: float = 180.0

    # Wetter auf der Übersicht (Open-Meteo). Orte werden in den Einstellungen per Name geocodiert;
    # erster Ort = Standard. WEATHER_PLACE/LAT/LON = Altformat (ein Ort), wird beim Speichern abgelöst.
    weather_places: list[dict] = Field(default_factory=list)
    weather_place: str = ""
    weather_lat: float | None = None
    weather_lon: float | None = None

    @field_validator("weather_lat", "weather_lon", mode="before")
    @classmethod
    def blank_coordinate(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    def resolved_database_url(self) -> str:
        """Bindet eine relative sqlite-URL (sqlite:///./...) an die Repo-Root,
        damit die DB unabhaengig vom Arbeitsverzeichnis immer am selben Ort liegt."""
        url = self.database_url
        prefix = "sqlite:///./"
        if url.startswith(prefix):
            return f"sqlite:///{(ROOT / url[len(prefix):]).as_posix()}"
        return url


def watch_source_for(day: date, config=None) -> str:
    """Return the configured watch source for a local calendar date."""
    config = config if config is not None else settings
    cutoff = getattr(config, "watch_source_switch_date", None)
    if cutoff is not None and day >= cutoff:
        return getattr(config, "watch_source_package", "")
    return config.steps_source_package


settings = Settings()

# Datenverzeichnisse sicherstellen
DATA_DIR.mkdir(parents=True, exist_ok=True)
INCOMING_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_DIR.mkdir(parents=True, exist_ok=True)


def update_env_file(updates: dict[str, str]) -> None:
    """Aktualisiert/ergänzt KEY=VALUE-Zeilen in server/.env (Kommentare bleiben erhalten)."""
    keys = {k.upper(): str(v) for k, v in updates.items()}
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    out, seen = [], set()
    for line in lines:
        m = re.match(r"\s*([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in keys:
            out.append(f"{m.group(1)}={keys[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(line)
    for k, v in keys.items():
        if k not in seen:
            out.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
