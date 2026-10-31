"""core-027: LLM'siz hızlı yol. Kural: kesinlik %100 (şüphede None). Etiketli 114 + 79 örnekte tek bir yanlış karar kabul edilmez."""
import json
from pathlib import Path

import pytest

from app import scenario as S
from app.voice import flow as F

ROOT = Path(__file__).resolve().parents[2]
SETS = ["prompt-samples.json", "prompt-holdout.json"]


def _load(name):
    d = json.loads((ROOT / "config" / "eval" / name).read_text(encoding="utf-8"))
    return d.get("samples", d) if isinstance(d, dict) else d


def _evaluate():
    wrong, hit, total = [], 0, 0
    for name in SETS:
        for s in _load(name):
            step = S.step_map(S.get(s["scenario"]))[s["step"]]
            total += 1
            fp = F.fastpath_obj(step, s["utterance"])
            if fp is None:
                continue
            hit += 1
            if fp != s["expected"]:
                wrong.append((s["id"], s["utterance"], fp, s["expected"]))
    return wrong, hit, total


def test_fastpath_never_wrong_on_labeled_sets():
    wrong, hit, total = _evaluate()
    assert wrong == []
    assert hit >= 10          # kapsam sıfır olmasın (ölçüm kanıtı: scripts/ değil bu test)


@pytest.mark.parametrize("utt,exp", [("Evet.", True), ("hayır", False), ("tamam olur", True), ("müsait değilim", False)])
def test_yesno_closed_vocab(utt, exp):
    step = {"kind": "YesNo", "code": "X", "key": "k"}
    assert F.fastpath_obj(step, utt) == {"intent": "answer", "value": exp}


@pytest.mark.parametrize("utt", ["evet ama yarın arayın", "hayır istemiyorum", "belki", "olur de mi", "tamam ama", "bot musun", "evet hayır"])
def test_yesno_falls_through(utt):
    assert F.fastpath_obj({"kind": "YesNo", "code": "X", "key": "k"}, utt) is None


@pytest.mark.parametrize("utt,exp", [("9", 9), ("sekiz", 8), ("sekiz puan veriyorum", 8), ("on", 10), ("7 puan", 7)])
def test_score_closed_vocab(utt, exp):
    step = {"kind": "Score", "code": "Q2", "key": "q2", "min": 1, "max": 10}
    assert F.fastpath_obj(step, utt) == {"intent": "answer", "value": exp}


@pytest.mark.parametrize("utt", ["2,5", "yedi sekiz", "11", "0", "bir", "bir tane", "dokuz buçuk", "yetmiş", "9 mu 10 mu", "on iki"])
def test_score_falls_through(utt):
    assert F.fastpath_obj({"kind": "Score", "code": "Q2", "key": "q2", "min": 1, "max": 10}, utt) is None


class _BoomLLM:
    def complete(self, *a, **k):
        raise AssertionError("LLM çağrılmamalıydı")


def test_driver_skips_llm_and_marks_event():
    d = F.FlowDriver(S.get("anket"), _BoomLLM(), score_policy="clarify")
    d.fast_path = True
    d.current = "musaitlik"
    r = d.handle("evet müsaitim")
    assert any(e.get("type") == "fast_path" for e in r.events)
    assert d.current != "musaitlik" and r.llm_s == 0.0


def test_driver_default_off_uses_llm():
    class L:
        options = {}
        calls = 0

        def complete(self, *a, **k):
            L.calls += 1
            from types import SimpleNamespace
            return SimpleNamespace(text='{"intent":"answer","value":true}', input_tokens=1, output_tokens=1, extra={})
    d = F.FlowDriver(S.get("anket"), L(), score_policy="clarify")
    d.current = "musaitlik"
    d.handle("evet müsaitim")
    assert L.calls == 1


def test_only_a1s_profile_enables_fast_path():
    from app.profiles import load_profiles
    on = {pid for pid, p in load_profiles().items() if p.fast_path}
    assert on == {"A1S"}
