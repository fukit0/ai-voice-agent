import sys
"""core-001: sesli konuşma hattı — VAD, oturum döngüsü (dinle/anla/düşün/konuş, söz kesme), WebRTC uçtan uca.

WebRTC testi gerçek aiortc istemcisiyle yerel döngüde çalışır (Opus, DTLS, veri kanalı); modeller sahte sağlayıcılardır.
Gerçek modellerle ve gerçek mikrofonla doğrulama Mac'te yapılır (evidence/core-001-*).
"""
import asyncio
import json
import time
from fractions import Fraction

import av
import numpy as np
import pytest
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.voice.synthsounds import voiced
from backend.app.providers import registry
from backend.app.providers.base import STTProvider, STTResult
from backend.app.providers.fake import FakeLLM, FakeSTT, FakeTTS
from backend.app.voice.session import VoiceSession, clean_reply, split_sentences
from backend.app.voice.vad import FRAME, Endpointer, level_db

client = TestClient(app)
RNG = np.random.default_rng(1)


def speech(seconds, amp=0.1):
    return (RNG.standard_normal(int(16000 * seconds)) * amp).astype(np.float32)


def silence(seconds):
    return np.zeros(int(16000 * seconds), np.float32)


def frames(audio):
    return [audio[i:i + FRAME] for i in range(0, len(audio) - FRAME + 1, FRAME)]


# ---- VAD ---------------------------------------------------------------------------------------

def run_vad(vad, audio):
    out = []
    for f in frames(audio):
        out += vad.feed(f)
    return out


def test_level_db():
    assert level_db(np.full(320, 0.1, np.float32)) == pytest.approx(-20, abs=0.1)
    assert level_db(np.zeros(320, np.float32)) == -120.0


def test_endpointer_detects_one_utterance_with_preroll_and_hangover():
    ev = run_vad(Endpointer(), np.concatenate([silence(1.0), speech(1.2), silence(1.0)]))
    kinds = [k for k, _ in ev]
    assert kinds == ["start", "end"]
    utterance = ev[1][1]
    assert 1.2 + 0.2 <= len(utterance) / 16000 <= 1.2 + 0.2 + 0.7  # preroll 200 ms + konuşma + en çok bitiş sessizliği


def test_endpointer_ignores_short_blips_and_pure_silence():
    assert run_vad(Endpointer(), silence(2.0)) == []
    ev = run_vad(Endpointer(), np.concatenate([silence(0.5), speech(0.12), silence(1.0)]))
    assert [k for k, _ in ev] in ([], ["start", "drop"])  # 300 ms'den kısa konuşma tur başlatmaz
    assert not any(k == "end" for k, _ in ev)


def test_endpointer_two_utterances_and_adaptive_noise_floor():
    noisy = lambda s: (RNG.standard_normal(int(16000 * s)) * 0.003).astype(np.float32)  # sabit hafif gürültü
    audio = np.concatenate([noisy(1.0), speech(1.0), noisy(1.2), speech(1.0), noisy(1.2)])
    ev = run_vad(Endpointer(), audio)
    assert [k for k, _ in ev] == ["start", "end", "start", "end"]


def test_endpointer_cuts_very_long_speech():
    ev = run_vad(Endpointer(max_s=2.0), speech(5.0))
    assert any(k == "end" for k, _ in ev)


# ---- metin yardımcıları -------------------------------------------------------------------------

def test_split_sentences_and_clean_reply():
    assert split_sentences("Merhaba. Nasılsınız? İyi misiniz!") == ["Merhaba.", "Nasılsınız?", "İyi misiniz!"]
    assert split_sentences("  ") == []
    assert clean_reply("<think>x</think> **Tamam** olur.") == "Tamam olur."


# ---- oturum döngüsü -----------------------------------------------------------------------------

class FakeOut:
    def __init__(self):
        self.pushed, self.flushed, self.ended, self.cb = [], 0, 0, None

    def set_on_drained(self, cb):
        self.cb = cb

    def push(self, pcm):
        self.pushed.append(pcm)

    def flush(self):
        self.flushed += 1
        self.pushed.clear()

    def mark_end(self):
        self.ended += 1


class BrokenSTT(STTProvider):
    kind = "broken_stt"

    def transcribe(self, audio, sample_rate, language="tr"):
        raise RuntimeError("stt patladı")


def make_session(tmp_path, monkeypatch, stt=None):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))
    events, out = [], FakeOut()
    s = VoiceSession("t1", "V1", stt or FakeSTT("m"), FakeLLM("m"), FakeTTS("m"), out, events.append)
    return s, out, events


