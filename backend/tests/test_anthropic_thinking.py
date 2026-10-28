"""core-012: Haiku 5.5 kısa max_tokens'ı düşünmeye harcayıp boş metin döndürüyordu (canlı ölçümde ~%12 boş çıktı)."""
import json
from types import SimpleNamespace

import pytest

from backend.app.providers import remote
from backend.app.providers.base import ProviderError


def make(monkeypatch, handler):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    calls = []

    def fake_post(url, json=None, headers=None):
        calls.append(dict(json))
        return handler(len(calls), json)
    monkeypatch.setattr(remote, "_post", fake_post)
    llm = remote.AnthropicLLM.__new__(remote.AnthropicLLM)
    llm.model = "claude-haiku-5-5"
    return llm, calls


def body(text="", stop="end_turn", blocks=("text",)):
    content = [{"type": b, **({"text": text} if b == "text" else {"thinking": "..."})} for b in blocks]
    return SimpleNamespace(json=lambda: {"content": content, "stop_reason": stop, "usage": {"output_tokens": 5}})


MSG = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


def test_thinking_is_disabled_by_default(monkeypatch):
    llm, calls = make(monkeypatch, lambda n, p: body('{"intent":"answer","value":true}'))
    res = llm.complete(MSG, 120, 0.0)
    assert calls[0]["thinking"] == {"type": "disabled"} and res.text.startswith("{")
    assert res.extra["stop_reason"] == "end_turn"


def test_model_rejecting_the_thinking_param_is_retried_without_it_and_remembered(monkeypatch):
    def handler(n, p):
        if "thinking" in p:
            raise ProviderError("thinking: disabled not supported")
        return body("{}")
    llm, calls = make(monkeypatch, handler)
    llm.complete(MSG, 120, 0.0)
    assert "thinking" not in calls[-1]
    llm.complete(MSG, 120, 0.0)
    assert "thinking" not in calls[-1] and len(calls) == 3        # ikinci çağrıda parametre hiç gönderilmedi


def test_empty_thinking_only_answer_is_retried_with_bigger_budget(monkeypatch):
    def handler(n, p):
        return body("", "max_tokens", ("thinking",)) if n == 1 else body('{"intent":"unclear","value":null}')
    llm, calls = make(monkeypatch, handler)
    res = llm.complete(MSG, 120, 0.0)
    assert len(calls) == 2 and calls[1]["max_tokens"] >= 960 and "unclear" in res.text
