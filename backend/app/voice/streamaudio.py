"""Akışlı TTS sesi için durum tutan ses işleme (A1 gecikme işi, faz 2).

Akışlı TTS'te cümle sesi parça parça gelir. Durumsuz işlemler (scipy `resample_poly`, telefon filtresi `phone.apply` =
`sosfiltfilt`) her parçaya ayrı uygulanırsa parça sınırlarında kenar etkisi (tık, süreksizlik) oluşur. Bu modül:

- `StreamResampler`: `resample_poly` ile AYNI filtreyi (Kaiser 5.0, half_len = 10*max(up, down)) akışta, durumlu FIR olarak
  uygular. Parçalar halinde verilen sesin çıktısı, tüm dizinin tek seferde `resample_poly` çıktısıyla sayısal olarak aynıdır
  (testte 1e-5 içinde); sonda `flush()` kuyruğu verir.
- `StreamPhoneFilter`: `phone.apply` sıfır fazlıdır (ileri-geri, nedensel değil) ve akışta uygulanamaz. Akışta aynı bant geçiren
  bölümün İKİ KEZ arka arkaya (nedensel, durumlu) uygulanması kullanılır: genlik yanıtı `sosfiltfilt` ile birebir aynıdır
  (|H|^2), yalnız faz farklıdır (konuşma bandında duyulmaz). Bu nedenle telefon filtresi açıkken akışlı ve akışsız çıktı
  örnek örnek aynı DEĞİLDİR; parça sınırlarında süreksizlik yoktur (testte tüm dizi = parçalar).
- `ChunkPipeline`: telefon filtresi (isteğe bağlı) -> yeniden örnekleme -> int16; çok küçük parçaları en az MIN_CHUNK_MS'ye
  biriktirir (gereksiz çok küçük çerçeve itmemek için; doğruluk için gerekli değildir).
"""
from __future__ import annotations

from math import gcd

import numpy as np
from scipy import signal

from . import phone

MIN_CHUNK_MS = 40


def to_int16(audio: np.ndarray) -> np.ndarray:
    """session.to_int16 ile aynı dönüşüm (döngüsel içe aktarmayı önlemek için burada da tanımlı)."""
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