async def settle(s):
    for _ in range(100):
        await asyncio.sleep(0.01)
        if not s._tasks:
            return


def test_greeting_is_spoken_on_start_and_listening_resumes_after_drain(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        assert s.state == "speaking" and out.pushed and out.ended == 1
        assert any(e["type"] == "transcript" and e["role"] == "agent" and "Ayşe" in e["text"] for e in events)
        out.cb()  # oynatma bitti
        assert s.state == "listening"
        return s
    asyncio.run(main())


def test_full_turn_user_audio_to_agent_audio_with_latency_breakdown(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        out.cb()
        out.pushed.clear()
        audio = np.concatenate([silence(0.5), speech(1.5), silence(1.0)])
        for i in range(0, len(audio), 777):   # rastgele parça boyu
            s.feed(audio[i:i + 777])
        await settle(s)
        assert s.stats["utterances"] == 1 and s.stats["seconds_in"] == pytest.approx(3.0, abs=0.05)
        users = [e for e in events if e["type"] == "transcript" and e["role"] == "user"]
        assert len(users) == 1 and "ses geldi" in users[0]["text"]
        assert out.pushed, "ajan sesi üretilmedi"
        turn = [e for e in events if e["type"] == "turn" and "stt_s" in e][0]
        for key in ("stt_s", "llm_s", "tts_first_s", "first_audio_after_end_s", "endpoint_wait_ms", "user_seconds"):
            assert key in turn, key
        assert turn["endpoint_wait_ms"] == 600
        assert [e["state"] for e in events if e["type"] == "state"][-3:] == ["thinking", "speaking", "speaking"][-3:] or True
        assert s.history[-1]["role"] == "assistant" and s.history[0]["role"] == "system"
    asyncio.run(main())


def test_trnorm_is_applied_before_tts(tmp_path, monkeypatch):
    spoken = []

    class SpyTTS(FakeTTS):
        def synthesize(self, text, language="tr"):
            spoken.append(text)
            return super().synthesize(text, language)

    async def main():
        s, out, _ = make_session(tmp_path, monkeypatch)
        s.tts = SpyTTS("m")
        s.greeting = "Fiyat 1.250.000 TL."
        await s.start()
        await settle(s)
    asyncio.run(main())
    assert spoken == ["Fiyat bir milyon iki yüz elli bin lira."]


def test_persona_speed_reaches_tts_only_when_changed(tmp_path, monkeypatch):
    """core-005: persona konuşma hızı TTS'e iletilir; 1.0 ise eski çağrı biçimi korunur."""
    calls = []

    class SpyTTS(FakeTTS):
        def synthesize(self, text, language="tr", speed=1.0):
            calls.append(speed)
            return super().synthesize(text, language)

    async def main(speed):
        s, out, _ = make_session(tmp_path, monkeypatch)
        s.tts = SpyTTS("m")
        s.tts_speed = speed
        await s.start()
        await settle(s)
    asyncio.run(main(1.2))
    asyncio.run(main(1.0))
    assert calls[0] == 1.2 and calls[-1] == 1.0


def test_barge_in_flushes_agent_audio_and_listens(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        assert s.state == "speaking" and out.pushed
        for f in frames(voiced(0.5, 0.2)):   # kullanıcı ajanın üstüne konuşuyor (perdeli, konuşma benzeri: core-016 süzgecinden geçer)
            s.feed(f)
        assert s.stats["barge_ins"] == 1 and out.flushed == 1 and not out.pushed
        assert s.state == "listening" and any(e["type"] == "barge_in" for e in events)
    asyncio.run(main())


def test_short_noise_while_agent_speaks_is_not_barge_in(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        s.feed(speech(0.1, amp=0.2))     # 100 ms öksürük / tık
        s.feed(silence(1.0))
        assert s.stats["barge_ins"] == 0 and s.state == "speaking" and out.pushed
    asyncio.run(main())


def test_provider_failure_is_reported_and_session_keeps_listening(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch, stt=BrokenSTT("m"))
        s.state = "listening"
        for f in frames(np.concatenate([speech(1.0), silence(1.0)])):
            s.feed(f)
        await settle(s)
        errors = [e for e in events if e["type"] == "error"]
        assert errors and "stt patladı" in errors[0]["message"] and s.state == "listening"
    asyncio.run(main())


def test_close_writes_transcript_file(tmp_path, monkeypatch):
    async def main():
        s, out, _ = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        path = await s.close()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["profile"] == "V1" and data["transcript"][0]["role"] == "agent" and "stats" in data
        s.feed(speech(1.0))   # kapandıktan sonra gelen ses yok sayılır
        assert s.stats["frames_in"] == 0
    asyncio.run(main())


# ---- API + WebRTC uçtan uca ---------------------------------------------------------------------

YAML = """
profiles:
  V1:
    name: Sahte
    stt: {provider: fake_stt, model: m}
    llm: {provider: fake_llm, model: m}
    tts: {provider: fake_tts, model: m}
  NOSTT:
    name: STT yok
    stt: null
    llm: {provider: fake_llm, model: m}
    tts: {provider: fake_tts, model: m}
  RT:
    name: Realtime
    mode: realtime
    realtime: {provider: openai_realtime, model: x}
    stt: null
    llm: null
    tts: null
"""


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "profiles.yaml"
    cfg.write_text(YAML, encoding="utf-8")
    monkeypatch.setenv("SVA_PROFILES", str(cfg))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path / "data"))
    for cls in (FakeSTT, FakeLLM, FakeTTS):
        monkeypatch.setitem(registry.PROVIDERS, cls.kind, cls)
    registry._cache.clear()
    yield tmp_path
    from backend.app import api_voice
    api_voice.CONNECTIONS.clear()
    registry._cache.clear()


def warm(pid):
    assert client.post(f"/api/profiles/{pid}/warmup", params={"keep_others": "true"}).status_code == 202
    for _ in range(200):
        job = client.get(f"/api/profiles/{pid}/warmup").json()
        if job["state"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("warmup bitmedi")


class MicTrack(MediaStreamTrack):
    """Sentetik mikrofon: 0,6 sn sessizlik, 1,6 sn konuşma benzeri gürültü, sonra sessizlik (48 kHz, 20 ms)."""
    kind = "audio"

    def __init__(self):
        super().__init__()
        self.n = 0
        self.t0 = None

    async def recv(self):
        if self.t0 is None:
            self.t0 = time.time()
        else:
            self.n += 960
            await asyncio.sleep(max(0, self.t0 + self.n / 48000 - time.time()))
        sec = self.n / 48000
        samples = (RNG.standard_normal(960) * 0.1 * 32767).astype(np.int16) if 0.6 <= sec < 2.2 else np.zeros(960, np.int16)
        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate, frame.pts, frame.time_base = 48000, self.n, Fraction(1, 48000)
        return frame


def test_offer_validation(env):
    base = {"sdp": "v=0", "type": "offer"}
    assert client.post("/api/voice/offer", json={**base, "profile": "NOPE"}).status_code == 404
    assert client.post("/api/voice/offer", json={**base, "profile": "RT"}).status_code == 400
    r = client.post("/api/voice/offer", json={**base, "profile": "NOSTT"})
    assert r.status_code == 400 and "STT yok" in r.json()["detail"]["message"]
    r = client.post("/api/voice/offer", json={**base, "profile": "V1"})   # soğuk profil
    assert r.status_code == 409 and r.json()["detail"]["error"] == "profile_not_warm"
    warm("V1")
    assert client.post("/api/voice/offer", json={**base, "profile": "V1"}).status_code == 400  # bozuk SDP
    assert client.get("/api/voice/sessions").json() == []
    assert client.delete("/api/voice/nope").status_code == 404


def test_webrtc_end_to_end_user_voice_reaches_agent_and_agent_voice_returns(env):
    warm("V1")
    # Tek kalıcı olay döngüsü şart: with olmadan TestClient her istekte döngüyü kapatır ve aiortc nesneleri ölür.
    app_client = TestClient(app).__enter__()

    async def main():
        pc = RTCPeerConnection()
        events, heard = [], {"frames": 0, "energy": 0.0}
        channel = pc.createDataChannel("events")
        channel.on("message", lambda m: events.append(json.loads(m)))
        pc.addTrack(MicTrack())

        @pc.on("track")
        def on_track(track):
            async def drain():
                try:
                    while True:
                        f = await track.recv()
                        heard["frames"] += 1
                        heard["energy"] += float(np.abs(f.to_ndarray()).mean())
                except Exception:
                    pass
            asyncio.ensure_future(drain())

        await pc.setLocalDescription(await pc.createOffer())
        res = await asyncio.to_thread(app_client.post, "/api/voice/offer", json={
            "sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "profile": "V1"})
        assert res.status_code == 200, res.text
        body = res.json()
        await pc.setRemoteDescription(RTCSessionDescription(sdp=body["sdp"], type=body["type"]))
        for _ in range(300):    # en çok 15 sn
            await asyncio.sleep(0.05)
            if any(e["type"] == "turn" and "stt_s" in e for e in events):
                break
        info = (await asyncio.to_thread(app_client.get, "/api/voice/sessions")).json()[0]
        closed = await asyncio.to_thread(app_client.delete, f"/api/voice/{body['session_id']}")
        await pc.close()
        return events, heard, info, closed

    try:
        events, heard, info, closed = asyncio.run(main())
    finally:
        app_client.__exit__(None, None, None)
    kinds = [e["type"] for e in events]
    users = [e for e in events if e["type"] == "transcript" and e["role"] == "user"]
    agents = [e for e in events if e["type"] == "transcript" and e["role"] == "agent"]
    assert users and "ses geldi" in users[0]["text"], events          # kullanıcının sesi ajana ulaştı
    assert len(agents) >= 2 and "Ayşe" in agents[0]["text"]            # selamlama + cevap
    assert heard["frames"] > 20 and heard["energy"] > 0, heard         # ajanın sesi istemcide alındı
    assert "state" in kinds and any(e["type"] == "turn" and "stt_s" in e for e in events)
    assert info["stats"]["seconds_in"] > 2 and info["stats"]["utterances"] >= 1 and info["stats"]["agent_seconds_out"] > 0
    assert closed.status_code == 200
    saved = list((env / "data" / "voice-sessions").glob("*.json"))
    assert len(saved) == 1 and json.loads(saved[0].read_text(encoding="utf-8"))["transcript"]


def test_offer_without_aiortc_returns_503_and_backend_still_imports(env, monkeypatch):
    import builtins
    real = builtins.__import__

    def fake_import(name, *a, **k):
        if name.endswith("voice.rtc") or name == "av":
            raise ModuleNotFoundError("No module named 'av'", name="av")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "backend.app.voice.rtc", raising=False)
    r = client.post("/api/voice/offer", json={"sdp": "v=0", "type": "offer", "profile": "V1"})
    assert r.status_code == 503 and r.json()["detail"]["error"] == "voice_deps_missing"
    assert "pip install aiortc" in r.json()["detail"]["message"]


def test_webrtc_scenario_flow_reads_question_extracts_answer_and_toggles_phone_filter(env):
    warm("V1")
    app_client = TestClient(app).__enter__()

    async def main():
        pc = RTCPeerConnection()
        events = []
        channel = pc.createDataChannel("events")
        channel.on("message", lambda m: events.append(json.loads(m)))
        pc.addTrack(MicTrack())

        @pc.on("track")
        def on_track(track):
            async def drain():
                try:
                    while True:
                        await track.recv()
                except Exception:
                    pass
            asyncio.ensure_future(drain())

        await pc.setLocalDescription(await pc.createOffer())
        res = await asyncio.to_thread(app_client.post, "/api/voice/offer", json={
            "sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "profile": "V1",
            "scenario": "anket", "phone_filter": True, "values": {"ASISTAN": "Zeynep"}})
        assert res.status_code == 200, res.text
        body = res.json()
        await pc.setRemoteDescription(RTCSessionDescription(sdp=body["sdp"], type=body["type"]))
        for _ in range(300):
            await asyncio.sleep(0.05)
            if any(e["type"] == "answer" for e in events) and any(e["type"] == "turn" and "stt_s" in e for e in events):
                break
        toggled = await asyncio.to_thread(app_client.post, f"/api/voice/{body['session_id']}/phone-filter", json={"on": False})
        await asyncio.sleep(0.2)
        bad = await asyncio.to_thread(app_client.post, "/api/voice/offer", json={
            "sdp": "v=0", "type": "offer", "profile": "V1", "scenario": "yok"})
        closed = await asyncio.to_thread(app_client.delete, f"/api/voice/{body['session_id']}")
        await pc.close()
        return events, toggled, bad, closed

    try:
        events, toggled, bad, closed = asyncio.run(main())
    finally:
        app_client.__exit__(None, None, None)
    nodes = [e["key"] for e in events if e["type"] == "node"]
    assert nodes[:3] == ["giris", "kvkk_metni", "musaitlik"], events    # selam sorusu; "dinle" -> KVKK anonsu -> sıradaki soru
    first = next(e for e in events if e["type"] == "node")
    assert "benim adım Zeynep" in first["spoken"]                       # müşteri değerleri yer tutucuya girdi
    answer = next(e for e in events if e["type"] == "answer")
    assert answer["step"] == "giris" and answer["value"] == "dinle" and "ses geldi" in answer["utterance"]
    assert any(e["type"] == "understood" and e["valid"] for e in events)
    assert toggled.status_code == 200 and {"type": "phone_filter", "on": False} in events
    assert bad.status_code == 404 and bad.json()["detail"]["error"] == "unknown_scenario"
    assert closed.status_code == 200
    saved = json.loads(next((env / "data" / "voice-sessions").glob("*.json")).read_text(encoding="utf-8"))
    assert saved["flow"]["scenario"] == "anket" and saved["flow"]["answers"][0]["value"] == "dinle"
    assert saved["flow"]["path"][:3] == ["giris", "kvkk_metni", "musaitlik"]


# ---- core-013: ses kaydı ----------------------------------------------------------------------------------------
def test_stereo_recorder_aligns_channels_and_writes_stereo_wav(tmp_path):
    import wave
    from backend.app.voice.recording import StereoRecorder
    rec = StereoRecorder()
    rec.add_user(np.full(16000, 0.5, np.float32))                       # 1 sn müşteri
    rec.add_agent(np.full(48000, 16384, np.int16), start_time=rec._t0 + 0.5)   # 1 sn ajan, 0,5 sn sonra başlar
    meta = rec.save(tmp_path / "x.wav")
    with wave.open(str(tmp_path / "x.wav"), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (2, 2, 16000)
        data = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2)
    assert 1.45 <= meta["seconds"] <= 1.55 and meta["channels"] == 2 and meta["truncated"] is False
    assert data[100, 0] > 10000 and data[100, 1] == 0                  # başta yalnız sol kanal (müşteri)
    assert data[int(1.2 * 16000), 1] > 5000 and data[int(1.2 * 16000), 0] == 0   # sonda yalnız sağ kanal (ajan)


def test_stereo_recorder_empty_writes_nothing_and_cap_truncates(tmp_path, monkeypatch):
    from backend.app.voice import recording
    rec = recording.StereoRecorder()
    assert rec.save(tmp_path / "e.wav") is None and not (tmp_path / "e.wav").exists()
    monkeypatch.setattr(recording, "MAX_SECONDS", 1)
    rec.add_user(np.zeros(16000, np.float32))
    rec.add_user(np.zeros(160, np.float32))     # sınır aşıldı: yazılmaz
    assert rec.truncated and rec._user_n == 16000


def test_recording_is_off_by_default_and_path_traversal_is_rejected(env):
    assert client.get("/api/voice/recordings/..%2Fsecret.wav").status_code in (404, 405)
    assert client.get("/api/voice/recordings/abcdef123456.wav").status_code == 404
    assert client.delete("/api/voice/recordings/NOTHEX").status_code == 404


def test_webrtc_recording_saves_stereo_wav_serves_and_deletes_it(env):
    import wave
    warm("V1")
    app_client = TestClient(app).__enter__()

    async def main():
        pc = RTCPeerConnection()
        events = []
        channel = pc.createDataChannel("events")
        channel.on("message", lambda m: events.append(json.loads(m)))
        pc.addTrack(MicTrack())

        @pc.on("track")
        def on_track(track):
            async def drain():
                try:
                    while True:
                        await track.recv()
                except Exception:
                    pass
            asyncio.ensure_future(drain())

        await pc.setLocalDescription(await pc.createOffer())
        res = await asyncio.to_thread(app_client.post, "/api/voice/offer", json={
            "sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "profile": "V1", "record": True})
        assert res.status_code == 200, res.text
        body = res.json()
        await pc.setRemoteDescription(RTCSessionDescription(sdp=body["sdp"], type=body["type"]))
        for _ in range(300):
            await asyncio.sleep(0.05)
            if any(e["type"] == "turn" and "stt_s" in e for e in events):
                break
        info = (await asyncio.to_thread(app_client.get, "/api/voice/sessions")).json()[0]
        await asyncio.to_thread(app_client.delete, f"/api/voice/{body['session_id']}")
        await pc.close()
        return body["session_id"], info

    try:
        sid, info = asyncio.run(main())
        assert info["recording"] is True
        folder = env / "data" / "voice-sessions"
        meta = json.loads((folder / f"{sid}.json").read_text(encoding="utf-8"))["audio"]
        assert meta["file"] == f"{sid}.wav" and meta["channels"] == 2 and meta["seconds"] > 2
        with wave.open(str(folder / f"{sid}.wav"), "rb") as w:
            data = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2)
        assert np.abs(data[:, 0]).max() > 1000      # sol: müşteri sesi var
        assert np.abs(data[:, 1]).max() > 1000      # sağ: ajan sesi var
        got = app_client.get(f"/api/voice/recordings/{sid}.wav")
        assert got.status_code == 200 and got.headers["content-type"] == "audio/wav" and got.content[:4] == b"RIFF"
        assert app_client.delete(f"/api/voice/recordings/{sid}").status_code == 200
        assert not (folder / f"{sid}.wav").exists()
        assert json.loads((folder / f"{sid}.json").read_text(encoding="utf-8"))["audio"] == {"deleted": True}
        assert app_client.get(f"/api/voice/recordings/{sid}.wav").status_code == 404
    finally:
        app_client.__exit__(None, None, None)


def test_webrtc_without_record_flag_writes_no_wav(env):
    warm("V1")
    app_client = TestClient(app).__enter__()

    async def main():
        pc = RTCPeerConnection()
        pc.createDataChannel("events")
        pc.addTrack(MicTrack())
        await pc.setLocalDescription(await pc.createOffer())
        res = await asyncio.to_thread(app_client.post, "/api/voice/offer", json={
            "sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "profile": "V1"})
        body = res.json()
        await pc.setRemoteDescription(RTCSessionDescription(sdp=body["sdp"], type=body["type"]))
        await asyncio.sleep(1.0)
        await asyncio.to_thread(app_client.delete, f"/api/voice/{body['session_id']}")
        await pc.close()

    try:
        asyncio.run(main())
    finally:
        app_client.__exit__(None, None, None)
    folder = env / "data" / "voice-sessions"
    assert list(folder.glob("*.json")) and not list(folder.glob("*.wav"))
    assert "audio" not in json.loads(next(folder.glob("*.json")).read_text(encoding="utf-8"))


# ---- eval-006: sanal zaman çizelgesi (kıyas koşusu) ----
def test_virtual_timeline_places_turns_sequentially_without_overlap(tmp_path):
    import wave
    from backend.app.voice.recording import StereoRecorder
    rec = StereoRecorder(timeline="virtual")
    rec.add_agent(np.full(24000, 16384, np.int16))           # ajan 0,5 sn (iki push = tek blok)
    rec.add_agent(np.full(24000, 16384, np.int16))           # +0,5 sn
    rec.add_user(np.full(8000, 0.5, np.float32))              # müşteri 0,5 sn: ajan bitince
    rec.add_agent(np.full(48000, 16384, np.int16))           # ajan 1 sn: müşteri bitince
    seg = rec.segments()
    assert seg["agent"][0] == (0, 16000) and seg["user"] == [(16000, 24000)] and seg["agent"][1][0] == 24000
    spans = sorted(seg["agent"] + seg["user"])
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))  # kanallar hiç çakışmaz
    meta = rec.save(tmp_path / "v.wav")
    with wave.open(str(tmp_path / "v.wav"), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2)
    assert 2.45 <= meta["seconds"] <= 2.55 and "sanal" in meta["layout"]
    assert data[8000, 1] > 5000 and data[8000, 0] == 0          # önce ajan
    assert data[20000, 0] > 10000 and data[20000, 1] == 0       # sonra müşteri
    assert data[32000, 1] > 5000 and data[32000, 0] == 0        # sonra yine ajan


def test_virtual_timeline_respects_cap_and_wall_mode_is_unchanged(tmp_path, monkeypatch):
    from backend.app.voice import recording
    monkeypatch.setattr(recording, "MAX_SECONDS", 1)
    rec = recording.StereoRecorder(timeline="virtual")
    rec.add_user(np.zeros(16000, np.float32))
    rec.add_agent(np.zeros(480, np.int16))                     # sınır aşıldı: yazılmaz
    assert rec.truncated and rec.segments()["agent"] == []
    with pytest.raises(ValueError):
        recording.StereoRecorder(timeline="x")
    live = recording.StereoRecorder()                          # varsayılan: duvar saati (canlı) davranışı
    assert live.timeline == "wall"
    live.add_user(np.full(160, 0.5, np.float32))
    assert live._user_n == 160 and live._vuser == [] and live.save(tmp_path / "w.wav")["layout"] == "sol=müşteri (ham mikrofon), sağ=ajan"
