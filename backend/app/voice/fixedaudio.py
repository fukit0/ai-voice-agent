"""core-019: gerçek zamanlı profillerde sabit (yasal) metinlerin önceden üretilmiş sesle çalınması.

Neden: speech-to-speech modeller 'AYNEN SÖYLE' dense bile KVKK/güvenlik metnini değiştirebilir (verbatim ölçümü <1 olabilir).
Yasal metinler kelimesi kelimesine okunmak zorunda; bu yüzden bu adımlar OpenAI TTS ile üretilir, diske önbelleğe alınır ve
model yalnızca müşteriyi dinler. Aynı metin + model + ses -> aynı dosya (tutarlılık, sıfır üretim gecikmesi, düşük maliyet).
Sınır: gerçek ses kalitesi/tutarlılığı canlı dinlemeyle doğrulanmadı; önbellek ilk çağrıda üretildiği için ilk oturumda gecikir
(`warm()` ile önceden ısıtılabilir).
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Callable

import numpy as np

from .. import stt_runs

SPEECH_URL = "https://api.openai.com/v1/audio/speech"
DEFAULT_MODEL = "gpt-4o-mini-tts"
DEFAULT_VOICE = "marin"
SAMPLE_RATE = 24000                                   # response_format=pcm: 24 kHz, 16 bit, mono
DEFAULT_STEPS = ("*",)   # core-024: TÜM sabit sorular önceden üretilmiş sesle (model soruyu yeniden yorumlamasın); profilde `steps: [...]` ile daraltılır
STYLE = "Sıcak, doğal ve anlaşılır bir Türkçe telefon konuşması tonu. Metni değiştirmeden, kelimesi kelimesine oku."


def openai_speech(text: str, model: str, voice: str) -> bytes:
    """OpenAI /v1/audio/speech çağrısı (bloklayıcı; thread'de çalıştırılır). Dönüş: 24 kHz s16le mono PCM."""
    import httpx

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY tanımlı değil")
    res = httpx.post(SPEECH_URL, timeout=60, headers={"Authorization": f"Bearer {key}"},
                     json={"model": model, "voice": voice, "input": text, "response_format": "pcm", "instructions": STYLE})
    if res.status_code >= 400:
        raise RuntimeError(f"OpenAI TTS HTTP {res.status_code}: {res.text[:200]}")
    return res.content


def fake_speech(text: str, model: str, voice: str) -> bytes:
    """Modelsiz testler için deterministik ton (üretimde kullanılmaz)."""
    n = int(SAMPLE_RATE * min(2.0, 0.05 * max(1, len(text.split()))))
    t = np.arange(n) / SAMPLE_RATE
    return (np.sin(2 * np.pi * 220 * t) * 8000).astype("<i2").tobytes()


class FixedAudio:
    def __init__(self, steps=DEFAULT_STEPS, model: str = DEFAULT_MODEL, voice: str = DEFAULT_VOICE,
                 fetch: Callable[[str, str, str], bytes] | None = None, cache_dir: Path | None = None):
        self.steps = set(steps)
        self.model, self.voice = model, voice
        self.fetch = fetch or (fake_speech if os.environ.get("SVA_FAKE_PROVIDERS") == "1" else openai_speech)
        self.cache_dir = cache_dir
        self.stats = {"hits": 0, "misses": 0, "errors": 0}

    @classmethod
    def from_spec(cls, spec: dict | None, **kw) -> "FixedAudio | None":
        """Profil `realtime:` bölümünden; `fixed_audio: false` ile kapatılır."""
        spec = spec or {}
        opt = spec.get("fixed_audio", True)
        if opt is False:
            return None
        opt = opt if isinstance(opt, dict) else {}
        return cls(steps=tuple(opt.get("steps", DEFAULT_STEPS)), model=opt.get("model", DEFAULT_MODEL),
                   voice=opt.get("voice", DEFAULT_VOICE), **kw)

    def applies(self, step_key: str | None) -> bool:
        return step_key is not None and ("*" in self.steps or step_key in self.steps)

    def _dir(self) -> Path:
        return self.cache_dir or stt_runs.data_dir() / "fixed-audio"

    def path_for(self, text: str) -> Path:
        h = hashlib.sha256(f"{self.model}|{self.voice}|{text}".encode("utf-8")).hexdigest()[:24]
        return self._dir() / f"{h}.pcm"

    async def get(self, text: str) -> bytes | None:
        """24 kHz s16le PCM; önbellekte yoksa üretir. Hata -> None (çağıran modele geri düşer)."""
        p = self.path_for(text)
        try:
            if p.exists():
                self.stats["hits"] += 1
                return p.read_bytes()
            self.stats["misses"] += 1
            pcm = await asyncio.to_thread(self.fetch, text, self.model, self.voice)
            if not pcm:
                raise RuntimeError("boş ses")
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(pcm)
            tmp.replace(p)
            return pcm
        except Exception:  # noqa: BLE001
            self.stats["errors"] += 1
            return None

    async def warm(self, texts: list[str]) -> int:
        return sum(1 for t in texts if await self.get(t) is not None)
