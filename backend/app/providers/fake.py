"""Model gerektirmeyen sahte sağlayıcılar: yalnızca SVA_FAKE_PROVIDERS=1 iken kayda girer.

Amaç: ses hattının (WebRTC, VAD, söz kesme, olay akışı) modelsiz uçtan uca test edilmesi ve bulutta CI.
Üretimde/demoda kullanılmaz; profiller gerçek sağlayıcıları işaret eder.
"""
from __future__ import annotations

import numpy as np

from .base import LLMProvider, LLMResult, STTProvider, STTResult, TTSProvider, TTSResult


class FakeSTT(STTProvider):
    kind = "fake_stt"

    def transcribe(self, audio, sample_rate, language="tr"):
        seconds = len(audio) / sample_rate
        rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
        text = f"ses geldi {seconds:.1f} saniye" if rms > 0.005 else ""
        return STTResult(text, 0.01, self.kind, self.model, {"rms": rms})


class FakeLLM(LLMProvider):
    kind = "fake_llm"

    def complete(self, messages, max_tokens=256, temperature=0.3):
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "cevap ayrıştırıcısısın" in system:  # senaryo akışı: değer kuralına göre deterministik cevap
            return LLMResult(self._extract(system, messages[-1]["content"]), 0.01, self.kind, self.model)
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return LLMResult(f"Anladım, {last} dediniz. Devam edelim mi?", 0.01, self.kind, self.model)


    @staticmethod
    def _extract(system: str, user: str) -> str:
        import json
        rule = system.split("value kuralı:", 1)[1].split("\n", 1)[0]
        if "true (evet)" in rule:
            value = "katıldınız mı" not in user.lower()      # elemeyi geçen müşteri: Q3 hayır, diğerleri evet
        elif "arası tam sayı" in rule:
            value = 8
        elif "seçenek anahtarlarından" in rule:
            value = rule.split(":", 1)[1].split(",")[0].strip().rstrip(".")
        elif "saniye" in rule:
            value = 30
        else:
            value = "yarın saat on beşte"
        return json.dumps({"intent": "answer", "value": value}, ensure_ascii=False)


class FakeTTS(TTSProvider):
    kind = "fake_tts"

    def synthesize(self, text, language="tr", speed=1.0):
        rate = 24000
        seconds = min(3.0, 0.08 * max(len(text), 1))
        t = np.arange(int(rate * seconds)) / rate
        audio = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        return TTSResult(audio, rate, 0.01, self.kind, self.model)
