"""Konuşma bitişi (endpointing) için enerji tabanlı ses etkinliği tespiti.

PoC kararı: bağımlılıksız, 20 ms'lik çerçevelerde dBFS enerjisi + uyarlanır gürültü tabanı. Telefon/ofis
gürültüsünde Silero VAD gibi öğrenilmiş bir model daha sağlamdır; Faz 1'de değiştirilebilsin diye arayüz
(`feed` -> olaylar) sabit tutuldu.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from .speechlike import PEAK_STRONG, is_voiced

SAMPLE_RATE = 16000
FRAME = 320  # 20 ms
BARGE_FRAMES = 8        # 160 ms kesintisiz yüksek ses: söz kesme (200 ms iken istemci ölçümü ≈380 ms; tarayıcı jitter payı için kısaltıldı)
BARGE_MARGIN_DB = 6.0
MANUAL_RANGE_DB = (-70.0, -10.0)
VOICED_MIN = 3          # core-016: söz kesme için kesintisiz yüksek ses içinde en az bu kadar SESLİ (perdeli) çerçeve gerekir (0 = süzgeç kapalı, eski davranış)
FORCE_FRAMES = 60       # 1,2 sn kesintisiz yüksek ses perdesiz olsa da (fısıltı/çok gürültülü hat) kesilir: süzgeç ajanı sonsuza dek susturamaz


def level_db(frame: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64)))) if len(frame) else 0.0
    return 20 * np.log10(rms) if rms > 1e-9 else -120.0


class Endpointer:
    """Çerçeve besler; ("start", None), ("end", utterance), ("drop", None) olayları üretir."""

    def __init__(self, start_ms=60, end_ms=600, min_ms=160, max_s=15.0, preroll_ms=200,
                 floor_db=-45.0, margin_db=12.0):
        self.start_frames = max(1, start_ms // 20)
        self.end_frames = max(1, end_ms // 20)
        self.min_frames = max(1, min_ms // 20)
        self.max_frames = int(max_s * 50)
        self.preroll = deque(maxlen=max(1, preroll_ms // 20))
        self.floor_db, self.margin_db = floor_db, margin_db
        self.noise_db = -60.0
        self.manual_db: float | None = None   # core-015: ekrandan elle eşik (dBFS); None = uyarlanır eşik (eski davranış)
        self.barge_frames = BARGE_FRAMES      # söz kesme için kesintisiz yüksek ses süresi (20 ms çerçeve)
        self.barge_margin_db = BARGE_MARGIN_DB
        self.voiced_min = VOICED_MIN          # core-016 akıllı söz kesme: konuşma benzeri (perdeli) çerçeve sayısı; 0 = kapalı
        self.force_frames = FORCE_FRAMES
        self.peak_strong = PEAK_STRONG        # güçlü perdede ≥400 Hz üst sınırı uygulanmaz (bağırarak konuşma); 0 = kapalı
        self.level = -120.0
        self.collecting = False
        self._run = 0       # ardışık konuşma çerçevesi (başlangıç doğrulaması)
        self._silence = 0
        self._frames: list[np.ndarray] = []
        self._speech_frames = 0

    def set_end_ms(self, end_ms: int) -> None:
        """Bitiş sessizliği süresi (söz sırası): düğüm türüne göre değişir (açık uçlu cevaplarda uzun)."""
        self.end_frames = max(1, end_ms // 20)

    @property
    def threshold_db(self) -> float:
        if self.manual_db is not None:
            return self.manual_db
        return max(self.floor_db, self.noise_db + self.margin_db)

    @property
    def barge_level_db(self) -> float:
        """Söz kesme seviyesi: eşik + marj. Otomatik modda eski davranış (eşik en az -45 dBFS) korunur; elle eşikte kullanıcının değeri esastır."""
        base = self.threshold_db if self.manual_db is not None else max(self.threshold_db, -45.0)
        return base + self.barge_margin_db

    def configure(self, threshold_db=None, barge_frames=None, barge_margin_db=None, reset_threshold=False, voiced_min=None,
                  peak_strong=None) -> dict:
        """Çalışırken ayar (core-015). Değerler güvenli aralığa kırpılır; ne uygulandıysa döndürülür."""
        lo, hi = MANUAL_RANGE_DB
        if peak_strong is not None:     # 0 = kapalı; aksi hâlde 0,75 (PEAK_MIN) ile 1,0 arası
            ps = float(peak_strong)
            self.peak_strong = 0.0 if ps <= 0 else max(0.75, min(1.0, ps))
        if voiced_min is not None:
            self.voiced_min = max(0, min(20, int(voiced_min)))
        if reset_threshold:
            self.manual_db = None
        elif threshold_db is not None:
            self.manual_db = max(lo, min(hi, float(threshold_db)))
        if barge_frames is not None:
            self.barge_frames = max(1, min(50, int(barge_frames)))
        if barge_margin_db is not None:
            self.barge_margin_db = max(0.0, min(30.0, float(barge_margin_db)))
        return self.settings()

    def settings(self) -> dict:
        return {"threshold_db": None if self.manual_db is None else round(self.manual_db, 1),
                "effective_threshold_db": round(self.threshold_db, 1), "barge_frames": self.barge_frames,
                "barge_margin_db": self.barge_margin_db, "barge_ms": self.barge_frames * 20,
                "voiced_min": self.voiced_min, "force_ms": self.force_frames * 20, "peak_strong": self.peak_strong}

    def is_speech(self, frame: np.ndarray) -> bool:
        self.level = level_db(frame)
        return self.level > self.threshold_db

    def feed(self, frame: np.ndarray) -> list[tuple[str, object]]:
        out: list[tuple[str, object]] = []
        speech = self.is_speech(frame)
        if not self.collecting:
            if not speech:
                self.noise_db = 0.95 * self.noise_db + 0.05 * self.level  # gürültü tabanı yalnızca sessizlikte öğrenilir
            self.preroll.append(frame)
            self._run = self._run + 1 if speech else 0
            if self._run >= self.start_frames:
                self.collecting = True
                self._frames = list(self.preroll)
                self._speech_frames = self._run
                self._silence = 0
                out.append(("start", None))
            return out
        self._frames.append(frame)
        if speech:
            self._speech_frames += 1
            self._silence = 0
        else:
            self._silence += 1
        if self._silence >= self.end_frames or len(self._frames) >= self.max_frames:
            audio = np.concatenate(self._frames) if self._frames else np.zeros(0, np.float32)
            enough = self._speech_frames >= self.min_frames
            self.reset()
            out.append(("end", audio) if enough else ("drop", None))
        return out

    def pending_audio(self) -> np.ndarray:
        """Toplanmakta olan konuşmanın şu ana kadarki sesi (ön kayıt dahil). Akışlı STT (faz 3) "start" anında bunu yollar;
        "end" ile verilen ses = bu + sonraki çerçeveler (aynı örnekler)."""
        return np.concatenate(self._frames) if self._frames else np.zeros(0, np.float32)

    def reset(self) -> None:
        self.collecting = False
        self._run = 0
        self._silence = 0
        self._frames = []
        self._speech_frames = 0
        self.preroll.clear()


class BargeTracker:
    """Söz kesme kararı (core-016): kesintisiz yüksek ses (seviye + süre, core-015) ARTI konuşma benzerliği.
    Seviye eşiğini geçen ama perdesi olmayan patlama (öksürük, boğaz temizleme, klavye, kapı, nefes) ajanı kesmez; kesme
    yalnızca koşuda `voiced_min` kadar sesli çerçeve görülünce olur (ya da koşu `force_frames`'i aşınca). `voiced_min=0` eski davranıştır.
    `update` -> "barge" (kes) | "blocked" (kesmeyecek bir gürültü koşusu bitti; kanıt sayacı) | None. session.py ve realtime.py ortak kullanır."""

    def __init__(self, vad: Endpointer):
        self.vad = vad
        self.reset()

    def reset(self) -> None:
        self.run = 0
        self.voiced = 0
        self.t0 = 0.0
        self.fired = False

    def update(self, frame: np.ndarray, now: float) -> str | None:
        v = self.vad
        loud = v.level > v.barge_level_db
        if not loud:
            blocked = self.run >= v.barge_frames and not self.fired    # eski mantıkla kesecekti, süzgeç engelledi
            self.reset()
            return "blocked" if blocked else None
        if self.run == 0:
            self.t0, self.voiced, self.fired = now, 0, False
        self.run += 1
        if v.voiced_min > 0 and is_voiced(frame, peak_strong=v.peak_strong):
            self.voiced += 1
        if self.fired or self.run < v.barge_frames:
            return None
        if v.voiced_min == 0 or self.voiced >= v.voiced_min or self.run >= v.force_frames:
            self.fired = True
            return "barge"
        return None

