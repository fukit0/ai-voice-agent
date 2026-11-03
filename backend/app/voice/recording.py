"""Konuşma ses kaydı (core-013): tek stereo WAV, sol kanal müşteri, sağ kanal ajan.

Neden taşıma katmanında kaydediliyor (oturum sınıflarında değil): ham mikrofon sesi ve tarayıcıya gerçekten gönderilen
ajan çerçeveleri yalnızca orada görünür; böylece VoiceSession ve RealtimeVoiceSession aynı kodla kaydedilir ve söz kesmede
boşaltılan (hiç çalınmayan) ajan sesi kayda girmez.

- Sol kanal: ham mikrofon (telefon filtresi ve VAD öncesi), 16 kHz. STT'ye giden ses filtreliyse oturum JSON'unda
  `phone_filter` işaretlidir; kaydı yeniden çözerek aynı filtreyi uygulayabilirsiniz.
- Sağ kanal: ajan çerçeveleri 48 kHz'den 16 kHz'e indirilir (telefon filtresi açıksa filtreli haliyle).
- İki kanalın başlangıç farkı duvar saatiyle hizalanır.
- Sınır: MAX_SECONDS; aşılırsa kayıt durur ve JSON'da `truncated` işaretlenir (disk/bellek koruması).

Sanal zaman çizelgesi (eval-006, `timeline="virtual"`): kıyas koşusu (evalrun) gerçek zamandan hızlı koştuğu için duvar saati
hizalaması anlamsızdır (ajan sesi anında "çalınmış" sayılır, müşteri klibi bir anda beslenir; kanallar üst üste biner). Bu kipte kayıt
olay sırasıyla bir sanal saat ilerletir: ajan push'ları peş peşe bir "ajan bloğu" oluşturur; müşteri klibi gelince blok kapanır ve
klip, o ana kadarki ajan sesinin bitişinden sonra yerleşir; sonraki ajan bloğu klibin (sondaki sessizlik dahil) bitişinden başlar.
Sonuç sıralıdır: söz kesme/çakışma yoktur, gerçek telefon kaydı gibi dinlenmemelidir. Canlı kip ("wall") hiç değişmedi.
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
    def __init__(self, timeline: str = "wall") -> None:
        if timeline not in ("wall", "virtual"):
            raise ValueError(f"timeline: {timeline}")
        self.timeline = timeline
        self._t0 = time.time()
        # sanal kip: (başlangıç örneği @16 kHz, int16 @16 kHz) parçaları + açık ajan bloğu (48 kHz)
        self._cursor = 0
        self._vuser: list[tuple[int, np.ndarray]] = []
        self._vagent: list[tuple[int, np.ndarray]] = []
        self._block: list[np.ndarray] = []
        self._block_start = 0
        self._user: list[np.ndarray] = []      # int16, 16 kHz
        self._agent: list[np.ndarray] = []     # int16, 48 kHz
        self._user_start: float | None = None
        self._agent_start: float | None = None
        self._user_n = 0
        self._agent_n = 0
        self.truncated = False

    def add_user(self, samples: np.ndarray) -> None:
        """16 kHz mono float32 (ham mikrofon)."""
        if self.timeline == "virtual":
            self._v_user(samples)
            return
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
        if self.timeline == "virtual":
            self._v_agent(pcm16)
            return
        if self._agent_n >= MAX_SECONDS * AGENT_RATE:
            self.truncated = True
            return
        if self._agent_start is None:
            self._agent_start = (start_time if start_time is not None else time.time()) - self._t0
        self._agent.append(pcm16.astype(np.int16, copy=False))
        self._agent_n += len(pcm16)

    # ---------- sanal zaman çizelgesi ----------
    def _cap(self, extra: int) -> bool:
        if self._cursor + extra > MAX_SECONDS * REC_RATE:
            self.truncated = True
            return False
        return True

    def _v_agent(self, pcm16: np.ndarray) -> None:
        pending = sum(len(b) for b in self._block)
        if not self._cap((pending + len(pcm16)) // (AGENT_RATE // REC_RATE)):
            return
        if not self._block:
            self._block_start = self._cursor
        self._block.append(pcm16.astype(np.int16, copy=False))
        self._agent_n += len(pcm16)

    def _close_block(self) -> None:
        """Açık ajan bloğunu 16 kHz'e indirip yerleştirir; saat bloğun sonuna ilerler (blok tek parça indirilir: sınır bozulması yok)."""
        if not self._block:
            return
        a = np.concatenate(self._block).astype(np.float32) / 32768.0
        pcm = (np.clip(resample(a, AGENT_RATE, REC_RATE), -1.0, 1.0) * 32767.0).astype(np.int16)
        self._block = []
        self._vagent.append((self._block_start, pcm))
        self._cursor = max(self._cursor, self._block_start + len(pcm))

    def _v_user(self, samples: np.ndarray) -> None:
        self._close_block()                       # ajan önce susar, müşteri sonra konuşur
        pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
        if not self._cap(len(pcm)):
            return
        self._vuser.append((self._cursor, pcm))
        self._cursor += len(pcm)
        self._user_n += len(pcm)

    def _v_tracks(self) -> tuple[np.ndarray, np.ndarray]:
        self._close_block()
        total = max([o + len(p) for o, p in self._vuser + self._vagent] or [0])
        left, right = np.zeros(total, np.int16), np.zeros(total, np.int16)
        for o, p in self._vuser:
            left[o:o + len(p)] = p
        for o, p in self._vagent:
            right[o:o + len(p)] = p
        return left, right

    def segments(self) -> dict[str, list[tuple[int, int]]]:
        """Sanal kipte kanal başına (başlangıç, bitiş) örnek aralıkları (test ve tanı için)."""
        self._close_block()
        return {"user": [(o, o + len(p)) for o, p in self._vuser], "agent": [(o, o + len(p)) for o, p in self._vagent]}

    def _tracks(self) -> tuple[np.ndarray, np.ndarray]:
        if self.timeline == "virtual":
            return self._v_tracks()
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
        if not self._user and not self._agent and not self._vuser and not self._vagent and not self._block:
            return None
        left, right = self._tracks()
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(REC_RATE)
            w.writeframes(np.column_stack([left, right]).astype("<i2").tobytes())
        layout = ("sol=müşteri (ham mikrofon), sağ=ajan" if self.timeline == "wall"
                  else "sol=müşteri (sentetik persona klibi), sağ=ajan; sıralı sanal zaman çizelgesi")
        return {"file": path.name, "seconds": round(len(left) / REC_RATE, 2), "sample_rate": REC_RATE, "channels": 2,
                "layout": layout, "truncated": self.truncated}
