"""core-012: ölçüm üretim promptunu kullanır; veri seti donmuş ve kapsamlı; prompt sürümü loglanır."""
import collections
import json
from types import SimpleNamespace

import pytest

from backend.app import prompt_eval as P
from backend.app.voice import flow as F


def test_eval_uses_the_exact_messages_the_agent_builds():
    d = P.load_dataset()
    s = next(x for x in d["samples"] if x["step"] == "q2")
    fd = P._driver(s["scenario"], s["step"])
    agent = F.build_messages(fd.steps["q2"], fd.text_of("q2"), s["utterance"], fd.score_policy)
    assert P.messages_for(s) == agent and P.messages_for(s, "v1") == agent
    assert "dnc" in agent[0]["content"]            # eski llm_eval prompt'unda dnc yoktu


def test_dataset_is_frozen_and_covers_every_type_and_subset():
    assert P.dataset_frozen()
    rows = P.load_dataset()["samples"]
    assert len(rows) >= 80
    kinds = collections.Counter(P.step_of(r)["kind"] for r in rows)
    for k in ("YesNo", "Score", "Duration", "Choice", "CallbackTime", "CheckIn"):
        assert kinds[k] >= 10, (k, kinds)
    assert {"normal", "dnc", "multi", "injection", "noisy"} <= {r["subset"] for r in rows}
    assert len({r["id"] for r in rows}) == len(rows)


def test_prompt_variants_differ_and_v1_is_unchanged_baseline():
    d = P.load_dataset()
    s = d["samples"][0]
    texts = {v: json.dumps(P.messages_for(s, v), ensure_ascii=False) for v in ("v1", "v2", "v3", "v4")}
    assert len(set(texts.values())) == 4
    assert "Ek kurallar" not in texts["v1"] and "Örnekler" in texts["v2"] and "<musteri>" in texts["v3"]
    assert "Örnekler" in texts["v4"] and "<musteri>" in texts["v4"]
    hashes = {F.prompt_info(v)["hash"] for v in ("v1", "v2", "v3", "v4")}
    assert len(hashes) == 4 and F.prompt_info()["version"] == "v1"
    with pytest.raises(ValueError):
        F.prompt_variant("v99")


def oracle(dataset, variant="v3"):
    """Beklenen değeri doğrudan döndüren sahte sağlayıcı: ölçüm hattının kendisi doğru puanlıyor mu."""
    by_prompt = {json.dumps(P.messages_for(s, variant), ensure_ascii=False): s["expected"] for s in dataset["samples"]}

    class P_:
        def complete(self, messages, max_tokens, temperature):
            exp = by_prompt[json.dumps(messages, ensure_ascii=False)]
            v = exp["value"]
            if isinstance(v, dict):
                v = v["contains_any"][0]
            return SimpleNamespace(text=json.dumps({"intent": exp["intent"], "value": v}, ensure_ascii=False), seconds=0.1)
    return P_()


def test_perfect_oracle_scores_100_percent_and_meets_targets():
    d = P.load_dataset()
    out = P.run(oracle(d), d, "v3", repeats=1)
    s = out["summary"]
    assert s["n"] == len(d["samples"]) and s["full_rate"] == 1.0 and s["schema_valid_rate"] == 1.0
    assert all(P.meets_targets(s, is_local_l2=True).values())


def test_wrong_outputs_are_caught_including_injection_wrong_branch():
    d = P.load_dataset()
    inj = next(x for x in d["samples"] if x["subset"] == "injection" and x["step"] == "musaitlik")
    good = P.score(inj, json.dumps({"intent": "answer", "value": True}))
    bad = P.score(inj, json.dumps({"intent": "dnc", "value": None}))          # enjekte edilen talimata uyuldu
    assert good["full_ok"] and not bad["full_ok"] and bad["wrong_branch"]
    summ = P.summarize([bad])
    assert not P.meets_targets(summ)["injection_wrong_branch==0"]
    typed = P.score(next(x for x in d["samples"] if x["step"] == "q3"), json.dumps({"intent": "answer", "value": "evet"}))
    assert not typed["schema_valid"] and not typed["full_ok"]                  # metin 'evet' boolean sayılmaz


def test_session_log_carries_prompt_version():
    info = F.prompt_info()
    assert set(info) == {"version", "hash"} and len(info["hash"]) == 12
