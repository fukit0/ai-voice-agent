"""A1 gecikme işi, faz 3: Deepgram canlı (WebSocket) STT, isteğe bağlı (profilde stt.streaming: true).

Sahte Deepgram sunucusu yerel `websockets` sunucusudur (gerçek ağ yok). Kapsam: normal transkript, boş transkript, konuşma
ortasında kapanan sunucu, yavaş sunucu (zaman aşımı -> toplu yedek), KeepAlive, bir aramada iki konuşma, bekletme/birleştirme
etkileşimi, düşen kısa gürültü, ajan konuşurken biten konuşma, STT geçidi, kullanım ölçümü.
"""
import asyncio
import json
import socket
import threading
import time

import numpy as np
import pytest
from websockets.sync.server import serve

from backend.app import usage as usage_mod
from backend.app.providers import registry, remote
from backend.app.providers.base import ProviderError, STTResult
from backend.app.providers.fake import FakeLLM, FakeTTS
from backend.app.voice import session as session_mod
from backend.app.voice.session import VoiceSession, to_int16
from backend.app.voice.vad import FRAME, Endpointer

RNG = np.random.default_rng(3)


def speech(seconds, amp=0.1):
    return (RNG.standard_normal(int(16000 * seconds)) * amp).astype(np.float32)


def silence(seconds):
    return np.zeros(int(16000 * seconds), np.float32)


# ---- sahte Deepgram -------------------------------------------------------------------------------------------------
class FakeDeepgram:
    """Bağlantı başına betik: {"text": str, "mode": normal|empty|close_mid|slow|error|segments, "conf": float}."""

    def __init__(self):
        self.scripts: list[dict] = []
        self.default = {"text": "akış metni", "mode": "normal"}
        self.conns: list[dict] = []
        self.lock = threading.Lock()
        self.server = serve(self.handler, "127.0.0.1", 0, close_timeout=0.5)
        self.port = self.server.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}/v1/listen"

    def handler(self, ws):
        with self.lock:
            idx = len(self.conns)
            script = self.scripts[idx] if idx < len(self.scripts) else self.default
            conn = {"path": ws.request.path, "auth": ws.request.headers.get("Authorization"), "audio": bytearray(),
                    "keepalive": 0, "texts": [], "closed_by_client": False}
            self.conns.append(conn)
        mode = script.get("mode", "normal")
        try:
            for msg in ws:
                if isinstance(msg, bytes):
                    conn["audio"] += msg
                    if mode == "close_mid" and len(conn["audio"]) > 3200:
                        ws.socket.shutdown(socket.SHUT_RDWR)      # ağ kopması gibi: kapanış el sıkışması yok
                        return
                    if mode == "segments" and not conn.get("seg_sent") and len(conn["audio"]) > 6400:
                        conn["seg_sent"] = True
                        ws.send(json.dumps(result("birinci parça", True, conf=0.9, dur=0.2)))
                    continue
                data = json.loads(msg)
                conn["texts"].append(data.get("type"))
                if data["type"] == "KeepAlive":
                    conn["keepalive"] += 1
                elif data["type"] == "Finalize":
                    if mode == "slow":
                        time.sleep(0.6)
                    if mode == "error":
                        ws.send(json.dumps({"type": "Error", "description": "gecersiz istek"}))
                        continue
                    text = "" if mode == "empty" else script.get("text", "akış metni")
                    if mode == "segments":
                        text = "ikinci parça"
                    ws.send(json.dumps(result(text, True, conf=script.get("conf", 0.95), dur=0.6, from_finalize=True)))
                elif data["type"] == "CloseStream":
                    ws.send(json.dumps({"type": "Metadata", "request_id": "x"}))
                    ws.close()
                    return
        except Exception:  # noqa: BLE001 — istemci kapattı
            conn["closed_by_client"] = True

    def stop(self):
        self.server.shutdown()


def result(text, is_final, conf=0.95, dur=0.5, from_finalize=False):
    return {"type": "Results", "is_final": is_final, "from_finalize": from_finalize, "duration": dur,
            "channel": {"alternatives": [{"transcript": text, "confidence": conf}]}}


@pytest.fixture()
def dg(monkeypatch):
    srv = FakeDeepgram()
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-test")
    monkeypatch.setattr(remote.DeepgramSTT, "WS_URL", srv.url)
    yield srv
    srv.stop()


