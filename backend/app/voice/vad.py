"""Konuşma bitişi (endpointing) için enerji tabanlı ses etkinliği tespiti.

PoC kararı: bağımlılıksız, 20 ms'lik çerçevelerde dBFS enerjisi + uyarlanır gürültü tabanı. Telefon/ofis
gürültüsünde Silero VAD gibi öğrenilmiş bir model daha sağlamdır; Faz 1'de değiştirilebilsin diye arayüz
(`feed` -> olaylar) sabit tutuldu.
"""
from __future__ import annotations

from collections import deque

import numpy as np

SAMPLE_RATE = 16000
FRAME = 320  # 20 ms


def level_db(frame: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64)))) if len(frame) else 0.0
    return 20 * np.log10(rms) if rms > 1e-9 else -120.0


class Endpointer:
    """Çerçeve besler; ("start", None), ("end", utterance), ("drop", None) olayları üretir."""

    def __init__(self, start_ms=60, end_ms=600, min_ms=300, max_s=15.0, preroll_ms=200,
                 floor_db=-45.0, margin_db=12.0):
        self.start_frames = max(1, start_ms // 20)
        self.end_frames = max(1, end_ms // 20)
        self.min_frames = max(1, min_ms // 20)
        self.max_frames = int(max_s * 50)
        self.preroll = deque(maxlen=max(1, preroll_ms // 20))
        self.floor_db, self.margin_db = floor_db, margin_db
        self.noise_db = -60.0
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
        return max(self.floor_db, self.noise_db + self.margin_db)

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

    def reset(self) -> None:
        self.collecting = False
        self._run = 0
        self._silence = 0
        self._frames = []
        self._speech_frames = 0
        self.preroll.clear()
