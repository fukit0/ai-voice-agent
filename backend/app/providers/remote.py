"""API sağlayıcıları (demo / referans profiller): Deepgram, Anthropic, ElevenLabs.

Anahtarlar ortam değişkenlerinden okunur; eksikse çağrı yapılmadan ProviderNotReady döner.
Gerçek müşteri verisi bu sağlayıcılara gönderilmemeli (KVKK; plan: Demo API'leri).
"""
from __future__ import annotations

import os
import time

import numpy as np

from .audio import encode_wav
from .base import LLMProvider, LLMResult, ProviderError, STTProvider, STTResult, TTSProvider, TTSResult


def _post(url: str, **kwargs):
    import httpx

    try:
        res = httpx.post(url, timeout=kwargs.pop("timeout", 60), **kwargs)
    except Exception as exc:
        raise ProviderError(f"{url} çağrısı başarısız: {exc}") from exc
    if res.status_code >= 400:
        raise ProviderError(f"{url} HTTP {res.status_code}: {res.text[:200]}")
    return res


class DeepgramSTT(STTProvider):
    kind = "deepgram"
    required_env = ("DEEPGRAM_API_KEY",)

    def transcribe(self, audio, sample_rate, language="tr"):
        t0 = time.perf_counter()
        res = _post(
            "https://api.deepgram.com/v1/listen",
            params={"model": self.model or "nova-3", "language": language, "smart_format": "true"},
            headers={"Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}", "Content-Type": "audio/wav"},
            content=encode_wav(audio, sample_rate),
        )
        alt = res.json()["results"]["channels"][0]["alternatives"][0]
        return STTResult(text=alt.get("transcript", "").strip(), seconds=time.perf_counter() - t0,
                         provider=self.kind, model=self.model, extra={"confidence": alt.get("confidence")})


class AnthropicLLM(LLMProvider):
    kind = "anthropic"
    required_env = ("ANTHROPIC_API_KEY",)

    def complete(self, messages, max_tokens=256, temperature=0.3):
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        chat = [m for m in messages if m["role"] != "system"]
        payload = {"model": self.model, "max_tokens": max_tokens, "messages": chat}
        if not getattr(self, "_no_temperature", False):
            payload["temperature"] = temperature  # yeni modeller reddeder ("temperature is deprecated"): aşağıda yeniden denenir
        if system:
            payload["system"] = system
        t0 = time.perf_counter()
        headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}
        if os.environ.get("ANTHROPIC_WORKSPACE_ID"):  # çalışma alanına bağlı olmayan anahtarlar bu başlığı ister
            headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
        try:
            try:
                res = _post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
            except ProviderError as exc:
                if "temperature" not in str(exc).lower() or "temperature" not in payload:
                    raise
                payload.pop("temperature")  # bu model sıcaklık parametresini kabul etmiyor: bir daha gönderme
                self._no_temperature = True
                res = _post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
        except ProviderError as exc:
            if "workspace" in str(exc).lower() and not os.environ.get("ANTHROPIC_WORKSPACE_ID"):
                raise ProviderError(
                    "Anthropic anahtarı bir çalışma alanına (workspace) bağlı değil. .env dosyasına "
                    "ANTHROPIC_WORKSPACE_ID=<çalışma alanı kimliği> ekleyip backend'i yeniden başlatın "
                    "(Console > Settings > Workspaces) ya da çalışma alanına bağlı bir anahtar kullanın.") from exc
            raise
        body = res.json()
        text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
        return LLMResult(text=text.strip(), seconds=time.perf_counter() - t0, provider=self.kind,
                         model=self.model, output_tokens=body.get("usage", {}).get("output_tokens"))


class ElevenLabsTTS(TTSProvider):
    kind = "elevenlabs"
    required_env = ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID")
    SAMPLE_RATE = 24000

    def synthesize(self, text, language="tr"):
        t0 = time.perf_counter()
        res = _post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{os.environ['ELEVENLABS_VOICE_ID']}",
            params={"output_format": f"pcm_{self.SAMPLE_RATE}"},
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            json={"text": text, "model_id": self.model or "eleven_flash_v2_5", "language_code": language},
        )
        audio = np.frombuffer(res.content, dtype="<i2").astype(np.float32) / 32768.0
        return TTSResult(audio=audio, sample_rate=self.SAMPLE_RATE, seconds=time.perf_counter() - t0,
                         provider=self.kind, model=self.model)
