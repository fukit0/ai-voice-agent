"""Lokal sağlayıcılar (Apple Silicon Mac): mlx-whisper, Ollama, EMA Lightning, Chatterbox, HF Whisper.

Ağır kütüphaneler yalnızca kullanıldığında içe aktarılır; böylece testler ve Linux ortamı
mlx / torch olmadan da çalışır. Model nesneleri kayıt defterinde önbelleklenir (registry.py).
"""
from __future__ import annotations

import os
import threading
import time

import numpy as np

from .audio import resample
from .base import LLMResult, LLMProvider, ProviderError, STTProvider, STTResult, TTSProvider, TTSResult

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


class MlxWhisperSTT(STTProvider):
    kind = "mlx_whisper"
    _lock = threading.Lock()  # mlx aynı anda tek çağrı

    def transcribe(self, audio, sample_rate, language="tr"):
        import mlx_whisper

        audio16 = resample(audio, sample_rate, 16000)
        t0 = time.perf_counter()
        with self._lock:
            out = mlx_whisper.transcribe(audio16, path_or_hf_repo=self.model, language=language,
                                         verbose=None, condition_on_previous_text=False)
        return STTResult(text=out.get("text", "").strip(), seconds=time.perf_counter() - t0,
                         provider=self.kind, model=self.model)


class HfWhisperSTT(STTProvider):
    """Transformers ile çalışan Whisper türevleri (ör. BuzzASR/turkish)."""

    kind = "hf_whisper"
    _lock = threading.Lock()

    def __init__(self, model=None, **options):
        super().__init__(model, **options)
        self._pipe = None

    def _pipeline(self):
        if self._pipe is None:
            import torch
            from transformers import pipeline

            device = "mps" if torch.backends.mps.is_available() else "cpu"
            self._pipe = pipeline("automatic-speech-recognition", model=self.model, device=device)
        return self._pipe

    def transcribe(self, audio, sample_rate, language="tr"):
        audio16 = resample(audio, sample_rate, 16000)
        t0 = time.perf_counter()
        with self._lock:
            out = self._pipeline()({"raw": audio16, "sampling_rate": 16000},
                                   generate_kwargs={"language": language, "task": "transcribe"})
        return STTResult(text=out.get("text", "").strip(), seconds=time.perf_counter() - t0,
                         provider=self.kind, model=self.model)


class OllamaLLM(LLMProvider):
    kind = "ollama"

    def readiness_issues(self):
        import httpx

        try:
            tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=1.0).json().get("models", [])
        except Exception:
            return [f"Ollama'ya ulaşılamıyor ({OLLAMA_URL}); `ollama serve` çalışıyor mu?"]
        names = {m.get("name") for m in tags}
        if self.model not in names:
            return [f"Ollama modeli indirilmemiş: ollama pull {self.model}"]
        return []

    def complete(self, messages, max_tokens=256, temperature=0.3):
        import httpx

        t0 = time.perf_counter()
        try:
            res = httpx.post(f"{OLLAMA_URL}/api/chat", timeout=120, json={
                "model": self.model, "messages": messages, "stream": False,
                "think": False,  # sesli ajanda düşünme gecikmesi kabul edilemez
                "options": {"num_predict": max_tokens, "temperature": temperature},
            })
            res.raise_for_status()
        except Exception as exc:
            raise ProviderError(f"Ollama çağrısı başarısız ({self.model}): {exc}") from exc
        body = res.json()
        return LLMResult(text=body.get("message", {}).get("content", "").strip(),
                         seconds=time.perf_counter() - t0, provider=self.kind, model=self.model,
                         output_tokens=body.get("eval_count"),
                         extra={"load_seconds": round(body.get("load_duration", 0) / 1e9, 2)})


class EmaTTS(TTSProvider):
    kind = "ema"
    _lock = threading.Lock()

    def __init__(self, model=None, **options):
        super().__init__(model or "ema-lightning", **options)
        self._engine = None

    def synthesize(self, text, language="tr"):
        from ema_lightning import EMA

        with self._lock:
            if self._engine is None:
                self._engine = EMA()
            t0 = time.perf_counter()
            speech = self._engine.say(text, sample_rate=24000)
        return TTSResult(audio=np.asarray(speech.audio, dtype=np.float32), sample_rate=24000,
                         seconds=time.perf_counter() - t0, provider=self.kind, model=self.model)


class ChatterboxTTS(TTSProvider):
    kind = "chatterbox"
    _lock = threading.Lock()

    def __init__(self, model=None, **options):
        super().__init__(model or "chatterbox-multilingual", **options)
        self._tts = None

    def synthesize(self, text, language="tr"):
        import torch
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        with self._lock:
            if self._tts is None:
                device = "mps" if torch.backends.mps.is_available() else "cpu"
                # cihaz string olmalı: kütüphane "mps"/"cpu" karşılaştırmasıyla CPU'ya map ediyor
                self._tts = ChatterboxMultilingualTTS.from_pretrained(device=device)
            t0 = time.perf_counter()
            wav = self._tts.generate(text, language_id=self.options.get("language", language))
            audio = wav.squeeze().detach().cpu().numpy().astype(np.float32)
        return TTSResult(audio=audio, sample_rate=int(self._tts.sr), seconds=time.perf_counter() - t0,
                         provider=self.kind, model=self.model)
