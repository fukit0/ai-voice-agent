"""core-010: STT'siz hat (L5) — ses doğrudan LLM'e. Burada sahte ses-girdili LLM kullanılır: gerçek Ollama/Gemma'nın sesi kabul edip
etmediği ve gecikme kazancı Mac'te scripts/audio_llm_probe.py ile ölçülür; bu testler yalnızca bizim tarafın sözleşmesini doğrular."""
import asyncio
import json

import numpy as np
import pytest

from backend.app import scenario as S
from backend.app.providers import local
from backend.app.providers.base import LLMProvider, LLMResult, ProviderError
from backend.app.providers.fake import FakeLLM, FakeTTS
from backend.app.providers.local import OllamaLLM
from backend.app.voice.flow import FlowDriver, build_audio_messages
from backend.app.voice.session import VoiceSession
from backend.tests.test_voice import FakeOut, settle


class AudioLLM:
    """Sırayla verilen çıktıları döndürür; aldığı ses ve mesajları kaydeder."""
    kind, model, accepts_audio = "scripted_audio", "a", True

    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []

    def complete_audio(self, messages, audio, sample_rate, max_tokens=256, temperature=0.0):
        self.calls.append({"messages": messages, "samples": len(audio), "rate": sample_rate})
        out = self.outputs.pop(0)
        return LLMResult(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False), 0.01, self.kind, self.model)

    def complete(self, messages, max_tokens=256, temperature=0.3):                   # metin yolu bu testlerde çağrılmamalı
        raise AssertionError("STT'siz hatta metin tamamlaması çağrılmamalı")


AUDIO = np.full(16000, 0.1, dtype=np.float32)


def driver(*outputs):
    llm = AudioLLM(outputs)
    return FlowDriver(S.get("anket"), llm, None), llm


def test_default_providers_reject_audio_and_ollama_needs_the_audio_option():
    class Plain(LLMProvider):
        kind = "plain"
    assert Plain("m").accepts_audio is False
    with pytest.raises(ProviderError):
        Plain("m").complete_audio([], AUDIO, 16000)
    assert OllamaLLM("gemma4:12b").accepts_audio is False and OllamaLLM("gemma4:12b", audio=True).accepts_audio is True
    with pytest.raises(ProviderError):
        OllamaLLM("gemma4:12b").complete_audio([{"role": "user", "content": "x"}], AUDIO, 16000)


def test_ollama_sends_audio_as_input_audio_part_and_parses_reply(monkeypatch):
    seen = {}

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": ' {"intent":"answer"} '}}], "usage": {"prompt_tokens": 30, "completion_tokens": 5}}

    def post(url, json=None, timeout=None):
        seen.update(url=url, body=json)
        return Resp()
    monkeypatch.setattr("httpx.post", post)
    r = OllamaLLM("gemma4:12b", audio=True).complete_audio(
        [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], AUDIO, 16000, 64, 0.0)
    assert seen["url"].endswith("/v1/chat/completions") and seen["body"]["model"] == "gemma4:12b"
    parts = seen["body"]["messages"][-1]["content"]
    assert parts[0] == {"type": "text", "text": "u"} and parts[1]["type"] == "input_audio" and parts[1]["input_audio"]["format"] == "wav"
    assert seen["body"]["messages"][0]["content"] == "s"                                # önceki mesajlar değişmez
    assert r.text == '{"intent":"answer"}' and (r.input_tokens, r.output_tokens) == (30, 5)


def test_ollama_http_error_becomes_provider_error(monkeypatch):
    def post(*a, **k):
        raise RuntimeError("400 audio not supported")
    monkeypatch.setattr("httpx.post", post)
    with pytest.raises(ProviderError, match="ses çağrısı başarısız"):
        OllamaLLM("gemma4:12b", audio=True).complete_audio([{"role": "user", "content": "u"}], AUDIO, 16000)


def test_audio_prompt_asks_for_transcript_and_has_no_customer_text():
    d, _ = driver()
    d.start()
    msgs = build_audio_messages(d.steps[d.current], d.text_of(d.current))
    assert "transcript" in msgs[0]["content"] and "uydurma" in msgs[0]["content"]
    assert "ekteki ses" in msgs[1]["content"] and "Müşteri:" not in msgs[1]["content"]


def test_handle_audio_advances_with_model_answer_and_records_transcript():
    d, llm = driver({"intent": "answer", "value": "devam", "transcript": "hayır devam edelim"})
    d.start()
    r = d.handle_audio(AUDIO, 16000)
    assert r.heard == "hayır devam edelim" and d.current == "musaitlik" and r.llm_s is not None
    assert llm.calls[0]["samples"] == len(AUDIO) and llm.calls[0]["rate"] == 16000
    assert any(e["type"] == "audio_heard" and e["text"] == "hayır devam edelim" for e in r.events)
    assert d.answers[0]["utterance"] == "hayır devam edelim"


def test_empty_transcript_is_unclear_even_if_model_claims_an_answer():
    d, _ = driver({"intent": "answer", "value": "devam", "transcript": "  "})
    d.start()
    r = d.handle_audio(AUDIO, 16000)
    assert d.current == "giris" and r.heard == "" and r.utterances                      # ilerlemez, tekrar sorar
    assert not d.answers


def test_bad_json_is_unclear_not_a_crash():
    d, _ = driver("anlamadım")
    d.start()
    r = d.handle_audio(AUDIO, 16000)
    assert d.current == "giris" and r.utterances


def test_identity_question_in_transcript_gets_the_honest_answer():
    d, _ = driver({"intent": "answer", "value": "devam", "transcript": "sen robot musun"})
    d.start()
    r = d.handle_audio(AUDIO, 16000)
    assert d.current == "giris" and any(e["type"] == "identity" for e in r.events)


def test_session_without_stt_routes_audio_to_llm_and_logs_transcript(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))

    async def main():
        llm = AudioLLM([{"intent": "answer", "value": "devam", "transcript": "devam edelim"}])
        flow = FlowDriver(S.get("anket"), llm, None)
        events, out = [], FakeOut()
        s = VoiceSession("t-audio", "L5", None, llm, FakeTTS("m"), out, events.append, flow=flow)
        await s.start()
        await settle(s)
        out.cb()
        await s._respond(AUDIO, 0.0)
        await settle(s)
        return s, events, llm

    s, events, llm = asyncio.run(main())
    assert len(llm.calls) == 1 and flow_current(s) == "musaitlik"
    assert any(e["type"] == "transcript" and e["role"] == "user" and e["text"] == "devam edelim" for e in events)
    assert not any(e["type"] == "error" for e in events)
    assert s.turns[-1].get("audio_in") is True and "stt_s" not in s.turns[-1]


def flow_current(s):
    return s.flow.current


def test_session_without_stt_and_without_audio_llm_reports_an_error_instead_of_hanging(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))

    async def main():
        events, out = [], FakeOut()
        s = VoiceSession("t-noaudio", "L5", None, FakeLLM("m"), FakeTTS("m"), out, events.append, flow=FlowDriver(S.get("anket"), FakeLLM("m"), None))
        await s.start()
        await settle(s)
        out.cb()
        await s._respond(AUDIO, 0.0)
        return s, events

    s, events = asyncio.run(main())
    assert any(e["type"] == "error" and "core-010" in e["message"] for e in events) and s.state == "listening"
