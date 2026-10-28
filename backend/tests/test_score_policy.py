"""core-021: puan politikası. 'clarify' (varsayılan): puan yalnız müşterinin söylediği tek sayıdan gelir; sözlü ifade ve aralık netleştirilir.
'free': eski davranış (model karar verir). Politika demoda değiştirilebilir (Playground)."""
import pytest

from backend.app import scenario as S
from backend.app.providers.fake import FakeLLM
from backend.app.voice.flow import FlowDriver, extract_numbers


def score_flow(policy="clarify"):
    f = FlowDriver(S.get("anket"), FakeLLM("m"), score_policy=policy)
    f.start()
    f.current = "q2"          # Score adımı
    f.retries = 0
    return f


@pytest.mark.parametrize("text,expected", [
    ("dokuz", [9.0]), ("9", [9.0]), ("yedi sekiz arası", [7.0, 8.0]), ("7-8", [7.0, 8.0]), ("2,5", [2.5]),
    ("çok memnun kaldım", []), ("on", [10.0]), ("bir", [1.0]), ("bir veririm", [1.0]), ("bir şey söyleyeyim", []),
    ("Sekiz veririm", [8.0]), ("ONU veririm", []),
])
def test_extract_numbers(text, expected):
    assert extract_numbers(text) == expected


def test_clarify_accepts_a_single_spoken_number_and_uses_it_over_the_model_value():
    f = score_flow()
    r = f.handle_structured({"intent": "answer", "value": 8}, "dokuz")      # model 8 dedi, müşteri dokuz dedi
    assert f.answers[-1]["value"] == 9 and f.answers[-1]["step"] == "q2"


def test_clarify_asks_for_one_number_when_range_is_spoken():
    f = score_flow()
    r = f.handle_structured({"intent": "answer", "value": 7}, "yedi sekiz arası")
    assert not f.answers and f.current == "q2"
    assert "Yedi mi, sekiz mi" in r.utterances[0] and "tek bir puan" in r.utterances[0]
    assert r.events[0]["intent"] == "clarify" and r.events[0]["valid"] is False


def test_clarify_does_not_invent_a_score_from_a_verbal_expression():
    f = score_flow()
    r = f.handle_structured({"intent": "answer", "value": 10}, "çok memnun kaldım")
    assert not f.answers and "bir sayı söyler misiniz" in r.utterances[0]
    r2 = f.handle_structured({"intent": "answer", "value": 10}, "gayet iyiydi")
    assert not f.answers and f.retries == 2
    r3 = f.handle_structured({"intent": "answer", "value": 10}, "bence harikaydı")     # tekrarlar bitti: cevapsız geçilir
    assert f.answers[-1]["unanswered"] is True and f.answers[-1]["value"] is None      # uydurma 10 kaydedilmez


def test_clarify_decimal_asks_for_whole_number():
    f = score_flow()
    r = f.handle_structured({"intent": "answer", "value": 2}, "2,5")
    assert not f.answers and "tam sayı" in r.utterances[0]


def test_free_policy_keeps_the_old_model_driven_behavior():
    f = score_flow("free")
    f.handle_structured({"intent": "answer", "value": 10}, "çok memnun kaldım")
    assert f.answers[-1]["value"] == 10


def test_policy_is_validated_and_defaults_to_clarify():
    assert FlowDriver(S.get("anket"), FakeLLM("m")).score_policy == "clarify"
    with pytest.raises(ValueError):
        FlowDriver(S.get("anket"), FakeLLM("m"), score_policy="x")


def test_cascade_prompt_forbids_inventing_scores_only_under_clarify():
    from backend.app.voice.flow import build_messages
    step = S.step_map(S.get("anket"))["q2"]
    assert "puan UYDURMA" in build_messages(step, "Soru", "çok iyi", "clarify")[0]["content"]
    assert "puan UYDURMA" not in build_messages(step, "Soru", "çok iyi", "free")[0]["content"]
