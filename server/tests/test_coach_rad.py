"""Coach und Rad (#74): Tool/MCP get_cycling_power, Snapshot-Zeilen, Zwift-Vorschlag im Morgenbriefing, Wochenzeilen.

Gemocktes LLM, synthetische Fahrten in tmp-SQLite, nie die echte API, nie Garmin."""
import json
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import weather
from app.coach import briefing, prompts, rad, tools, weekly_auto
from app.garmin_indoor import GarminIndoorRide
from app.mcp import server as mcp_server
from app.metrics import body, cycling, endurance, health, running

from test_coach_briefing import HOME, WEATHER_AT, at, db, forecast_raw, llm, world  # noqa: F401  (fixtures)

TODAY = datetime.now(ZoneInfo(endurance.settings.timezone)).date()


def fill(engine, fitter: bool, seed: int, n: int = 20):
    """n Fahrten im 2-Tage-Abstand bis gestern; Puls hängt von der Leistung ab (und fällt mit der Zeit, wenn fitter)."""
    rng = np.random.default_rng(seed)
    with Session(engine) as s:
        for i in range(n):
            day = TODAY - timedelta(days=1 + (n - 1 - i) * 2)
            power = float(180 + (i * 37) % 20)
            hr = round(60 + 0.45 * power - (0.08 * i * 6 if fitter else 0.0) + float(rng.normal(0, 2.0)), 1)
            started = datetime.combine(day, time(8))
            s.add(GarminIndoorRide(activity_id=f"r{i}", activity_type="virtual_ride", title="Zwift - Tempus Fugit in Watopia",
                                   world="Watopia", route="Tempus Fugit", started_at=started, duration_seconds=1800,
                                   elapsed_duration_seconds=1800, distance_km=15.0, avg_power_w=power, norm_power_w=power,
                                   avg_hr=hr, hr_valid=True, power_curve_json=json.dumps({"1200": power}), synced_at=started))
        s.commit()


@pytest.fixture
def rides_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'rad.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for module in (running, cycling, health, body):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(running.settings, "run_hr_max", 180.0)
    yield engine
    engine.dispose()


# --- Tool + MCP ----------------------------------------------------------------------------

def test_tool_returns_power_verdicts_curve_form_and_recent_rides(rides_db):
    fill(rides_db, fitter=True, seed=7)
    assert "get_cycling_power" in [t["function"]["name"] for t in tools.TOOLS]
    description = next(t["function"]["description"] for t in tools.TOOLS if t["function"]["name"] == "get_cycling_power")
    assert "significant=true" in description
    result = tools.dispatch("get_cycling_power", {})
    assert "significant=true" in result["hinweis"] and "Sehnen" in result["hinweis"]
    assert result["summary"]["rides"] == 20 and result["eftp"]["value"] and result["eftp"]["source"]
    assert result["power_curve"] and result["power_curve"][0]["seconds"] == 1200
    assert result["hr_at_power"]["trend"]["verdict"] == "besser" and result["hr_at_power"]["trend"]["significant"]
    assert result["efficiency"]["trend"]["significant"] and result["efficiency"]["rides"] == 20
    assert result["form"]["form"] in ("ausgeruht", "belastet", "ausgeglichen")
    assert len(result["recent_rides"]) == 5 and result["recent_rides"][0]["world"] == "Watopia"
    raw = json.dumps(result, ensure_ascii=False, allow_nan=False).lower()
    assert "latitude" not in raw and "longitude" not in raw


def test_tool_is_neutral_on_noise(rides_db):
    fill(rides_db, fitter=False, seed=11)
    trend = tools.dispatch("get_cycling_power", {})["hr_at_power"]["trend"]
    assert trend["verdict"] == "unklar" and trend["significant"] is False


def test_tool_on_empty_database_does_not_crash(rides_db):
    result = tools.dispatch("get_cycling_power", {})
    assert result["summary"]["rides"] == 0 and result["recent_rides"] == [] and result["form"] is None
    json.dumps(result, allow_nan=False)


def test_mcp_tool_returns_the_same_overview(rides_db):
    fill(rides_db, fitter=True, seed=7)
    assert mcp_server.get_cycling_power().keys() == tools.dispatch("get_cycling_power", {}).keys()


# --- Snapshot ------------------------------------------------------------------------------

def test_snapshot_lines_have_form_in_endurance_line_and_rad_line(rides_db):
    fill(rides_db, fitter=True, seed=7)
    lines = rad.snapshot_lines()
    endurance_line = next(line for line in lines if line.startswith("AUSDAUER:"))
    assert "Form (TSB)" in endurance_line and "CTL" in endurance_line
    rad_line = next(line for line in lines if line.startswith("RAD (Zwift/Rolle):"))
    assert "20 Fahrten" in rad_line and "eFTP" in rad_line and "W/kg" in rad_line
    assert "besser (signifikant" in rad_line and "Watt-TSS nicht mit Lauflast" in rad_line


