from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config, weather
from app.api import settings as settings_api


def test_unconfigured_location(monkeypatch):
    monkeypatch.setattr(weather.settings, "weather_places", [])
    monkeypatch.setattr(weather.settings, "weather_lat", None)
    monkeypatch.setattr(weather.settings, "weather_lon", None)
    assert weather.today() == {"configured": False}


def test_today_maps_hours_codes_and_caches(monkeypatch):
    calls = []
    raw = {
        "current": {"temperature_2m": 11.2, "apparent_temperature": 9.0, "weather_code": 3, "wind_speed_10m": 14, "is_day": 1},
        "hourly": {"time": ["2026-10-09T00:00", "2026-10-09T01:00"], "temperature_2m": [9.5, 9.1],
                   "precipitation_probability": [10, 80], "precipitation": [0, 1.2],
                   "weather_code": [0, 63], "is_day": [0, 0]},
        "daily": {"temperature_2m_max": [13.1], "temperature_2m_min": [9.1], "precipitation_sum": [1.2],
                  "precipitation_probability_max": [80], "sunrise": ["2026-10-09T07:45"],
                  "sunset": ["2026-10-09T18:52"], "weather_code": [95]},
    }
    monkeypatch.setattr(weather, "_fetch", lambda lat, lon: calls.append((lat, lon)) or raw)
    monkeypatch.setattr(weather, "_cache", {})
    monkeypatch.setattr(weather.settings, "weather_lat", 50.93)
    monkeypatch.setattr(weather.settings, "weather_lon", 6.95)
    monkeypatch.setattr(weather.settings, "weather_places", [])
    result = weather.today(now=datetime(2026, 10, 9, 15, 42))
    assert result["now_hour"] == "2026-10-09T15:00"
    assert result["hours"][1] == {"time": "2026-10-09T01:00", "temp": 9.1, "rain_prob": 80, "rain_mm": 1.2, "wind_kmh": None,
                                  "is_day": False, "code": 63, "icon": "rain", "text": "Regen"}
    assert result["run"] is None  # keine Sonnenzeiten im Testdatensatz → keine Empfehlung
    assert result["current"]["icon"] == "cloudy" and result["day"]["icon"] == "thunder"
    weather.today()
    assert calls == [(50.93, 6.95)]
    assert weather.describe(None)["text"] == "Unbekannt"


def test_places_browse_and_settings_roundtrip(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("WEATHER_PLACE=Wesel\nWEATHER_LAT=51.67\nWEATHER_LON=6.62\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env)
    monkeypatch.setattr(weather.settings, "weather_places", [])
    monkeypatch.setattr(weather.settings, "weather_place", "Wesel")
    monkeypatch.setattr(weather.settings, "weather_lat", 51.67)
    monkeypatch.setattr(weather.settings, "weather_lon", 6.62)
    lookups = []
    def geocode(name):
        lookups.append(name)
        return None if name == "Nirgendwo" else {"place": f"{name}, Ä-Land, DE", "lat": 50.0, "lon": 7.0}
    monkeypatch.setattr(weather, "geocode", geocode)
    app = FastAPI()
    app.include_router(settings_api.router)
    client = TestClient(app)
    assert client.get("/settings").json()["weather_places"] == ["Wesel"]
    saved = client.put("/settings", json={"weather_places": ["Wesel", "Köln", "  "]}).json()
    assert saved["weather_places"] == ["Wesel", "Köln, Ä-Land, DE"] and lookups == ["Köln"]
    assert client.put("/settings", json={"weather_places": ["Nirgendwo"]}).status_code == 422
    assert weather.settings.weather_places[1]["lat"] == 50.0
    # The JSON line written to .env must parse back into the same list.
    parsed = config.Settings(_env_file=str(env))
    assert parsed.weather_places == weather.settings.weather_places and parsed.weather_lat is None
    monkeypatch.setattr(weather, "_fetch", lambda lat, lon: {"hourly": {}, "daily": {}, "current": {}})
    monkeypatch.setattr(weather, "_cache", {})
    browsed = weather.today(3)
    assert browsed["index"] == 1 and browsed["place"] == "Köln, Ä-Land, DE" and len(browsed["places"]) == 2
    assert client.put("/settings", json={"weather_places": []}).json()["weather_places"] == []
    assert config.Settings(_env_file=str(env)).weather_places == []


def hours(day, temps, rain=None):
    return [{"time": f"2026-10-{day:02d}T{h:02d}:00", "temp": temp, "rain_prob": (rain or {}).get(h, 0),
             "rain_mm": 1.0 if (rain or {}).get(h, 0) >= 50 else 0.0, "wind_kmh": 5}
            for h, temp in enumerate(temps)]


SUNS = [("2026-10-09T07:47", "2026-10-09T18:53"), ("2026-10-10T07:49", "2026-10-10T18:51")]


def test_run_advice_morning_and_best_daylight_window():
    temps = [8] * 8 + [10, 11, 12, 13, 14, 15, 15, 14, 13, 12, 11, 10] + [9] * 4
    data = hours(9, temps, rain={13: 80}) + hours(10, temps)
    advice = weather.run_advice(data, datetime(2026, 10, 9, 6, 30), SUNS)
    assert advice["day"] == "heute"
    morning = advice["morning"]
    assert (morning["start"], morning["end"]) == ("2026-10-09T07:50", "2026-10-09T08:50")
    assert morning["temp"] == 9.7 and morning["clothing"]["level"] == "kompression"
    best = advice["best"]  # 13/14 Uhr wären ideal, 13 Uhr regnet → 14:00 gewinnt
    assert best["start"] == "2026-10-09T14:00" and best["rating"] == "ideal" and not best["wet"]


def test_run_advice_rolls_to_tomorrow_and_respects_sunset():
    data = hours(9, [10] * 24) + hours(10, [10] * 24)
    late = weather.run_advice(data, datetime(2026, 10, 9, 18, 0), SUNS)
    assert late["day"] == "morgen" and late["morning"]["start"] == "2026-10-10T07:50"
    assert late["best"] is None  # gleiches Wetter → Morgenlauf ist auch das beste Fenster
    afternoon = weather.run_advice(data, datetime(2026, 10, 9, 17, 41), SUNS)
    assert afternoon["day"] == "heute" and afternoon["morning"] is None
    assert afternoon["best"]["start"] == "2026-10-09T17:45"  # endet vor Sonnenuntergang 18:53
    assert weather.run_advice(data, datetime(2026, 10, 9, 18, 0), []) is None


def test_clothing_thresholds_and_adjustments():
    level = lambda t, wet=False, wind=0: weather.clothing(t, wet, wind)["level"]  # noqa: E731
    assert [level(t) for t in (31, 25, 15, 12, 11, 9, 3, -2)] == [
        "hitze", "warm", "kurz", "kurz", "kompression-oben", "kompression", "kalt", "frost"]
    assert level(13, wet=True) == "kompression-oben"  # nass fühlt sich 2 °C kälter an
    assert weather.clothing(13, True, 25) == {"level": "kompression", "text": "Lange Kompression oben & unten",
                                              "extras": ["wasserabweisende Schicht", "Windweste"], "felt": 9, "adjust": 4}
