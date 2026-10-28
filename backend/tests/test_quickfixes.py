"""Canlı test bulgularının hızlı düzeltmeleri (2026-10-28): Gemini çağrı kapısı, yarı-dupleks gönderim, STT geçidi, kısa cevaplar."""
import asyncio
import json

import numpy as np

from backend.app import scenario as S
from backend.app.providers.base import STTProvider, STTResult
from backend.app.voice import sttguard
from backend.app.voice.flow import FlowDriver
from backend.app.voice.realtime import FakeRealtime, RealtimeVoiceSession, TOOL_NAME
from backend.app.voice.vad import FRAME, Endpointer
from backend.tests.test_realtime import build, settle_rt, user_says  # noqa: F401
from backend.tests.test_voice import FakeOut, env, frames, make_session, settle, silence, speech  # noqa: F401


# ---- A3 (Gemini): konuşma bitişi olayı yok, çağrının kendisi cevap turudur --------------------------------------------
class GeminiLikeFake(FakeRealtime):
    """Gemini benzeri: speech_stopped üretmez, auto_answer yok; konuşma sonrası doğrudan fonksiyon çağırır."""
    auto_answer = False

    async def send_audio(self, pcm16: bytes) -> None:
        a = np.frombuffer(pcm16, np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(a * a))) if len(a) else 0.0
        if rms > 0.02:
            self._loud += 1
            self._quiet = 0
            self._in_speech = self._loud >= 3
        else:
            self._quiet += 1
            if self._in_speech and self._quiet >= 25:
                self._in_speech = False
                self._loud = 0
                self._n_calls += 1
                self._q.put_nowait({"type": "tool_call", "id": f"call{self._n_calls}", "name": TOOL_NAME,
                                    "args": {"intent": "answer", "value": True}})
                self._q.put_nowait({"type": "response_done"})


def test_gemini_style_tool_call_without_speech_stopped_advances_flow_and_is_acknowledged(tmp_path, monkeypatch):
    async def main():
        monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path / "data"))
        events, out = [], FakeOut()
        backend = GeminiLikeFake("m")
        s = RealtimeVoiceSession("g1", "RT", backend, out, events.append, FlowDriver(S.get("welcome"), None))
        await s.start()
        await settle_rt(s, lambda: s.turns)
        first = s.flow.current
        await user_says(s, out)
        await settle_rt(s, lambda: len(s.turns) == 2)
        assert s.flow.current != first and s.stats["tool_calls"] == 1      # akış ilerledi
        assert backend.results == ["call1"]                                 # toolResponse gönderildi
        await s.close()
    asyncio.run(main())


def test_unexpected_tool_call_while_speaking_is_acknowledged_not_dropped(tmp_path, monkeypatch):
    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch)
        await s.start()
        s._expect = "speak"
        await s._on_tool_call({"type": "tool_call", "id": "x1", "name": TOOL_NAME, "args": {"intent": "answer", "value": True}})
        assert backend.results == ["x1"] and s.stats["tool_calls"] == 0
    asyncio.run(main())


# ---- A2: yarı-dupleks ----------------------------------------------------------------------------------------------
def test_server_gets_silence_while_agent_speaks_and_audio_when_listening(tmp_path, monkeypatch):
    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch)
        sent = []
        orig = backend.send_audio

        async def spy(pcm):
            sent.append(float(np.abs(np.frombuffer(pcm, np.int16)).max()))
            await orig(pcm)
        backend.send_audio = spy
        await s.start()
        s.state = "speaking"
        s.feed(speech(0.2, amp=0.3))
        await asyncio.sleep(0.2)
        assert sent and max(sent) == 0.0                    # ajan konuşurken sunucu sessizlik duyar
        sent.clear()
        s.state = "listening"
        s.feed(speech(0.2, amp=0.3))
        await asyncio.sleep(0.2)
        assert sent and max(sent) > 1000                    # dinlerken gerçek ses gider
        await s.close()
    asyncio.run(main())


def test_speech_stopped_while_agent_is_speaking_is_not_taken_as_an_answer(tmp_path, monkeypatch):
    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch)
        await s.start()
        s._expect = "idle"
        s.state = "speaking"                                # yanıt üretimi bitti ama ses hâlâ çalıyor
        await s._on_event({"type": "speech_stopped"})
        assert s._expect == "idle"                          # sahte tur açılmadı
        s.state = "listening"
        await s._on_event({"type": "speech_stopped"})
        assert s._expect == "answer"
        await s.close()
    asyncio.run(main())