def test_snapshot_rad_line_names_noise_as_no_trend_and_is_empty_without_data(rides_db):
    assert rad.snapshot_lines() == []
    fill(rides_db, fitter=False, seed=11)
    assert "kein belastbarer Trend" in next(line for line in rad.snapshot_lines() if line.startswith("RAD"))


def test_snapshot_text_carries_the_rad_lines(monkeypatch):
    from app.coach import snapshot
    data = {key: {} for key in ["koerper", "tdee", "laufen", "kraft", "schritte", "radfahren", "gewicht_prognose",
                               "kraft_index", "schlaf", "ernaehrung"]}
    data.update(stand="2026-09-20", lauf_volumen_4w=[], kraft_tonnage_6w=[])
    data["checkins"] = {"count": 0, "days": 30, "energy_avg": None, "energy_days": 0,
                        "training_effort_avg": None, "training_effort_days": 0}
    monkeypatch.setattr(snapshot, "build_snapshot", lambda: data)
    monkeypatch.setattr(snapshot.rad_context, "snapshot_lines", lambda: ["AUSDAUER: Form x", "RAD (Zwift/Rolle): y"])
    text = snapshot.snapshot_text()
    assert "AUSDAUER: Form x\nRAD (Zwift/Rolle): y" in text


def test_verdict_text_names_a_direction_only_when_significant():
    assert rad._verdict({"verdict": "besser", "significant": True, "n": 12}) == "besser (signifikant, n=12)"
    assert rad._verdict({"verdict": "besser", "significant": False, "n": 12}) == "kein belastbarer Trend"
    assert rad._verdict({"verdict": "wenig_daten"}) == "zu wenig Daten" and rad._verdict(None) == "kein belastbarer Trend"


def test_system_prompt_carries_the_honest_bike_note():
    flat = " ".join(prompts.SYSTEM.split())
    assert "ersetzt aber nicht Laufökonomie" in flat and "Sehnen und Knochen" in flat


# --- Zwift-Regel ---------------------------------------------------------------------------

@pytest.mark.parametrize("window,expected", [
    ({"temp": -0.5, "wet": False, "wind_kmh": 5}, True),                # Frost
    ({"temp": 0.0, "wet": False, "wind_kmh": 5}, False),                # genau 0 °C ist kein Frost
    ({"temp": 3.0, "wet": False, "icy": True, "wind_kmh": 5}, True),    # Glätte
    ({"temp": 4.0, "wet": True, "wind_kmh": 5}, True),                  # Regen + < 5 °C
    ({"temp": 5.0, "wet": True, "wind_kmh": 5}, False),
    ({"temp": 3.0, "wet": False, "wind_kmh": 5}, False),                # kalt, aber trocken
    ({"temp": 12.0, "wet": False, "wind_kmh": 30}, True),               # Wind >= 30
    ({"temp": 12.0, "wet": False, "wind_kmh": 29}, False),
])
def test_zwift_reasons_follow_the_thresholds(window, expected):
    assert bool(rad.zwift_reasons(window)) is expected


def test_intensity_follows_form():
    assert rad.intensity_for_form(-30) == "Z1 oder Ruhetag"
    assert rad.intensity_for_form(-18) == "Z2"
    assert rad.intensity_for_form(0).startswith("Z2 mit")
    assert rad.intensity_for_form(12).startswith("Z2 bis Z4")


def test_zwift_line_names_form_number_and_zone_with_watts(monkeypatch):
    monkeypatch.setattr(rad, "form", lambda today=None: {"tsb": -18.2, "form": "belastet", "ctl": 40, "atl": 58})
    monkeypatch.setattr(rad.cycling, "eftp", lambda today=None: {"value": 200.0})
    run = {"morning": {"start": "2026-10-17T08:00", "end": "2026-10-17T09:00", "temp": -2.0, "wet": False, "wind_kmh": 5}}
    line = rad.zwift_line(run)
    assert "Form -18 (belastet) → Z2 (110–150 W bei eFTP 200 W)" in line and "Frost" in line
    assert "ersetzt Laufökonomie" in line
    assert rad.zwift_line({"morning": {**run["morning"], "temp": 9.0}}) is None
    assert rad.zwift_line(None) is None


def test_zwift_line_falls_back_to_best_window_without_morning_window(monkeypatch):
    monkeypatch.setattr(rad, "form", lambda today=None: None)
    monkeypatch.setattr(rad.cycling, "eftp", lambda today=None: {"value": None})
    best = {"start": "2026-10-17T10:00", "end": "2026-10-17T11:00", "temp": 3.0, "wet": False, "wind_kmh": 40}
    line = rad.zwift_line({"morning": None, "best": best})
    assert "10:00–11:00" in line and "Wind 40" in line and "Form unbekannt" in line
    assert rad.zwift_line({"morning": {**best, "wind_kmh": 5}, "best": best}) is None   # Morgenfenster hat Vorrang


