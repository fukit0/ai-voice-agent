"""core-020 / core-023: ölçüm araçlarının hesabı (gerçek klip ve gerçek arama ölçümü kullanıcıdan gelir)."""
import json
import wave

import numpy as np

from backend.app.providers.base import STTProvider, STTResult
from backend.app.voice import realtime_report as RR
from backend.app.voice import stt_eval as E


class ScriptedSTT(STTProvider):
    kind = "scripted"

    def __init__(self, answers):
        super().__init__(None)
        self.answers, self.i = answers, 0

    def transcribe(self, audio, sample_rate, language="tr"):
        text, extra = self.answers[self.i]
        self.i += 1
        return STTResult(text=text, seconds=0.2, provider=self.kind, model="m", extra=extra)


def write_clips(tmp_path, rows):
    manifest = []
    for i, (text, cat) in enumerate(rows):
        f = tmp_path / f"c{i}.wav"
        with wave.open(str(f), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes((np.zeros(1600, np.int16)).tobytes())
        manifest.append({"file": f.name, "text": text, "category": cat})
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path / "manifest.json"


def test_wer_guard_rates_and_recommendation(tmp_path):
    clips = E.load_manifest(write_clips(tmp_path, [
        ("on", "rakam"), ("evet", "evet_hayir"), ("okay", "kod_karisimi"), ("", "oksuruk"), ("", "gurultu")]))
    stt = ScriptedSTT([("on", {"confidence": 0.9}),                     # doğru
                       ("evet", {"confidence": 0.9}),                   # doğru
                       ("okey", {"confidence": 0.4}),                   # yanlış + düşük güven -> doğru reddedilir
                       ("merhaba teşekkür", {"confidence": 0.3}),       # öksürük yazıya döküldü, reddedilmeli
                       ("谢谢", {"confidence": 0.8})])                   # yabancı yazı
    rep = E.evaluate(clips, {"S": stt})
    p = rep["providers"]["S"]
    assert p["clips"] == 5 and p["enough_clips"] is False
    assert p["exact_match_rate"] == 0.667                                # 2/3 cevap klibi
    assert p["foreign_script_rate"] == 0.2 and p["noise_transcribed_rate"] == 1.0
    g = p["guard_default"]
    assert g["bad_clips"] == 3 and g["true_reject_rate"] == 1.0 and g["false_reject_rate"] == 0.0
    silent = [{"file": "x", "category": "oksuruk", "reference": "", "hypothesis": "", "seconds": 0.1,
               "extra": {"confidence": 0.0}, "should_reject": True}]
    assert E.guard_rates(silent)["good_clips"] == 0 and E.guard_rates(silent)["bad_clips"] == 0     # boş dönüş doğru: yanlış ret değil
    assert p["recommended_thresholds"]["false_reject_rate"] <= 0.05
    text = E.render(rep)
    assert "örnek yetersiz (5/50 klip)" in text


def test_guard_thresholds_are_restored_after_sweep(tmp_path):
    from backend.app.voice import sttguard
    before = (sttguard.MIN_CONFIDENCE, sttguard.MIN_AVG_LOGPROB, sttguard.MAX_COMPRESSION)
    rows = [{"file": "x", "category": "rakam", "reference": "on", "hypothesis": "on", "seconds": 0.1,
             "extra": {"confidence": 0.45}, "should_reject": False}]
    assert E.guard_decision(rows[0]) == "low_confidence"
    assert E.guard_decision(rows[0], {"min_confidence": 0.4}) is None
    E.threshold_sweep(rows)
    assert (sttguard.MIN_CONFIDENCE, sttguard.MIN_AVG_LOGPROB, sttguard.MAX_COMPRESSION) == before


def test_missing_clip_is_reported(tmp_path):
    (tmp_path / "m.json").write_text(json.dumps([{"file": "yok.wav", "text": "on", "category": "rakam"}]))
    try:
        E.load_manifest(tmp_path / "m.json")
        raise AssertionError("beklenen hata gelmedi")
    except FileNotFoundError as exc:
        assert "yok.wav" in str(exc)


def test_realtime_report_counts_tool_calls_completion_and_language():
    docs = [
        {"profile": "A3", "id": "a", "stats": {"tool_calls": 2, "invalid_tool_calls": 0},
         "turns": [{"greeting": True, "realtime": True}, {"realtime": True, "tool_args": {}}, {"realtime": True, "tool_args": {}}],
         "transcript": [{"role": "user", "text": "evet"}, {"role": "user", "text": "hola gracias"}],
         "flow": {"outcome": "tamamlandi"}, "errors": []},
        {"profile": "A3", "id": "b", "stats": {"tool_calls": 0, "invalid_tool_calls": 1},
         "turns": [{"realtime": True, "no_tool_call": True}, {"realtime": True, "tool_args": {}}],
         "transcript": [{"role": "user", "text": "谢谢"}], "flow": {"outcome": None}, "errors": ["x"]},
        {"profile": "A2", "id": "c", "stats": {}, "turns": [], "transcript": [], "flow": {}},
    ]
    rep = RR.summarize(docs, "A3")
    assert rep["sessions"] == 2 and rep["enough_sessions"] is False
    assert rep["answer_turns"] == 4 and rep["tool_call_rate"] == 0.75
    assert rep["completion_rate"] == 0.5 and rep["outcomes"] == {"tamamlandi": 1, "bitmedi": 1}
    assert rep["foreign_or_non_turkish_transcript_rate"] == 0.667 and rep["sessions_with_errors"] == 1
    assert "örnek yetersiz" in RR.render(rep)
    assert RR.language_flags("Evet, müsaitim") == []
