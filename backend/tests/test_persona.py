"""core-005: persona — doğrulama, istem üretimi, API, kademeli hatta onay sözü, cümle uzunluğu raporu."""
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import persona as P
from backend.app import scenario as S
from backend.app.main import app
from backend.app.voice.flow import FlowDriver

client = TestClient(app)


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    return tmp_path


def valid(**kw):
    return {**P.defaults(), **kw}


def test_default_persona_is_valid_and_prompt_reflects_fields(data):
    p = P.load()
    assert P.validate(p) == []
    text = P.system_prompt(valid(name="Ayşe", tone="resmi", address="siz", max_words_per_sentence=10, extra_rules="Asla tartışma."))
    assert "Ayşe adlı" in text and "resmî" in text and "en çok 10 kelime" in text and "yalnızca 'siz'" in text
    assert "Asla tartışma." in text and "Sayın müşterimiz" in text            # yasak kalıplar istemde
    assert P.greeting(valid(name="Ayşe")).startswith("Merhaba, ben Ayşe.")


@pytest.mark.parametrize("bad", [
    {"name": ""}, {"name": "A1"}, {"tone": "kaba"}, {"address": "x"}, {"max_words_per_sentence": 2},
    {"max_sentences": 9}, {"acknowledgements": [" "]}, {"acknowledgements": ["bir iki üç dört beş altı yedi sekiz dokuz on on bir on iki on üç on dört on beş"]},
    {"extra_rules": "x" * 601},
])
def test_validate_rejects_bad_values(bad):
    assert P.validate(valid(**bad)), bad


def test_api_get_put_reset_roundtrip(data):
    got = client.get("/api/persona").json()
    assert got["persona"]["name"] == "Ayşe" and "Ayşe adlı" in got["prompt"]
    body = {**got["persona"], "name": "Zeynep", "acknowledgements": ["Tamamdır."]}
    saved = client.put("/api/persona", json=body).json()
    assert saved["persona"]["name"] == "Zeynep" and saved["greeting"].startswith("Merhaba, ben Zeynep")
    assert json.loads((data / "persona.json").read_text(encoding="utf-8"))["name"] == "Zeynep"
    assert client.get("/api/persona").json()["persona"]["name"] == "Zeynep"          # kalıcı
    bad = client.put("/api/persona", json={**body, "name": "1"})
    assert bad.status_code == 422 and bad.json()["detail"]["problems"]
    assert client.post("/api/persona/reset").json()["persona"]["name"] == "Ayşe"
    assert not (data / "persona.json").exists()
    prev = client.post("/api/persona/preview", json={**body, "tone": "resmi"}).json()
    assert prev["problems"] == [] and "resmî" in prev["prompt"]
    assert client.post("/api/persona/preview", json={**body, "name": ""}).json()["problems"]


class _LLM:   # her cevabı answer olarak döndürür
    def complete(self, messages, *a, **k):
        from backend.app.providers.base import LLMResult
        return LLMResult(text='{"intent":"answer","value":true}', seconds=0.0)


def test_ack_is_spoken_before_next_question_only_when_persona_given(data):
    sc = S.get("anket")
    for persona, expect in ((None, False), (valid(acknowledgements=["Anladım."], reactions={}, reaction_rate=1.0), True)):
        fd = FlowDriver(sc, _LLM(), persona=persona)
        fd.start()
        rep = fd.handle_structured({"intent": "answer", "value": "devam"}, "devam")
        assert (rep.utterances[0] == "Anladım.") is expect, rep.utterances
        assert len(rep.utterances) >= 1
    fd = FlowDriver(sc, _LLM(), persona=valid(acknowledgements=["Anladım."], reactions={}, reaction_rate=1.0))
    fd.start()
    fd.coerce = True   # realtime yolu: onay sözü eklenmez
    assert "Anladım." not in fd.handle_structured({"intent": "answer", "value": "devam"}, "devam").utterances


def test_ack_rotates_and_empty_list_means_none():
    p = valid(acknowledgements=["A.", "B."])
    assert [P.ack(p, i) for i in range(4)] == ["A.", "B.", "A.", "B."]
    assert P.ack(valid(acknowledgements=[]), 0) is None


def test_sentence_stats_and_report_flag_violations(data):
    p = valid(max_words_per_sentence=6, avoid_phrases=["Sayın müşterimiz"])
    st = P.sentence_stats(["Merhaba, ben Ayşe. Sayın müşterimiz size çok uzun ve gereksiz bir cümle kuruyorum şimdi."], p)
    assert st["sentences"] == 2 and st["avg_words_per_sentence"] == 7.0 and st["max_words"] == 11
    assert len(st["over_limit"]) == 1 and st["avoid_hits"] == ["Sayın müşterimiz"] and st["over_limit_rate"] == 0.5
    folder = data / "voice-sessions"
    folder.mkdir()
    (folder / "abc123abc123.json").write_text(json.dumps({"id": "abc123abc123", "profile": "L2", "started_at": "2026-10-29T20:00:00",
        "transcript": [{"role": "agent", "text": "Merhaba, ben Ayşe."}, {"role": "user", "text": "çok uzun müşteri cümlesi sayılmaz bu"}]}),
        encoding="utf-8")
    rep = client.get("/api/persona/report").json()
    assert len(rep["sessions"]) == 1 and rep["sessions"][0]["sentences"] == 1 and rep["total"]["avg_words_per_sentence"] == 3.0


def test_speed_validation_and_default():
    assert P.defaults()["speed"] == 1.0 and P.validate(valid()) == []
    for bad in (0.5, 1.5, "hızlı", True):
        assert P.validate(valid(speed=bad)), bad
    assert P.validate(valid(speed=1.2)) == []


