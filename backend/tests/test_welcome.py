"""lab-003 devamı: Welcome Call senaryosu (referans panelin ikinci senaryosu, Premium Plus yeni mağaza bilgilendirmesi)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import scenario as S
from backend.app.main import app
from backend.tests.test_flow import ScriptedLLM, ans
from backend.app.voice.flow import FlowDriver, QUESTION_NOTED, check_value


def driver(*outputs):
    llm = ScriptedLLM(outputs)
    return FlowDriver(S.get("welcome"), llm), llm


def run(d, *outputs_and_texts):
    for t in outputs_and_texts:
        r = d.handle(t)
    return r


def test_welcome_is_valid_and_listed_next_to_anket():
    sc = S.get("welcome")
    assert S.validate(sc) == [] and len(sc["steps"]) == 24 and len(sc["outcomes"]) == 9
    assert {"anket", "welcome"} <= set(S.load_all())
    assert S.unknown_placeholders(sc, " ".join(s["defaultText"] for s in sc["steps"])) == []
    kinds = {s["kind"] for s in sc["steps"]}
    assert kinds == {"YesNo", "Statement", "CheckIn", "CallbackTime", "Terminal"}
    c = TestClient(app)
    lst = c.get("/api/scenarios").json()
    assert any(x["key"] == "welcome" and x["steps"] == 24 for x in lst)
    assert c.get("/api/scenarios/welcome").status_code == 200


def test_opening_confirms_person_then_reads_security_script_and_asks_welcome():
    d, _ = driver()
    r = d.start()
    assert d.current == "acilis" and "{" not in r.utterances[0]
    assert d.sc["steps"][0]["key"] == "acilis"


def test_branch_a_new_to_website_with_2fa_completes():
    d, llm = driver(ans(True), ans(True),                       # acilis, hosgeldin
                    ans(False), ans(False), ans(False), ans(False),  # paket, taahhüt, kurallar, özellikler: soru yok
                    ans(False),                                 # web_bilgi: Hayır -> web_bilgilendirme
                    ans(False), ans(False),                     # web_bilgilendirme, afis_branda
                    ans(True), ans(False), ans(False))  # iki_fa: Evet -> adımlar; adımlar; arama_dogrulama
    d.start()
    for t in ["evet benim", "evet buyurun", "tamam", "tamam", "tamam", "tamam", "bilmiyorum", "tamam", "tamam",
              "evet açalım", "devam", "anladım"]:
        r = d.handle(t)
    assert r.finished and d.outcome == "tamamlandi" and d.path[-1] == "kapanis"
    assert "web_bilgilendirme" in d.path and "web_soru" not in d.path          # dal: web sitesi hizmetini bilmiyor
    assert "iki_fa_adimlar" in d.path and "paket_taahhutsuz" not in d.path      # taahhütlü profil
    assert not llm.outputs
    assert next(a for a in d.answers if a["step"] == "web_bilgi")["value"] is False


def test_branch_b_knows_website_and_declines_2fa_skips_steps():
    d, _ = driver(ans(True), ans(True), ans(False), ans(False), ans(False), ans(False),
                  ans(True), ans(False), ans(False), ans(False), ans(False))
    d.start()
    for t in ["evet", "evet", "t", "t", "t", "t", "biliyorum", "tamam", "tamam", "hayır istemiyorum", "tamam"]:
        r = d.handle(t)
    assert r.finished and d.outcome == "tamamlandi"
    assert "web_soru" in d.path and "web_bilgilendirme" not in d.path
    assert "iki_fa_adimlar" not in d.path and "guvenlik_uyarilari" in d.path


def test_customer_question_is_noted_and_info_continues():
    d, _ = driver(ans(True), ans(True), ans(True))
    d.start(); d.handle("evet"); d.handle("evet")
    r = d.handle("ücret ne zaman çekilecek")
    assert r.utterances[0] == QUESTION_NOTED and d.current == "taahhut_bilgisi"
    a = d.answers[-1]
    assert a["step"] == "paket_taahhutlu" and a["value"] is True and a["utterance"] == "ücret ne zaman çekilecek"


def test_unclear_check_in_does_not_hang_up_after_two_reasks():
    d, _ = driver(ans(True), ans(True), ans(None, "unclear"), ans(None, "unclear"), ans(None, "unclear"))
    d.start(); d.handle("evet"); d.handle("evet")
    r1 = d.handle("hmm"); r2 = d.handle("ee")
    assert r1.utterances[0].startswith("Özür dilerim") and "Sorunuz varsa" in r2.utterances[0]
    d.handle("...")
    assert d.answers[-1]["unanswered"] and d.current == "taahhut_bilgisi" and not d.finished


@pytest.mark.parametrize("script,texts,outcome,last", [
    ([ans(False)], ["hayır ben değilim"], "kisi_ulasilamadi", "kapanis_kisi_yok"),
    ([ans(True), ans(None, "refuse")], ["evet", "istemiyorum"], "gorusmek_istemedi", "kapanis_ret"),
    ([ans(True), ans(None, "dnc")], ["evet", "beni aramayın"], "aranmak_istemiyor", "kapanis_dnc"),
])
def test_early_exits(script, texts, outcome, last):
    d, _ = driver(*script)
    d.start()
    for t in texts:
        r = d.handle(t)
    assert r.finished and d.outcome == outcome and d.path[-1] == last


def test_not_available_now_gets_callback_time():
    d, _ = driver(ans(True), ans(False), ans("yarın saat on beşte"))
    d.start(); d.handle("evet"); d.handle("şimdi müsait değilim")
    assert d.current == "randevu"
    r = d.handle("yarın saat on beşte")
    assert r.finished and d.outcome == "geri_arama" and "yarın saat on beşte tekrar arayacağım" in r.utterances[-1]


def test_check_in_value_is_strict_boolean():
    step = S.step_map(S.get("welcome"))["paket_taahhutlu"]
    assert check_value(step, {"intent": "answer", "value": True}) == (True, True)
    assert check_value(step, {"intent": "answer", "value": "evet"})[0] is False


# ---- giris (KVKK) adımı: 'dinlemek istemiyorum' ret değil, devam seçimidir (prompt kuralı; gerçek LLM Mac'te doğrulanır) ----
def test_giris_step_prompt_carries_listen_preference_hint_and_stt_garbage_rule():
    from app import scenario as S
    from app.voice.flow import INTENTS, build_messages
    sc = S.get("anket")
    giris = next(s for s in sc["steps"] if s["key"] == "giris")
    system = build_messages(giris, "Aydınlatma metnini dinlemek ister misiniz?", "dinlemek istemiyorum")[0]["content"]
    assert "DİNLEME tercihini" in system and "value=devam" in system and "refuse DEĞİLDİR" in system
    other = next(s for s in sc["steps"] if s["key"] == "musaitlik")
    assert "Bu soruya özel kural" not in build_messages(other, "Müsait misiniz?", "evet")[0]["content"]
    assert "anlamsız" in INTENTS["unclear"] and "off_topic değildir" in INTENTS["off_topic"]


def test_giris_dinlemek_istemiyorum_as_devam_choice_skips_kvkk_text_and_continues():
    from app import scenario as S
    from app.voice.flow import FlowDriver

    class R:
        text = '{"intent":"answer","value":"devam"}'

    class L:
        def complete(self, m, n, t):
            return R()

    f = FlowDriver(S.get("anket"), L(), None)
    f.start()
    r = f.handle("dinlemek istemiyorum")
    assert not f.finished and f.path == ["giris", "musaitlik"]
    assert any("müsait" in u.lower() for u in r.utterances)
