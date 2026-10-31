"""Gecikme ölçüm betiği (scripts/latency_probe.py): sahte sağlayıcılarla mantık testi; gerçek ağ çağrısı yok."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from backend.app.providers.base import STTProvider, STTResult, TTSProvider, TTSResult, TTSStream, LLMProvider, LLMResult

SPEC = importlib.util.spec_from_file_location("latency_probe", Path(__file__).resolve().parents[2] / "scripts" / "latency_probe.py")
lp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lp)


class FakeStream:
    def __init__(self):
        self.sent = 0
        self.aborted = False

    def open(self):
        pass

    def send(self, b):
        self.sent += len(b)

    def finish(self):
        return STTResult("evet", 0.0, "fake", "m")

    def abort(self):
        self.aborted = True


class STT(STTProvider):
    kind = "fake_stt"

    @property
    def streaming(self):
        return bool(self.options.get("streaming"))

    def transcribe(self, audio, sample_rate, language="tr"):
        return STTResult("evet", 0.0, self.kind, self.model)

    def open_stream(self, sample_rate=16000, language="tr"):
        self.last = FakeStream()
        return self.last


class LLM(LLMProvider):
    kind = "fake_llm"

    def complete(self, messages, max_tokens=256, temperature=0.3):
        assert messages and messages[0]["role"] == "system"
        return LLMResult("{}", 0.0, self.kind, self.model)


class TTS(TTSProvider):
    kind = "fake_tts"

    @property
    def streaming(self):
        return bool(self.options.get("streaming"))

    def synthesize(self, text, language="tr", speed=1.0, tone=None):
        return TTSResult(np.zeros(2400, np.float32), 24000, 0.0, self.kind, self.model)

    def synthesize_stream(self, text, language="tr", speed=1.0, tone=None, voice=None):
        return TTSStream(iter([np.zeros(1200, np.float32), np.zeros(1200, np.float32)]), 24000)


def test_summarize_splits_cold_first_rep_from_warm():
    s = lp.summarize([2.0, 1.0, 1.2, 0.8])
    assert s["cold"] == 2.0 and s["warm_median"] == 1.0 and s["n_warm"] == 3 and s["warm_min"] == 0.8 and s["warm_max"] == 1.2
    assert lp.summarize([1.5])["warm_median"] is None


def test_probe_batch_profile_reports_all_components_without_stream_keys():
    stt, llm, tts = STT("m"), LLM("m"), TTS("m")
    r = lp.probe("A1", stt, llm, tts, np.zeros(16000, np.float32), 16000, reps=3, pace=False, sentences=["a", "b"])
    assert r["stt_streaming"] is False and r["tts_streaming"] is False and "stt_stream_after_speech" not in r
    for k in ("stt_batch", "llm", "tts_first_audio", "tts_total"):
        assert r[k]["n_warm"] == 2 and r[k]["warm_median"] is not None
    assert r["estimated_first_audio_s"] is not None and r["components"]["tts"] == "fake_tts:m"


def test_probe_streaming_profile_measures_stream_paths():
    stt, llm, tts = STT("m", streaming=True), LLM("m"), TTS("m", streaming=True)
    r = lp.probe("A1S", stt, llm, tts, np.zeros(1600, np.float32), 16000, reps=2, pace=False, sentences=["a"])
    assert r["stt_streaming"] is True and r["tts_streaming"] is True and r["stt_stream_after_speech"]["n_warm"] == 1
    assert stt.last.sent == 1600 * 2          # tüm ses int16 olarak akıtıldı
    assert render_has(r, "STT akışlı") and render_has(r, "(akışlı)")


def render_has(r, text):
    return text in lp.render(r)


def test_main_exits_cleanly_without_keys_or_clip(monkeypatch, tmp_path, capsys):
    for k in ("DEEPGRAM_API_KEY", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(lp, "ROOT", tmp_path)       # .env ve klip yok
    assert lp.main(["--profile", "A1S", "--out-dir", str(tmp_path)]) == 2
    assert "tanımlı değil" in capsys.readouterr().out
    assert lp.main(["--profile", "A2"]) == 2 and lp.main(["--profile", "YOK"]) == 2 and lp.main(["--reps", "1"]) == 2


def test_main_requires_clip_when_keys_exist(monkeypatch, tmp_path, capsys):
    for k in ("DEEPGRAM_API_KEY", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")
    monkeypatch.setattr(lp, "ROOT", tmp_path)
    assert lp.main(["--profile", "A1S", "--out-dir", str(tmp_path)]) == 2
    assert "Klip yok" in capsys.readouterr().out
