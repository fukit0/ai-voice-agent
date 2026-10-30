"""core-016: akıllı söz kesme. Seviye eşiğini geçen ama konuşma benzemeyen sesler (öksürük, boğaz temizleme, klavye, kapı, nefes) ajanı kesmez;
konuşma benzeyen ses keser. NOT: sentetik işaretlerle doğrulanır, gerçek kayıtlarla (core-013) `scripts/eval_barge_gate.py` ile ayrıca ölçülmelidir."""
import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from backend.app.voice import synthsounds as snd
from backend.app.voice.realtime import RealtimeVoiceSession
from backend.app.voice.speechlike import is_voiced
from backend.app.voice.vad import Endpointer
from backend.tests.test_voice import FRAME, env, frames, make_session, settle, silence  # noqa: F401


def voiced_rate(x):
    fr = frames(x)
    return float(np.mean([is_voiced(f) for f in fr]))


@pytest.mark.parametrize("f0", [100.0, 140.0, 220.0])
def test_speech_like_frames_are_voiced(f0):
    assert voiced_rate(snd.voiced(1.0, 0.1, f0=f0)) >= 0.95
    assert voiced_rate(snd.voiced(1.0, 0.01, f0=f0)) >= 0.95          # düşük ses seviyesinde de (özellik seviyeden bağımsız)


@pytest.mark.parametrize("name", sorted(snd.NON_SPEECH))
def test_non_speech_frames_are_not_voiced(name):
    assert voiced_rate(snd.NON_SPEECH[name](0.5)) <= 0.10, name


def feed_until_barge(s, signal, max_frames=100):
    """Çerçeve çerçeve besler; kesme olduğu çerçeve sayısını döndürür (yoksa None)."""
    for i, f in enumerate(frames(signal), 1):
        s.feed(f)
        if s.stats["barge_ins"]:
            return i
    return None


@pytest.mark.parametrize("name", ["cough", "throat_clear", "keyboard", "door", "breath"])
def test_loud_non_speech_does_not_interrupt_the_agent(tmp_path, monkeypatch, name):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        assert s.state == "speaking"
        s.feed(snd.NON_SPEECH[name](0.5, rms=0.3))     # seviye eşiğinin çok üstünde
        s.feed(silence(0.3))
        assert s.stats["barge_ins"] == 0 and s.state == "speaking" and out.pushed, name
    asyncio.run(main())


def test_blocked_runs_are_counted_as_evidence(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        s.feed(snd.breath(0.5, rms=0.3))
        s.feed(silence(0.2))
        assert s.stats["barge_ins"] == 0 and s.stats["barge_blocked"] == 1
        assert any(e["type"] == "barge_blocked" for e in events)
    asyncio.run(main())


def test_speech_still_interrupts_within_the_500ms_budget(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        n = feed_until_barge(s, snd.voiced(0.6, 0.2))
        assert n is not None and n * 20 <= 200, n     # 160 ms koşu + sesli çerçeve payı; core-002 sınırı 500 ms
        assert s.stats["barge_blocked"] == 0
    asyncio.run(main())


def test_fricative_onset_then_vowel_interrupts_late_but_inside_budget(tmp_path, monkeypatch):
    """'ş' gibi perdesiz başlangıç (100 ms gürültü) + sesli ünlü: kesme sesli çerçeveler gelince olur, 500 ms sınırı içinde."""
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        n = feed_until_barge(s, np.concatenate([snd.breath(0.1, rms=0.2), snd.voiced(0.6, 0.2)]))
        assert n is not None and n * 20 <= 300, n
    asyncio.run(main())


def test_long_unvoiced_loud_input_eventually_interrupts_so_the_filter_cannot_mute_the_caller(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        n = feed_until_barge(s, snd.breath(2.0, rms=0.3))
        assert n is not None and n * 20 >= 1200, n      # force_ms (1,2 sn) dolunca
    asyncio.run(main())


def test_filter_can_be_turned_off_for_legacy_behavior(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        s.set_vad({"voiced_min": 0})
        s.feed(snd.breath(0.4, rms=0.3))
        assert s.stats["barge_ins"] == 1               # eski davranış: yalnız seviye + süre
        assert [e for e in events if e["type"] == "vad_settings"][-1]["voiced_min"] == 0
    asyncio.run(main())


def test_settings_report_and_clamp_voiced_min():
    v = Endpointer()
    assert v.settings()["voiced_min"] == 3 and v.settings()["force_ms"] == 1200
    assert v.configure(voiced_min=99)["voiced_min"] == 20
    assert v.configure(voiced_min=-4)["voiced_min"] == 0


def test_cough_during_thinking_does_not_cancel_the_pending_answer(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        s.state = "thinking"
        before = s._turn_id
        s.feed(snd.cough(0.5, rms=0.3))
        s.feed(silence(0.2))
        assert s._turn_id == before and s.state == "thinking" and s.stats["barge_ins"] == 0
    asyncio.run(main())


def test_gemini_style_server_interrupts_are_reported_as_ineffective():
    me = SimpleNamespace(backend=SimpleNamespace(local_turns=False))      # set_sensitivity yok = sunucu kendi VAD'iyle keser
    note = RealtimeVoiceSession._server_vad_note(me, {"effective_threshold_db": -40.0})
    assert "ETKİSİZ" in note and "core-016" in note
