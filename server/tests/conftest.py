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
