from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.coach import profile, prompts, snapshot, tools
from app.config import settings


@pytest.mark.parametrize("size", [17, 30, 90])
def test_thinning_keeps_first_and_latest_observation(size):
    values = list(range(size))
    result = tools._thin(values)
    assert len(result) == 16
    assert result[0] == 0
    assert result[-1] == size - 1
    assert result == sorted(set(result))


def test_nutrition_tool_preserves_coverage(monkeypatch):
    summary = {"last_day": "2026-09-10", "protein_days_7": 3, "protein_avg7": 120}
    monkeypatch.setattr(tools.nutrition, "summary", lambda: summary)
    assert "get_nutrition_summary" in [tool["function"]["name"] for tool in tools.TOOLS]
    assert tools.dispatch("get_nutrition_summary", {}) == summary


def test_reports_use_configured_goals_and_current_date(monkeypatch):
    monkeypatch.setattr(profile, "load", lambda: profile.Profile(context="Next race: 2027-04-18."))
    system = prompts.build_messages("weekly", "fixture snapshot")[0]["content"]
    assert "2027-04-18" in system
    assert datetime.now(ZoneInfo(settings.timezone)).date().isoformat() in system
    assert "70 kg" not in system
    assert "12.09." not in system


def test_snapshot_labels_old_observations_and_nutrition_coverage(monkeypatch):
    data = {key: {} for key in ["koerper", "tdee", "laufen", "kraft", "schritte",
                               "radfahren", "gewicht_prognose", "kfa_prognose", "kraft_index"]}
    data.update(stand="2026-09-20", lauf_volumen_4w=[], kraft_tonnage_6w=[])
    data["koerper"] = {"weight_date": "2026-09-10", "weight_days7": 3}
    data["schritte"] = {"last_day": "2026-09-11", "last": 4321, "days7": 2}
    data["ernaehrung"] = {"window_start": "2026-09-04", "last_day": "2026-09-10",
                           "protein_days_7": 3, "kcal_days_7": 2, "protein_avg7": 120}
    data["schlaf"] = {}
    data["checkins"] = {"count": 0, "days": 30, "energy_avg": None, "energy_days": 0,
                        "training_effort_avg": None, "training_effort_days": 0}
    monkeypatch.setattr(snapshot, "build_snapshot", lambda: data)
    text = snapshot.snapshot_text()
    assert "2026-09-10" in text
    assert "2026-09-11" in text
    assert "Schritte heute" not in text
    assert "3/7" in text
    assert "2/7" in text
    assert "120" in text


def test_sleep_tool_keeps_device_statistics_and_thins_only_plot_points(monkeypatch):
    from app.metrics import sleep
    group = {"label": "Garmin", "n": 30, "correlation": 0.2, "ci95": [-0.2, 0.6],
             "points": [{"date": str(n), "value": n} for n in range(30)]}
    called = []

    def performance(*args):
        called.append(args)
        return {"groups": [group], "caveat": "No causality"}

    monkeypatch.setattr(sleep, "performance", performance)
    result = tools.dispatch("get_sleep_performance", {"kind": "strength", "source": "current"})
    assert called == [("strength", "current", 180)]
    assert result["caveat"] == "No causality"
    assert result["groups"][0]["n"] == 30 and result["groups"][0]["ci95"] == [-0.2, 0.6]
    assert len(result["groups"][0]["points"]) == 12
    assert result["groups"][0]["points"][-1]["value"] == 29
    with pytest.raises(ValueError):
        tools.dispatch("get_sleep_performance", {"source": "pooled"})
    with pytest.raises(ValueError):
        tools.dispatch("get_sleep_performance", {"kind": "gym"})


def test_run_zones_tool_preserves_reference_coverage_and_unsupported_pace(monkeypatch):
    from app.metrics import run_zones
    result = {"hr_max": 190, "hr_max_source": "configured_reference",
              "schema_source": "official reference", "sensor": {"label": "Garmin"},
              "runs": 3, "pace_status": "insufficient", "caveat": "Orientation only",
              "zones": [{"zone": 2, "hr_low": 114, "hr_high": 132,
                         "pace_fast_seconds": None, "pace_slow_seconds": None,
                         "reason": "Not enough supported runs"}]}
    monkeypatch.setattr(run_zones, "zones", lambda: result)
    assert tools.dispatch("get_run_zones", {}) == result
    tool = next(item["function"] for item in tools.TOOLS if item["function"]["name"] == "get_run_zones")
    assert tool["parameters"]["properties"] == {}


def test_optional_checkin_tool_preserves_missing_values(monkeypatch):
    from app import checkins
    monkeypatch.setattr(checkins, "summary", lambda days: {"count": 0, "energy_avg": None, "caveat": "Voluntary"})
    result = tools.dispatch("get_checkin_summary", {"days": 30})
    assert result == {"count": 0, "energy_avg": None, "caveat": "Voluntary"}
    names = {item["function"]["name"] for item in tools.TOOLS}
    assert {"get_sleep_overview", "get_sleep_performance", "get_checkin_summary"} <= names
