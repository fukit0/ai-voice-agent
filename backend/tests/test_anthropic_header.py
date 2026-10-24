"""Anthropic anahtarı çalışma alanına bağlı değilse `anthropic-workspace-id` başlığı gerekir (ANTHROPIC_WORKSPACE_ID)."""
import pytest

from backend.app.providers import remote
from backend.app.providers.base import ProviderError


class Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"content": [{"type": "text", "text": "tamam"}], "usage": {"output_tokens": 1}}


def call(monkeypatch, workspace):
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(kwargs)
        return Resp()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    if workspace:
        monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", workspace)
    else:
        monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    monkeypatch.setattr(remote, "_post", fake_post)
    remote.AnthropicLLM("claude-haiku-5-5").complete([{"role": "user", "content": "selam"}])
    return seen["headers"]


def test_workspace_header_sent_when_configured(monkeypatch):
    assert call(monkeypatch, "wrkspc_123")["anthropic-workspace-id"] == "wrkspc_123"


def test_no_workspace_header_by_default(monkeypatch):
    assert "anthropic-workspace-id" not in call(monkeypatch, None)


def test_workspace_error_explains_the_fix(monkeypatch):
    def failing(url, **kwargs):
        raise ProviderError("HTTP 400: This API key is not scoped to a workspace, so this request must include ...")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    monkeypatch.setattr(remote, "_post", failing)
    with pytest.raises(ProviderError, match="ANTHROPIC_WORKSPACE_ID"):
        remote.AnthropicLLM("m").complete([{"role": "user", "content": "x"}])


def test_temperature_rejected_by_model_is_retried_without_it_and_remembered(monkeypatch):
    sent = []

    def fake_post(url, **kwargs):
        sent.append("temperature" in kwargs["json"])
        if "temperature" in kwargs["json"]:
            raise ProviderError('HTTP 400: {"message":"`temperature` is deprecated for this model."}')
        return Resp()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(remote, "_post", fake_post)
    llm = remote.AnthropicLLM("claude-haiku-5-5")
    assert llm.complete([{"role": "user", "content": "selam"}], temperature=0).text == "tamam"
    llm.complete([{"role": "user", "content": "tekrar"}], temperature=0)
    assert sent == [True, False, False]  # ilk çağrıda denendi, sonrakilerde hiç gönderilmedi


def test_other_errors_are_not_swallowed_by_the_temperature_retry(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(remote, "_post", lambda url, **kw: (_ for _ in ()).throw(ProviderError("HTTP 401: invalid key")))
    with pytest.raises(ProviderError, match="401"):
        remote.AnthropicLLM("m").complete([{"role": "user", "content": "x"}])