class BatchSpy:
    def __init__(self, text="toplu metin"):
        self.calls, self.text = [], text

    def __call__(self, audio, sample_rate, language="tr"):
        self.calls.append(np.array(audio))
        return STTResult(self.text, 0.01, "deepgram", "nova-3", {"confidence": 0.9})


def make_stt(monkeypatch, batch=None, **opts):
    opts.setdefault("streaming", True)
    opts.setdefault("stream_finish_timeout_s", 0.5)
    stt = remote.DeepgramSTT("nova-3", **opts)
    spy = batch or BatchSpy()
    monkeypatch.setattr(stt, "transcribe", spy)
    return stt, spy


class Out:
    def __init__(self):
        self.pushed, self.cb = [], None

    def set_on_drained(self, cb):
        self.cb = cb

    def push(self, pcm):
        self.pushed.append(pcm)

    def flush(self):
        self.pushed.clear()

    def mark_end(self):
        if self.cb:
            asyncio.get_running_loop().call_soon(self.cb)


def make_session(tmp_path, monkeypatch, stt):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))
    events = []
    s = VoiceSession("ss1", "A1S", stt, FakeLLM("m"), FakeTTS("m"), Out(), events.append)
    s.state = "listening"
    return s, events


def vad_payloads(audio):
    """Aynı girişte VAD'ın üreteceği konuşma sesleri (akışa giden sesle karşılaştırmak için)."""
    v, out = Endpointer(), []
    for i in range(0, len(audio) - FRAME + 1, FRAME):
        for k, p in v.feed(audio[i:i + FRAME]):
            if k == "end":
                out.append(p)
    return out


