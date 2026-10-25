"""core-002: söz sırası (Smart Turn, PoC sürümü) ve söz kesme (barge-in) süresi.

Doğrulama maddeleri: (1) ajan konuşurken kullanıcı konuşmaya başlar, ajan sesi 500 ms içinde kesilir;
(2) kısa duraksamalarda ajan söz almaz. (1) gerçek aiortc istemcisiyle istemci tarafında ölçülür.
"""
import asyncio
import json
import time

import numpy as np
import pytest
from aiortc import RTCPeerConnection, RTCSessionDescription
from fastapi.testclient import TestClient

from backend.app import scenario as S
from backend.app.main import app
from backend.app.providers.base import STTProvider, STTResult
from backend.app.providers.fake import FakeLLM
from backend.app.voice import session as session_mod
from backend.app.voice.flow import FlowDriver
from backend.app.voice.session import looks_incomplete
from backend.tests.test_voice import (  # noqa: F401 — fixture'lar ve yardımcılar
    MicTrack, env, frames, make_session, settle, silence, speech, warm,
)


class ScriptSTT(STTProvider):
    """Her çağrıda sıradaki metni döndürür ve gelen ses uzunluğunu kaydeder."""
    kind = "script_stt"

    def __init__(self, texts):
        super().__init__("m")
        self.texts, self.seen = list(texts), []

    def transcribe(self, audio, sample_rate, language="tr"):
        self.seen.append(len(audio) / sample_rate)
        return STTResult(self.texts.pop(0), 0.01, self.kind, self.model, {})


@pytest.mark.parametrize("text,expected", [
    ("evet ama", True), ("bence çünkü", True), ("şey", True), ("yani,", True), ("ee...", True), ("hmm", True),
    ("hem de", False), ("evet", False), ("dokuz veririm", False), ("hayır istemiyorum.", False), ("", False),
    ("yarın saat on beşte uygun olur", False), ("ya da", True), ("bir de", True),
])
def test_looks_incomplete(text, expected):
    assert looks_incomplete(text) is expected


def test_short_pause_inside_speech_does_not_end_turn_but_long_pause_does(tmp_path, monkeypatch):
    async def run(gap):
        s, out, events = make_session(tmp_path, monkeypatch, stt=ScriptSTT(["bir", "iki", "üç"]))
        s.state = "listening"
        audio = np.concatenate([silence(0.3), speech(1.0), silence(gap), speech(1.0), silence(1.0)])
        s.feed(audio)
        await settle(s)
        return s.stats["utterances"], s.stt.seen

    one, seen = asyncio.run(run(0.4))        # 400 ms duraksama < 600 ms: tek tur
    assert one == 1 and seen[0] > 2.2
    two, _ = asyncio.run(run(0.9))           # 900 ms: iki ayrı tur
    assert two == 2


def test_incomplete_sentence_is_held_then_merged_with_continuation(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "HOLD_S", 1.0)

    async def main():
        stt = ScriptSTT(["evet ama", "evet ama hepsi iyiydi"])
        s, out, events = make_session(tmp_path, monkeypatch, stt=stt)
        s.state = "listening"
        s.feed(np.concatenate([silence(0.3), speech(1.0), silence(0.8)]))
        await settle(s)
        assert {"type": "hold", "on": True, "text": "evet ama"} in events
        assert not out.pushed and s.stats["holds"] == 1            # ajan söz almadı
        assert not [e for e in events if e["type"] == "transcript"]  # yarım cümle transkripte girmedi
        s.feed(np.concatenate([speech(0.8), silence(0.8)]))          # devam geldi
        await settle(s)
        users = [e["text"] for e in events if e["type"] == "transcript" and e["role"] == "user"]
        assert users == ["evet ama hepsi iyiydi"] and s.stats["merged"] == 1
        assert stt.seen[1] > stt.seen[0] + 0.8 and out.pushed       # birleşik ses çözüldü, ajan şimdi cevap verdi
        assert {"type": "hold", "on": False} in events
    asyncio.run(main())


def test_held_sentence_is_answered_after_timeout_if_user_stays_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "HOLD_S", 0.3)

    async def main():
        s, out, events = make_session(tmp_path, monkeypatch, stt=ScriptSTT(["evet ama"]))
        s.state = "listening"
        s.feed(np.concatenate([silence(0.3), speech(1.0), silence(0.8)]))
        await settle(s)
        assert not out.pushed
        await asyncio.sleep(0.6)
        await settle(s)
        users = [e["text"] for e in events if e["type"] == "transcript" and e["role"] == "user"]
        assert users == ["evet ama"] and out.pushed                  # süre doldu: yarım cümleye de cevap verilir
        turn = [e for e in events if e["type"] == "turn" and "stt_s" in e][0]
        assert turn["held_s"] == 0.3
    asyncio.run(main())


