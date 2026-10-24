"""eval-llm: LLM fonksiyon çağrısı testi — çıktı ayrıştırma, puanlama, dal türetme, çoklu model koşusu.

Gerçek modellerle doğrulama Mac'te yapılır (evidence/eval-llm-*.json); burada sahte LLM'lerle hattın
kendisi (puanlama doğruluğu dahil) sınanır.
"""
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import llm_eval
from backend.app.main import app
from backend.app.providers import registry
from backend.app.providers.base import LLMProvider, LLMResult

client = TestClient(app)
DATA = llm_eval.load_dataset()
BY_UTTERANCE = {s["utterance"]: s for s in DATA["samples"]}


def _warmup(messages, kind, model):
    """Isınma isteği (veri setinden değil): kısa bir cevap yeter."""
    return None if "Müşteri: " in messages[-1]["content"] else LLMResult("hazır", 0.01, kind, model)


def _sample_of(messages):
    utterance = messages[-1]["content"].rsplit("Müşteri: ", 1)[1]
    return BY_UTTERANCE[utterance]


class LlmPerfect(LLMProvider):
    kind = "llm_perfect"

    def complete(self, messages, max_tokens=256, temperature=0.3):
        if (w := _warmup(messages, self.kind, self.model)):
            return w
        e = _sample_of(messages)["expected"]
        return LLMResult(json.dumps({"intent": e["intent"], "value": e["value"]}), 0.1, self.kind, self.model, 12)


class LlmSloppy(LLMProvider):
    """Düşünce etiketi + kod çiti ile doğru cevap verir (tolere edilmeli); sayıları metin yazar (geçersiz)."""
    kind = "llm_sloppy"

    def complete(self, messages, max_tokens=256, temperature=0.3):
        if (w := _warmup(messages, self.kind, self.model)):
            return w
        s = _sample_of(messages)
        e = s["expected"]
        value = str(e["value"]) if DATA["nodes"][s["node"]]["type"] in ("rating", "number") and e["value"] is not None else e["value"]
        body = json.dumps({"intent": e["intent"], "value": value})
        return LLMResult(f"<think>düşünüyorum</think>\n```json\n{body}\n```", 0.3, self.kind, self.model)


class LlmGarbage(LLMProvider):
    kind = "llm_garbage"

    def complete(self, messages, max_tokens=256, temperature=0.3):
        return LLMResult("Tabii, memnuniyet puanı güzel görünüyor!", 0.2, self.kind, self.model)


class LlmBroken(LLMProvider):
    kind = "llm_broken"

    def complete(self, messages, max_tokens=256, temperature=0.3):
        if (w := _warmup(messages, self.kind, self.model)):
            return w
        raise RuntimeError("model patladı")


# ---- ayrıştırma ve şema ----------------------------------------------------------------------------

def test_dataset_has_30_samples_and_expected_branches_match_router():
    assert len(DATA["samples"]) == 30
    assert len({s["id"] for s in DATA["samples"]}) == 30
    for s in DATA["samples"]:
        obj = {"intent": s["expected"]["intent"], "value": s["expected"]["value"]}
        assert llm_eval.schema_error(DATA, s["node"], obj) is None, s["id"]
        assert llm_eval.route(DATA, s["node"], obj) == s["expected"]["branch"], s["id"]


@pytest.mark.parametrize("text,ok", [
    ('{"intent":"answer","value":9}', True),
    ('```json\n{"intent":"answer","value":9}\n```', True),
    ('<think>hmm</think>{"intent":"answer","value":9}', True),
    ('Tabii: {"intent": "answer", "value": 9} umarım yardımcı olur', True),
    ('{"intent":"answer","value":9', False),
    ("cevap dokuz", False),
    ("[1, 2]", False),
    ("", False),
])
def test_parse_output(text, ok):
    obj, err = llm_eval.parse_output(text)
    assert (obj is not None) is ok
    assert (err is None) is ok


