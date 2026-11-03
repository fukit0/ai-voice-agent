"""Söz kesme: yüksek sesle / bağırarak konuşma (2026-11-03, oturumlar a75c42b14e09 ve 981040abd23b).

Kayıtlarda müşteri ajanın üstüne bağırarak konuştu; çerçeveler çok belirgin perdeli (0,93-1,00) ama açık ünlülerin F1'i yükseldiği için
enerjinin ≥400 Hz payı 0,5-0,9 idi. core-016 süzgeci (HF_MAX=0,30 üst sınırı) bunları 'sesli değil' saydı ve söz kesme ya hiç olmadı ya da
1,2 sn zorla kesmeye kadar gecikti. Düzeltme: perde ≥ PEAK_STRONG (0,90) ise HF üst sınırı uygulanmaz. Testler sentetik sesle; gerçek kayıt
önce/sonra ölçümü docs/soz-kesme-analizi-a75c42b14e09-981040abd23b.md içinde.
"""
import asyncio

import numpy as np
import pytest

from backend.app.voice import synthsounds as snd
from backend.app.voice.speechlike import PEAK_STRONG, features, is_voiced
from backend.app.voice.vad import BargeTracker, Endpointer
from backend.tests.test_voice import frames, make_session, settle, silence  # noqa: F401

SR = 16000


def raised_voice(seconds: float, rms: float = 0.2, f0: float = 110.0) -> np.ndarray:
    """Bağırarak söylenen açık ünlü benzeri: erkek temel frekansı, baskın F1 ≈700 Hz ve F2 ≈1200 Hz (enerjinin çoğu ≥400 Hz)."""
    n = int(SR * seconds)
    t = np.arange(n) / SR
    phase = 2 * np.pi * np.cumsum(f0 * (1 + 0.02 * np.sin(2 * np.pi * 5 * t))) / SR
    env = lambda f: 0.25 * np.exp(-((f - f0) / 60) ** 2) + np.exp(-((f - 700) / 150) ** 2) + 0.4 * np.exp(-((f - 1200) / 200) ** 2)  # noqa: E731
    x = sum(np.sin(k * phase) * env(k * f0) for k in range(1, int(3500 / f0)))
    x = x / np.sqrt(np.mean(x ** 2)) * rms
    return x.astype(np.float32)


def feed_until_barge(s, signal):
    for i, f in enumerate(frames(signal), 1):
        s.feed(f)
        if s.stats["barge_ins"]:
            return i
    return None


def test_raised_voice_signal_reproduces_the_recorded_feature_profile():
    fs = [features(f) for f in frames(raised_voice(0.5))]
    assert np.median([p for p, _, _ in fs]) >= 0.93          # çok belirgin perde (kayıtta 0,93-1,00)
    assert np.median([h for _, _, h in fs]) > 0.30           # ≥400 Hz payı HF_MAX'ın üstünde (kayıtta 0,5-0,9)


def test_raised_voice_frames_are_voiced_but_were_rejected_by_the_old_rule():
    fr = frames(raised_voice(0.5))
    assert np.mean([is_voiced(f) for f in fr]) >= 0.95
    assert np.mean([is_voiced(f, peak_strong=0) for f in fr]) <= 0.05     # eski kural: hata buradan doğuyordu


@pytest.mark.parametrize("name", sorted(snd.NON_SPEECH))
def test_strong_pitch_rule_does_not_make_non_speech_voiced(name):
    for rms in (0.1, 0.3):
        fr = frames(snd.NON_SPEECH[name](0.5, rms=rms))
        assert np.mean([is_voiced(f) for f in fr]) <= 0.10, name


def test_shouting_over_the_agent_interrupts_within_the_budget(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        assert s.state == "speaking"
        n = feed_until_barge(s, raised_voice(0.8, rms=0.2))
        assert n is not None and n * 20 <= 200, n                 # 160 ms koşu; core-002 sınırı 500 ms
        assert s.state == "listening" and s.stats["barge_blocked"] == 0
    asyncio.run(main())


def test_old_behavior_is_still_available_and_shows_the_bug(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        await s.start()
        await settle(s)
        s.set_vad({"peak_strong": 0})
        assert [e for e in events if e["type"] == "vad_settings"][-1]["peak_strong"] == 0.0
        s.feed(raised_voice(0.8, rms=0.2))                       # 1,2 sn zorla kesme süresinin altında
        assert s.stats["barge_ins"] == 0 and s.state == "speaking"
    asyncio.run(main())


def test_tracker_counts_raised_voice_as_voiced():
    v = Endpointer()
    g = BargeTracker(v)
    verdicts = []
    for i, f in enumerate(frames(raised_voice(0.4, rms=0.2))):
        v.feed(f)
        verdicts.append(g.update(f, i * 0.02))
    assert verdicts.index("barge") == v.barge_frames - 1


def test_peak_strong_setting_is_reported_and_clamped():
    v = Endpointer()
    assert v.settings()["peak_strong"] == PEAK_STRONG == 0.90
    assert v.configure(peak_strong=0.5)["peak_strong"] == 0.75     # PEAK_MIN'in altına inemez
    assert v.configure(peak_strong=1.7)["peak_strong"] == 1.0
    assert v.configure(peak_strong=0)["peak_strong"] == 0.0         # kapalı = eski davranış
    assert v.configure(peak_strong=-1)["peak_strong"] == 0.0
