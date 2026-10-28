"""core-018: A2'de tur sınırlarını yerel VAD verir (sunucu VAD'ı kapalı)."""
import asyncio

import numpy as np

from backend.app import scenario as S
from backend.app.voice.flow import FlowDriver
from backend.app.voice.realtime import FakeRealtime, OpenAIRealtime, RealtimeVoiceSession, TOOL_NAME, make_backend
from backend.tests.test_realtime import Sent, settle_rt, user_says  # noqa: F401
from backend.tests.test_voice import FakeOut, env, silence, speech  # noqa: F401


class LocalTurnFake(FakeRealtime):
    """OpenAI benzeri, sunucu VAD'ı yok: tur yalnızca commit + cevap isteğiyle başlar."""
    local_turns = True
    auto_answer = True

    def __init__(self, model="m", script=None):
        super().__init__(model, script)
        self.log = []

    async def send_audio(self, pcm16: bytes) -> None:
        self.log.append(("audio", float(np.abs(np.frombuffer(pcm16, np.int16)).max())))

    async def commit_audio(self) -> None:
        self.log.append(("commit", 0))

    async def clear_audio(self) -> None:
        self.log.append(("clear", 0))

    async def request_answer(self) -> None:
        self.log.append(("answer", 0))
        await self.inject_user_text("evet")


def make_session(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path / "data"))
    events, out = [], FakeOut()
    s = RealtimeVoiceSession("lt1", "RT", backend, out, events.append, FlowDriver(S.get("welcome"), None))
    return s, out, events


def test_openai_local_turns_disables_server_vad_and_exposes_commit_and_clear():
    b = OpenAIRealtime("m")
    assert b.local_turns is True and OpenAIRealtime("m", local_turns=False).local_turns is False
    b.ws = Sent()
    asyncio.run(b.commit_audio())
    asyncio.run(b.clear_audio())
    assert [m["type"] for m in b.ws.msgs] == ["input_audio_buffer.commit", "input_audio_buffer.clear"]
    assert make_backend({"provider": "openai_realtime", "model": "x", "local_turns": False}).local_turns is False
    assert make_backend({"provider": "openai_realtime", "model": "x"}).local_turns is True


def test_local_end_commits_then_requests_answer_and_flow_advances(tmp_path, monkeypatch):
    async def main():
        backend = LocalTurnFake()
        s, out, events = make_session(tmp_path, monkeypatch, backend)
        await s.start()
        await settle_rt(s, lambda: s.turns)
        first = s.flow.current
        await user_says(s, out)
        await settle_rt(s, lambda: len(s.turns) == 2)
        kinds = [k for k, _ in backend.log]
        assert "commit" in kinds and kinds.index("commit") < kinds.index("answer")      # önce commit, sonra cevap isteği
        assert s.flow.current != first and s.stats["tool_calls"] == 1
        await s.close()
    asyncio.run(main())


def test_short_noise_is_cleared_from_server_buffer_and_never_becomes_a_turn(tmp_path, monkeypatch):
    async def main():
        backend = LocalTurnFake()
        s, out, events = make_session(tmp_path, monkeypatch, backend)
        await s.start()
        await settle_rt(s, lambda: s.turns)
        out.cb()
        backend.log.clear()
        s.feed(np.concatenate([silence(0.3), speech(0.1, amp=0.3), silence(1.0)]))     # 100 ms tık: drop
        await asyncio.sleep(0.2)
        kinds = [k for k, _ in backend.log]
        assert "clear" in kinds and "commit" not in kinds and "answer" not in kinds
        assert s.stats["tool_calls"] == 0
        await s.close()
    asyncio.run(main())


def test_audio_is_silent_while_agent_speaks_and_barge_in_catches_up_with_the_last_400ms(tmp_path, monkeypatch):
    async def main():
        backend = LocalTurnFake()
        s, out, events = make_session(tmp_path, monkeypatch, backend)
        await s.start()
        await settle_rt(s, lambda: s._first_audio is not None)
        await asyncio.sleep(0.1)
        backend.log.clear()
        s.feed(speech(0.4, amp=0.3))                       # ajan konuşurken müşteri konuşmaya başlar -> söz kesme
        await asyncio.sleep(0.2)
        assert s.stats["barge_ins"] == 1
        audio = [v for k, v in backend.log if k == "audio"]
        assert audio and max(audio) > 1000                 # yetiştirilen gerçek ses sunucuya gitti (ilk kelimeler kaybolmadı)
        kinds = [k for k, _ in backend.log]
        assert "clear" in kinds
        assert s._expect == "idle"
        await s.close()
    asyncio.run(main())


def test_openai_turn_detection_is_null_when_local_and_server_vad_otherwise(monkeypatch):
    import websockets
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class Ws(Sent):
        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(3600)

    for local in (True, False):
        ws = Ws()

        async def fake_connect(url, **kw):
            return ws
        monkeypatch.setattr(websockets, "connect", fake_connect)

        async def go():
            b = OpenAIRealtime("m", local_turns=local)
            await b.connect("talimat")
            await b.close()
        asyncio.run(go())
        td = ws.msgs[0]["session"]["audio"]["input"]["turn_detection"]
        if local:
            assert td is None
        else:
            assert td["type"] == "server_vad" and td["create_response"] is False and td["interrupt_response"] is False
