"""Morgenbriefing (#52): Auslöser, Idempotenz und Prompt-Inhalt — gemocktes LLM, synthetische Daten, tmp-SQLite."""
from datetime import date, datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app import hero_world, weather
from app.api import coach as coach_api
from app.coach import briefing
from app.garmin_daily import GarminDaily, PACKAGE
from app.metrics import sleep
from app.models import CoachReport

TZ = ZoneInfo("Europe/Berlin")
DAY = date(2026, 10, 17)
SUNRISE, SUNSET = "2026-10-17T07:58", "2026-10-17T18:40"
HOME = (51.6789, 6.6123)          # synthetische Heimat; darf nie im Prompt landen
WEATHER_AT = (51.6612, 6.6234)    # synthetischer Wetterort
USAGE = {"prompt_tokens": 1200, "completion_tokens": 180, "cost": 0.012, "cache_read_tokens": 0,
         "provider": "anthropic", "model": "claude-opus-5-5", "fallback_reason": None}


def at(hour, minute=0, day=DAY):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for module in (briefing, sleep):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(briefing.settings, "timezone", "Europe/Berlin")
    yield engine
    engine.dispose()


@pytest.fixture
def llm(monkeypatch):
    calls = []

    def complete(messages, temperature=0.4):
        calls.append(messages)
        return "**Heute:** lockerer Lauf, 45 min ab 8:00\n- **Schlaf & Erholung:** …", dict(USAGE)

    monkeypatch.setattr(briefing.client, "complete", complete)
    monkeypatch.setattr(briefing.prompts, "system_prompt", lambda: "SYSTEM")
    monkeypatch.setattr(briefing.snapshot, "snapshot_text", lambda: "SNAPSHOT")
    monkeypatch.setattr(briefing, "_context_lines", lambda day: ["CHECK-IN (heute/gestern, freiwillig): keine Einträge"])
    return calls


def forecast_raw() -> dict:
    """Open-Meteo-Antwort für zwei Tage: 10 °C nachts, 14 °C tagsüber, trocken."""
    times = [f"{d}T{h:02d}:00" for d in ("2026-10-17", "2026-10-18") for h in range(24)]
    temps = [14.0 if 8 <= int(t[11:13]) <= 17 else 10.0 for t in times]
    return {"hourly": {"time": times, "temperature_2m": temps, "precipitation_probability": [5] * len(times),
                       "precipitation": [0.0] * len(times), "weather_code": [2] * len(times),
                       "is_day": [int(8 <= int(t[11:13]) <= 18) for t in times], "wind_speed_10m": [8.0] * len(times)},
            "daily": {"time": ["2026-10-17", "2026-10-18"], "sunrise": [SUNRISE, "2026-10-18T08:00"],
                      "sunset": [SUNSET, "2026-10-18T18:38"]},
            "current": {"temperature_2m": 9.0, "weather_code": 2, "is_day": 0}}


@pytest.fixture
def world(monkeypatch):
    """Echtes Wetter- und Weltkarten-Rechnen auf synthetischen Koordinaten."""
    monkeypatch.setattr(weather, "_cache", {})
    monkeypatch.setattr(weather, "_fetch", lambda lat, lon: forecast_raw())
    monkeypatch.setattr(briefing.settings, "weather_places", [{"place": "Testdorf", "lat": WEATHER_AT[0], "lon": WEATHER_AT[1]}])
    east = [(HOME[0], HOME[1] + 0.0003 * i) for i in range(50)]  # ~1 km Lauf nach Osten
    monkeypatch.setattr(hero_world, "_routes", lambda: [(date(2026, 10, 10), east)])
    near = [[HOME[0] + 0.019 + 0.0005 * i, HOME[1] + 0.031] for i in range(8)]   # ~3 km im Nordosten
    far = [[HOME[0] - 0.08 - 0.0005 * i, HOME[1]] for i in range(8)]            # ~9 km im Süden
    monkeypatch.setattr(hero_world, "dungeon_defs", lambda: [
        {"key": "fern", "name": "Ferne Gruft", "type": "dorf", "desc": "", "length_m": 900,
         "segments": [{"boss": "B", "points": far}]},
        {"key": "teich", "name": "Spiegel des Testteichs", "type": "wasser", "desc": "", "length_m": 900,
         "segments": [{"boss": "A", "points": near}]}])
    monkeypatch.setattr(hero_world, "_memo", {})


