"""Canlı test 45e4e7002bc2 regresyonu: KVKK 'dinlemek ister misiniz?' sorusuna çıplak 'İstemiyorum.' ret değil, devam seçimidir;
yeniden sorulurken yalnız soru cümlesi okunur. (Gerçek LLM doğrulaması Mac'te; burada LLM'in refuse döndüğü kötü durum taklit edilir.)"""
import pytest

from backend.app import scenario as S
from backend.app.voice.flow import FlowDriver, bare_no_fix
from backend.tests.test_flow import ScriptedLLM, ans


def refuse():
    return '{"intent":"refuse","value":null}'


def driver(*outputs):
    llm = ScriptedLLM(outputs)
    return FlowDriver(S.get("anket"), llm), llm


GIRIS = next(s for s in S.get("anket")["steps"] if s["key"] == "giris")


@pytest.mark.parametrize("said", ["İstemiyorum.", "istemiyorum", "Hayır.", "Gerek yok.", "Dinlemek istemiyorum.", "Yok, istemem."])
def test_bare_no_continues_even_when_llm_says_refuse(said):
    d, _ = driver(refuse())
    d.start()
    r = d.handle(said)
    assert d.current == "musaitlik" and not r.finished and d.outcome is None
    assert any(e.get("type") == "crosscheck" and "bareNo" in e["fix"] for e in r.events)


@pytest.mark.parametrize("said", ["İlgilenmiyorum.", "Katılmak istemiyorum.", "Beni aramayın.", "Rahatsız etmeyin istemiyorum", "Anketi istemiyorum"])
def test_real_refusals_still_close_the_call(said):
    d, _ = driver(refuse())
    d.start()
    r = d.handle(said)
    assert r.finished and d.outcome == "katilmak_istemedi"


def test_positive_or_garbled_answers_are_not_rewritten():
    assert bare_no_fix(GIRIS, {"intent": "refuse", "value": None}, "Evet dinlemek istiyorum") == ({"intent": "refuse", "value": None}, None)
    assert bare_no_fix(GIRIS, {"intent": "unclear", "value": None}, "Debiyorum.")[1] is None          # STT çöpü: soru tekrar sorulur
    assert bare_no_fix(GIRIS, {"intent": "answer", "value": "dinle"}, "istemiyorum")[1] is None        # geçerli cevaba dokunulmaz
    other = next(s for s in S.get("anket")["steps"] if s["key"] == "musaitlik")
    assert bare_no_fix(other, {"intent": "refuse", "value": None}, "istemiyorum")[1] is None            # yalnız bareNo taşıyan adım


def test_reprompt_reads_only_the_question_not_the_whole_opening():
    d, _ = driver('{"intent":"unclear","value":null}')
    first = d.start().utterances[0]
    r = d.handle("Debiyorum.")
    spoken = r.utterances[0]
    assert spoken.startswith("Özür dilerim, tam anlayamadım. Aydınlatma Metni'ni dinlemek ister misiniz?")
    assert "Nielsen" not in spoken and len(spoken) < len(first) / 2
    assert "1'i" in spoken and "2'yi" in spoken                      # seçenekler hâlâ söyleniyor


def test_silence_reprompt_is_short_too_and_editor_override_wins():
    d, _ = driver()
    d.start()
    assert "Nielsen" not in d.silence().utterances[0]
    d2, _ = driver()
    d2.texts["giris"] = "Özel giriş metni. Dinlemek ister misiniz?"
    d2.start()
    assert d2.retry_of("giris") == "Özel giriş metni. Dinlemek ister misiniz?"   # editörden değişen metin kısa metinle ezilmez
