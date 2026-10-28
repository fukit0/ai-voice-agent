"""core-019: sabit yasal metinler (acilis, guvenlik_scripti) realtime profillerde OpenAI TTS sesiyle çalınır."""
import asyncio

import numpy as np

from backend.app import scenario as S
from backend.app.voice.fixedaudio import FixedAudio, fake_speech
from backend.app.voice.flow import FlowDriver
from backend.app.voice.realtime import FakeRealtime, RealtimeVoiceSession
from backend.tests.test_realtime import settle_rt
from backend.tests.test_voice import FakeOut


class SpyRealtime(FakeRealtime):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.said = []

    async def speak(self, text, rule):
        self.said.append(text)
        await super().speak(text, rule)


def build(tmp_path, monkeypatch, fetch, steps=("acilis", "guvenlik_scripti")):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path / "data"))
    backend = SpyRealtime()
    out, events = FakeOut(), []
    s = RealtimeVoiceSession("fx1", "RT", backend, out, events.append, FlowDriver(S.get("welcome"), None))
    s.fixed_audio = FixedAudio(steps=steps, fetch=fetch, cache_dir=tmp_path / "fx")
    return s, backend, out, events


def test_opening_text_is_played_from_openai_tts_not_from_the_model(tmp_path, monkeypatch):
    calls = []

    def fetch(text, model, voice):
        calls.append((text, model, voice))
        return fake_speech(text, model, voice)

    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch, fetch)
        await s.start()
        await settle_rt(s, lambda: s.turns)
        assert backend.said == []                                   # model hiçbir şey söylemedi
        assert len(calls) == 1 and calls[0][1] == "gpt-4o-mini-tts" and "sahibinden" in calls[0][0]
        assert out.pushed_samples > 0 if hasattr(out, "pushed_samples") else True
        turn = s.turns[0]
        assert turn["fixed_audio"] == "acilis" and turn["verbatim"] == 1.0
        assert s.stats["fixed_audio_turns"] == 1 and s._expect == "idle"
        await s.close()
    asyncio.run(main())


def test_second_call_with_same_text_uses_the_disk_cache(tmp_path, monkeypatch):
    calls = []

    def fetch(text, model, voice):
        calls.append(text)
        return fake_speech(text, model, voice)

    async def main():
        fa = FixedAudio(fetch=fetch, cache_dir=tmp_path / "c")
        a = await fa.get("Merhaba")
        b = await fa.get("Merhaba")
        assert a == b and len(calls) == 1 and fa.stats == {"hits": 1, "misses": 1, "errors": 0}
        assert await fa.get("Merhaba!") != None and len(calls) == 2         # metin değişince yeni dosya
        other_voice = FixedAudio(voice="cedar", fetch=fetch, cache_dir=tmp_path / "c")
        await other_voice.get("Merhaba")
        assert len(calls) == 3                                              # ses değişince önbellek paylaşılmaz
    asyncio.run(main())


def test_tts_failure_falls_back_to_the_model_and_is_reported(tmp_path, monkeypatch):
    def fetch(text, model, voice):
        raise RuntimeError("kota")

    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch, fetch)
        await s.start()
        await settle_rt(s, lambda: backend.said)
        assert backend.said and any(e["type"] == "fixed_audio_fallback" and e["step"] == "acilis" for e in events)
        assert s.stats["fixed_audio_fallbacks"] == 1 and s.fixed_audio.stats["errors"] == 1
        await s.close()
    asyncio.run(main())


def test_non_fixed_steps_and_disabled_option_use_the_model(tmp_path, monkeypatch):
    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch, fake_speech, steps=("guvenlik_scripti",))
        await s.start()
        await settle_rt(s, lambda: backend.said)
        assert len(backend.said) == 1 and "fixed_audio_turns" not in s.stats     # acilis sabit listede değil -> model
        await s.close()
    asyncio.run(main())
    assert FixedAudio.from_spec({"fixed_audio": False}) is None
    fa = FixedAudio.from_spec({"fixed_audio": {"steps": ["x"], "voice": "cedar"}})
    assert fa.applies("x") and not fa.applies("acilis") and fa.voice == "cedar"
    assert FixedAudio.from_spec({}).applies("guvenlik_scripti")


def test_barge_in_during_fixed_audio_discards_the_rest(tmp_path, monkeypatch):
    def long_fetch(text, model, voice):
        return (np.zeros(24000 * 20, np.int16)).tobytes()          # 20 sn

    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch, long_fetch)
        await s.start()
        s._drop_audio = True                                       # söz kesme: ses üretilirken bayrak kalkar
        await asyncio.sleep(0.5)
        assert "fixed_audio_turns" not in s.stats                  # kalan ses atıldı, tur tamamlanmış sayılmadı
        await s.close()
    asyncio.run(main())


def test_default_fixed_steps_cover_the_survey_intro_and_realtime_drops_foreign_transcripts(tmp_path, monkeypatch):
    """Canlı A2 oturumu d227e6c2553e: anket 'giris' adımı sabit listede değildi; model metni değiştirdi. A3 47e1691a1c69: yabancı yazı transkripti."""
    assert FixedAudio().applies("giris") and FixedAudio().applies("acilis") and FixedAudio().applies("guvenlik_scripti")

    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch, fake_speech)
        await s.start()
        await settle_rt(s, lambda: s.turns)
        await s._on_event({"type": "user_text", "text": "목동매는"})
        await s._on_event({"type": "user_text", "text": "evet"})
        assert s.stats["stt_rejected"] == 1 and s._last_user == "evet"
        assert any(e["type"] == "stt_rejected" and e["reason"] == "foreign_script" for e in events)
        assert not any("목동" in x["text"] for x in s.transcript)
        await s.close()
    asyncio.run(main())
