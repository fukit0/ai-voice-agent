"""Ses yardımcıları: örnekleme hızı dönüşümü ve WAV kodlama."""
from __future__ import annotations

import io
from math import gcd

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


def to_mono_float32(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio


def resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return audio.astype(np.float32, copy=False)
    g = gcd(src_rate, dst_rate)
    return resample_poly(audio, dst_rate // g, src_rate // g).astype(np.float32)


def decode_audio(data: bytes, channel: str = "mix") -> tuple[np.ndarray, int]:
    """WAV/FLAC/OGG baytlarını mono float32'ye çevirir.

    channel: "mix" (kanalların ortalaması), "left" ya da "right". Ses kaydı (core-013) stereodur: sol müşteri, sağ ajan;
    STT karşılaştırması için "left" seçilmezse iki ses karışır. Tek kanallı dosyada seçim yok sayılır."""
    audio, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    if channel in ("left", "right") and audio.shape[1] >= 2:
        return np.ascontiguousarray(audio[:, 0 if channel == "left" else 1]), int(rate)
    return to_mono_float32(audio), int(rate)


def decode_stereo(data: bytes) -> tuple[np.ndarray, np.ndarray, int]:
    """Stereo kaydı (sol = müşteri, sağ = ajan) iki ayrı mono diziye böler. Tek kanallı dosyada ValueError."""
    audio, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    if audio.shape[1] < 2:
        raise ValueError("ses tek kanallı; müşteri ve ajan ayrılamaz (stereo kayıt gerekir)")
    return np.ascontiguousarray(audio[:, 0]), np.ascontiguousarray(audio[:, 1]), int(rate)


def rms_dbfs(audio: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
    return -120.0 if rms <= 1e-6 else 20.0 * float(np.log10(rms))


def encode_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, np.clip(audio, -1.0, 1.0), sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()
