"""Tageswetter für die Übersicht via Open-Meteo (kein API-Key). Der Ort liegt nur in server/.env;
an Open-Meteo gehen ausschließlich die (auf 2 Nachkommastellen gerundeten) Koordinaten."""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from .config import settings

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
CACHE_SECONDS = 20 * 60
_cache: dict[tuple, tuple[float, dict]] = {}

# WMO-Wettercodes → (Symbol, deutscher Text). Symbole rendert das Frontend als Inline-SVG.
_CODES = {
    0: ("clear", "Klar"), 1: ("mostly-clear", "Überwiegend klar"), 2: ("partly-cloudy", "Teils bewölkt"),
    3: ("cloudy", "Bedeckt"), 45: ("fog", "Nebel"), 48: ("fog", "Reifnebel"),
    51: ("drizzle", "Leichter Niesel"), 53: ("drizzle", "Niesel"), 55: ("drizzle", "Starker Niesel"),
    56: ("sleet", "Gefrierender Niesel"), 57: ("sleet", "Gefrierender Niesel"),
    61: ("rain", "Leichter Regen"), 63: ("rain", "Regen"), 65: ("heavy-rain", "Starker Regen"),
    66: ("sleet", "Gefrierender Regen"), 67: ("sleet", "Gefrierender Regen"),
    71: ("snow", "Leichter Schnee"), 73: ("snow", "Schnee"), 75: ("snow", "Starker Schnee"), 77: ("snow", "Schneegriesel"),
    80: ("rain", "Regenschauer"), 81: ("rain", "Regenschauer"), 82: ("heavy-rain", "Heftige Schauer"),
    85: ("snow", "Schneeschauer"), 86: ("snow", "Schneeschauer"),
    95: ("thunder", "Gewitter"), 96: ("thunder", "Gewitter mit Hagel"), 99: ("thunder", "Gewitter mit Hagel"),
}


def describe(code: int | None) -> dict:
    icon, text = _CODES.get(int(code) if code is not None else -1, ("cloudy", "Unbekannt"))
    return {"code": code, "icon": icon, "text": text}


def geocode(place: str) -> dict | None:
    response = httpx.get(GEOCODE_URL, params={"name": place, "count": 1, "language": "de", "format": "json"}, timeout=10)
    response.raise_for_status()
    hits = response.json().get("results") or []
    if not hits:
        return None
    hit = hits[0]
    label = ", ".join(part for part in (hit.get("name"), hit.get("admin1"), hit.get("country_code")) if part)
    return {"place": label, "lat": round(float(hit["latitude"]), 2), "lon": round(float(hit["longitude"]), 2)}


def _fetch(lat: float, lon: float) -> dict:
    response = httpx.get(FORECAST_URL, timeout=10, params={
        "latitude": lat, "longitude": lon, "timezone": settings.timezone, "forecast_days": 1,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,is_day",
        "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code,is_day",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,sunrise,sunset,weather_code",
    })
    response.raise_for_status()
    return response.json()


def today(now: datetime | None = None) -> dict:
    """Stündlicher Verlauf des heutigen Tages + aktuelle Werte. `configured=False` ohne Ort."""
    lat, lon = settings.weather_lat, settings.weather_lon
    if lat is None or lon is None:
        return {"configured": False}
    key = (lat, lon, settings.timezone)
    cached = _cache.get(key)
    if cached is None or time.monotonic() - cached[0] > CACHE_SECONDS:
        cached = (time.monotonic(), _fetch(lat, lon))
        _cache[key] = cached
    raw = cached[1]
    local_now = now or datetime.now(ZoneInfo(settings.timezone))
    hourly, daily, current = raw.get("hourly", {}), raw.get("daily", {}), raw.get("current", {})
    hours = [{
        "time": stamp,
        "temp": hourly["temperature_2m"][i],
        "rain_prob": hourly["precipitation_probability"][i],
        "rain_mm": hourly["precipitation"][i],
        "is_day": bool(hourly["is_day"][i]),
        **describe(hourly["weather_code"][i]),
    } for i, stamp in enumerate(hourly.get("time", []))]
    first = lambda name: (daily.get(name) or [None])[0]  # noqa: E731
    return {
        "configured": True,
        "place": settings.weather_place,
        "now_hour": local_now.strftime("%Y-%m-%dT%H:00"),
        "current": {
            "temp": current.get("temperature_2m"), "feels_like": current.get("apparent_temperature"),
            "wind_kmh": current.get("wind_speed_10m"), "is_day": bool(current.get("is_day", 1)),
            **describe(current.get("weather_code")),
        },
        "day": {
            "temp_max": first("temperature_2m_max"), "temp_min": first("temperature_2m_min"),
            "rain_mm": first("precipitation_sum"), "rain_prob_max": first("precipitation_probability_max"),
            "sunrise": first("sunrise"), "sunset": first("sunset"), **describe(first("weather_code")),
        },
        "hours": hours,
        "source": "Open-Meteo",
    }