def night_row(engine, day=DAY):
    end = datetime(day.year, day.month, day.day, 4, 10, tzinfo=timezone.utc)  # 06:10 Ortszeit
    start = end - timedelta(hours=7)
    levels = [{"startGMT": (start + timedelta(hours=i)).isoformat(), "endGMT": (start + timedelta(hours=i + 1)).isoformat(),
               "activityLevel": 3 if i == 6 else 1} for i in range(7)]
    data = {"dailySleepDTO": {"sleepStartTimestampGMT": start.timestamp() * 1000,
                              "sleepEndTimestampGMT": end.timestamp() * 1000}, "sleepLevels": levels}
    with Session(engine) as s:
        s.add(GarminDaily(day=day, raw_json=json.dumps({"sleep": data}), status_json="{}"))
        s.commit()


def reports(engine):
    with Session(engine) as s:
        return s.exec(select(CoachReport)).all()


# --- Auslöser -------------------------------------------------------------------------------

def test_due_waits_for_four_then_sleep_or_deadline():
    rise = datetime(2026, 10, 17, 7, 58)
    assert briefing.due(at(3, 55), True, rise) is None             # vor 04:00 nie
    assert briefing.due(at(4, 0), True, rise) == "sleep"
    assert briefing.due(at(6, 57), False, rise) is None            # Frist = 06:58
    assert briefing.due(at(6, 58), False, rise) == "deadline"
    assert briefing.due(at(5, 59), False, None) is None            # ohne Sonnenaufgang: Ersatzfrist 06:00
    assert briefing.due(at(6, 0), False, None) == "deadline"


def test_sleep_present_generates_immediately_and_second_run_does_nothing(db, llm, world, monkeypatch):
    monkeypatch.setattr(briefing.settings, "watch_source_package", PACKAGE)
    monkeypatch.setattr(briefing.settings, "watch_source_switch_date", date(2026, 9, 25))
    night_row(db)
    first = briefing.maybe_run(at(4, 20))
    assert first and first["kind"] == "briefing" and first["cost_usd"] == 0.012
    assert briefing.maybe_run(at(4, 35)) is None
    assert briefing.maybe_run(at(9, 0)) is None
    rows = reports(db)
    assert len(rows) == 1 and len(llm) == 1
    assert rows[0].created_at == datetime(2026, 10, 17, 4, 20)
    assert rows[0].provider == "anthropic" and rows[0].prompt_tokens == 1200
    assert json.loads(rows[0].prompt) == llm[0]                    # Prompt gespeichert
    assert "SCHLAF LETZTE NACHT (Garmin): 23:10–06:10, Schlafzeit 6.0 h" in llm[0][-1]["content"]


def test_without_sleep_waits_until_one_hour_before_sunrise(db, llm, world, monkeypatch):
    monkeypatch.setattr(briefing, "main_night", lambda day: None)
    assert briefing.maybe_run(at(4, 20)) is None
    assert briefing.maybe_run(at(6, 55)) is None
    assert briefing.maybe_run(at(6, 58))["kind"] == "briefing"
    assert "keine Hauptnacht synchronisiert (Stand 06:58)" in llm[0][-1]["content"]
    assert briefing.maybe_run(at(7, 30)) is None
    assert len(reports(db)) == 1


def test_new_day_gets_its_own_briefing(db, llm, world, monkeypatch):
    monkeypatch.setattr(briefing, "main_night", lambda day: {"source": "Garmin", "started_at": "x" * 16,
                                                              "ended_at": "x" * 16, "asleep_minutes": 420,
                                                              "window_minutes": 450, "awake_minutes": 30})
    assert briefing.maybe_run(at(4, 10))
    assert briefing.maybe_run(at(4, 10, DAY + timedelta(days=1)))
    assert len(reports(db)) == 2


