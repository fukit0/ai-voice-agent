import json

import numpy as np
import pytest

from backend.app import scenario as S
from backend.app.providers.base import LLMResult
from backend.app.voice import phone
from backend.app.voice.flow import FALLBACK_CLOSE, FlowDriver, check_value


class ScriptedLLM:
    """Sırayla verilen JSON çıktılarını döndürür (metin = ham çıktı)."""
    kind, model = "scripted", "s"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def complete(self, messages, max_tokens=256, temperature=0.3):
        self.calls.append(messages)
        out = self.outputs.pop(0)
        return LLMResult(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False), 0.01, "scripted", "s")


def ans(value, intent="answer"):
    return {"intent": intent, "value": value}


def driver(*outputs, values=None):
    llm = ScriptedLLM(outputs)
    return FlowDriver(S.get("anket"), llm, values), llm


def test_start_reads_opening_question_with_filled_placeholders():
    d, _ = driver()
    r = d.start()
    assert d.current == "giris" and not r.finished
    assert r.utterances[0].startswith("İyi günler, benim adım Elif.")
    assert "{" not in r.utterances[0]
    assert r.events[0]["type"] == "node" and r.events[0]["key"] == "giris"


def test_complete_survey_records_typed_answers_and_ends_tamamlandi():
    d, llm = driver(
        ans("devam"), ans(True), ans(False), ans(True),            # giris, musaitlik, q3, q3x
        ans(8),                                                      # q2 (Score); q4 açık uçlu LLM çağırmaz
        ans(7), ans(8), ans(9), ans(6), ans(10),                    # q3_1..q3_5
        ans(45), ans(9), ans(10),                                    # q5 süre (sn), q6, q12 (NPS)
        ans(False), ans(True))                                       # geri_arama_istegi, onay
    d.start()
    said = []
    for text in ["hayır devam", "evet müsaitim", "hayır katılmadım", "evet hatırlıyorum", "sekiz veririm"]:
        said += d.handle(text).utterances
    # q2 cevabı {Q2} yer tutucusuna sözle girer: Q4 sorusu "sekiz" der
    assert any("performansını sekiz olarak değerlendirdiniz" in u for u in said)
    assert d.current == "q4" and len(llm.calls) == 5
    d.handle("çünkü çok yardımcı oldular")                           # açık uçlu: LLM çağrılmadan kaydedilir
    assert d.answers[-1]["value"] == "çünkü çok yardımcı oldular" and d.current == "q3_1" and len(llm.calls) == 5
    for text in ["yedi", "sekiz", "dokuz", "altı", "on", "kırk beş saniye", "dokuz", "on"]:
        d.handle(text)
    assert d.current == "q12_neden"
    d.handle("güvenilir bir site")                                    # q12_neden
    d.handle("eklemek istediğim bir şey yok")                         # q8
    d.handle("hayır aranmak istemem")                                 # geri_arama_istegi
    r = d.handle("evet paylaşabilirsiniz")                            # onay -> kapanış
    assert r.finished and d.outcome == "tamamlandi" and d.path[-1] == "kapanis" and not llm.outputs
    codes = [a["code"] for a in d.answers]
    assert codes[:3] == [None, None, "Q3"] and "Q4" in codes and "Q12_NEDEN" in codes
    assert next(a for a in d.answers if a["code"] == "Q5")["value"] == 45
    assert next(a for a in d.answers if a["code"] == "Q12")["value"] == 10
    assert next(a for a in d.answers if a["step"] == "geri_arama_istegi")["value"] is False
    assert r.events[-1] == {"type": "outcome", "outcome": "tamamlandi", "label": "Anket tamamlandı"}


def test_unclear_asks_again_differently_then_skips_open_score_question():
    d, _ = driver(ans("devam"), ans(True), ans(False), ans(True), "bu bir json değil",
                  ans(None, "unclear"), ans(None, "unclear"))
    d.start()
    for s in ["a", "b", "c", "d"]:
        d.handle(s)
    assert d.current == "q2"
    r1 = d.handle("hmm")
    assert r1.utterances[0].startswith("Özür dilerim, tam anlayamadım.") and d.current == "q2"
    r2 = d.handle("bilmem")
    assert r2.utterances[0].startswith("Kusura bakmayın, tekrar soruyorum.") and "bir ile on arasında" in r2.utterances[0]
    r3 = d.handle("yok")     # iki tekrardan sonra: "Cevap vermedi" dalı, Q4 atlanır
    assert d.answers[-1]["unanswered"] and d.answers[-1]["code"] == "Q2"
    assert d.current == "q3_1" and "Q4" not in [a["code"] for a in d.answers]
    assert any("Puanın" in e.get("title", "") for e in r3.events) is False  # q4 sorulmadı


