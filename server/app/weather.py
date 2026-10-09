"""Tageswetter für die Übersicht via Open-Meteo (kein API-Key). Der Ort liegt nur in server/.env;
an Open-Meteo gehen ausschließlich die (auf 2 Nachkommastellen gerundeten) Koordinaten."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
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


def places() -> list[dict]:
    if settings.weather_places:
        return settings.weather_places
    if settings.weather_lat is not None and settings.weather_lon is not None:
        return [{"place": settings.weather_place, "lat": settings.weather_lat, "lon": settings.weather_lon}]
    return []


def _fetch(lat: float, lon: float) -> dict:
    response = httpx.get(FORECAST_URL, timeout=10, params={
        "latitude": lat, "longitude": lon, "timezone": settings.timezone, "forecast_days": 7,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,is_day",
        "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code,is_day,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,sunrise,sunset,weather_code,wind_speed_10m_max",
    })
    response.raise_for_status()
    return response.json()


def today(index: int = 0, day: int = 0, now: datetime | None = None) -> dict:
    """Stündlicher Verlauf eines Tages (0 = heute … 6) + aktuelle Werte + 7-Tage-Streifen.
    `configured=False` ohne Ort."""
    known = places()
    if not known:
        return {"configured": False}
    index %= len(known)
    lat, lon = known[index]["lat"], known[index]["lon"]
    key = (lat, lon, settings.timezone)
    cached = _cache.get(key)
    if cached is None or time.monotonic() - cached[0] > CACHE_SECONDS:
        try:
            cached = (time.monotonic(), _fetch(lat, lon))
            _cache[key] = cached
        except httpx.HTTPError:
            if cached is None:  # ohne Altstand gibt es nichts anzuzeigen
                raise
    raw = cached[1]
    local_now = now or datetime.now(ZoneInfo(settings.timezone))
    hourly, daily, current = raw.get("hourly", {}), raw.get("daily", {}), raw.get("current", {})
    all_hours = [{
        "time": stamp,
        "temp": hourly["temperature_2m"][i],
        "rain_prob": hourly["precipitation_probability"][i],
        "rain_mm": hourly["precipitation"][i],
        "wind_kmh": (hourly.get("wind_speed_10m") or [None] * (i + 1))[i],
        "is_day": bool(hourly["is_day"][i]),
        **describe(hourly["weather_code"][i]),
    } for i, stamp in enumerate(hourly.get("time", []))]
    dates = daily.get("time") or [local_now.strftime("%Y-%m-%d")]
    day = max(0, min(day, len(dates) - 1))
    date = dates[day]
    hours = [h for h in all_hours if h["time"].startswith(date)]
    suns = list(zip(daily.get("sunrise") or [], daily.get("sunset") or []))
    pick = lambda name, i=day: (daily.get(name) or [None] * (i + 1))[i]  # noqa: E731
    # Kommende Tage: Empfehlung ab Mitternacht des gewählten Tages, heute ab jetzt.
    start = local_now.replace(tzinfo=None) if day == 0 else datetime.fromisoformat(date)
    return {
        "configured": True,
        "place": known[index]["place"],
        "index": index,
        "places": [item["place"] for item in known],
        "date": date,
        "now_hour": local_now.strftime("%Y-%m-%dT%H:00") if day == 0 else None,
        "current": {
            "temp": current.get("temperature_2m"), "feels_like": current.get("apparent_temperature"),
            "wind_kmh": current.get("wind_speed_10m"), "is_day": bool(current.get("is_day", 1)),
            **describe(current.get("weather_code")),
        },
        "day": {
            "temp_max": pick("temperature_2m_max"), "temp_min": pick("temperature_2m_min"),
            "rain_mm": pick("precipitation_sum"), "rain_prob_max": pick("precipitation_probability_max"),
            "wind_max_kmh": pick("wind_speed_10m_max"),
            "sunrise": pick("sunrise"), "sunset": pick("sunset"), **describe(pick("weather_code")),
        },
        "days": [{"date": d, "temp_max": pick("temperature_2m_max", i), "temp_min": pick("temperature_2m_min", i),
                  "rain_prob_max": pick("precipitation_probability_max", i), **describe(pick("weather_code", i))}
                 for i, d in enumerate(dates)],
        "hours": hours,
        "run": run_advice(all_hours, start, suns[day:]),
        "source": "Open-Meteo",
    }


# --- Laufempfehlung -------------------------------------------------------------------------
# Persönliche Schwellen (trocken, Lufttemperatur): ~15 °C ideal, ≥12 °C kurz, <12 °C langes
# Kompressions-Oberteil, <10 °C lang oben + unten, ab 30 °C Wald/Schatten + mehr Wasser.
# Nässe und Wind fühlen sich kälter an → je 2 °C Abzug für die Kleidungswahl.
# Gelaufen wird bei Tageslicht (frühestens Sonnenaufgang) ~1 Stunde, gern morgens.
IDEAL_C = 15.0
RUN_MINUTES = 60
_CLOTHING = [  # (ab gefühlt °C, Stufe, Kleidung)
    (30, "hitze", "Kurz & luftig, Kappe · schattige Waldstrecke, deutlich mehr Wasser"),
    (22, "warm", "Kurz · Wasser mitnehmen, Schatten bevorzugen"),
    (12, "kurz", "Kurze Sachen"),
    (10, "kompression-oben", "Kurze Hose + langes Kompressions-Oberteil"),
    (5, "kompression", "Lange Kompression oben & unten"),
    (0, "kalt", "Lange Kompression + winddichte Jacke, dünne Handschuhe, Stirnband"),
    (-99, "frost", "Thermo-Tights, Jacke, Handschuhe, Mütze · auf Glätte achten"),
]


def clothing(temp: float, wet: bool, wind_kmh: float | None) -> dict:
    adjust = (2 if wet else 0) + (2 if (wind_kmh or 0) >= 20 else 0)
    felt = temp - adjust
    level, text = next((lvl, txt) for limit, lvl, txt in _CLOTHING if felt >= limit)
    extras = []
    if wet:
        extras.append("wasserabweisende Schicht")
    if (wind_kmh or 0) >= 20 and level not in ("kalt", "frost"):
        extras.append("Windweste")
    return {"level": level, "text": text, "extras": extras, "felt": round(felt, 1), "adjust": adjust}


def _window(by_hour: dict[datetime, dict], start: datetime) -> dict | None:
    """Wetter eines 60-min-Laufs ab `start`, gewichtet nach Minuten je Stundenwert."""
    end = start + timedelta(minutes=RUN_MINUTES)
    parts, cursor = [], start
    while cursor < end:
        slot = cursor.replace(minute=0, second=0, microsecond=0)
        upto = min(end, slot + timedelta(hours=1))
        hour = by_hour.get(slot)
        if hour is None or hour.get("temp") is None:
            return None
        parts.append(((upto - cursor).total_seconds() / 60, hour))
        cursor = upto
    total = sum(minutes for minutes, _ in parts)
    temp = sum(minutes * h["temp"] for minutes, h in parts) / total
    rain_prob = max(h.get("rain_prob") or 0 for _, h in parts)
    rain_mm = sum(minutes / 60 * (h.get("rain_mm") or 0) for minutes, h in parts)
    wind = max(h.get("wind_kmh") or 0 for _, h in parts)
    score = abs(temp - IDEAL_C) + rain_prob / 10 + min(rain_mm, 3) * 3 + max(0.0, wind - 15) / 5
    wet = rain_prob >= 50 or rain_mm >= 0.3
    return {
        "start": start.strftime("%Y-%m-%dT%H:%M"), "end": end.strftime("%Y-%m-%dT%H:%M"),
        "temp": round(temp, 1), "rain_prob": rain_prob, "wind_kmh": round(wind), "wet": wet,
        "score": round(score, 1), "rating": "ideal" if score <= 3 else "gut" if score <= 8 else "mäßig",
        "clothing": clothing(temp, wet, wind),
    }


def _ceil5(moment: datetime) -> datetime:
    moment = moment.replace(second=0, microsecond=0)
    return moment + timedelta(minutes=-moment.minute % 5)


def run_advice(hours: list[dict], now: datetime, suns: list[tuple[str, str]]) -> dict | None:
    """Uhrzeit-Empfehlungen bei Tageslicht: Morgenlauf ab Sonnenaufgang + bestes 60-min-Fenster.
    Ist heute kein Fenster mehr übrig, gilt morgen."""
    by_hour = {datetime.fromisoformat(h["time"]): h for h in hours}
    for offset, (rise, set_) in enumerate(suns[:2]):
        sunrise, sunset = datetime.fromisoformat(rise), datetime.fromisoformat(set_)
        latest = sunset - timedelta(minutes=RUN_MINUTES)
        first = max(_ceil5(sunrise), _ceil5(now))
        starts = {first} | {sunrise.replace(minute=0) + timedelta(hours=k) for k in range(1, 24)}
        windows = [w for start in sorted(starts) if first <= start <= latest
                   for w in [_window(by_hour, start)] if w is not None]
        if not windows:
            continue
        day = "heute" if offset == 0 else "morgen"  # relativ zum angefragten Tag
        best = min(windows, key=lambda w: w["score"])
        morning = windows[0] if windows[0]["start"] == _ceil5(sunrise).strftime("%Y-%m-%dT%H:%M") else None
        notes = []
        if all(w["wet"] for w in windows):
            notes.append("Keine trockene Stunde bei Tageslicht")
        if max(w["temp"] for w in windows) >= 30:
            notes.append("Hitze: möglichst früh laufen")
        return {"day": day, "date": rise[:10], "sunrise": rise, "sunset": set_, "morning": morning,
                "best": None if morning and best["start"] == morning["start"] else best, "notes": notes}
    return None