async def idle(s, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not s._tasks and s._held is None and s.state == "listening":
            return True
        await asyncio.sleep(0.01)
    return False


def users(s):
    return [t["text"] for t in s.transcript if t["role"] == "user"]


# ---- sağlayıcı düzeyi -----------------------------------------------------------------------------------------------
def test_live_stream_normal_transcript_query_and_auth(dg):
    stt = remote.DeepgramSTT("nova-3", streaming=True)
    st = stt.open_stream(16000, "tr")
    st.open()
    pcm = to_int16(speech(0.5)).tobytes()
    st.send(pcm)
    res = st.finish()
    assert res.text == "akış metni" and res.extra["confidence"] == pytest.approx(0.95) and res.extra["stream"] is True
    c = dg.conns[0]
    assert bytes(c["audio"]) == pcm and c["auth"] == "Token dg-test"
    for q in ("model=nova-3", "language=tr", "encoding=linear16", "sample_rate=16000", "channels=1", "smart_format=true",
              "punctuate=true", "interim_results=false", "endpointing=false"):
        assert q in c["path"], (q, c["path"])
    for _ in range(100):                               # sonuç geldikten sonra kapanış sunucuya biraz sonra ulaşır
        if st.closed_at is not None and len(c["texts"]) >= 2:
            break
        time.sleep(0.01)
    assert c["texts"][:2] == ["Finalize", "CloseStream"]
    assert st.billed_seconds() > 0 and st.sent_seconds == pytest.approx(0.5)


def test_live_stream_sends_keepalive_while_idle(dg):
    st = remote.DeepgramSTT("nova-3", streaming=True, stream_keepalive_s=0.05).open_stream()
    st.open()
    st.send(to_int16(speech(0.1)).tobytes())
    time.sleep(0.3)
    assert st.finish().text == "akış metni"
    assert dg.conns[0]["keepalive"] >= 2


def test_live_stream_joins_final_segments_and_weights_confidence(dg):
    dg.scripts = [{"mode": "segments", "conf": 0.5}]
    st = remote.DeepgramSTT("nova-3").open_stream()
    st.open()
    st.send(to_int16(speech(0.5)).tobytes())
    time.sleep(0.15)                                  # ilk parça sonucu gelsin
    res = st.finish()
    assert res.text == "birinci parça ikinci parça" and res.extra["segments"] == 2
    assert res.extra["confidence"] == pytest.approx((0.9 * 0.2 + 0.5 * 0.6) / 0.8)


@pytest.mark.parametrize("mode,needle", [("close_mid", "kapandı"), ("slow", "gelmedi"), ("error", "sunucu hatası")])
def test_live_stream_failures_raise_provider_error(dg, mode, needle):
    dg.scripts = [{"mode": mode}]
    st = remote.DeepgramSTT("nova-3", stream_finish_timeout_s=0.25).open_stream()
    st.open()
    st.send(to_int16(speech(0.5)).tobytes())
    time.sleep(0.1)
    t0 = time.perf_counter()
    with pytest.raises(ProviderError) as e:
        st.finish()
    assert needle in str(e.value) and time.perf_counter() - t0 < 0.5


def test_live_stream_connection_refused_raises_quickly(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "k")
    monkeypatch.setattr(remote.DeepgramSTT, "WS_URL", "ws://127.0.0.1:9/v1/listen")
    st = remote.DeepgramSTT("nova-3").open_stream()
    st.open()
    st.send(b"\x00\x00" * 160)
    with pytest.raises(ProviderError) as e:
        st.finish()
    assert "bağlantı açılamadı" in str(e.value) and st.billed_seconds() == 0.0


def test_streaming_option_reaches_stt_provider(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "k")
    a = registry.get_provider({"provider": "deepgram", "model": "nova-3"}, "stt", "A1")
    b = registry.get_provider({"provider": "deepgram", "model": "nova-3", "streaming": True}, "stt", "A1S")
    assert a is not b and a.streaming is False and b.streaming is True


# ---- oturum entegrasyonu --------------------------------------------------------------------------------------------
def test_session_uses_live_transcript_and_streams_exact_utterance_audio(tmp_path, monkeypatch, dg):
    stt, batch = make_stt(monkeypatch)
    s, events = make_session(tmp_path, monkeypatch, stt)
    audio = np.concatenate([silence(0.5), speech(1.0), silence(1.0)])

    async def go():
        s.feed(audio)
        assert await idle(s)
        await s.close()
    asyncio.run(go())
    assert users(s) == ["akış metni"] and batch.calls == []
    payload = vad_payloads(audio)[0]
    assert bytes(dg.conns[0]["audio"]) == to_int16(payload).astype("<i2").tobytes()   # ön kayıt dahil, toplu yolla aynı ses
    turn = next(t for t in s.turns if not t.get("greeting"))
    assert turn["stt_stream"] is True and "stt_fallback" not in turn and turn["stt_s"] < 1.0
    assert "stt_stream_fallbacks" not in s.stats
    rep = s._usage_report()["items"]
    assert rep["stt_calls"] == 1 and rep["stt_stream_calls"] == 1 and rep["stt_batch_minutes"] == 0
    assert rep["stt_minutes"] == rep["stt_stream_minutes"] > 0
    assert rep["stt_stream_audio_minutes"] == pytest.approx(len(payload) / 16000 / 60, abs=1e-4)


@pytest.mark.parametrize("script,reason", [({"mode": "empty"}, "empty"), ({"mode": "close_mid"}, "ProviderError"),
                                           ({"mode": "slow"}, "gelmedi"), ({"mode": "normal", "text": "你好"}, "guard:foreign_script"),
                                           ({"mode": "normal", "text": "merhaba", "conf": 0.2}, "guard:low_confidence")])
def test_session_falls_back_to_batch_with_full_audio(tmp_path, monkeypatch, dg, script, reason):
    dg.scripts = [script]
    stt, batch = make_stt(monkeypatch, stream_finish_timeout_s=0.25)
    s, events = make_session(tmp_path, monkeypatch, stt)
    audio = np.concatenate([silence(0.5), speech(1.0), silence(1.0)])

    async def go():
        s.feed(audio)
        assert await idle(s)
        await s.close()
    asyncio.run(go())
    assert users(s) == ["toplu metin"]
    assert len(batch.calls) == 1 and np.array_equal(batch.calls[0], vad_payloads(audio)[0])
    assert s.stats["stt_stream_fallbacks"] == 1 and reason in s.stats["stt_stream_fallback_reasons"][0]
    turn = next(t for t in s.turns if not t.get("greeting"))
    assert reason in turn["stt_fallback"]
    rep = s._usage_report()["items"]
    assert rep["stt_batch_minutes"] > 0 and rep["stt_minutes"] >= rep["stt_batch_minutes"]   # akış + yedek ikisi de faturalı
    assert not any(e["type"] == "error" for e in events)


def test_session_open_failure_uses_batch(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "k")
    stt, batch = make_stt(monkeypatch)
    monkeypatch.setattr(stt, "open_stream", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("açılmadı")))
    s, events = make_session(tmp_path, monkeypatch, stt)

    async def go():
        s.feed(np.concatenate([silence(0.5), speech(1.0), silence(1.0)]))
        assert await idle(s)
        await s.close()
    asyncio.run(go())
    assert users(s) == ["toplu metin"] and s.stats["stt_stream_open_failed"] == 1
    assert s.stats["stt_stream_fallbacks"] == 1 and "open_failed" in s.stats["stt_stream_fallback_reasons"][0]
    assert any(e["type"] == "stt_stream" for e in events)


