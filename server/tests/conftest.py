import pytest
from sqlmodel import SQLModel, create_engine

from app import models  # noqa: F401 - registriert die Tabellen in SQLModel.metadata
from app.coach import client
from app.config import settings


@pytest.fixture(autouse=True)
def _no_real_llm_provider(monkeypatch):
    """server/.env may hold a real ANTHROPIC_API_KEY; tests must never reach the live API."""
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "llm_provider", "")


@pytest.fixture(autouse=True)
def _no_real_hevy(monkeypatch):
    """Der Plan-Schreiber setzt Hevy-Routinen; Tests dürfen nie das echte Konto beschreiben."""
    monkeypatch.setattr(settings, "hevy_api_key", "")


@pytest.fixture(scope="session")
def _costs_engine(tmp_path_factory):
    engine = create_engine(f"sqlite:///{tmp_path_factory.mktemp('costs') / 'costs.db'}",
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_real_cost_db(monkeypatch, _costs_engine):
    """Die Budget-Pruefung (client._skip_reason, GET /settings) liest coach_reports; nie aus data/tracker.db."""
    monkeypatch.setattr(client, "engine", _costs_engine)


@pytest.fixture(scope="session")
def _world_engine(tmp_path_factory):
    engine = create_engine(f"sqlite:///{tmp_path_factory.mktemp('world') / 'world.db'}",
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_real_world_db(monkeypatch, _world_engine):
    """hero_world liest Radfahrten und eigene Strecken über sein engine; Tests, die nur _routes mocken,
    dürfen dabei nie data/tracker.db öffnen. Tests mit eigener DB setzen hero_world.engine danach selbst."""
    from app import hero_world
    monkeypatch.setattr(hero_world, "engine", _world_engine)


@pytest.fixture(scope="session")
def _ride_engine(tmp_path_factory):
    from app import bike_plan, garmin_indoor  # noqa: F401 -- registriert garmin_indoor_*/bike_plan_* vor create_all
    engine = create_engine(f"sqlite:///{tmp_path_factory.mktemp('rides') / 'rides.db'}",
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_real_ride_db(monkeypatch, _ride_engine):
    """Fahrten zählen als Trainingstage (activity.*, weekly_journal); cycling/health lesen sie über ihr
    eigenes engine und dürfen in Tests nie data/tracker.db öffnen. Tests mit eigener DB setzen es danach selbst."""
    from app import bike_plan
    from app.metrics import cycling, health
    monkeypatch.setattr(cycling, "engine", _ride_engine)
    monkeypatch.setattr(health, "engine", _ride_engine)
    monkeypatch.setattr(bike_plan, "engine", _ride_engine)  # Morgenbriefing liest den Rad-Plan


@pytest.fixture(scope="session")
def _indoor_engine(tmp_path_factory):
    from app import garmin_indoor  # noqa: F401 -- registriert garmin_indoor_* vor create_all
    engine = create_engine(f"sqlite:///{tmp_path_factory.mktemp('indoor') / 'indoor.db'}",
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_real_indoor_db(monkeypatch, _indoor_engine):
    """Jeder Garmin-Sync mit gemocktem Client reicht Indoor-Fahrten an garmin_indoor weiter; der darf
    nie data/tracker.db öffnen. Tests mit eigener DB setzen garmin_indoor.engine danach selbst."""
    from app import garmin_indoor
    monkeypatch.setattr(garmin_indoor, "engine", _indoor_engine)


@pytest.fixture(scope="session")
def _walkpad_engine(tmp_path_factory):
    from app import walkpad  # noqa: F401 -- registriert walkpad_sessions vor create_all
    engine = create_engine(f"sqlite:///{tmp_path_factory.mktemp('walkpad') / 'walkpad.db'}",
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_real_walkpad_db(monkeypatch, _walkpad_engine):
    """Jeder Garmin-Sync (gemockter Client) lädt Laufband-Walks hoch und liest Uhr-Schritte; nie aus data/tracker.db."""
    from app import walkpad
    monkeypatch.setattr(walkpad, "engine", _walkpad_engine)
    monkeypatch.setattr(walkpad, "_weights", lambda: None)  # ACSM-kcal liest sonst das Gewicht aus tracker.db
    monkeypatch.setattr(settings, "walkpad_token", "")