@pytest.mark.parametrize("node,obj,valid", [
    ("memnuniyet", {"intent": "answer", "value": 9}, True),
    ("memnuniyet", {"intent": "answer", "value": 9.0}, True),
    ("memnuniyet", {"intent": "answer", "value": "9"}, False),   # metin sayı değil
    ("memnuniyet", {"intent": "answer", "value": 11}, False),
    ("memnuniyet", {"intent": "answer", "value": True}, False),  # bool sayı değil
    ("ilan_verdi_mi", {"intent": "answer", "value": True}, True),
    ("ilan_verdi_mi", {"intent": "answer", "value": "evet"}, False),
    ("kanal", {"intent": "answer", "value": "app"}, True),
    ("kanal", {"intent": "answer", "value": "mobil"}, False),
    ("satis_fiyati", {"intent": "answer", "value": 150000}, True),
    ("satis_fiyati", {"intent": "answer", "value": -5}, False),
    ("satis_fiyati", {"intent": "answer", "value": 12.5}, False),
    ("kanal", {"intent": "repeat", "value": None}, True),
    ("kanal", {"intent": "repeat", "value": "app"}, False),
    ("kanal", {"intent": "dans", "value": None}, False),
])
def test_schema_validation(node, obj, valid):
    assert (llm_eval.schema_error(DATA, node, obj) is None) is valid


@pytest.mark.parametrize("node,obj,branch", [
    ("memnuniyet", {"intent": "answer", "value": 6}, "dusuk_puan"),
    ("memnuniyet", {"intent": "answer", "value": 7}, "yuksek_puan"),
    ("satis_fiyati", {"intent": "answer", "value": 999999}, "normal_fiyat"),
    ("satis_fiyati", {"intent": "answer", "value": 1000000}, "yuksek_fiyat"),
    ("ilan_verdi_mi", {"intent": "answer", "value": False}, "ilan_vermedi"),
    ("kanal", {"intent": "refuse", "value": None}, "ret"),
    ("kanal", {"intent": "answer", "value": "mobil"}, None),  # geçersiz çıktı: motor yeniden sorar
])
def test_route(node, obj, branch):
    assert llm_eval.route(DATA, node, obj) == branch


def test_prompt_carries_question_options_and_utterance():
    msgs = llm_eval.build_messages(DATA, "kanal", "masaüstü")
    assert msgs[0]["role"] == "system" and "JSON" in msgs[0]["content"]
    assert "app = mobil uygulama" in msgs[1]["content"] and msgs[1]["content"].endswith("Müşteri: masaüstü")


def test_value_comparison_is_type_strict():
    assert llm_eval._values_equal(150000.0, 150000)
    assert not llm_eval._values_equal(True, 1)   # bool != 1
    assert not llm_eval._values_equal(1, True)
    assert llm_eval._values_equal(None, None)
    assert not llm_eval._values_equal(0, None)


# ---- koşucu ve özet --------------------------------------------------------------------------------

def test_perfect_model_scores_100_percent():
    out = llm_eval.run_eval(LlmPerfect(model="x"), DATA)
    s = out["summary"]
    assert s["n"] == 30 and s["n_answers"] == 24
    for key in ("json_valid_rate", "schema_valid_rate", "intent_rate", "normalize_rate", "branch_rate", "full_rate"):
        assert s[key] == 1.0, key
    assert s["latency_p50"] == 0.1


def test_sloppy_model_text_numbers_fail_normalize_and_branch_but_fence_and_think_are_tolerated():
    s = llm_eval.run_eval(LlmSloppy(model="x"), DATA)["summary"]
    assert s["json_valid_rate"] == 1.0           # çit + düşünce etiketi sorun değil
    assert s["schema_valid_rate"] == 1 - 12 / 30  # rating(6)+number(6) örneklerinde sayı metin
    assert s["normalize_rate"] == 12 / 24
    assert s["by_type"]["yes_no"]["full_rate"] == 1.0 and s["by_type"]["rating"]["full_rate"] < 1.0


def test_garbage_model_scores_zero_and_broken_model_is_isolated():
    g = llm_eval.run_eval(LlmGarbage(model="x"), DATA)["summary"]
    assert g["json_valid_rate"] == 0 and g["full_rate"] == 0 and g["branch_rate"] == 0
    b = llm_eval.run_eval(LlmBroken(model="x"), DATA, limit=3)
    assert len(b["rows"]) == 3 and all("sağlayıcı hatası" in r["problem"] for r in b["rows"])
    assert b["summary"]["latency_p50"] is None


def test_limit_runs_first_n_samples():
    assert llm_eval.run_eval(LlmPerfect(model="x"), DATA, limit=5)["summary"]["n"] == 5


# ---- API -------------------------------------------------------------------------------------------