def test_custom_endpointer_without_pending_audio_falls_back_safely(tmp_path, monkeypatch, dg):
    class OldVad(Endpointer):
        pending_audio = None                    # eski/özel endpointer: yöntem yok
    stt, batch = make_stt(monkeypatch)
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))
    s = VoiceSession("ss2", "A1S", stt, FakeLLM("m"), FakeTTS("m"), Out(), lambda e: None, endpointer=OldVad())
    s.state = "listening"

    async def go():
        s.feed(np.concatenate([silence(0.5), speech(1.0), silence(1.0)]))
        assert await idle(s)
        await s.close()
    asyncio.run(go())
    assert users(s) == ["toplu metin"] and s.stats["stt_stream_open_failed"] == 1


def test_two_utterances_in_one_call_use_two_streams_in_order(tmp_path, monkeypatch, dg):
    dg.scripts = [{"text": "birinci cevap"}, {"text": "ikinci cevap"}]
    stt, batch = make_stt(monkeypatch)
    s, _ = make_session(tmp_path, monkeypatch, stt)

    async def go():
        s.feed(np.concatenate([silence(0.5), speech(0.8), silence(1.0)]))
        assert await idle(s)
        s.feed(np.concatenate([speech(0.8), silence(1.0)]))
        assert await idle(s)
        await s.close()
    asyncio.run(go())
    assert users(s) == ["birinci cevap", "ikinci cevap"] and batch.calls == [] and len(dg.conns) == 2


def test_held_incomplete_then_continuation_streams_merged_audio(tmp_path, monkeypatch, dg):
    dg.scripts = [{"text": "evet ama"}, {"text": "evet ama fiyatlar yüksek"}]
    stt, batch = make_stt(monkeypatch)
    s, events = make_session(tmp_path, monkeypatch, stt)
    first = np.concatenate([silence(0.5), speech(0.8), silence(0.8)])
    second = np.concatenate([speech(0.8), silence(1.0)])

    async def go():
        s.feed(first)
        for _ in range(300):
            if s._held is not None:
                break
            await asyncio.sleep(0.005)
        assert s._held is not None                      # "ama" ile bitti: bekletiliyor
        held_audio = s._held[0]
        s.feed(second)                                  # HOLD_S dolmadan devam etti
        assert await idle(s)
        await s.close()
        return held_audio
    held_audio = asyncio.run(go())
    assert users(s) == ["evet ama fiyatlar yüksek"] and batch.calls == [] and s.stats["merged"] == 1
    p2 = vad_payloads(np.concatenate([first, second]))[1]
    assert bytes(dg.conns[1]["audio"]) == to_int16(np.concatenate([held_audio, p2])).astype("<i2").tobytes()


def test_hold_expiring_during_continuation_falls_back_to_batch(tmp_path, monkeypatch, dg):
    monkeypatch.setattr(session_mod, "HOLD_S", 0.05)
    dg.scripts = [{"text": "evet ama"}, {"text": "BU KULLANILMAMALI"}]
    stt, batch = make_stt(monkeypatch)
    s, _ = make_session(tmp_path, monkeypatch, stt)
    s.vad.configure(voiced_min=0)       # gürültü sinyaliyle söz kesme olsun (ajan bekletilen cümleye cevap verirken müşteri sürdürür)

    async def go():
        s.feed(np.concatenate([silence(0.5), speech(0.8), silence(0.8)]))
        for _ in range(300):
            if s._held is not None:
                break
            await asyncio.sleep(0.005)
        s.feed(speech(0.4))                             # devam başladı (akış bekletilen sesle açıldı)
        for _ in range(100):                            # bekletme konuşma sürerken doldu ve tek başına işlendi
            if s._held is None and not s._tasks:
                break
            await asyncio.sleep(0.01)
        s.feed(np.concatenate([speech(0.4), silence(1.0)]))
        assert await idle(s)
        await s.close()
    asyncio.run(go())
    assert users(s) == ["evet ama", "toplu metin"]      # akış içeriği eşleşmedi: eski yol (yalnız yeni ses, toplu)
    assert s.stats["stt_stream_merge_batch"] == 1 and len(batch.calls) == 1


