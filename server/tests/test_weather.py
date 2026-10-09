from datetime import datetime

from app import weather


def test_unconfigured_location(monkeypatch):
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
    result = weather.today(datetime(2026, 10, 9, 15, 42))
    assert result["now_hour"] == "2026-10-09T15:00"
    assert result["hours"][1] == {"time": "2026-10-09T01:00", "temp": 9.1, "rain_prob": 80, "rain_mm": 1.2,
                                  "is_day": False, "code": 63, "icon": "rain", "text": "Regen"}
    assert result["current"]["icon"] == "cloudy" and result["day"]["icon"] == "thunder"
    weather.today()
    assert calls == [(50.93, 6.95)]
    assert weather.describe(None)["text"] == "Unbekannt"
