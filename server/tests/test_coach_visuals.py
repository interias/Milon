import base64
import io
import json
from unittest.mock import patch

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from app.api.coach import ImageIn
from app.coach import visuals


def test_report_chart_is_validated_and_keeps_its_saved_values():
    with patch.object(visuals.body, "weight_trend", return_value=[
        {"date": "2026-10-02", "avg7": 72.1}, {"date": "2026-10-03", "avg7": None},
    ]):
        cards = visuals.build_visuals("chat-tools", "Wie entwickelt sich mein Gewicht?")
    stored = json.dumps(cards)
    with patch.object(visuals.body, "weight_trend", side_effect=AssertionError("Historical charts must not query live metrics")):
        restored = visuals.parse_visuals(stored)
    assert [card["id"] for card in restored] == ["weight"]
    assert restored[0]["points"] == [{"date": "2026-10-02", "value": 72.1}, {"date": "2026-10-03", "value": None}]


def test_visuals_reject_html_unknown_types_and_nonfinite_values():
    assert visuals.parse_visuals(None) == []
    assert visuals.parse_visuals('<script>alert(1)</script>') == []
    card = {"id": "weight", "kind": "html", "title": "X", "unit": "kg", "description": "",
            "captured_at": "2026-10-04T12:00:00", "points": []}
    assert visuals.parse_visuals(json.dumps([card])) == []
    card["kind"] = "line"
    card["points"] = [{"date": "2026-10-04", "value": float("nan")}]
    assert visuals.parse_visuals(json.dumps([card])) == []


def test_sleep_chart_does_not_connect_devices_or_count_naps():
    from app.metrics import sleep
    from datetime import date
    rows = [
        {"date": "2026-10-01", "main_sleep": True, "source_package": "old", "asleep_hours": 9},
        {"date": "2026-10-02", "main_sleep": True, "source_package": "new", "asleep_hours": 7},
        {"date": "2026-10-03", "main_sleep": False, "source_package": "new", "asleep_hours": 1},
        {"date": "2026-10-04", "main_sleep": True, "source_package": "new", "asleep_hours": 8},
    ]
    with patch.object(sleep, "overview", return_value={"series": rows}), \
            patch.object(visuals.settings, "steps_source_package", "old"), \
            patch.object(visuals.settings, "watch_source_switch_date", date(2026, 9, 25)), \
            patch.object(visuals.settings, "watch_source_package", "new"):
        cards = visuals.build_visuals("chat-tools", "Wie ist mein Schlaf?")
    assert len(cards) == 1 and cards[0]["id"] == "sleep"
    assert cards[0]["points"] == [{"date": "2026-10-02", "value": 7},
                                   {"date": "2026-10-03", "value": None},
                                   {"date": "2026-10-04", "value": 8}]


def _png(size=(1024, 1024)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_image_uses_existing_key_and_only_explicit_prompt(tmp_path):
    request_data = {}

    def answer(request):
        request_data.update(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-key"
        assert str(request.url) == "https://openrouter.ai/api/v1/images"
        return httpx.Response(200, json={"data": [{"b64_json": _png(), "media_type": "image/png"}],
                                         "usage": {"cost": 0.02}})

    provider = httpx.Client(transport=httpx.MockTransport(answer))
    with patch.object(visuals.httpx, "Client", return_value=provider), \
            patch.object(visuals.settings, "openrouter_api_key", "test-key"), \
            patch.object(visuals, "IMAGE_DIR", tmp_path):
        generated = visuals.generate_image("Runner silhouette")
    assert request_data["model"] == "openai/gpt-image-2.5-flare"
    assert request_data["size"] == "1024x1024" and request_data["quality"] == "low"
    assert "Runner silhouette" in request_data["prompt"]
    assert "input_references" not in request_data and "messages" not in request_data
    assert generated["cost_usd"] == 0.02
    assert generated["url"].startswith("/media/coach-images/")
    paths = list(tmp_path.iterdir())
    assert len(paths) == 1
    assert paths[0].name in generated["url"]
    with Image.open(paths[0]) as image:
        assert image.size == (1024, 1024) and image.format == "PNG"


@pytest.mark.parametrize("payload", [None, [], {"data": []}, {"data": [{"b64_json": 42}]},
                                     {"data": [{"b64_json": "oops"}]},
                                     {"data": [{"b64_json": _png((16, 16))}]}])
def test_invalid_image_provider_response_does_not_write_files(tmp_path, payload):
    if not isinstance(payload, dict):
        payload = {"data": payload}
    with pytest.raises(ValueError):
        visuals._store_image(payload, tmp_path)
    assert not list(tmp_path.iterdir())


def test_missing_key_and_blank_subject_are_clear_errors():
    with patch.object(visuals.settings, "openrouter_api_key", ""):
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            visuals.generate_image("Runner")
    with pytest.raises(ValidationError):
        ImageIn(prompt="   ")