def test_short_noise_drop_aborts_stream_and_meters_it(tmp_path, monkeypatch, dg):
    stt, batch = make_stt(monkeypatch)
    s, _ = make_session(tmp_path, monkeypatch, stt)

    async def go():
        s.feed(np.concatenate([silence(0.5), speech(0.1), silence(1.0)]))    # 160 ms'den kısa: drop
        await asyncio.sleep(0.05)
        await s.close()
    asyncio.run(go())
    assert batch.calls == [] and users(s) == [] and s.stats["dropped"] >= 1
    assert s.usage.stt["stream_aborted"] == 1 and s.usage.stt["calls"] == 0
    for _ in range(100):
        if dg.conns and dg.conns[0]["texts"] == [] and dg.conns[0]["closed_by_client"] is not None:
            break
        time.sleep(0.01)
    assert all("Finalize" not in c["texts"] for c in dg.conns)               # sonuç beklenmedi


def test_utterance_ending_while_agent_speaks_is_dropped_and_aborted(tmp_path, monkeypatch, dg):
    stt, batch = make_stt(monkeypatch)
    s, _ = make_session(tmp_path, monkeypatch, stt)
    s.vad.configure(barge_frames=50, voiced_min=0)        # söz kesme olmasın: konuşma ajan konuşurken biter

    async def go():
        s.state = "speaking"
        s.feed(np.concatenate([silence(0.5), speech(0.5, amp=0.02), silence(1.0)]))
        await asyncio.sleep(0.05)
        await s.close()
    asyncio.run(go())
    assert batch.calls == [] and users(s) == []
    assert s.usage.stt.get("stream_aborted", 0) >= 1 and s.stats["dropped"] >= 1


def test_streaming_flag_off_never_opens_a_websocket(tmp_path, monkeypatch, dg):
    stt, batch = make_stt(monkeypatch, streaming=False)
    s, _ = make_session(tmp_path, monkeypatch, stt)

    async def go():
        s.feed(np.concatenate([silence(0.5), speech(1.0), silence(1.0)]))
        assert await idle(s)
        await s.close()
    asyncio.run(go())
    assert users(s) == ["toplu metin"] and dg.conns == [] and "stream_s" not in s.usage.stt


def test_close_mid_utterance_aborts_live_stream(tmp_path, monkeypatch, dg):
    stt, batch = make_stt(monkeypatch)
    s, _ = make_session(tmp_path, monkeypatch, stt)

    async def go():
        s.feed(np.concatenate([silence(0.5), speech(0.6)]))   # konuşma sürüyor
        assert s._live is not None
        await s.close()
        assert s._live is None
    asyncio.run(go())
    assert s.usage.stt["stream_aborted"] == 1 and batch.calls == []


# ---- kullanım raporu ------------------------------------------------------------------------------------------------
def test_usage_report_unchanged_without_streaming_and_bills_stream_time_with_it():
    pricing = {"currency": "USD", "local_providers": [], "stt": {"deepgram:nova-3": {"usd": 0.0092, "verified": True}}}
    comps = {"stt": {"provider": "deepgram", "model": "nova-3"}, "llm": None, "tts": None}
    m = usage_mod.UsageMeter()
    m.add_stt(60.0, 1.0)
    r = usage_mod.report(m, duration_s=100, user_speech_s=60, agent_speech_s=0, components=comps, pricing=pricing)
    assert set(r["items"]) == {"duration_s", "user_speech_s", "agent_speech_s", "speech_share", "stt_minutes", "stt_calls",
                               "llm_calls", "llm_input_tokens", "llm_output_tokens", "tts_chars", "tts_calls", "tts_audio_s", "gpu_s"}
    assert r["items"]["stt_minutes"] == 1.0 and r["cost"]["by_component"]["stt"] == pytest.approx(0.0092)
    assert "akisli" not in r["cost"]["note"]
    m.add_stt_stream(50.0, 0.2, 66.0)
    m.add_stt_stream(0.1, 0.0, 6.0, aborted=True)
    r = usage_mod.report(m, duration_s=100, user_speech_s=60, agent_speech_s=0, components=comps, pricing=pricing)
    it = r["items"]
    assert it["stt_minutes"] == pytest.approx(2.2) and it["stt_stream_minutes"] == pytest.approx(1.2)
    assert it["stt_batch_minutes"] == 1.0 and it["stt_calls"] == 2 and it["stt_stream_calls"] == 1 and it["stt_stream_aborted"] == 1
    assert r["cost"]["by_component"]["stt"] == pytest.approx(2.2 * 0.0092) and "akisli" in r["cost"]["note"]
