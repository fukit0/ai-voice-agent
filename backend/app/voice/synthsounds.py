"""Sentetik ses işaretleri (core-016): söz kesme süzgecini test etmek ve `scripts/eval_barge_gate.py` taban çizgisi için.

Bunlar GERÇEK kayıt değildir. Konuşma benzeri işaret ünlü formantlarıyla zenginleştirilmiş perdeli (80-400 Hz) bir dizidir (enerji temel + birinci formantta toplanır; gerçek kayıtlarda ≥400 Hz payı ≈0,08-0,26); öksürük, klavye, kapı ve
nefes süzülmüş gürültü/dürtüdür. Gerçek öksürük kısmen sesli olabilir; bu yüzden sentetik sonuç gerçek doğrulamanın yerine geçmez.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, lfilter

SR = 16000


def _scale(x: np.ndarray, rms: float) -> np.ndarray:
    return (x / max(1e-12, float(np.sqrt(np.mean(np.square(x))))) * rms).astype(np.float32)


def voiced(seconds: float, rms: float = 0.1, f0: float = 140.0) -> np.ndarray:
    """Konuşma benzeri: titreşimli temel frekans + ünlü formantları (baskın 250 Hz, zayıf 1500/2500 Hz) + hafif 4 Hz hece genliği (±1,5 dB; seviye koşusunu bölmesin)."""
    n = int(SR * seconds)
    t = np.arange(n) / SR
    phase = 2 * np.pi * np.cumsum(f0 * (1 + 0.03 * np.sin(2 * np.pi * 5 * t))) / SR
    env = lambda f: np.exp(-((f - 250) / 130) ** 2) + 0.03 * np.exp(-((f - 1500) / 500) ** 2) + 0.015 * np.exp(-((f - 2500) / 600) ** 2) + 0.002  # noqa: E731
    x = sum(np.sin(k * phase) * env(k * f0) for k in range(1, int(3500 / f0))) * (0.85 + 0.15 * np.sin(2 * np.pi * 4 * t))
    return _scale(x, rms)


def cough(seconds: float = 0.3, rms: float = 0.1, seed: int = 3) -> np.ndarray:
    n = int(SR * seconds)
    t = np.arange(n) / SR
    b, a = butter(2, [300 / 8000, 4000 / 8000], "band")
    x = lfilter(b, a, np.random.default_rng(seed).standard_normal(n) * np.exp(-t * 8) * (1 + 0.5 * np.sin(2 * np.pi * 20 * t)))
    return _scale(x, rms)


def throat_clear(seconds: float = 0.5, rms: float = 0.1, seed: int = 4) -> np.ndarray:
    """İki kısa gürültü patlaması art arda."""
    return np.concatenate([cough(seconds * 0.4, rms, seed), np.zeros(int(SR * seconds * 0.2), np.float32), cough(seconds * 0.4, rms, seed + 1)])


def keyboard(seconds: float = 0.4, rms: float = 0.1, seed: int = 5) -> np.ndarray:
    n = int(SR * seconds)
    x = np.zeros(n)
    rng = np.random.default_rng(seed)
    for p in range(0, n, int(SR * 0.08)):
        m = min(40, n - p)
        x[p:p + m] = rng.standard_normal(m) * np.exp(-np.arange(m) / 8)
    return _scale(x, rms)


def door(seconds: float = 0.4, rms: float = 0.1, seed: int = 6) -> np.ndarray:
    n = int(SR * seconds)
    t = np.arange(n) / SR
    b, a = butter(2, 200 / 8000)
    return _scale(lfilter(b, a, np.random.default_rng(seed).standard_normal(n)) * np.exp(-t * 6), rms)


def breath(seconds: float = 0.5, rms: float = 0.1, seed: int = 7) -> np.ndarray:
    n = int(SR * seconds)
    b, a = butter(2, [500 / 8000, 3000 / 8000], "band")
    return _scale(lfilter(b, a, np.random.default_rng(seed).standard_normal(n)), rms)


NON_SPEECH = {"cough": cough, "throat_clear": throat_clear, "keyboard": keyboard, "door": door, "breath": breath}
