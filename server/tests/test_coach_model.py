from types import SimpleNamespace
from unittest.mock import patch

from app.coach import client


class FakeProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.responses)


def response(content="Kurz und belegt.", tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
                           model_dump=lambda: {"usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.001}})


def assert_luna_options(provider):
    for call in provider.calls:
        assert call["reasoning_effort"] == "none"
        assert "temperature" not in call
        assert call["extra_body"]["verbosity"] == "low"
        assert call["extra_body"]["usage"] == {"include": True}


def test_luna_plain_and_tool_requests_use_compatible_parameters():
    tool_call = SimpleNamespace(id="call-1", function=SimpleNamespace(name="get_weight_trend", arguments='{"days": 7}'))
    provider = FakeProvider([response(), response(tool_calls=[tool_call]), response()])
    with patch.object(client.settings, "openrouter_model", "openai/gpt-6-luna"), \
            patch.object(client, "_client", return_value=provider):
        content, usage = client.complete([{"role": "user", "content": "Mein Trend?"}])
        answer, used, trace, tool_usage = client.complete_with_tools(
            [{"role": "user", "content": "Mein Gewicht?"}], [], lambda name, args: {"weight": 72},
        )
    assert content == answer == "Kurz und belegt."
    assert used == [{"name": "get_weight_trend", "args": {"days": 7}}]
    assert trace[-1]["role"] == "tool" and '"weight": 72' in trace[-1]["content"]
    assert usage["cost"] == 0.001 and tool_usage["cost"] == 0.002
    assert_luna_options(provider)


def test_luna_final_request_after_tool_limit_is_also_compatible():
    provider = FakeProvider([response()])
    with patch.object(client.settings, "openrouter_model", "openai/gpt-6-luna"), \
            patch.object(client, "_client", return_value=provider):
        client.complete_with_tools([{"role": "user", "content": "Hallo"}], [], lambda *_: {}, max_rounds=0)
    assert_luna_options(provider)


def test_other_configured_models_keep_their_existing_parameters():
    provider = FakeProvider([response()])
    with patch.object(client.settings, "openrouter_model", "deepseek/deepseek-v4-flash-0731"), \
            patch.object(client, "_client", return_value=provider):
        client.complete([{"role": "user", "content": "Hallo"}], temperature=0.3)
    assert provider.calls[0]["temperature"] == 0.3
    assert "reasoning_effort" not in provider.calls[0]
