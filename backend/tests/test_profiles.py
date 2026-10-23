"""core-003: profil yapılandırması, sağlayıcı yönlendirmesi, loglama ve eksik anahtar hataları.

Gerçek modeller yerine sahte sağlayıcılar kullanılır; gerçek modellerle doğrulama Mac'te yapılır
(evidence/core-003-*.json).
"""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.profiles import load_profiles
from backend.app.providers import registry
from backend.app.providers.audio import encode_wav
from backend.app.providers.base import (LLMProvider, LLMResult, ProviderError, STTProvider, STTResult,
                                        TTSProvider, TTSResult)

client = TestClient(app)


class FakeTTSA(TTSProvider):
    kind = "fake_tts_a"

    def synthesize(self, text, language="tr"):
        return TTSResult(np.zeros(16000, dtype=np.float32), 16000, 0.01, self.kind, self.model)


class FakeTTSB(FakeTTSA):
    kind = "fake_tts_b"


class FakeSTT(STTProvider):
    kind = "fake_stt"

    def transcribe(self, audio, sample_rate, language="tr"):
        return STTResult(f"{len(audio)}@{sample_rate}", 0.02, self.kind, self.model)


class FakeLLM(LLMProvider):
    kind = "fake_llm"

    def complete(self, messages, max_tokens=256, temperature=0.3):
        return LLMResult("Ankara", 0.03, self.kind, self.model, output_tokens=1)


class KeyedTTS(FakeTTSA):
    kind = "keyed_tts"
    required_env = ("FAKE_TTS_API_KEY",)


class BrokenTTS(FakeTTSA):
    kind = "broken_tts"

    def synthesize(self, text, language="tr"):
        raise ProviderError("model patladı")


PROFILES_YAML = """
profiles:
  P1:
    name: Bir
    stt: {provider: fake_stt, model: s1}
    llm: {provider: fake_llm, model: l1}
    tts: {provider: fake_tts_a, model: a}
  P2:
    name: İki
    stt: {provider: fake_stt, model: s2}
    llm: {provider: fake_llm, model: l2}
    tts: {provider: fake_tts_b, model: b}
  KEY:
    name: Anahtarlı
    stt: null
    llm: null
    tts: {provider: keyed_tts}
  BROKEN:
    name: Bozuk
    tts: {provider: broken_tts}
  RT:
    name: Realtime
    mode: realtime
    realtime: {provider: openai_realtime, model: x}
"""


@pytest.fixture()
def fake_env(tmp_path, monkeypatch):
    cfg = tmp_path / "profiles.yaml"
    cfg.write_text(PROFILES_YAML, encoding="utf-8")
    monkeypatch.setenv("SVA_PROFILES", str(cfg))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("FAKE_TTS_API_KEY", raising=False)
    for cls in (FakeTTSA, FakeTTSB, FakeSTT, FakeLLM, KeyedTTS, BrokenTTS):
        monkeypatch.setitem(registry.PROVIDERS, cls.kind, cls)
    registry._cache.clear()
    yield tmp_path
    registry._cache.clear()


def calls(tmp_path):
    path = tmp_path / "logs" / "provider-calls.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_real_config_defines_plan_profiles():
    profiles = load_profiles()
    assert list(profiles) == ["L1", "L2", "L3", "L4", "L5", "A1", "A2"]
    assert profiles["L1"].component("tts")["provider"] == "ema"
    assert profiles["L2"].component("llm")["model"] == "qwen3:30b-a3b-instruct-2507-q4_K_M"
    assert profiles["L5"].component("stt") is None
    assert profiles["A2"].mode == "realtime"
    for p in profiles.values():
        for comp in ("stt", "llm", "tts"):
            spec = p.component(comp)
            if spec:
                assert spec["provider"] in registry.PROVIDERS, (p.id, comp, spec)


def test_api_profile_status_lists_missing_keys(monkeypatch):
    for key in ("DEEPGRAM_API_KEY", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"):
        monkeypatch.delenv(key, raising=False)
    res = client.get("/api/profiles", params={"check": "false"})
    assert res.status_code == 200
    a1 = next(p for p in res.json() if p["id"] == "A1")
    assert a1["ready"] is False
    assert set(a1["missing_env"]) == {"DEEPGRAM_API_KEY", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY",
                                      "ELEVENLABS_VOICE_ID"}


def test_switching_profile_routes_tts_to_its_provider_and_logs(fake_env):
    r1 = client.post("/api/profiles/P1/tts", json={"text": "Merhaba"})
    r2 = client.post("/api/profiles/P2/tts", json={"text": "Merhaba"})
    assert r1.status_code == r2.status_code == 200
    assert r1.headers["content-type"] == "audio/wav"
    assert (r1.headers["X-Provider"], r1.headers["X-Model"]) == ("fake_tts_a", "a")
    assert (r2.headers["X-Provider"], r2.headers["X-Model"]) == ("fake_tts_b", "b")
    logged = [(c["profile"], c["component"], c["provider"], c["ok"]) for c in calls(fake_env)]
    assert logged == [("P1", "tts", "fake_tts_a", True), ("P2", "tts", "fake_tts_b", True)]


def test_stt_upload_routed_to_profile_provider(fake_env):
    wav = encode_wav(np.zeros(8000, dtype=np.float32), 8000)
    res = client.post("/api/profiles/P2/stt", files={"audio": ("a.wav", wav, "audio/wav")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["provider"], body["model"], body["text"]) == ("fake_stt", "s2", "8000@8000")
    assert calls(fake_env)[-1]["component"] == "stt"


def test_llm_routed(fake_env):
    res = client.post("/api/profiles/P1/llm", json={"prompt": "Başkent?"})
    assert res.status_code == 200
    assert res.json()["text"] == "Ankara"


def test_missing_api_key_gives_clear_error(fake_env):
    res = client.post("/api/profiles/KEY/tts", json={"text": "Merhaba"})
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["error"] == "provider_not_ready"
    assert detail["missing_env"] == ["FAKE_TTS_API_KEY"]
    assert "FAKE_TTS_API_KEY" in detail["message"] and ".env" in detail["message"]


def test_key_present_makes_profile_usable(fake_env, monkeypatch):
    monkeypatch.setenv("FAKE_TTS_API_KEY", "x")
    assert client.post("/api/profiles/KEY/tts", json={"text": "Merhaba"}).status_code == 200


def test_missing_component_and_realtime_profile(fake_env):
    res = client.post("/api/profiles/KEY/llm", json={"prompt": "x"})
    assert res.status_code == 400 and res.json()["detail"]["error"] == "component_unavailable"
    res = client.post("/api/profiles/RT/tts", json={"text": "x"})
    assert res.status_code == 400 and "realtime" in res.json()["detail"]["message"]


def test_unknown_profile_404(fake_env):
    res = client.post("/api/profiles/NOPE/tts", json={"text": "x"})
    assert res.status_code == 404 and res.json()["detail"]["error"] == "unknown_profile"


def test_provider_failure_is_502_and_logged(fake_env):
    res = client.post("/api/profiles/BROKEN/tts", json={"text": "x"})
    assert res.status_code == 502 and "patladı" in res.json()["detail"]["message"]
    assert calls(fake_env)[-1]["ok"] is False


def test_provider_instances_are_cached(fake_env):
    client.post("/api/profiles/P1/tts", json={"text": "a"})
    client.post("/api/profiles/P1/tts", json={"text": "b"})
    assert sum(1 for k in registry._cache if k[0] == "fake_tts_a") == 1
