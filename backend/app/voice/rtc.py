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

from .recording import StereoRecorder
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
        self.tap = None   # core-013: kayıt açıksa tarayıcıya giden her çerçeve (sessizlik dahil) buraya da verilir
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
        if self.tap is not None:
            self.tap(samples, self._start + self._timestamp / OUT_RATE)
        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = OUT_RATE
        frame.pts = self._timestamp
        frame.time_base = Fraction(1, OUT_RATE)
        return frame


class RtcVoiceConnection:
    def __init__(self, profile_id: str, stt, llm, tts, flow=None, phone_filter: bool = False, realtime_backend=None,
                 record: bool = False):
        self.sid = uuid.uuid4().hex[:12]
        self.recorder = StereoRecorder() if record else None   # core-013: varsayılan kapalı (gizlilik)
        self.pc = RTCPeerConnection()
        self.track = AgentAudioTrack()
        self.channel = None
        self._pending_events: list[dict] = []
        if realtime_backend is not None:   # tek modelli realtime profil (core-011): STT/LLM/TTS yok
            from .realtime import RealtimeVoiceSession
            self.session = RealtimeVoiceSession(self.sid, profile_id, realtime_backend, self.track, self._send, flow,
                                                phone_filter=phone_filter)
        else:
            self.session = VoiceSession(self.sid, profile_id, stt, llm, tts, self.track, self._send, flow=flow,
                                        phone_filter=phone_filter)
        self._reader: asyncio.Task | None = None
        self.closed = False
        self.pc.addTrack(self.track)
        if self.recorder is not None:
            rec = self.recorder
            self.track.tap = lambda samples, t: rec.add_agent(samples, t)

        @self.pc.on("datachannel")
        def on_channel(channel):
            self.channel = channel

            @channel.on("message")
            def on_message(message):  # tarayıcıdan komutlar: {"type": "phone_filter", "on": true}
                try:
                    cmd = json.loads(message)
                except (TypeError, ValueError):
                    return
                if isinstance(cmd, dict) and cmd.get("type") == "phone_filter":
                    self.session.set_phone_filter(bool(cmd.get("on")))

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
                    if self.recorder is not None:
                        self.recorder.add_user(pcm)   # ham mikrofon: filtre/VAD öncesi
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
        json_path = await self.session.close()
        self._save_recording(json_path)
        if self._reader:
            self._reader.cancel()
        self.track.stop()
        await self.pc.close()

    def _save_recording(self, json_path) -> None:
        """Kapanışta WAV'ı oturum JSON'unun yanına yazar ve JSON'a `audio` alanını ekler. Hata oturumu bozmaz."""
        if self.recorder is None or json_path is None:
            return
        try:
            meta = self.recorder.save(json_path.with_suffix(".wav"))
            doc = json.loads(json_path.read_text(encoding="utf-8"))
            doc["audio"] = meta        # kayıt istenmişti ama ses gelmediyse None
            json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001  (kayıt yardımcı özelliktir; oturum kapanışını engellemez)
            pass

    def info(self) -> dict:
        return {"id": self.sid, "recording": self.recorder is not None, "profile": self.session.profile_id, "state": self.session.state,
                "connection": self.pc.connectionState, "stats": self.session.stats,
                "queued_agent_seconds": round(self.track.queued_seconds, 2), "turns": len(self.session.turns)}