def test_unclear_yes_no_three_times_closes_politely():
    d, _ = driver(ans(None, "unclear"), ans(None, "unclear"), ans(None, "unclear"))
    d.start()
    d.handle("x"), d.handle("y")
    r = d.handle("z")
    assert r.finished and d.outcome == "sistem_sonlandirdi" and r.utterances == [FALLBACK_CLOSE]


def test_repeat_does_not_consume_retries_and_rereads_question():
    d, _ = driver(ans(None, "repeat"), ans(None, "repeat"), ans("devam"))
    d.start()
    r = d.handle("tekrar")
    assert r.utterances == [d.text_of("giris")] and d.retries == 0
    d.handle("tekrar eder misiniz"); d.handle("devam")
    assert d.current == "musaitlik"


@pytest.mark.parametrize("intent,outcome", [("refuse", "katilmak_istemedi"), ("dnc", "aranmak_istemiyor")])
def test_refuse_and_do_not_call_end_with_global_exit(intent, outcome):
    d, _ = driver(ans("devam"), ans(True), ans(None, intent))
    d.start(); d.handle("a"); d.handle("b")
    r = d.handle("istemiyorum")
    assert r.finished and d.outcome == outcome


def test_callback_jumps_to_appointment_and_uses_spoken_time():
    d, _ = driver(ans("devam"), ans(None, "callback"), ans("yarın saat on beşte"))
    d.start(); d.handle("a")
    r = d.handle("şimdi müsait değilim sonra arayın")
    assert d.current == "randevu" and not r.finished
    r = d.handle("yarın saat on beşte")
    assert r.finished and d.outcome == "geri_arama"
    assert "yarın saat on beşte tekrar arayacağız" in r.utterances[-1]


def test_off_topic_returns_to_question_and_wrong_type_is_rejected():
    d, _ = driver(ans(None, "off_topic"), ans("9"))     # "9" metin: Score için geçersiz -> unclear gibi
    d.start()
    r = d.handle("siz kimsiniz")
    assert r.utterances[0].startswith("Sorunuzu not aldım") and d.current == "giris"
    r = d.handle("dokuz")
    assert r.utterances[0].startswith("Özür dilerim") or r.utterances[0].startswith("Kusura")


def test_check_value_is_strict():
    st = S.step_map(S.get("anket"))
    assert check_value(st["q2"], {"intent": "answer", "value": 8}) == (True, 8)
    assert check_value(st["q2"], {"intent": "answer", "value": 11})[0] is False
    assert check_value(st["q2"], {"intent": "answer", "value": True})[0] is False
    assert check_value(st["q12"], {"intent": "answer", "value": 0}) == (True, 0)      # NPS 0 geçerli
    assert check_value(st["musaitlik"], {"intent": "answer", "value": "evet"})[0] is False
    assert check_value(st["giris"], {"intent": "answer", "value": "dinle"}) == (True, "dinle")
    assert check_value(st["giris"], {"intent": "answer", "value": "belki"})[0] is False
    assert check_value(st["q2"], {"intent": "bilinmeyen", "value": None})[0] is False


def test_phone_filter_removes_low_and_high_frequencies_but_keeps_speech_band():
    rate = 16000
    t = np.arange(rate) / rate

    def power(sig, f):
        spec = np.abs(np.fft.rfft(sig))
        return spec[int(f)] / len(sig)

    low, mid, high = (np.sin(2 * np.pi * f * t).astype(np.float32) for f in (80, 1000, 6000))
    for tone, f, keep in ((low, 80, False), (mid, 1000, True), (high, 6000, False)):
        out = phone.apply(tone, rate)
        ratio = power(out, f) / power(tone, f)
        assert (ratio > 0.8) if keep else (ratio < 0.1), (f, ratio)
    f = phone.PhoneFilter(rate)       # akış (parçalı) ile bütün aynı sonuca yakın
    chunks = np.concatenate([f.process(mid[i:i + 320]) for i in range(0, rate, 320)])
    rms = lambda x: float(np.sqrt(np.mean(np.square(x[2000:]))))  # noqa: E731 — faz farkı olabilir, genlik aynı olmalı
    assert abs(rms(chunks) - rms(phone.apply(mid, rate))) < 0.03
