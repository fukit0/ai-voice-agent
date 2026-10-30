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


def _post_stream(url: str, **kwargs) -> tuple[float, float, bytes]:
    """Akışlı POST: (ilk ses baytına kadar sn, toplam sn, gövde). Canlı hatta önemli olan ilk ses süresini ölçer."""
    import httpx

    t0 = time.perf_counter()
    first, chunks = None, []
    try:
        with httpx.stream("POST", url, timeout=kwargs.pop("timeout", 60), **kwargs) as res:
            if res.status_code >= 400:
                res.read()
                raise ProviderError(f"{url} HTTP {res.status_code}: {res.text[:200]}")
            for chunk in res.iter_bytes():
                if chunk and first is None:
                    first = time.perf_counter() - t0
                chunks.append(chunk)
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"{url} çağrısı başarısız: {exc}") from exc
    total = time.perf_counter() - t0
    return (first if first is not None else total), total, b"".join(chunks)


def _get(url: str, **kwargs):
    import httpx

    try:
        res = httpx.get(url, timeout=kwargs.pop("timeout", 30), **kwargs)
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
        if not getattr(self, "_no_thinking_param", False):
            # Canlı ölçüm (core-012, 38/342 + 38/237 boş çıktı): Haiku 5.5 varsayılan olarak düşünüyor ve kısa max_tokens'ı (120) düşünmeye harcayıp
            # metin üretmeden bitiyor (stop_reason=max_tokens, yalnız 'thinking' bloğu). Kısa yapılandırılmış cevapta düşünme kapatılır.
            payload["thinking"] = {"type": "disabled"}
        t0 = time.perf_counter()
        headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}
        if os.environ.get("ANTHROPIC_WORKSPACE_ID"):  # çalışma alanına bağlı olmayan anahtarlar bu başlığı ister
            headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
        try:
            while True:
                try:
                    res = _post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
                    break
                except ProviderError as exc:
                    msg = str(exc).lower()
                    if "temperature" in msg and "temperature" in payload:
                        payload.pop("temperature")  # bu model sıcaklık parametresini kabul etmiyor: bir daha gönderme
                        self._no_temperature = True
                    elif "thinking" in msg and "thinking" in payload:
                        payload.pop("thinking")     # bu model 'disabled' kabul etmiyor: bir daha gönderme
                        self._no_thinking_param = True
                    else:
                        raise
        except ProviderError as exc:
            if "workspace" in str(exc).lower() and not os.environ.get("ANTHROPIC_WORKSPACE_ID"):
                raise ProviderError(
                    "Anthropic anahtarı bir çalışma alanına (workspace) bağlı değil. .env dosyasına "
                    "ANTHROPIC_WORKSPACE_ID=<çalışma alanı kimliği> ekleyip backend'i yeniden başlatın "
                    "(Console > Settings > Workspaces) ya da çalışma alanına bağlı bir anahtar kullanın.") from exc
            raise
        body = res.json()
        text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
        if not text.strip() and body.get("stop_reason") == "max_tokens" and max_tokens < 2048:
            # düşünme kapatılamadıysa: bütçeyi büyütüp bir kez daha dene (boş çıktı 'anlaşılmadı' sayılıp müşteriye yanlış tekrar sordurur)
            payload["max_tokens"] = max(max_tokens * 8, 1024)
            res = _post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
            body = res.json()
            text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
        extra = {"stop_reason": body.get("stop_reason"), "blocks": [b.get("type") for b in body.get("content", [])]}
        return LLMResult(text=text.strip(), seconds=time.perf_counter() - t0, provider=self.kind, model=self.model,
                         output_tokens=body.get("usage", {}).get("output_tokens"),
                         input_tokens=body.get("usage", {}).get("input_tokens"), extra=extra)


class ElevenLabsTTS(TTSProvider):
    kind = "elevenlabs"
    # Ses kimliği artık zorunlu ortam değişkeni değil: Persona > Ses stüdyosu'ndan atanan ses de yeterli (readiness_issues denetler).
    required_env = ("ELEVENLABS_API_KEY",)
    SAMPLE_RATE = 24000

    def readiness_issues(self) -> list[str]:
        from .. import tone_voice

        miss = tone_voice.missing_voice_tones()
        if not miss:
            return []
        return [f"ses atanmamış tonlar: {', '.join(miss)}. Persona > Ses stüdyosu'ndan 'Genel ses' ya da bu tonlara ses atayın "
                "(veya ELEVENLABS_VOICE_ID tanımlayın)"]

    def request(self, text, language="tr", speed=1.0, tone=None, voice=None):
        """İstek gövdesi ve ses kimliği (synthesize ve TTS laboratuvarı ortak kullanır). `voice` verilirse en yüksek öncelik."""
        from .. import tone_voice

        model = self.model or "eleven_flash_v2_5"
        body = {"text": text, "model_id": model}
        if "multilingual_v2" not in model:   # language_code multilingual_v2'de desteklenmiyor
            body["language_code"] = language
        tp = tone_voice.params(self.kind, model, tone)   # ton -> voice_settings (+ v3/v4'te ses etiketi); ton yoksa {}
        vs = {k: tp[k] for k in ("stability", "similarity_boost", "style", "use_speaker_boost") if k in tp}
        eff = tp.get("speed", 1.0) * speed   # ton hızı persona hızıyla çarpılır
        if eff != 1.0:   # ElevenLabs voice_settings.speed kabul aralığı 0.7-1.2
            vs["speed"] = round(min(1.2, max(0.7, eff)), 3)
        if vs:
            body["voice_settings"] = vs
        if tp.get("tag") and tone_voice.uses_tags(model):
            body["text"] = f"{tp['tag']} {text}"
        if self.options.get("seed") is not None:   # A/B karşılaştırmada tekrarlanabilirlik (best-effort)
            body["seed"] = int(self.options["seed"])
        # Ton başına ayrı ses (Voice Library/Voice Design): ELEVENLABS_VOICE_ID_ENERJIK vb. tanımlıysa o kullanılır.
        # voice_settings'ten çok daha belirgin fark verir; tanımlı değilse tek ses + ayar kullanılır.
        # Öncelik: açık `voice` > ton ortam değişkeni > ekrandan o tona atanan ses > ekrandan Genel ses > ELEVENLABS_VOICE_ID
        voice = voice or tone_voice.resolve_voice(tone)
        if not voice:
            raise ProviderError("ElevenLabs sesi yok: Persona > Ses stüdyosu'ndan 'Genel ses' ya da bu tona ses atayın "
                                "(veya ELEVENLABS_VOICE_ID tanımlayın).")
        return voice, body

    def synthesize(self, text, language="tr", speed=1.0, tone=None, voice=None):
        t0 = time.perf_counter()
        voice, body = self.request(text, language, speed, tone, voice=voice)   # voice: eval-001 test müşterisi sesleri
        res = _post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            params={"output_format": f"pcm_{self.SAMPLE_RATE}"},
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            json=body,
        )
        audio = np.frombuffer(res.content, dtype="<i2").astype(np.float32) / 32768.0
        return TTSResult(audio=audio, sample_rate=self.SAMPLE_RATE, seconds=time.perf_counter() - t0,
                         provider=self.kind, model=self.model)
