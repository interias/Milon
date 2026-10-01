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
    monkeypatch.setattr(snapshot, "build_snapshot", lambda: data)
    text = snapshot.snapshot_text()
    assert "2026-09-10" in text
    assert "2026-09-11" in text
    assert "Schritte heute" not in text
    assert "3/7" in text
    assert "2/7" in text
    assert "120" in text
