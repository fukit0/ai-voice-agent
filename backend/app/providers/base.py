"""Sağlayıcı sözleşmeleri: STT, LLM ve TTS için ortak arayüz ve sonuç tipleri.

Lab ekranları ve ajan yalnızca bu arayüzleri görür; hangi modelin çalıştığı profilden gelir.
Ses her yerde mono float32 numpy dizisi ([-1, 1]) + örnekleme hızı olarak taşınır.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

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


class Provider:
    """Tüm sağlayıcıların tabanı. Alt sınıflar `kind`, `component` ve gerekirse `required_env` tanımlar."""

    kind: ClassVar[str]
    component: ClassVar[str]  # "stt" | "llm" | "tts"
    required_env: ClassVar[tuple[str, ...]] = ()

    def __init__(self, model: str | None = None, **options: Any):
        self.model = model or ""
        self.options = options

    def describe(self) -> str:
        return f"{self.kind}:{self.model}" if self.model else self.kind

    def readiness_issues(self) -> list[str]:
        """Model yüklemeden, hızlıca bulunabilen sorunlar (ör. Ollama'da model indirilmemiş)."""
        return []


class STTProvider(Provider):
    component = "stt"

    def transcribe(self, audio: np.ndarray, sample_rate: int, language: str = "tr") -> STTResult:
        raise NotImplementedError


class LLMProvider(Provider):
    component = "llm"

    def complete(self, messages: list[dict[str, str]], max_tokens: int = 256,
                 temperature: float = 0.3) -> LLMResult:
        raise NotImplementedError


class TTSProvider(Provider):
    component = "tts"

    def synthesize(self, text: str, language: str = "tr") -> TTSResult:
        raise NotImplementedError
