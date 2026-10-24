"""Telefon hattı filtresi (lab-003): dar bant (≈300–3400 Hz) ses; müşterinin telefondan duyacağı/göndereceği ses kalitesini taklit eder.

Hem müşteri sesine (STT telefon kalitesinde sınanır) hem ajan sesine (müşterinin duyacağı) uygulanabilir.
Bu bir yaklaşıktır: codec (G.711/AMR) sıkıştırma ve paket kaybı yoktur, yalnızca bant sınırlama ve 8 kHz örnekleme.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

LOW_HZ, HIGH_HZ = 300.0, 3400.0


def _sos(rate: int) -> np.ndarray:
    return signal.butter(4, [LOW_HZ, min(HIGH_HZ, rate / 2 - 100)], btype="bandpass", fs=rate, output="sos")


class PhoneFilter:
    """Akış için durum tutan filtre (16 kHz müşteri sesi parçaları)."""

    def __init__(self, rate: int = 16000):
        self.rate = rate
        self.sos = _sos(rate)
        self.reset()

    def reset(self) -> None:
        self.zi = np.zeros((self.sos.shape[0], 2))

    def process(self, chunk: np.ndarray) -> np.ndarray:
        out, self.zi = signal.sosfilt(self.sos, chunk.astype(np.float64), zi=self.zi)
        return out.astype(np.float32)


def apply(audio: np.ndarray, rate: int) -> np.ndarray:
    """Tek parça (ör. TTS cümlesi) için durumsuz uygulama."""
    if len(audio) == 0:
        return audio
    out = signal.sosfiltfilt(_sos(rate), audio.astype(np.float64))
    return out.astype(np.float32)
