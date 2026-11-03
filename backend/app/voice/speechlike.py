"""Konuşma benzerliği (core-016): söz kesmede öksürük/nefes/klavye/kapı gibi konuşma OLMAYAN sesleri ayırmak için hafif, bağımlılıksız özellikler.

Yöntem: 20 ms'lik (320 örnek, 16 kHz) çerçevede *ses perdesi periyodikliği*. Sesli ünlüler ve ünsüzler (a, e, m, n, l, r...) 80-400 Hz aralığında
belirgin bir temel periyoda sahiptir; öksürük, nefes, klavye tıkı, kapı gürültüsü gürültü benzeri ya da dürtüdür ve periyodik değildir.
Üç özellik: (1) normalleştirilmiş özilinti tepe değeri (80-400 Hz gecikme aralığında), (2) sıfır geçiş oranı (çok yüksek = gürültü/frikatif, çok düşük = gümbürtü),
(3) enerjinin 400 Hz üstündeki payı: GERÇEK kayıtlarda konuşma çerçevelerinde bu pay düşüktür (≈0,08-0,26, enerji temel+ilk formantta), öksürük/boğaz temizleme
gibi kısmen perdeli patlamalarda yüksektir; bu yüzden ALT değil ÜST sınır olarak kullanılır (ilk sürüm alt sınırdı ve gerçek konuşmayı eliyordu).

SINIRLAR (demoda saklanmaz): sessiz konuşma (fısıltı) ve frikatif başlangıçlar ('ş', 's') sesli sayılmaz; kesme bir sonraki sesli çerçeveye kadar bekler.
Sesli, sürekli 'hmm' bu yöntemle konuşmadan ayrılamaz (perdesi vardır); onun için kısa STT doğrulaması gerekir (yapılmadı).
Eşikler ilk sentetik işaretlerle ayarlandı, SONRA gerçek kayıtlarla (33 dosya, tek konuşmacı/mikrofon, sınıf başına n=5, evidence/core-016-gercek-*.json) yeniden ayarlandı: aşırı uydurma riski vardır;
yeni konuşmacı/mikrofonla `scripts/eval_barge_gate.py --dir` yeniden koşulmalıdır. Boğaz temizleme ve 'hmm' bu özelliklerle konuşmadan ayrılamadı (ADR 0011).
"""
from __future__ import annotations

import numpy as np

SAMPLE_RATE = 16000
LAG_MIN = SAMPLE_RATE // 400      # 400 Hz
LAG_MAX = SAMPLE_RATE // 80       # 80 Hz
PEAK_MIN = 0.75                   # normalleştirilmiş özilinti tepe eşiği (gerçek kayıtlarda 0,60'ta öksürük çerçeveleri geçiyordu: 0,58-0,68)
ZCR_MIN = 0.02                    # çerçeve başına sıfır geçiş oranı alt sınırı: <200 Hz'lik gümbürtü/kapı çarpması (≈0,01) konuşma değildir
ZCR_MAX = 0.30                    # üst sınır: yüksek = gürültü/frikatif
HF_MAX = 0.30                     # enerjinin ≥400 Hz payı ÜST sınırı: gerçek konuşma ≈0,08-0,26; yüksek pay = öksürük/boğaz temizleme
# Güçlü perde: periyodiklik bu değerin üstündeyse HF_MAX uygulanmaz (zcr sınırları geçerli). Neden (2026-11-03, oturum a75c42b14e09 ve
# 981040abd23b, docs/soz-kesme-analizi-a75c42b14e09-981040abd23b.md): yüksek sesle/bağırarak konuşmada açık ünlülerin F1'i 600-800 Hz'e çıkar,
# enerjinin ≥400 Hz payı 0,5-0,9 olur; perde 0,93-1,00 olduğu hâlde çerçeveler 'sesli değil' sayıldı ve söz kesme ~2-8 sn gecikti/hiç olmadı.
# Gerçek 33 kayıtta öksürük çerçevelerinin perdesi 0,58-0,68 (ADR 0011); 0,90 ile yanlış kesme artmadı, 0,85 bir öksürük ekledi. 0 = kapalı (eski davranış).
PEAK_STRONG = 0.90


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


def is_voiced(frame: np.ndarray, peak_min: float = PEAK_MIN, zcr_min: float = ZCR_MIN, zcr_max: float = ZCR_MAX, hf_max: float = HF_MAX,
              peak_strong: float = PEAK_STRONG) -> bool:
    peak, zcr, hf = features(frame)
    if not zcr_min <= zcr <= zcr_max:
        return False
    if peak_strong and peak >= peak_strong:     # çok belirgin perde: yüksek sesli konuşma (≥400 Hz payı yüksek) da sesli sayılır
        return True
    return peak >= peak_min and hf <= hf_max