class StreamResampler:
    """`scipy.signal.resample_poly(x, up, down)` ile aynı sonucu parça parça üreten durumlu çokfazlı yeniden örnekleyici.

    resample_poly çıkışı k, yukarı örneklenmiş evrişimin m = k*down + half_len indisidir. Her parçada yalnızca girdisi tamamen
    bilinen (m < n_in*up) çıkışlar üretilir; filtre uzunluğu kadar geçmiş giriş saklanır. Hesap `upfirdn` ile (çokfazlı, verimli).
    """

    def __init__(self, src_rate: int, dst_rate: int):
        g = gcd(src_rate, dst_rate)
        self.up, self.down = dst_rate // g, src_rate // g
        self.passthrough = self.up == self.down
        max_rate = max(self.up, self.down)
        self.half_len = 10 * max_rate
        if self.passthrough:      # aynı hız: audio.resample de dokunmadan döndürür
            self.h = np.ones(1)
        else:
            self.h = signal.firwin(2 * self.half_len + 1, 1.0 / max_rate, window=("kaiser", 5.0)) * self.up
        self.keep = len(self.h) // self.up + 2     # saklanan geçmiş giriş örneği
        self.hist = np.zeros(0)
        self.n_in = 0       # görülen giriş örneği
        self.emitted = 0    # verilen çıkış örneği
        self.done = False

    def _emit(self, xwin: np.ndarray, s0: int, k_end: int) -> np.ndarray:
        """xwin = global giriş [s0, s0+len); çıkışlar [emitted, k_end)."""
        cnt = k_end - self.emitted
        if cnt <= 0:
            return np.zeros(0, np.float32)
        i0 = self.emitted * self.down + self.half_len - s0 * self.up
        if i0 < 0:          # geçmiş yetersiz: olmamalı (keep filtre boyunu kapsar); savunma
            raise RuntimeError("yeniden örnekleyici geçmişi yetersiz")
        d = (-i0) % self.down                  # evrişimi d kadar geciktir: istenen indis down'ın katına düşsün
        y = signal.upfirdn(np.concatenate([np.zeros(d), self.h]), xwin, self.up, self.down)
        j0 = (i0 + d) // self.down
        out = y[j0:j0 + cnt]
        if len(out) != cnt:
            raise RuntimeError("yeniden örnekleyici çıkış uzunluğu beklenmedik")
        self.emitted = k_end
        return out.astype(np.float32)

    def process(self, x: np.ndarray) -> np.ndarray:
        if self.done:
            raise RuntimeError("flush sonrası process çağrıldı")
        x = np.asarray(x, dtype=np.float64)
        if self.passthrough:
            self.n_in += len(x)
            return x.astype(np.float32)
        if len(x) == 0:
            return np.zeros(0, np.float32)
        s0 = self.n_in - len(self.hist)
        xwin = np.concatenate([self.hist, x])
        self.n_in += len(x)
        last_m = self.n_in * self.up - 1                    # girdisi tamamen bilinen son evrişim indisi
        k_end = (last_m - self.half_len) // self.down + 1 if last_m >= self.half_len else 0
        out = self._emit(xwin, s0, k_end)
        self.hist = xwin[-self.keep:]
        return out

    def flush(self) -> np.ndarray:
        """Kuyruk: toplam çıkış `ceil(n_in*up/down)` örneğe tamamlanır (resample_poly ile aynı uzunluk)."""
        if self.done:
            return np.zeros(0, np.float32)
        self.done = True
        if self.passthrough or self.n_in == 0:
            return np.zeros(0, np.float32)
        n_out = -(-self.n_in * self.up // self.down)
        s0 = self.n_in - len(self.hist)
        xwin = np.concatenate([self.hist, np.zeros(self.keep)])   # sondaki sıfırlar (resample_poly de sıfırla doldurur)
        return self._emit(xwin, s0, n_out)


class StreamPhoneFilter:
    """Telefon bant geçiren filtresinin akış sürümü: aynı SOS iki kez arka arkaya (genlik = sosfiltfilt), durumlu."""

    def __init__(self, rate: int):
        sos = phone._sos(rate)
        self.sos = np.vstack([sos, sos])
        self.zi = np.zeros((self.sos.shape[0], 2))

    def process(self, x: np.ndarray) -> np.ndarray:
        if len(x) == 0:
            return np.zeros(0, np.float32)
        y, self.zi = signal.sosfilt(self.sos, np.asarray(x, dtype=np.float64), zi=self.zi)
        return y.astype(np.float32)


class ChunkPipeline:
    """TTS parçası (float32, `rate`) -> çıkış int16 (`out_rate`). `feed` boş dizi dönebilir (biriktirme); sonda `finish`."""

    def __init__(self, rate: int, out_rate: int, phone_filter: bool = False, min_chunk_ms: int = MIN_CHUNK_MS):
        self.rate = rate
        self.filter = StreamPhoneFilter(rate) if phone_filter else None
        self.rs = StreamResampler(rate, out_rate)
        self.min_samples = max(1, rate * min_chunk_ms // 1000)
        self._pending: list[np.ndarray] = []
        self._n = 0

    def _process(self, x: np.ndarray) -> np.ndarray:
        if self.filter is not None:
            x = self.filter.process(x)
        return self.rs.process(x)

    def feed(self, chunk: np.ndarray) -> np.ndarray:
        chunk = np.asarray(chunk, dtype=np.float32)
        if len(chunk) == 0:
            return np.zeros(0, np.int16)
        self._pending.append(chunk)
        self._n += len(chunk)
        if self._n < self.min_samples:
            return np.zeros(0, np.int16)
        x = np.concatenate(self._pending)
        self._pending, self._n = [], 0
        return to_int16(self._process(x))

    def finish(self) -> np.ndarray:
        parts = []
        if self._pending:
            parts.append(self._process(np.concatenate(self._pending)))
            self._pending, self._n = [], 0
        parts.append(self.rs.flush())
        out = np.concatenate(parts) if parts else np.zeros(0, np.float32)
        return to_int16(out)
