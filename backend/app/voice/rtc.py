"""WebRTC taşıma katmanı (aiortc): tarayıcı mikrofonu -> VoiceSession, ajan sesi -> tarayıcı.

Yerel (localhost) kullanım: STUN/TURN yok, ICE yalnızca ana bilgisayar adayları. Opus kodlama/çözme aiortc'tadır.
Olaylar (durum, transkript, gecikme) tarayıcının açtığı "events" veri kanalıyla JSON olarak gider.
"""
from __future__ import annotations

import asyncio
import collections
import json
import time
import uuid
from fractions import Fraction

import av
import numpy as np
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError

from .session import OUT_RATE, VoiceSession
from .vad import SAMPLE_RATE

FRAME_MS = 20
OUT_FRAME = OUT_RATE * FRAME_MS // 1000  # 960


class AgentAudioTrack(MediaStreamTrack):
    """Ajanın sesini 20 ms'lik Opus çerçeveleriyle gerçek zamanlı yayınlar; kuyruk boşken sessizlik üretir."""

    kind = "audio"

    def __init__(self):
        super().__init__()
        self._queue: collections.deque[np.ndarray] = collections.deque()
        self._pending = np.zeros(0, np.int16)
        self._timestamp = 0
        self._start: float | None = None
        self._had_audio = False
        self._ended = False
        self._on_drained = lambda: None
        self._loop = asyncio.get_event_loop()

    def set_on_drained(self, cb) -> None:
        self._on_drained = cb

    def push(self, pcm16: np.ndarray) -> None:
        self._queue.append(pcm16)
        self._had_audio = True
        self._ended = False

    def mark_end(self) -> None:
        self._ended = True

    def flush(self) -> None:
        self._queue.clear()
        self._pending = np.zeros(0, np.int16)
        self._had_audio = False

    @property
    def queued_seconds(self) -> float:
        return (sum(len(c) for c in self._queue) + len(self._pending)) / OUT_RATE

    async def recv(self) -> av.AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError
        if self._start is None:
            self._start = time.time()
        else:
            self._timestamp += OUT_FRAME
            wait = self._start + self._timestamp / OUT_RATE - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
        while len(self._pending) < OUT_FRAME and self._queue:
            self._pending = np.concatenate([self._pending, self._queue.popleft()])
        if len(self._pending) >= OUT_FRAME:
            samples, self._pending = self._pending[:OUT_FRAME], self._pending[OUT_FRAME:]
        elif len(self._pending) > 0:  # son kısmi çerçeveyi sessizlikle tamamla
            samples = np.concatenate([self._pending, np.zeros(OUT_FRAME - len(self._pending), np.int16)])
            self._pending = np.zeros(0, np.int16)
        else:
            samples = np.zeros(OUT_FRAME, np.int16)
        if self._had_audio and not self._queue and len(self._pending) == 0 and self._ended:
            self._had_audio = False
            self._loop.call_soon(self._on_drained)
        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = OUT_RATE
        frame.pts = self._timestamp
        frame.time_base = Fraction(1, OUT_RATE)
        return frame


class RtcVoiceConnection:
    def __init__(self, profile_id: str, stt, llm, tts):
        self.sid = uuid.uuid4().hex[:12]
        self.pc = RTCPeerConnection()
        self.track = AgentAudioTrack()
        self.channel = None
        self._pending_events: list[dict] = []
        self.session = VoiceSession(self.sid, profile_id, stt, llm, tts, self.track, self._send)
        self._reader: asyncio.Task | None = None
        self.closed = False
        self.pc.addTrack(self.track)

        @self.pc.on("datachannel")
        def on_channel(channel):
            self.channel = channel
            for event in self._pending_events:
                channel.send(json.dumps(event, ensure_ascii=False))
            self._pending_events.clear()

        @self.pc.on("track")
        def on_track(track):
            if track.kind == "audio" and self._reader is None:
                self._reader = asyncio.ensure_future(self._read(track))

        @self.pc.on("connectionstatechange")
        async def on_state():
            if self.pc.connectionState in ("failed", "closed", "disconnected"):
                await self.close()

    def _send(self, event: dict) -> None:
        if self.channel is not None and self.channel.readyState == "open":
            self.channel.send(json.dumps(event, ensure_ascii=False))
        else:
            self._pending_events.append(event)

    async def _read(self, track) -> None:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        started = False
        try:
            while True:
                frame = await track.recv()
                if not started:  # ilk ses geldiğinde ajanı başlat (selamlama)
                    started = True
                    await self.session.start()
                for out in resampler.resample(frame):
                    pcm = out.to_ndarray().reshape(-1).astype(np.float32) / 32768.0
                    self.session.feed(pcm)
        except MediaStreamError:
            pass
        except Exception as exc:  # noqa: BLE001
            self._send({"type": "error", "message": f"ses okuma hatası: {exc}"})

    async def accept(self, sdp: str, kind: str) -> RTCSessionDescription:
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=kind))
        await self.pc.setLocalDescription(await self.pc.createAnswer())
        return self.pc.localDescription

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        await self.session.close()
        if self._reader:
            self._reader.cancel()
        self.track.stop()
        await self.pc.close()

    def info(self) -> dict:
        return {"id": self.sid, "profile": self.session.profile_id, "state": self.session.state,
                "connection": self.pc.connectionState, "stats": self.session.stats,
                "queued_agent_seconds": round(self.track.queued_seconds, 2), "turns": len(self.session.turns)}