def test_main_night_ignores_missing_rows(db, monkeypatch):
    monkeypatch.setattr(briefing.settings, "watch_source_package", PACKAGE)
    monkeypatch.setattr(briefing.settings, "watch_source_switch_date", date(2026, 9, 25))
    assert briefing.main_night(DAY) is None
    night_row(db, DAY - timedelta(days=1))                        # die Nacht davor zählt nicht
    assert briefing.main_night(DAY) is None


# --- Prompt-Inhalt --------------------------------------------------------------------------

def test_prompt_has_weather_from_sunrise_and_dungeon_without_coordinates(db, llm, world, monkeypatch):
    monkeypatch.setattr(briefing, "main_night", lambda day: None)
    briefing.maybe_run(at(7, 0))
    messages = llm[0]
    assert [m["role"] for m in messages] == ["system", "system", "user"]
    assert messages[1]["content"].endswith("SNAPSHOT")             # Snapshot im letzten System-Block (Cache)
    user = messages[-1]["content"]
    assert "Sonnenaufgang 07:58" in user
    assert "Morgenlauf ab Sonnenaufgang 08:00–09:00: 14.0 °C" in user
    assert "Kleidung: Kurze Sachen" in user
    assert "„Spiegel des Testteichs“ (Wasser" in user and "im Nordosten von zu Hause" in user
    assert "3,1 km" in user or "3,0 km" in user
    assert "Ferne Gruft" not in user                                # nur das nächstgelegene
    raw = json.dumps(messages, ensure_ascii=False)
    for value in (*HOME, *WEATHER_AT):
        assert str(value)[:5] not in raw and str(value)[:5].replace(".", ",") not in raw
    dungeon = next(d for d in hero_world.world()["dungeons"] if d["key"] == "teich")
    assert f'{dungeon["x"]}' not in raw and f'{dungeon["y"]}' not in raw


def test_nearest_dungeon_skips_cleared_and_handles_missing_world(monkeypatch):
    monkeypatch.setattr(hero_world, "world", lambda: {"dungeons": [
        {"name": "Nah, aber bezwungen", "km": 1.0, "x": 0, "y": 1000, "cleared": True},
        {"name": "Offen", "type_label": "Wald", "km": 4.2, "x": -4200, "y": 10, "cleared": False,
         "discovered": False, "length_km": 3.0, "level": 20, "segments": [{"cleared": True}, {"cleared": False}]}]})
    d = briefing.nearest_dungeon()
    assert d == {"name": "Offen", "type": "Wald", "km": 4.2, "direction": "Westen", "length_km": 3.0, "level": 20,
                 "discovered": False, "sections_cleared": 1, "sections": 2}
    monkeypatch.setattr(hero_world, "world", lambda: {"available": False})
    assert briefing.nearest_dungeon() is None


def test_compass_eight_points():
    assert [briefing.compass(x, y) for x, y in ((0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1))] == \
        briefing.DIRECTIONS


# --- API ------------------------------------------------------------------------------------

def test_get_today_returns_todays_briefing_only(db, monkeypatch):
    monkeypatch.setattr(briefing, "_now", lambda: at(9, 0))
    app = FastAPI()
    app.include_router(coach_api.router)
    api = TestClient(app)
    assert api.get("/coach/briefing/today").json() == {"date": "2026-10-17", "briefing": None}
    with Session(db) as s:
        s.add(CoachReport(created_at=datetime(2026, 10, 16, 5, 0), kind="briefing", content="gestern"))
        s.add(CoachReport(created_at=datetime(2026, 10, 17, 5, 0), kind="daily", content="anderer Bericht"))
        s.add(CoachReport(created_at=datetime(2026, 10, 17, 4, 30), kind="briefing", content="**Heute:** Ruhe",
                          cost_usd=0.02, provider="anthropic", model="claude-opus-5-5"))
        s.commit()
    body = api.get("/coach/briefing/today").json()
    assert body["briefing"]["content"] == "**Heute:** Ruhe" and body["briefing"]["cost_usd"] == 0.02