def test_ema_passes_speed_to_engine(monkeypatch):
    import sys
    import types

    import numpy as np

    from backend.app.providers.local import EmaTTS
    seen = {}

    class Engine:
        def say(self, text, speed=1.0, seed=None, sample_rate=48000, path=None):
            seen.update(text=text, speed=speed, sr=sample_rate)
            return types.SimpleNamespace(audio=np.zeros(240, dtype=np.float32))

    monkeypatch.setitem(sys.modules, "ema_lightning", types.SimpleNamespace(EMA=Engine))
    EmaTTS().synthesize("merhaba", "tr", 1.2)
    assert seen == {"text": "merhaba", "speed": 1.2, "sr": 24000}
    EmaTTS().synthesize("merhaba")
    assert seen["speed"] == 1.0


def test_elevenlabs_sends_speed_only_when_changed(monkeypatch):
    from backend.app.providers import remote
    from backend.app.providers.remote import ElevenLabsTTS
    sent = []

    class Res:
        content = b"\x00\x00" * 100

    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")
    monkeypatch.setattr(remote, "_post", lambda url, **kw: sent.append(kw["json"]) or Res())
    t = ElevenLabsTTS()
    t.synthesize("a")
    t.synthesize("b", "tr", 1.1)
    t.synthesize("c", "tr", 2.0)
    assert "voice_settings" not in sent[0]
    assert sent[1]["voice_settings"] == {"speed": 1.1} and sent[2]["voice_settings"] == {"speed": 1.2}   # sınırlanır



# --- hum-001: cevaba bağlı tepki (hibrit konuşma katmanı: akışı kod yönetir, LLM değil; tepki cümleleri havuzdan) ---
import random

STEP_SCORE = {"kind": "Score", "code": "Q2", "min": 1, "max": 10}


def test_bucket_of_uses_score_range_and_yesno():
    b = lambda step, v: P.bucket_of(step, v)   # noqa: E731
    assert [b(STEP_SCORE, v) for v in (1, 4, 5, 7, 8, 10)] == ["score_low", "score_low", "score_mid", "score_mid", "score_high", "score_high"]
    assert b({"kind": "Score", "code": "Q12", "min": 1, "max": 10}, 0) == "score_low"      # Q12 aralığı 0-10
    assert (b({"kind": "YesNo"}, True), b({"kind": "YesNo"}, False), b({"kind": "Choice"}, "x")) == ("yes", "no", "other")


def test_reaction_depends_on_answer_and_never_repeats_within_call():
    p = valid(reaction_rate=1.0, reactions={"score_high": ["A.", "B.", "C."], "score_low": ["L."]})
    used, rng = [], random.Random(1)
    got = [P.reaction(p, STEP_SCORE, 10, used, rng)[0] for _ in range(3)]
    assert sorted(got) == ["A.", "B.", "C."]                                   # havuz bitene kadar tekrar yok
    assert P.reaction(p, STEP_SCORE, 2, used, rng) == ("L.", "score_low")      # düşük puan başka kovadan
    nxt = [P.reaction(p, STEP_SCORE, 9, used, rng)[0] for _ in range(6)]       # havuz bitince: art arda aynı cümle olmaz
    assert all(a != b for a, b in zip([got[-1]] + nxt, nxt))


def test_reaction_rate_skips_some_and_falls_back_to_acks_without_pool():
    p = valid(reaction_rate=0.5, reactions={"yes": ["Y."]})
    rng = random.Random(7)
    outs = [P.reaction(p, {"kind": "YesNo"}, True, [], rng)[0] for _ in range(200)]
    assert 60 < sum(o is None for o in outs) < 140                              # yaklaşık yarısı sessiz
    q = valid(reaction_rate=1.0, reactions={}, acknowledgements=["Anladım."])
    assert P.reaction(q, STEP_SCORE, 9, [], random.Random(), 0) == ("Anladım.", "ack")   # eski davranış korunur
    assert P.reaction(valid(reaction_rate=1.0, reactions={}, acknowledgements=[]), STEP_SCORE, 9, [], random.Random()) == (None, None)


@pytest.mark.parametrize("bad", [
    {"reaction_rate": 1.5}, {"reaction_rate": True}, {"reactions": {"x": ["a."]}}, {"reactions": {"yes": ["Peki mi?"]}},
    {"reactions": {"yes": [" "]}}, {"reactions": {"yes": ["Sayın müşterimiz teşekkürler."]}},
    {"reactions": {"yes": ["bir iki üç dört beş altı yedi sekiz dokuz on on bir on iki on üç on dört on beş"]}},
])
def test_reaction_validation_rejects_bad_pools(bad):
    assert P.validate(valid(**bad)), bad


def test_default_reactions_are_valid_and_cover_every_bucket(data):
    p = P.load()
    assert P.validate(p) == [] and set(p["reactions"]) == set(P.REACTION_BUCKETS)
    assert all(len(v) >= 3 for k, v in p["reactions"].items() if k != "no")


def test_flow_speaks_bucketed_reaction_event_and_varies_across_a_call(data):
    sc = S.get("anket")
    p = valid(reaction_rate=1.0, reactions={"yes": ["Y1.", "Y2."], "other": ["O1.", "O2."]})
    fd = FlowDriver(sc, _LLM(), persona=p, rng=random.Random(3))
    fd.start()
    rep = fd.handle_structured({"intent": "answer", "value": "devam"}, "devam")
    ev = [e for e in rep.events if e["type"] == "reaction"]
    assert ev and ev[0]["bucket"] == "other" and ev[0]["text"] in ("O1.", "O2.") and ev[0]["text"] in rep.utterances
