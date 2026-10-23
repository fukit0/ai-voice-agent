"""ADR 0001 / lab-006: Hazırla (warmup), soğuk çağrı koruması ve bellekten çıkarma."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.providers import registry
from backend.app.providers.base import STTProvider, STTResult, TTSProvider, TTSResult
from backend.app.providers.local import OllamaLLM

from .test_profiles import FakeLLM, KeyedTTS, warm

client = TestClient(app)
EVENTS: list[tuple[str, str]] = []


class CountingTTS(TTSProvider):
    kind = "counting_tts"

    def synthesize(self, text, language="tr"):
        EVENTS.append(("tts_call", self.model))
        return TTSResult(np.zeros(160, dtype=np.float32), 16000, 0.001, self.kind, self.model)

    def unload(self):
        super().unload()
        EVENTS.append(("unload", self.model))


class CountingSTT(STTProvider):
    kind = "counting_stt"

    def transcribe(self, audio, sample_rate, language="tr"):
        EVENTS.append(("stt_call", self.model))
        return STTResult("x", 0.001, self.kind, self.model)

    def unload(self):
        super().unload()
        EVENTS.append(("unload", self.model))


class FailingTTS(CountingTTS):
    kind = "failing_tts"

    def synthesize(self, text, language="tr"):
        raise RuntimeError("yüklenemedi")


YAML = """
profiles:
  W1:
    name: Bir
    stt: {provider: counting_stt, model: shared-stt}
    llm: {provider: fake_llm, model: l}
    tts: {provider: counting_tts, model: tts-1}
  W2:
    name: İki
    stt: {provider: counting_stt, model: shared-stt}
    llm: {provider: fake_llm, model: l}
    tts: {provider: counting_tts, model: tts-2}
  WK:
    name: Anahtarlı
    stt: {provider: counting_stt, model: shared-stt}
    llm: {provider: fake_llm, model: l}
    tts: {provider: keyed_tts}
  WF:
    name: Bozuk
    stt: {provider: counting_stt, model: shared-stt}
    llm: {provider: fake_llm, model: l}
    tts: {provider: failing_tts, model: f}
  RT:
    name: Realtime
    mode: realtime
    realtime: {provider: openai_realtime, model: x}
"""


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "profiles.yaml"
    cfg.write_text(YAML, encoding="utf-8")
    monkeypatch.setenv("SVA_PROFILES", str(cfg))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("FAKE_TTS_API_KEY", raising=False)
    for cls in (CountingTTS, CountingSTT, FailingTTS, FakeLLM, KeyedTTS):
        monkeypatch.setitem(registry.PROVIDERS, cls.kind, cls)
    monkeypatch.setattr(OllamaLLM, "loaded_models", staticmethod(lambda: set()))
    registry._cache.clear()
    EVENTS.clear()
    yield
    registry._cache.clear()


def status(pid):
    return next(p for p in client.get("/api/profiles").json() if p["id"] == pid)


def test_cold_profile_refuses_measurement_calls():
    res = client.post("/api/profiles/W1/tts", json={"text": "Merhaba"})
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["error"] == "profile_not_warm" and "Hazırla" in detail["message"]
    assert status("W1")["warm"] is False


def test_warmup_loads_measures_and_marks_warm():
    job = warm("W1")
    assert job["state"] == "ready"
    for comp in ("stt", "llm", "tts"):
        c = job["components"][comp]
        assert c["state"] == "ready" and c["load_seconds"] >= 0 and c["warm_seconds"] >= 0
    # her bileşen iki kez çağrıldı: ısınma + sıcak ölçüm
    assert EVENTS.count(("tts_call", "tts-1")) == 2 and EVENTS.count(("stt_call", "shared-stt")) == 2
    st = status("W1")
    assert st["warm"] is True and all(c["warm"] for c in st["components"].values())
    res = client.post("/api/profiles/W1/tts", json={"text": "Merhaba"})
    assert res.status_code == 200 and res.headers["X-Warm"] == "true"


def test_switching_profile_evicts_unused_models_but_keeps_shared():
    warm("W1")
    EVENTS.clear()
    res = client.post("/api/profiles/W2/warmup")  # keep_others=false (varsayılan)
    assert res.status_code == 202
    import time

    while client.get("/api/profiles/W2/warmup").json()["state"] == "running":
        time.sleep(0.01)
    job = client.get("/api/profiles/W2/warmup").json()
    assert "counting_tts:tts-1" in job["evicted"]
    assert ("unload", "tts-1") in EVENTS and ("unload", "shared-stt") not in EVENTS
    assert status("W1")["warm"] is False and status("W2")["warm"] is True
    assert client.post("/api/profiles/W1/tts", json={"text": "x"}).status_code == 409


def test_keep_others_keeps_both_profiles_warm():
    warm("W1")
    warm("W2")  # yardımcı keep_others=true kullanır
    assert status("W1")["warm"] is True and status("W2")["warm"] is True


def test_warmup_reports_missing_key_per_component():
    job = warm("WK")
    assert job["state"] == "failed"
    assert job["components"]["tts"]["missing_env"] == ["FAKE_TTS_API_KEY"]
    assert job["components"]["stt"]["state"] == "ready"


def test_warmup_reports_component_failure():
    job = warm("WF")
    assert job["state"] == "failed" and "yüklenemedi" in job["components"]["tts"]["error"]


def test_realtime_profile_warmup_unsupported():
    res = client.post("/api/profiles/RT/warmup")
    assert res.status_code == 400 and res.json()["detail"]["error"] == "warmup_unsupported"


def test_allow_cold_is_explicit_and_logged(tmp_path):
    res = client.post("/api/profiles/W1/tts", params={"allow_cold": "true"}, json={"text": "x"})
    assert res.status_code == 200 and res.headers["X-Warm"] == "false"


def test_ollama_requests_keep_model_resident(monkeypatch):
    sent = {}

    class Res:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "Ankara"}, "eval_count": 1}

    def fake_post(url, json=None, timeout=None):
        sent.update(json)
        return Res()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.delenv("OLLAMA_KEEP_ALIVE", raising=False)
    OllamaLLM("qwen").complete([{"role": "user", "content": "x"}])
    assert sent["keep_alive"] == -1 and sent["think"] is False


def test_system_reports_memory():
    body = client.get("/api/system").json()
    assert "memory_gb" in body
