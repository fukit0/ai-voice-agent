"""core-022: sessiz hat bekçisi."""
import asyncio

import numpy as np

from backend.app import scenario as S
from backend.app.providers.fake import FakeLLM
from backend.app.voice.flow import FlowDriver
from backend.app.voice.silence import SilenceGuard
from backend.tests.test_quickfixes import GeminiLikeFake  # noqa: F401
from backend.tests.test_realtime import build, settle_rt, user_says  # noqa: F401
from backend.tests.test_voice import env, make_session, settle, silence, speech  # noqa: F401


def test_guard_counts_only_quiet_listening_and_shortens_after_short_drop():
    g = SilenceGuard(silence_s=0.2, after_drop_s=0.1)       # 10 / 5 çerçeve
    assert not any(g.tick(True, False) for _ in range(9)) and g.tick(True, False)
    assert not any(g.tick(False, False) for _ in range(50))   # ajan konuşuyor: sayılmaz
    assert not any(g.tick(True, True) for _ in range(50))     # müşteri konuşuyor: sayılmaz
    g.note_drop()
    assert not any(g.tick(True, False) for _ in range(4)) and g.tick(True, False)


def test_flow_silence_reasks_once_then_closes_with_scenario_outcome():
    f = FlowDriver(S.get("anket"), FakeLLM("m"))
    f.start()
    first = f.current
    r1 = f.silence()
    assert r1.utterances[0].startswith("Sizi duyamadım") and f.current == first and not f.finished
    r2 = f.silence()
    assert f.finished and f.outcome == "sessiz_cagri" and any("Sesinizi alamadığım" in u for u in r2.utterances)
    w = FlowDriver(S.get("welcome"), FakeLLM("m"))
    w.start()
    w.silence()
    w.silence()
    assert w.finished and w.outcome == "sessiz_cagri"                 # welcome'da da sessiz hat kapanışı var
    g = FlowDriver(S.get("welcome"), FakeLLM("m"))
    g.start()
    g.steps.pop("kapanis_sessiz")                                      # senaryoda kapanış adımı yoksa genel kapanış
    g.silence()
    g.silence()
    assert g.finished and g.outcome == "sistem_sonlandirdi"


def test_real_answer_resets_the_silence_count():
    f = FlowDriver(S.get("anket"), FakeLLM("m"))
    f.start()
    f.silence()
    f.handle_structured({"intent": "repeat", "value": None}, "tekrar")
    assert f.silences == 0


def test_cascade_session_reasks_after_6s_silence_and_hangs_up_after_second(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        s.flow = FlowDriver(S.get("anket"), FakeLLM("m"))
        await s.start()
        await settle(s)
        s.state = "listening"
        s.feed(silence(5.0))
        assert not [e for e in events if e["type"] == "silence"]          # 6 sn dolmadı
        s.feed(silence(1.5))
        await settle(s)
        assert [e["count"] for e in events if e["type"] == "silence"] == [1]
        assert any("Sizi duyamadım" in e.get("text", "") for e in events if e["type"] == "transcript")
        assert not s.flow.finished
        s.state = "listening"
        s.feed(silence(6.5))
        await settle(s)
        assert s.flow.finished and s.flow.outcome == "sessiz_cagri"
    asyncio.run(main())


def test_short_unheard_sound_shortens_the_wait(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        s.flow = FlowDriver(S.get("anket"), FakeLLM("m"))
        await s.start()
        await settle(s)
        s.state = "listening"
        s.feed(np.concatenate([silence(0.3), speech(0.1, amp=0.3), silence(0.8)]))     # 100 ms: drop
        assert s.stats["dropped"] == 1
        s.feed(silence(3.2))
        await settle(s)
        assert [e["count"] for e in events if e["type"] == "silence"] == [1]           # 6 sn değil ≈ 4 sn sonra
    asyncio.run(main())


def test_no_silence_prompt_while_customer_is_talking_or_agent_speaking(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        s.flow = FlowDriver(S.get("anket"), FakeLLM("m"))
        await s.start()
        await settle(s)
        s.state = "speaking"
        s.feed(silence(9.0))
        assert not [e for e in events if e["type"] == "silence"]
    asyncio.run(main())


def test_realtime_session_reasks_on_silence(tmp_path, monkeypatch):
    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch)
        await s.start()
        await settle_rt(s, lambda: s.turns)
        out.cb()                                   # oynatma bitti -> dinliyor
        s.feed(silence(6.5))
        await settle_rt(s, lambda: len(backend.spoken) >= 2)
        assert backend.spoken[1][0].startswith("Sizi duyamadım")
        assert s.stats["silences"] == 1
        await s.close()
    asyncio.run(main())
