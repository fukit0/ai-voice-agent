"""Konuşma benzerliği (core-016): söz kesmede öksürük/nefes/klavye/kapı gibi konuşma OLMAYAN sesleri ayırmak için hafif, bağımlılıksız özellikler.

Yöntem: 20 ms'lik (320 örnek, 16 kHz) çerçevede *ses perdesi periyodikliği*. Sesli ünlüler ve ünsüzler (a, e, m, n, l, r...) 80-400 Hz aralığında
belirgin bir temel periyoda sahiptir; öksürük, nefes, klavye tıkı, kapı gürültüsü gürültü benzeri ya da dürtüdür ve periyodik değildir.
Üç özellik: (1) normalleştirilmiş özilinti tepe değeri (80-400 Hz gecikme aralığında), (2) sıfır geçiş oranı (çok yüksek = gürültü/frikatif, çok düşük = gümbürtü),
(3) enerjinin 400 Hz üstündeki payı (düşük frekanslı kapı/masa gümbürtüsü periyodik görünse de konuşma değildir).

SINIRLAR (demoda saklanmaz): sessiz konuşma (fısıltı) ve frikatif başlangıçlar ('ş', 's') sesli sayılmaz; kesme bir sonraki sesli çerçeveye kadar bekler.
Sesli, sürekli 'hmm' bu yöntemle konuşmadan ayrılamaz (perdesi vardır); onun için kısa STT doğrulaması gerekir (yapılmadı).
Eşikler sentetik işaretlerle ayarlandı; gerçek kayıtlarla (core-013) `scripts/eval_barge_gate.py` ile doğrulanmalıdır.
"""
from __future__ import annotations

import numpy as np

SAMPLE_RATE = 16000
LAG_MIN = SAMPLE_RATE // 400      # 400 Hz
LAG_MAX = SAMPLE_RATE // 80       # 80 Hz
PEAK_MIN = 0.60                   # normalleştirilmiş özilinti tepe eşiği (gerçek sesli konuşma ≈0,7-0,95; düşük frekanslı gürültü bunu seyrek aşar)
ZCR_MIN = 0.02                    # çerçeve başına sıfır geçiş oranı alt sınırı: <200 Hz'lik gümbürtü/kapı çarpması (≈0,01) konuşma değildir
ZCR_MAX = 0.30                    # üst sınır: yüksek = gürültü/frikatif
HF_MIN = 0.15                     # enerjinin ≥400 Hz payı: gümbürtü/kapı çarpması (<200 Hz) ≈0, konuşma (formantlar) belirgin


def features(frame: np.ndarray) -> tuple[float, float, float]:
    """(periyodiklik tepe değeri 0-1, sıfır geçiş oranı 0-1, ≥400 Hz enerji payı 0-1). Sessiz/boş çerçevede (0, 0, 0)."""
    x = np.asarray(frame, dtype=np.float64)
    if len(x) <= LAG_MAX + 8:
        return 0.0, 0.0, 0.0
    x = x - x.mean()
    if float(np.dot(x, x)) < 1e-12:
        return 0.0, 0.0, 0.0
    zcr = float(np.mean(np.abs(np.diff(np.signbit(x).astype(np.int8)))))
    n = len(x)
    # özilinti: FFT ile (uzun gecikme için örtüşme payı normalleştirilir)
    size = 1 << (2 * n - 1).bit_length()
    spec = np.fft.rfft(x, size)
    ac = np.fft.irfft(spec * np.conj(spec), size)[: LAG_MAX + 1]
    cum = np.concatenate([[0.0], np.cumsum(x * x)])
    lags = np.arange(LAG_MIN, LAG_MAX + 1)
    denom = np.sqrt(cum[n - lags] * (cum[n] - cum[lags]))
    ok = denom > 1e-12
    best = float(np.max(ac[lags][ok] / denom[ok])) if ok.any() else 0.0
    power = np.abs(np.fft.rfft(x)) ** 2
    hf = float(power[int(400 * len(x) / SAMPLE_RATE):].sum() / max(1e-12, power.sum()))
    return min(1.0, max(0.0, best)), zcr, hf


def is_voiced(frame: np.ndarray, peak_min: float = PEAK_MIN, zcr_min: float = ZCR_MIN, zcr_max: float = ZCR_MAX, hf_min: float = HF_MIN) -> bool:
    peak, zcr, hf = features(frame)
    return peak >= peak_min and zcr_min <= zcr <= zcr_max and hf >= hf_min
