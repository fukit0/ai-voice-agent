"""core-015: giriş sesi eşiği ekrandan ayarlanır; gürültü söz kesmez, normal konuşma keser.

Not: spec metnindeki -40 dBFS örneği varsayılan söz kesme seviyesinin (-45 + 6 = -39 dBFS) altında kaldığı için
varsayılanda zaten kesmezdi; gerçek "gürültü kesiyor" vakasını temsil eden -35 dBFS kullanılır.
"""
import asyncio

import numpy as np

from backend.app.voice.vad import Endpointer
from backend.app.voice.realtime import OpenAIRealtime
from backend.tests.test_voice import FRAME, env, frames, make_session, settle, silence  # noqa: F401


def tone(seconds, db):
    """Verilen RMS seviyesinde (dBFS) gürültü."""
    rng = np.random.default_rng(7)
    return (rng.standard_normal(int(16000 * seconds)) * 10 ** (db / 20)).astype(np.float32)


def test_default_behavior_is_unchanged():
    v = Endpointer()
    assert v.manual_db is None and v.threshold_db == -45.0
    assert v.barge_level_db == -39.0 and v.barge_frames == 8


def test_configure_clamps_and_reports():
    v = Endpointer()
    assert v.configure(threshold_db=-5)["threshold_db"] == -10.0
    assert v.configure(threshold_db=-99)["threshold_db"] == -70.0
    s = v.configure(barge_frames=0, barge_margin_db=99)
    assert s["barge_frames"] == 1 and s["barge_margin_db"] == 30.0
    assert v.configure(reset_threshold=True)["threshold_db"] is None


def test_noise_burst_barges_at_default_but_not_at_raised_threshold(tmp_path, monkeypatch):
    async def run(db_threshold):
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        if db_threshold is not None:
            s.set_vad({"db": db_threshold})
        s.feed(tone(0.2, -35))   # 200 ms gürültü patlaması
        return s.stats["barge_ins"]
    assert asyncio.run(run(None)) == 1       # varsayılan eşikte gürültü ajanı keser (kullanıcının şikâyeti)
    assert asyncio.run(run(-30)) == 0        # eşik -30 dBFS: kesmez


def test_normal_speech_still_barges_at_raised_threshold(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        s.set_vad({"db": -30})
        s.feed(tone(0.4, -20))
        assert s.stats["barge_ins"] == 1
    asyncio.run(main())


def test_noise_does_not_cancel_pending_answer_while_thinking(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        s.state = "thinking"
        s.set_vad({"db": -30})
        before = s._turn_id
        s.feed(tone(0.4, -35))
        assert s._turn_id == before and s.state == "thinking" and s.stats["barge_ins"] == 0
        s.feed(tone(0.4, -20))                 # normal ses seviyesi bekleyen cevabı iptal eder
        assert s.stats["barge_ins"] == 1
    asyncio.run(main())


def test_threshold_also_governs_utterance_start_and_end():
    """Aynı değer konuşma başlangıcı/bitişini de belirler: yükseltilmiş eşikte gürültü 'start' açmaz."""
    audio = np.concatenate([silence(0.3), tone(1.0, -35), silence(1.0)])
    def count(v):
        n = {"start": 0, "end": 0, "drop": 0}
        for f in frames(audio):
            for k, _ in v.feed(f):
                n[k] += 1
        return n
    assert count(Endpointer())["start"] == 1
    hi = Endpointer()
    hi.configure(threshold_db=-30)
    assert count(hi) == {"start": 0, "end": 0, "drop": 0}


def test_barge_duration_and_margin_are_adjustable_and_saved(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        s.set_vad({"barge_frames": 30})
        s.feed(tone(0.4, -20))                  # 20 çerçeve < 30: kesmez
        assert s.stats["barge_ins"] == 0
        s.feed(tone(0.4, -20))
        assert s.stats["barge_ins"] == 1
        ev = [e for e in events if e["type"] == "vad_settings"][-1]
        assert ev["barge_frames"] == 30 and ev["barge_ms"] == 600
        assert s.stats["vad"]["barge_frames"] == 30
    asyncio.run(main())


def test_vad_settings_are_written_to_session_json(tmp_path, monkeypatch):
    import json

    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        s.set_vad({"db": -33, "barge_margin_db": 9})
        path = await s.close()
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["vad"]["threshold_db"] == -33.0 and doc["vad"]["barge_margin_db"] == 9.0
    asyncio.run(main())


def test_openai_threshold_mapping_is_monotonic_and_bounded():
    t = [OpenAIRealtime.threshold_for_db(d) for d in (-70, -60, -40, -20, -10)]
    assert t == sorted(t) and t[0] == 0.2 and t[-1] == 0.9


def test_webrtc_offer_applies_initial_vad_and_datachannel_command_updates_it(env):
    import json as _json
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.tests.test_voice import MicTrack, warm

    warm("V1")
    client = TestClient(app).__enter__()

    async def main():
        pc = RTCPeerConnection()
        events = []
        channel = pc.createDataChannel("events")
        channel.on("message", lambda m: events.append(_json.loads(m)))
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
        res = await asyncio.to_thread(client.post, "/api/voice/offer", json={
            "sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "profile": "V1",
            "vad": {"db": -38, "barge_frames": 12}})
        assert res.status_code == 200, res.text
        body = res.json()
        await pc.setRemoteDescription(RTCSessionDescription(sdp=body["sdp"], type=body["type"]))
        for _ in range(100):
            await asyncio.sleep(0.05)
            if channel.readyState == "open":
                break
        channel.send(_json.dumps({"type": "vad_threshold", "db": -28}))
        for _ in range(100):
            await asyncio.sleep(0.05)
            if any(e["type"] == "vad_settings" and e["threshold_db"] == -28.0 for e in events):
                break
        await asyncio.to_thread(client.delete, f"/api/voice/{body['session_id']}")
        await pc.close()
        return events

    try:
        events = asyncio.run(main())
    finally:
        client.__exit__(None, None, None)
    first = next(e for e in events if e["type"] == "vad_settings")
    assert first["threshold_db"] == -38.0 and first["barge_frames"] == 12      # teklifle gelen başlangıç ayarı
    assert any(e["type"] == "vad_settings" and e["threshold_db"] == -28.0 and e["barge_frames"] == 12 for e in events)
    saved = _json.loads(next((env / "data" / "voice-sessions").glob("*.json")).read_text(encoding="utf-8"))
    assert saved["vad"]["threshold_db"] == -28.0