YAML = """
profiles:
  P1:
    name: Mükemmel
    llm: {provider: llm_perfect, model: m1}
  P2:
    name: Özensiz
    llm: {provider: llm_sloppy, model: m2}
  P3:
    name: Mükemmel aynı model
    llm: {provider: llm_perfect, model: m1}
  P4:
    name: Bozuk
    llm: {provider: llm_broken, model: m4}
  NOLLM:
    name: LLM yok
    llm: null
"""


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "profiles.yaml"
    cfg.write_text(YAML, encoding="utf-8")
    monkeypatch.setenv("SVA_PROFILES", str(cfg))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path / "data"))
    for cls in (LlmPerfect, LlmSloppy, LlmBroken):
        monkeypatch.setitem(registry.PROVIDERS, cls.kind, cls)
    registry._cache.clear()
    yield tmp_path
    registry._cache.clear()


def warm(pid):
    assert client.post(f"/api/profiles/{pid}/warmup", params={"keep_others": "true"}).status_code == 202
    for _ in range(200):
        job = client.get(f"/api/profiles/{pid}/warmup").json()
        if job["state"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("warmup bitmedi")


def test_models_and_samples_endpoints(env):
    models = client.get("/api/eval/llm/models").json()
    assert {m["model"] for m in models} == {"m1", "m2", "m4"}  # aynı model tek satır, LLM'siz profil yok
    assert next(m for m in models if m["model"] == "m1")["profiles"] == ["P1", "P3"]
    smp = client.get("/api/eval/llm/samples").json()
    assert len(smp["samples"]) == 30 and "memnuniyet" in smp["nodes"]


def test_run_compares_models_side_by_side_and_saves(env):
    warm("P1"); warm("P2")
    res = client.post("/api/eval/llm/run", json={"profiles": ["P1", "P2", "P3"]})
    assert res.status_code == 200, res.text
    run = res.json()
    assert [r["profile"] for r in run["results"]] == ["P1", "P2"]  # P3 = P1 ile aynı model, bir kez koşar
    perfect, sloppy = run["results"]
    assert perfect["status"] == "ok" and perfect["summary"]["full_rate"] == 1.0 and len(perfect["rows"]) == 30
    assert sloppy["summary"]["full_rate"] < perfect["summary"]["full_rate"]
    assert run["n_samples"] == 30
    listed = client.get("/api/eval/llm/runs").json()
    assert listed[0]["id"] == run["id"] and listed[0]["best_full_rate"] == 1.0
    assert client.get(f"/api/eval/llm/runs/{run['id']}").json()["results"][0]["summary"]["full_rate"] == 1.0


def test_cold_model_is_reported_not_measured(env):
    run = client.post("/api/eval/llm/run", json={"profiles": ["P1"]}).json()
    assert run["results"][0]["status"] == "cold" and "rows" not in run["results"][0]


def test_unreachable_model_is_failed_not_zero_percent(env):
    warm("P4")
    run = client.post("/api/eval/llm/run", json={"profiles": ["P4"], "limit": 3}).json()
    r = run["results"][0]
    assert r["status"] == "failed" and "sağlayıcı hatası" in r["error"]


def test_validation_and_malicious_ids(env):
    assert client.post("/api/eval/llm/run", json={"profiles": []}).status_code == 400
    assert client.post("/api/eval/llm/run", json={"profiles": ["NOLLM"]}).status_code == 400
    assert client.post("/api/eval/llm/run", json={"profiles": ["P1"], "limit": 0}).status_code == 400
    assert client.get("/api/eval/llm/runs/../../etc/passwd").status_code in (404, 422)
    assert client.get("/api/eval/llm/runs/nope").status_code == 404


def test_limit_and_call_logging(env):
    warm("P1")
    run = client.post("/api/eval/llm/run", json={"profiles": ["P1"], "limit": 4}).json()
    assert run["n_samples"] == 4 and len(run["results"][0]["rows"]) == 4
    logs = list((env / "logs").rglob("*"))
    assert any("eval-llm" in p.read_text(encoding="utf-8") for p in logs if p.is_file())


# ---- terminal betiği -------------------------------------------------------------------------------

def test_cli_script_runs_profiles_and_writes_evidence(env, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("eval_llm_cli", Path(__file__).resolve().parents[2] / "scripts" / "eval_llm.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    out = env / "evidence.json"
    assert cli.main(["P1", "P2", "P3", "--limit", "6", "--out", str(out)]) == 0  # P3 = P1 ile aynı model
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["n_samples"] == 6 and [r["profile"] for r in data["results"]] == ["P1", "P2"]
    assert data["results"][0]["summary"]["full_rate"] == 1.0 and data["results"][0]["status"] == "ok"
    assert "Kanıt:" in capsys.readouterr().out
    assert cli.main(["NOLLM", "--out", str(out)]) == 2
