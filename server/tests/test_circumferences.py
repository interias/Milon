import json
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app import circumferences
from app.api import circumferences as circumferences_api


PATH = "/body-circumferences"
BASE = {"date": "2026-10-03", "protocol": "standard", "values": {"abdomen_navel": 86.2, "waist_narrowest": 81.5}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'circumferences.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[circumferences.CircumferenceEntry.__table__,
                                               circumferences.CircumferencePreferences.__table__])
    monkeypatch.setattr(circumferences, "engine", engine)
    monkeypatch.setattr(circumferences, "local_today", lambda: date(2026, 10, 4))
    app = FastAPI()
    app.include_router(circumferences_api.router)
    with TestClient(app) as test_client:
        yield test_client
    circumferences.engine.dispose()


def test_roundtrip_reopen_replace_delete_and_protocol_isolation(client, monkeypatch):
    initial = client.get(PATH).json()
    assert initial["today"] == "2026-10-04" and initial["entries"] == []
    assert len(initial["definitions"]) == 8
    assert all(set(row) == {"key", "name", "site", "color", "definition", "guide"} for row in initial["definitions"])
    created = client.post(PATH, json=BASE)
    assert created.status_code == 200
    entry_id = created.json()["id"]
    unknown = client.post(PATH, json={**BASE, "protocol": "unknown", "values": {"abdomen_navel": 88}}).json()
    older = client.post(PATH, json={**BASE, "date": "2025-10-03"}).json()
    with Session(circumferences.engine) as session:
        assert session.get(circumferences.CircumferenceEntry, entry_id).definition_version == "v1"
    database_url = str(circumferences.engine.url)
    circumferences.engine.dispose()
    reopened = create_engine(database_url, connect_args={"check_same_thread": False})
    monkeypatch.setattr(circumferences, "engine", reopened)
    entries = client.get(PATH).json()["entries"]
    assert [row["id"] for row in entries] == [unknown["id"], entry_id, older["id"]]
    replacement = {"date": "2026-10-04", "protocol": "standard", "values": {"hip_widest": 96.5}}
    changed = client.put(f"{PATH}/{entry_id}", json=replacement)
    assert changed.status_code == 200 and changed.json() == {"id": entry_id, **replacement}
    assert client.get(PATH).json()["entries"][1] == unknown
    assert client.delete(f"{PATH}/{entry_id}").json() == {"deleted": entry_id}
    assert [row["id"] for row in client.get(PATH).json()["entries"]] == [unknown["id"], older["id"]]


def test_duplicate_create_and_move_do_not_overwrite_existing_entries(client):
    first = client.post(PATH, json=BASE).json()
    second = client.post(PATH, json={**BASE, "date": "2026-10-04"}).json()
    duplicate = client.post(PATH, json={**BASE, "values": {"hip_widest": 95}})
    assert duplicate.status_code == 409 and "bearbeiten" in duplicate.json()["detail"]
    assert client.put(f"{PATH}/{second['id']}", json=BASE).status_code == 409
    assert client.get(PATH).json()["entries"] == [second, first]
    assert client.put(f"{PATH}/{first['id']}", json=BASE).status_code == 200


@pytest.mark.parametrize("values", [{}, {"other": 90}, {"abdomen_navel": True},
                                     {"abdomen_navel": "86.2"}, {"abdomen_navel": None},
                                     {"abdomen_navel": []}, {"abdomen_navel": 9.99}, {"abdomen_navel": 250.01},
                                     {"abdomen_navel": 10 ** 400}])
def test_invalid_values_do_not_create_or_replace(client, values):
    saved = client.post(PATH, json=BASE).json()
    assert client.post(PATH, json={**BASE, "date": "2026-10-04", "values": values}).status_code == 422
    assert client.put(f"{PATH}/{saved['id']}", json={**BASE, "values": values}).status_code == 422
    assert client.get(PATH).json()["entries"] == [saved]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_values_return_json_error(client, value):
    payload = json.dumps({**BASE, "values": {"abdomen_navel": value}})
    result = client.post(PATH, content=payload, headers={"Content-Type": "application/json"})
    assert result.status_code == 422 and "endlichen" in result.json()["detail"]
    assert client.get(PATH).json()["entries"] == []


@pytest.mark.parametrize("patch", [{"date": "2026-10-05"}, {"date": "2026-02-30"}, {"date": 0}, {"date": "0000000000"},
                                    {"protocol": "other"}, {"source": "health_connect"}])
def test_invalid_dates_protocol_and_extra_fields(client, patch):
    result = client.post(PATH, json={**BASE, **patch})
    assert result.status_code == 422
    assert client.get(PATH).json()["entries"] == []


def test_boundaries_and_missing_ids(client):
    valid = {**BASE, "values": {"abdomen_navel": 10, "shoulders_deltoid": 250}}
    assert client.post(PATH, json=valid).status_code == 200
    assert client.put(f"{PATH}/999", json=valid).status_code == 404
    assert client.delete(f"{PATH}/999").status_code == 404


def test_preferences_are_persistent_and_singleton(client, monkeypatch):
    assert client.get(PATH).json()["preferences"] == {
        "visible_keys": ["abdomen_navel", "waist_narrowest", "hip_widest", "upper_arm_right"],
        "layout": "rows", "period": "6m"}
    preferences = {"visible_keys": ["calf_right_max", "chest_nipple"], "layout": "atlas", "period": "12m"}
    assert client.put(f"{PATH}/preferences", json=preferences).json() == preferences
    url = str(circumferences.engine.url)
    circumferences.engine.dispose()
    monkeypatch.setattr(circumferences, "engine", create_engine(url, connect_args={"check_same_thread": False}))
    assert client.get(PATH).json()["preferences"] == preferences
    preferences["period"] = "all"
    assert client.put(f"{PATH}/preferences", json=preferences).json() == preferences
    with Session(circumferences.engine) as session:
        assert len(session.exec(select(circumferences.CircumferencePreferences)).all()) == 1


@pytest.mark.parametrize("patch", [
    {"visible_keys": []}, {"visible_keys": ["abdomen_navel", "abdomen_navel"]},
    {"visible_keys": ["other"]}, {"visible_keys": ["abdomen_navel", "waist_narrowest", "hip_widest", "upper_arm_right", "chest_nipple"]},
    {"visible_keys": [True]}, {"layout": "other"}, {"period": "2m"}, {"extra": True},
])
def test_invalid_preferences_preserve_saved_selection(client, patch):
    preferences = {"visible_keys": ["abdomen_navel"], "layout": "rows", "period": "1m"}
    assert client.put(f"{PATH}/preferences", json=preferences).status_code == 200
    assert client.put(f"{PATH}/preferences", json={**preferences, **patch}).status_code == 422
    assert client.get(PATH).json()["preferences"] == preferences


def test_today_uses_configured_timezone(monkeypatch):
    now = datetime(2026, 10, 3, 23, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(circumferences.settings, "timezone", "Europe/Berlin")
    assert circumferences.local_today(now) == date(2026, 10, 4)
    monkeypatch.setattr(circumferences.settings, "timezone", "America/New_York")
    assert circumferences.local_today(now) == date(2026, 10, 3)