def test_dropped_counter_counts_only_drops_and_agent_text_gives_verbatim_ratio(tmp_path, monkeypatch):
    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch)
        await s.start()
        await settle_rt(s, lambda: s.turns)
        assert s.stats["dropped"] == 0                      # 'start' olayları artık 'dropped' sayılmıyor
        s._expect, s._rec, s._last_spoken, s._first_audio = "speak", {"turn": 9}, "Merhaba Ahmet Bey nasılsınız", 1.0
        await s._on_event({"type": "agent_text", "text": "Merhaba Ahmet Bey nasılsınız"})
        await s._on_response_done()
        assert s.turns[-1]["verbatim"] == 1.0 and s.turns[-1]["agent_said"].startswith("Merhaba")
        await s.close()
    asyncio.run(main())


# ---- VAD: kısa cevaplar ("on", "evet") -------------------------------------------------------------------------------
def test_short_one_word_answer_is_not_dropped():
    v = Endpointer()
    audio = np.concatenate([silence(0.5), speech(0.24, amp=0.25), silence(1.0)])     # 240 ms, ≈ -12 dBFS
    out = []
    for f in frames(audio):
        out += [k for k, _ in v.feed(f)]
    assert out == ["start", "end"]
    short = np.concatenate([silence(0.5), speech(0.1, amp=0.25), silence(1.0)])      # 100 ms: yine de tık/öksürük sayılır
    v2 = Endpointer()
    out2 = []
    for f in frames(short):
        out2 += [k for k, _ in v2.feed(f)]
    assert "end" not in out2


# ---- STT geçidi -----------------------------------------------------------------------------------------------------
def test_sttguard_rejects_foreign_script_hallucinations_and_low_confidence_but_keeps_short_answers():
    for bad in ("擊", "своей eş gamers", "Birון Peki Artem", "Çocuklar email vermenção five ok vermen", "¿Qué?",
                "Altyazı M.K.", "İzlediğiniz için teşekkür ederim.", "abone ol"):
        assert sttguard.check(bad)[0] is False, bad
    for good in ("On.", "Evet müsaitim.", "Dinlemek isterim.", "yedi sekiz arası", "Müşteri memnuniyetini ön planda tutan bir firma"):
        assert sttguard.check(good) == (True, None), good
    assert sttguard.check("Merhaba, teşekkür", {"confidence": 0.3}) == (False, "low_confidence")
    assert sttguard.check("Merhaba, teşekkür", {"confidence": 0.9})[0] is True
    assert sttguard.check("tamam", {"avg_logprob": -1.4}) == (False, "low_logprob")
    assert sttguard.check("tamam", {"compression_ratio": 3.0}) == (False, "high_compression")


class ScriptedSTT(STTProvider):
    kind = "script_stt"

    def __init__(self, items):
        super().__init__("m")
        self.items = list(items)

    def transcribe(self, audio, sample_rate, language="tr"):
        text, extra = self.items.pop(0)
        return STTResult(text, 0.01, self.kind, self.model, extra)


def test_cascade_rejects_garbage_transcript_as_unclear_and_reasks_without_recording_an_answer(tmp_path, monkeypatch):
    async def main():
        stt = ScriptedSTT([("擊", {}), ("Evet.", {})])
        s, out, events = make_session(tmp_path, monkeypatch, stt=stt)
        from backend.app.providers.fake import FakeLLM
        s.flow = FlowDriver(S.get("welcome"), FakeLLM("m"))
        await s.start()
        await settle(s)
        s.state = "listening"
        first = s.flow.current
        s.feed(np.concatenate([silence(0.3), speech(0.8, amp=0.2), silence(1.0)]))
        await settle(s)
        rej = [e for e in events if e["type"] == "stt_rejected"]
        assert rej and rej[0]["reason"] == "foreign_script"
        assert s.flow.answers == [] and s.flow.current == first and s.flow.retries == 1      # cevap kaydedilmedi, tekrar soruldu
        assert s.stats["stt_rejected"] == 1
    asyncio.run(main())


def test_sttguard_rejects_repetition_loops_but_keeps_real_answers():
    """core-020 ölçümü: Whisper öksürükte 'Hıhıhı…' döngüsü üretti; metin değil, reddedilmeli."""
    from backend.app.voice import sttguard
    assert sttguard.check("Hı" + "hı" * 40)[1] == "repetition_loop"
    assert sttguard.check("Kıhıhıhıhıhıhıhıhıhıhıhıhıhıhıhıhı")[1] == "repetition_loop"
    for ok in ("evet evet", "hayır hayır hayır", "on", "yedi sekiz arası", "okay devam", "tamam tamam tamam"):
        assert sttguard.check(ok) == (True, None), ok