# --- Morgenbriefing ------------------------------------------------------------------------

def set_weather(monkeypatch, temp=-2.0, rain=5, wind=8.0, code=2):
    raw = forecast_raw()
    size = len(raw["hourly"]["time"])
    raw["hourly"]["temperature_2m"] = [temp] * size
    raw["hourly"]["precipitation_probability"] = [rain] * size
    raw["hourly"]["wind_speed_10m"] = [wind] * size
    raw["hourly"]["weather_code"] = [code] * size
    monkeypatch.setattr(weather, "_fetch", lambda lat, lon: raw)


def briefing_messages(llm, monkeypatch):
    monkeypatch.setattr(briefing, "main_night", lambda day: None)
    monkeypatch.setattr(rad.cycling, "eftp", lambda today=None: {"value": None})
    monkeypatch.setattr(rad, "form", lambda today=None: {"tsb": -18.0, "form": "belastet", "ctl": 40.0, "atl": 58.0})
    briefing.maybe_run(at(7, 0))
    return llm[0]


@pytest.mark.parametrize("kwargs,reason", [({"temp": -2.0}, "Frost"), ({"temp": 3.0, "rain": 80}, "Regen bei"),
                                           ({"temp": 3.0, "code": 73}, "Glätte"), ({"temp": 12.0, "wind": 35.0}, "Wind 35")])
def test_briefing_suggests_zwift_in_bad_weather_with_form(db, llm, world, monkeypatch, kwargs, reason):
    set_weather(monkeypatch, **kwargs)
    messages = briefing_messages(llm, monkeypatch)
    user = messages[-1]["content"]
    line = next(line for line in user.splitlines() if line.startswith("ZWIFT-VORSCHLAG"))
    assert reason in line and "Form -18 (belastet) → Z2" in line
    assert "FORM: Form (TSB) -18" in user and "**Zwift:**" in user          # Anweisung + Form-Zeile
    raw = json.dumps(messages, ensure_ascii=False)                          # keine Koordinaten, auch gerundet/mit Komma
    for value in (*HOME, *WEATHER_AT):
        whole, decimals = str(value).split(".")
        assert not re.search(rf"(?<![\d.,]){whole}[.,]{decimals[0]}", raw)


def test_briefing_has_no_zwift_line_in_good_weather_but_keeps_form(db, llm, world, monkeypatch):
    user = briefing_messages(llm, monkeypatch)[-1]["content"]             # 14 °C, trocken, 8 km/h
    assert not any(line.startswith("ZWIFT-VORSCHLAG") for line in user.splitlines())
    assert "FORM: Form (TSB) -18" in user


def test_cold_but_dry_and_calm_morning_is_no_zwift_day(world, monkeypatch):
    set_weather(monkeypatch, temp=3.0)
    assert rad.zwift_line(weather.today(0, now=at(7, 0))["run"]) is None


# --- Wochenbericht -------------------------------------------------------------------------

def test_week_lines_have_share_form_course_and_verdicts(rides_db):
    fill(rides_db, fitter=True, seed=7)
    monday = TODAY - timedelta(days=TODAY.weekday() + 7)     # abgeschlossene Vorwoche, Fahrten alle 2 Tage
    text = "\n".join(rad.week_lines(monday, monday + timedelta(days=6)))
    assert "AUSDAUER DER WOCHE: Last Lauf 0 / Rad" in text and "Lauf-Anteil 0 %" in text
    assert "FORM-VERLAUF DER WOCHE: TSB" in text and "(Mo) →" in text and "(So)" in text
    assert "RAD DER WOCHE:" in text and "RAD-URTEILE" in text and "besser (signifikant" in text


def test_week_lines_are_empty_without_data(rides_db):
    assert rad.week_lines(date(2026, 10, 12), date(2026, 10, 18)) == []


def test_weekly_report_prompt_asks_for_rad_and_includes_lines(monkeypatch):
    monkeypatch.setattr(rad, "week_lines", lambda first, last: ["RAD DER WOCHE: x"])
    monkeypatch.setattr(weekly_auto.settings, "timezone", "Europe/Berlin")
    lines = weekly_auto._week_lines(date(2026, 10, 12), date(2026, 10, 18))
    assert "RAD DER WOCHE: x" in lines
    assert "**Rad & Form:**" in weekly_auto.INSTRUCTIONS and "Sehnenbelastbarkeit" in weekly_auto.INSTRUCTIONS
