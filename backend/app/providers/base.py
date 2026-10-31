"""Sağlayıcı sözleşmeleri: STT, LLM ve TTS için ortak arayüz ve sonuç tipleri.

Lab ekranları ve ajan yalnızca bu arayüzleri görür; hangi modelin çalıştığı profilden gelir.
Ses her yerde mono float32 numpy dizisi ([-1, 1]) + örnekleme hızı olarak taşınır.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterator

import numpy as np


class ProviderError(Exception):
    """Sağlayıcı çağrısı başarısız oldu (ağ, model, beklenmeyen yanıt)."""


class ProviderNotReady(ProviderError):
    """Sağlayıcı yapılandırması eksik (ör. API anahtarı yok). Kullanıcıya gösterilecek mesaj taşır."""

    def __init__(self, message: str, missing_env: list[str] | None = None):
        super().__init__(message)
        self.missing_env = missing_env or []


@dataclass
class STTResult:
    text: str
    seconds: float
    provider: str
    model: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResult:
    text: str
    seconds: float
    provider: str
    model: str
    output_tokens: int | None = None
    input_tokens: int | None = None      # eval-003: maliyet icin; saglayici vermezse None (sifir yazilmaz)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSResult:
    audio: np.ndarray  # mono float32, [-1, 1]
    sample_rate: int
    seconds: float  # üretim süresi
    provider: str
    model: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def audio_seconds(self) -> float:
        return len(self.audio) / self.sample_rate if self.sample_rate else 0.0

    @property
    def rtf(self) -> float | None:
        return self.seconds / self.audio_seconds if self.audio_seconds else None


class TTSStream:
    """Akışlı TTS çıktısı (A1 gecikme işi, faz 2): mono float32 ([-1, 1]) parçalar üreten yinelenebilir + örnekleme hızı.

    `close()` alttaki HTTP akışını kapatır (söz kesmede kalan gövde okunmaz). Aynı iş parçacığında yinelenip kapatılmalıdır."""

    def __init__(self, chunks: Iterator[np.ndarray], sample_rate: int):
        self._chunks = chunks
        self.sample_rate = sample_rate

    def __iter__(self) -> Iterator[np.ndarray]:
        return iter(self._chunks)

    def close(self) -> None:
        close = getattr(self._chunks, "close", None)
        if close is not None:
            close()


class StreamingSTT:
    """Akışlı STT oturumu (A1 gecikme işi, faz 3): TEK müşteri konuşması için canlı bağlantı.

    Sözleşme (VoiceSession olay döngüsünden çağrılır; `send`/`abort`/`open` BLOKLAMAZ, `finish` iş parçacığında çağrılır):
    - open(): bağlantıyı arka planda açmaya başlar; bağlantı kurulmadan gelen ses sıraya alınır (ön kayıt kaybolmaz).
    - send(pcm16): 16 kHz mono little-endian int16 baytları.
    - finish() -> STTResult: sesin bittiğini bildirir, son transkripti kısa bir zaman aşımıyla bekler; başarısızlıkta ProviderError.
    - abort(): konuşma sayılmadı (gürültü/düştü); bağlantıyı kapatır, sonuç beklenmez.
    - billed_seconds(): faturaya esas bağlantı süresi (sn).
    """

    def open(self) -> None:
        raise NotImplementedError

    def send(self, pcm16: bytes) -> None:
        raise NotImplementedError

    def finish(self) -> STTResult:
        raise NotImplementedError

    def abort(self) -> None:
        raise NotImplementedError

    def billed_seconds(self) -> float:
        return 0.0


class Provider:
    """Tüm sağlayıcıların tabanı. Alt sınıflar `kind`, `component` ve gerekirse `required_env` tanımlar."""

    kind: ClassVar[str]
    component: ClassVar[str]  # "stt" | "llm" | "tts"
    required_env: ClassVar[tuple[str, ...]] = ()

    def __init__(self, model: str | None = None, **options: Any):
        self.model = model or ""
        self.options = options
        self._warm = False

    # --- Ön yükleme (ADR 0001) -------------------------------------------------
    def is_warm(self) -> bool:
        """Model bellekte ve en az bir çıkarım yapılmış mı (ilk çağrı maliyeti ödenmiş mi)."""
        return self._warm

    def mark_warm(self, warm: bool = True) -> None:
        self._warm = warm

    def is_loaded(self) -> bool:
        """Model şu an bellekte mi (yüklü ama henüz ısınmamış olabilir). Boşaltma kararı buna göre verilir."""
        return self._warm

    def warmup_call(self) -> Any:
        """Isınma için küçük ama gerçek bir çıkarım. Bileşen sınıfları tanımlar."""
        raise NotImplementedError

    def unload(self) -> None:
        """Modeli bellekten çıkarır. Alt sınıflar kendi nesnelerini bırakır."""
        self._warm = False

    def describe(self) -> str:
        return f"{self.kind}:{self.model}" if self.model else self.kind

    def readiness_issues(self) -> list[str]:
        """Model yüklemeden, hızlıca bulunabilen sorunlar (ör. Ollama'da model indirilmemiş)."""
        return []


class STTProvider(Provider):
    component = "stt"

    def warmup_call(self):
        # 1,5 sn hafif gürültü: modeli yükler ve kod yollarını ısıtır; çıktı metni önemsiz
        noise = (np.random.default_rng(0).standard_normal(24000) * 0.01).astype(np.float32)
        return self.transcribe(noise, 16000)

    def transcribe(self, audio: np.ndarray, sample_rate: int, language: str = "tr") -> STTResult:
        raise NotImplementedError


class LLMProvider(Provider):
    component = "llm"

    def warmup_call(self):
        return self.complete([{"role": "user", "content": "Tek kelimeyle cevap ver: hazır mısın?"}],
                             max_tokens=8, temperature=0)

    def complete(self, messages: list[dict[str, str]], max_tokens: int = 256,
                 temperature: float = 0.3) -> LLMResult:
        raise NotImplementedError


class TTSProvider(Provider):
    component = "tts"

    def warmup_call(self):
        return self.synthesize("Merhaba, hazırım.")

    def synthesize(self, text: str, language: str = "tr", speed: float = 1.0, tone: str | None = None) -> TTSResult:   # speed: 1.0 = normal; desteklemeyen sağlayıcı yok sayar
        raise NotImplementedError
