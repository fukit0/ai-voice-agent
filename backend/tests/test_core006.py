"""core-006: sessizlik kontrol cümlesi, 'müsait değilim' geri aramaya, 'bot musun?' dürüst cevap."""
import asyncio
import time

import pytest

from backend.app import scenario as S
from backend.app.providers.fake import FakeLLM
from backend.app.voice.flow import IDENTITY_ANSWER, MAX_IDENTITY_ASKS, FlowDriver, callback_phrase, identity_question
from backend.tests.test_flow import ScriptedLLM, ans, driver
from backend.tests.test_voice import env, make_session, settle, silence  # noqa: F401


# ---- 'Bot musun?' ----
@pytest.mark.parametrize("text", [
    "Bot musun?", "bot musunuz", "Robot musun sen?", "siz robot musunuz", "Yapay zekâ mısın?", "yapay zeka mısınız",
    "Gerçek bir insan mısınız?", "insan mısın", "gerçek kişi misiniz", "makine misin", "bilgisayar mısınız", "Bu bir robot mu?",
    "BOT MUSUN", "İnsan mısınız yoksa",
])
def test_identity_question_detected(text):
    assert identity_question(text)


@pytest.mark.parametrize("text", [
    "evet müsaitim", "sekiz", "robot süpürge aldım", "insanlar çok yardımcı oldu", "bot yok", "kayıt mı yapıyorsunuz", "yapay zekâ kullanıyorsunuz",
    "çok yardımcı oldular", "makineler bozuktu", "",
])
def test_identity_question_has_no_false_positives(text):
    assert not identity_question(text)


def test_bot_question_gets_honest_answer_without_llm_and_question_is_repeated():
    d, llm = driver()
    d.start()
    key = d.current
    r = d.handle("Bot musun sen?")
    assert llm.calls == []                                           # LLM'e gitmedi
    assert r.utterances[0] == IDENTITY_ANSWER
    assert "dijital asistan" in IDENTITY_ANSWER and "gerçek bir kişi değilim" in IDENTITY_ANSWER
    assert r.utterances[1] == d.retry_of(key)                         # bekleyen soru yeniden sorulur
    assert d.current == key and not d.answers and d.retries == 0 and not d.finished   # cevap sayılmaz, hak harcanmaz
    assert r.events[0]["type"] == "identity" and r.events[0]["step"] == key


def test_identity_answer_never_claims_to_be_human():
    low = IDENTITY_ANSWER.casefold()
    assert "insanım" not in low and "gerçek bir insan" not in low and "değilim" in low


def test_identity_cap_then_normal_flow_resumes():
    d, llm = driver(ans("devam"))
    d.start()
    said = []
    for _ in range(MAX_IDENTITY_ASKS):
        r = d.handle("bot musun")
        said.append(r.utterances[0])
        low = r.utterances[0].casefold()
        assert "yapay zek" in low or "dijital asistan" in low          # her seferinde dürüst: yapay zekâ olduğunu söyler
        assert "insanım" not in low and not d.finished and r.utterances[-1] == d.retry_of(d.current)
    # off-001: ilk cevap aynen IDENTITY_ANSWER; tekrar sorulunca aynı cümle art arda okunmaz (yine dürüst bir söyleyiş)
    assert said[0] == IDENTITY_ANSWER and all(said[i] != said[i + 1] for i in range(len(said) - 1))
    assert llm.calls == []
    d.handle("bot musun")                                             # sınır aşıldı: döngü yok, normal LLM yoluna gider
    assert len(llm.calls) == 1


def test_identity_question_resets_silence_count():
    d, _ = driver()
    d.start()
    d.silence()
    assert d.silences == 1
    d.handle("robot musunuz")
    assert d.silences == 0


# ---- 'Şu an müsait değilim' ----
@pytest.mark.parametrize("text", ["şu an müsait değilim", "Müsait değilim, sonra arayın", "şimdi uygun değilim", "meşgulüm", "daha sonra arayın",
                                  "başka bir zaman olur mu", "Şu an konuşamıyorum"])
def test_callback_phrases(text):
    assert callback_phrase(text)


@pytest.mark.parametrize("intent", ["refuse", "unclear", "off_topic"])
def test_not_available_goes_to_callback_even_if_llm_says_refuse(intent):
    d, _ = driver(ans("devam"), ans(True), ans(None, intent), ans("yarın saat on beşte"))
    d.start()
    d.handle("devam")
    d.handle("evet müsaitim")
    assert d.current == "q3"                                          # soru adımında
    r = d.handle("şu an müsait değilim")
    assert d.current == "randevu" and not d.finished and d.outcome != "reddetti"
    assert any(e.get("type") == "crosscheck" and "callback" in e["fix"] for e in r.events)
    d.handle("yarın saat on beşte")
    assert d.values.get("RANDEVU") == "yarın saat on beşte"


def test_explicit_refusal_is_not_turned_into_callback():
    d, _ = driver(ans("devam"), ans(True), ans(None, "refuse"))
    d.start()
    d.handle("devam")
    d.handle("evet müsaitim")
    d.handle("müsait değilim, ilgilenmiyorum")                        # görüşmenin kendisi reddedildi: ret kalır
    assert d.finished and d.outcome == "katilmak_istemedi"


def test_valid_answer_is_not_hijacked_by_callback_phrase():
    d, _ = driver(ans("devam"), ans(True), ans(False))
    d.start()
    d.handle("devam")
    d.handle("evet müsaitim")
    d.handle("hayır, meşgulüm ama katılmadım")                        # geçerli cevap (answer) korunur
    assert d.answers[-1]["value"] is False


# ---- sessizlik ----
def test_control_phrase_is_spoken_before_8_seconds_of_silence(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        s.flow = FlowDriver(S.get("anket"), FakeLLM("m"))
        await s.start()
        await settle(s)
        s.state = "listening"
        s.feed(silence(8.0))
        await settle(s)
        spoken = [e["text"] for e in events if e["type"] == "transcript" and e.get("role") == "agent"]
        assert [e["count"] for e in events if e["type"] == "silence"] == [1]
        assert any("Sizi duyamadım, sesiniz geliyor mu?" in t for t in spoken)
    asyncio.run(main())


# ---- oturum düzeyi: bot sorusu ----
def test_session_answers_bot_question_honestly(tmp_path, monkeypatch):
    async def main():
        s, out, events = make_session(tmp_path, monkeypatch)
        s.flow = FlowDriver(S.get("anket"), ScriptedLLM([]))           # LLM çağrılırsa IndexError: çağrılmamalı
        await s.start()
        await settle(s)
        s.state = "thinking"
        await s._flow_turn("Bot musun sen?", s._next_turn(), time.perf_counter(), {})
        await settle(s)
        assert [e["count"] for e in events if e["type"] == "identity"] == [1]
        spoken = " ".join(e["text"] for e in events if e["type"] == "transcript" and e.get("role") == "agent")
        assert "dijital asistanıyım" in spoken and "gerçek bir kişi değilim" in spoken
        assert not s.flow.finished and not s.flow.answers
    asyncio.run(main())
