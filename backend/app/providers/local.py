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


def _keep_alive():
    """Ollama'nın modeli bellekte tutma süresi. Varsayılan -1: ısınan model boşta kalınca atılmaz (ADR 0001)."""
    raw = os.environ.get("OLLAMA_KEEP_ALIVE", "-1")
    try:
        return int(raw)
    except ValueError:
        return raw  # "30m" gibi süre ifadeleri


def _free_accelerator_memory() -> None:
    import gc

    gc.collect()
    try:
        import torch

        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:  # noqa: BLE001 — torch yoksa sorun değil
        pass


class MlxWhisperSTT(STTProvider):
    kind = "mlx_whisper"
    _lock = threading.Lock()  # mlx aynı anda tek çağrı

    def transcribe(self, audio, sample_rate, language="tr", prompt=None):
        """prompt: Whisper `initial_prompt` (alan kelimeleri ipucu); verilmezse profildeki `initial_prompt` seçeneği.
        Varsayılan kapalıdır: kısa seslerde ipucu metnini aynen yazma (halüsinasyon) riski var, ölçülerek açılmalı."""
        import mlx_whisper

        audio16 = resample(audio, sample_rate, 16000)
        prompt = prompt or self.options.get("initial_prompt")
        extra = {"initial_prompt": prompt} if prompt else {}
        t0 = time.perf_counter()
        with self._lock:
            # temperature=0.0: sıcaklık geri düşmesi (fallback) kapalı; canlı testte kod karışımında 5 kat yavaşlayıp
            # halüsinasyon ("vermenção") üretti. Profil seçeneği `temperature` ile geri açılabilir.
            out = mlx_whisper.transcribe(audio16, path_or_hf_repo=self.model, language=language, verbose=None,
                                         condition_on_previous_text=False,
                                         temperature=self.options.get("temperature", 0.0), **extra)
        segs = out.get("segments") or []
        metrics = {}
        if segs:
            metrics = {"avg_logprob": min(float(s.get("avg_logprob", 0.0)) for s in segs),
                       "compression_ratio": max(float(s.get("compression_ratio", 0.0)) for s in segs),
                       "no_speech_prob": max(float(s.get("no_speech_prob", 0.0)) for s in segs)}
        return STTResult(text=out.get("text", "").strip(), seconds=time.perf_counter() - t0,
                         provider=self.kind, model=self.model, extra=metrics)

    def is_loaded(self):
        try:
            from mlx_whisper.transcribe import ModelHolder
        except Exception:  # noqa: BLE001
            return False
        return ModelHolder.model is not None and ModelHolder.model_path == self.model

    def unload(self):
        super().unload()
        try:
            import mlx.core as mx
            from mlx_whisper.transcribe import ModelHolder

            with self._lock:
                if ModelHolder.model_path == self.model:
                    ModelHolder.model = None
                    ModelHolder.model_path = None
                mx.clear_cache()
        except Exception:  # noqa: BLE001
            pass


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
            try:
                self._pipe = pipeline("automatic-speech-recognition", model=self.model, device=device)
            except OSError as exc:
                offline = os.environ.get("HF_HUB_OFFLINE") == "1"
                raise ProviderError(
                    f"{self.model} modeli bu bilgisayarın önbelleğinde yok"
                    + (" ve backend çevrimdışı modda (HF_HUB_OFFLINE=1)" if offline else
                       " ve Hugging Face'e bağlanılamadı") + ". Backend'i yeniden başlatmadan indirmek için: "
                    f"./.venv/bin/python scripts/fetch_models.py {self.model}  (sonra Hazırla'yı tekrar deneyin). "
                    f"Ayrıntı: {str(exc).splitlines()[0][:160]}") from exc
        return self._pipe

    def transcribe(self, audio, sample_rate, language="tr"):
        audio16 = resample(audio, sample_rate, 16000)
        t0 = time.perf_counter()
        with self._lock:
            out = self._pipeline()({"raw": audio16, "sampling_rate": 16000},
                                   generate_kwargs={"language": language, "task": "transcribe"})
        return STTResult(text=out.get("text", "").strip(), seconds=time.perf_counter() - t0,
                         provider=self.kind, model=self.model)

    def is_loaded(self):
        return self._pipe is not None

    def unload(self):
        super().unload()
        with self._lock:
            self._pipe = None
        _free_accelerator_memory()


class OllamaLLM(LLMProvider):
    kind = "ollama"

    @staticmethod
    def loaded_models() -> set[str] | None:
        """Ollama'da şu an bellekte olan modeller (/api/ps). Ulaşılamazsa None."""
        import httpx

        try:
            models = httpx.get(f"{OLLAMA_URL}/api/ps", timeout=1.0).json().get("models", [])
        except Exception:  # noqa: BLE001
            return None
        return {m.get("name") or m.get("model") for m in models}

    @staticmethod
    def unload_model(name: str) -> None:
        import httpx

        try:
            httpx.post(f"{OLLAMA_URL}/api/generate", json={"model": name, "keep_alive": 0}, timeout=30)
        except Exception:  # noqa: BLE001
            pass

    def is_warm(self):
        # Ollama ayrı bir süreç: backend yeniden başlasa da model bellekte kalmış olabilir, gerçeği /api/ps söyler.
        loaded = self.loaded_models()
        return bool(loaded and self.model in loaded)

    def is_loaded(self):
        return self.is_warm()

    def unload(self):
        super().unload()
        # Yalnızca gerçekten yüklüyse boşalt: Ollama boş istekte modeli önce YÜKLER (gereksiz 10+ GB okuma).
        if self.model in (self.loaded_models() or set()):
            self.unload_model(self.model)

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
                "keep_alive": _keep_alive(),
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

    def is_loaded(self):
        return self._engine is not None

    def unload(self):
        super().unload()
        with self._lock:
            self._engine = None
        _free_accelerator_memory()


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

    def is_loaded(self):
        return self._tts is not None

    def unload(self):
        super().unload()
        with self._lock:
            self._tts = None
        _free_accelerator_memory()