def test_open_text_steps_wait_longer_before_ending_the_turn(tmp_path, monkeypatch):
    async def main():
        s, _, _ = make_session(tmp_path, monkeypatch)
        s.flow = FlowDriver(S.get("anket"), FakeLLM("m"))
        s.flow.current = "musaitlik"
        s._apply_endpointing()
        assert s.vad.end_frames * 20 == 600
        s.flow.current = "q4"                       # "Puanın nedeni" açık uçlu
        s._apply_endpointing()
        assert s.vad.end_frames * 20 == 1200
        # 900 ms düşünme duraksaması açık uçlu cevapta turu bitirmez
        s.state = "listening"
        s.feed(np.concatenate([silence(0.3), speech(1.0), silence(0.9), speech(1.0), silence(1.4)]))
        await settle(s)
        assert s.stats["utterances"] == 1
    asyncio.run(main())


def test_barge_in_event_reports_detection_time(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        s.feed(speech(0.5, amp=0.2))
        ev = next(e for e in events if e["type"] == "barge_in")
        assert 0 <= ev["cut_ms"] < 100                  # çerçeveler hızlı beslendi; gerçek zamanda ≈ 200 ms (BARGE_FRAMES)
        assert s.stats["barge_cut_ms"] == [ev["cut_ms"]]
    asyncio.run(main())


class BargeMic(MicTrack):
    """Sentetik mikrofon: sessizlik, ajan konuşurken (onset sn) 1,5 sn gürültü; onset'in duvar saati kaydedilir."""
    ONSET = 1.5

    def __init__(self):
        super().__init__()
        self.onset_wall = None

    async def recv(self):
        frame = await super().recv()
        sec = self.n / 48000
        if self.onset_wall is None and sec >= self.ONSET:
            self.onset_wall = time.time()
        return frame


def test_agent_audio_stops_within_500ms_of_user_speech_over_real_webrtc(env):
    """Ölçüm istemci tarafındadır: kullanıcı konuşmaya başladığı andan, ajan sesinin istemcide kesildiği ana kadar."""
    import av
    from fractions import Fraction
    rng = np.random.default_rng(3)

    class Mic(BargeMic):
        async def recv(self):
            if self.t0 is None:
                self.t0 = time.time()
            else:
                self.n += 960
                await asyncio.sleep(max(0, self.t0 + self.n / 48000 - time.time()))
            sec = self.n / 48000
            loud = self.ONSET <= sec < self.ONSET + 1.5
            if loud and self.onset_wall is None:
                self.onset_wall = time.time()
            samples = (rng.standard_normal(960) * 0.1 * 32767).astype(np.int16) if loud else np.zeros(960, np.int16)
            frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate, frame.pts, frame.time_base = 48000, self.n, Fraction(1, 48000)
            return frame

    warm("V1")
    app_client = TestClient(app).__enter__()

    async def main():
        pc = RTCPeerConnection()
        mic = Mic()
        heard = []                                   # (duvar saati, ortalama genlik)
        events = []
        channel = pc.createDataChannel("events")
        channel.on("message", lambda m: events.append(json.loads(m)))
        pc.addTrack(mic)

        @pc.on("track")
        def on_track(track):
            async def drain():
                try:
                    while True:
                        f = await track.recv()
                        heard.append((time.time(), float(np.abs(f.to_ndarray()).mean())))
                except Exception:
                    pass
            asyncio.ensure_future(drain())

        await pc.setLocalDescription(await pc.createOffer())
        res = await asyncio.to_thread(app_client.post, "/api/voice/offer", json={
            "sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "profile": "V1"})
        assert res.status_code == 200, res.text
        body = res.json()
        await pc.setRemoteDescription(RTCSessionDescription(sdp=body["sdp"], type=body["type"]))
        await asyncio.sleep(mic.ONSET + 2.0)
        await asyncio.to_thread(app_client.delete, f"/api/voice/{body['session_id']}")
        await pc.close()
        return mic.onset_wall, heard, events

    try:
        onset, heard, events = asyncio.run(main())
    finally:
        app_client.__exit__(None, None, None)
    assert onset is not None
    before = [e for t, e in heard if onset - 0.4 <= t < onset]
    assert before and max(before) > 200, "ajan konuşmuyordu (test geçersiz)"
    window = [(t, e) for t, e in heard if onset <= t < onset + 1.2]
    loud_times = [t for t, e in window if e > 200]
    cut = (max(loud_times) - onset) if loud_times else 0.0
    print(f"BARGE_IN_MEASURED client_cut_ms={cut * 1000:.0f} server_cut_ms={[e for e in events if e['type'] == 'barge_in'][0]['cut_ms']}")
    assert cut <= 0.5, f"ajan sesi {cut * 1000:.0f} ms sonra kesildi"
    tail = [e for t, e in window if t >= onset + 0.7]
    assert tail and max(tail) < 50, "söz kesmeden sonra ajan sesi sürdü"
    barge = next(e for e in events if e["type"] == "barge_in")
    assert barge["cut_ms"] < 400
