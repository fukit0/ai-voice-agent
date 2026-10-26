"""Konuşma ses kaydı (core-013): tek stereo WAV, sol kanal müşteri, sağ kanal ajan.

Neden taşıma katmanında kaydediliyor (oturum sınıflarında değil): ham mikrofon sesi ve tarayıcıya gerçekten gönderilen
ajan çerçeveleri yalnızca orada görünür; böylece VoiceSession ve RealtimeVoiceSession aynı kodla kaydedilir ve söz kesmede
boşaltılan (hiç çalınmayan) ajan sesi kayda girmez.

- Sol kanal: ham mikrofon (telefon filtresi ve VAD öncesi), 16 kHz. STT'ye giden ses filtreliyse oturum JSON'unda
  `phone_filter` işaretlidir; kaydı yeniden çözerek aynı filtreyi uygulayabilirsiniz.
- Sağ kanal: ajan çerçeveleri 48 kHz'den 16 kHz'e indirilir (telefon filtresi açıksa filtreli haliyle).
- İki kanalın başlangıç farkı duvar saatiyle hizalanır.
- Sınır: MAX_SECONDS; aşılırsa kayıt durur ve JSON'da `truncated` işaretlenir (disk/bellek koruması).
"""
from __future__ import annotations

import time
import wave
from pathlib import Path

import numpy as np

from ..providers.audio import resample

REC_RATE = 16000
AGENT_RATE = 48000
MAX_SECONDS = 1800   # 30 dk


class StereoRecorder:
    def __init__(self) -> None:
        self._t0 = time.time()
        self._user: list[np.ndarray] = []      # int16, 16 kHz
        self._agent: list[np.ndarray] = []     # int16, 48 kHz
        self._user_start: float | None = None
        self._agent_start: float | None = None
        self._user_n = 0
        self._agent_n = 0
        self.truncated = False

    def add_user(self, samples: np.ndarray) -> None:
        """16 kHz mono float32 (ham mikrofon)."""
        if self._user_n >= MAX_SECONDS * REC_RATE:
            self.truncated = True
            return
        if self._user_start is None:
            self._user_start = time.time() - self._t0
        pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
        self._user.append(pcm)
        self._user_n += len(pcm)

    def add_agent(self, pcm16: np.ndarray, start_time: float | None = None) -> None:
        """48 kHz mono int16: AgentAudioTrack'in tarayıcıya gönderdiği çerçeve (sessizlik dahil)."""
        if self._agent_n >= MAX_SECONDS * AGENT_RATE:
            self.truncated = True
            return
        if self._agent_start is None:
            self._agent_start = (start_time if start_time is not None else time.time()) - self._t0
        self._agent.append(pcm16.astype(np.int16, copy=False))
        self._agent_n += len(pcm16)

    def _tracks(self) -> tuple[np.ndarray, np.ndarray]:
        user = np.concatenate(self._user) if self._user else np.zeros(0, np.int16)
        if self._agent:
            a = np.concatenate(self._agent).astype(np.float32) / 32768.0
            agent = (np.clip(resample(a, AGENT_RATE, REC_RATE), -1.0, 1.0) * 32767.0).astype(np.int16)
        else:
            agent = np.zeros(0, np.int16)
        u_off = int(round((self._user_start or 0.0) * REC_RATE))
        a_off = int(round((self._agent_start or 0.0) * REC_RATE))
        total = max(u_off + len(user), a_off + len(agent))
        left, right = np.zeros(total, np.int16), np.zeros(total, np.int16)
        left[u_off:u_off + len(user)] = user
        right[a_off:a_off + len(agent)] = agent
        return left, right

    def save(self, path: Path) -> dict | None:
        """Stereo 16-bit WAV yazar; hiç ses yoksa dosya oluşturmaz (None)."""
        if not self._user and not self._agent:
            return None
        left, right = self._tracks()
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(REC_RATE)
            w.writeframes(np.column_stack([left, right]).astype("<i2").tobytes())
        return {"file": path.name, "seconds": round(len(left) / REC_RATE, 2), "sample_rate": REC_RATE, "channels": 2,
                "layout": "sol=müşteri (ham mikrofon), sağ=ajan", "truncated": self.truncated}
