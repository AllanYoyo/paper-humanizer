"""LLM provider abstraction, prompt loading, JSON extraction."""
import io
import json
import urllib.error

import pytest

from paper_humanizer.errors import ProviderError, ProviderNotConfigured, PromptError
from paper_humanizer.prompts_loader import ask_json, extract_json, load_prompt, render
from paper_humanizer.provider import OpenAICompatibleProvider, provider_from_env


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._payload


def test_provider_from_env_defaults_to_null():
    provider = provider_from_env(env={})
    assert provider.available is False


def test_provider_requires_model_when_key_set():
    with pytest.raises(ProviderNotConfigured):
        provider_from_env(env={"PAPER_HUMANIZER_API_KEY": "sk-test"})


def test_provider_builds_openai_compatible_request():
    captured = {}

    def fake_opener(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["auth"] = request.headers.get("Authorization")
        return _FakeResponse(json.dumps(
            {"choices": [{"message": {"content": "hello"}}]}).encode("utf-8"))

    provider = OpenAICompatibleProvider(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/", "sk-test", "qwen-plus",
        opener=fake_opener)
    out = provider.complete("prompt text", system="sys")
    assert out == "hello"
    assert captured["url"].endswith("/chat/completions")
    assert captured["body"]["model"] == "qwen-plus"
    assert captured["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert captured["auth"] == "Bearer sk-test"


def test_provider_http_error_wrapped():
    def failing_opener(request, timeout=None):
        raise urllib.error.HTTPError("http://x", 401, "unauthorized", {}, io.BytesIO(b"denied"))

    provider = OpenAICompatibleProvider("https://x/v1", "k", "m", opener=failing_opener)
    with pytest.raises(ProviderError):
        provider.complete("p")


def test_prompt_load_and_render():
    template = load_prompt("rewrite")
    assert template.name == "rewrite"
    rendered = render(template, language="zh", section_type="results",
                      section_text="文本", lock_atoms="[]", claims="[]",
                      issues="{}", repair_instructions="(none)")
    assert "文本" in rendered
    with pytest.raises(PromptError):
        render(template, language="zh")  # missing placeholders


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here you go:\n{"a": {"b": 2}}\nDone.') == {"a": {"b": 2}}
    with pytest.raises(PromptError):
        extract_json("no json here")


def test_ask_json_retries_then_raises():
    provider = _BadJsonProvider()
    template = load_prompt("diagnosis")
    with pytest.raises(ProviderError):
        ask_json(provider, "diagnosis",
                 {"language": "zh", "text": "t", "stats_summary": "{}"}, attempts=2)
    assert provider.calls == 2


class _BadJsonProvider:
    available = True

    def __init__(self):
        self.calls = 0

    def complete(self, prompt, *, system=None, temperature=0.2, max_tokens=4096):
        self.calls += 1
        return "not json at all"
