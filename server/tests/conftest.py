import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _no_real_llm_provider(monkeypatch):
    """server/.env may hold a real ANTHROPIC_API_KEY; tests must never reach the live API."""
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "llm_provider", "")
