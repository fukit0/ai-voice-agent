"""lab-002: STT test ekranı backend'i — WER hesabı, çoklu model karşılaştırması, soğuk koruma, kayıt.

Gerçek modellerle doğrulama Mac'te yapılır (evidence/lab-002-*.json).
"""
import io
import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.providers import registry
from backend.app.providers.base import STTProvider, STTResult
from backend.app.wer import normalize_tr, wer

client = TestClient(app)
REF = "Merhaba, ilanınız için teşekkür ederiz."


def test_normalize_turkish_case_and_punctuation():
    assert normalize_tr("İSTANBUL'da, IŞIK!") == "istanbul da ışık"
    assert normalize_tr("  Merhaba,   dünya.  ") == "merhaba dünya"


@pytest.mark.parametrize("ref,hyp,rate,sub,dele,ins", [
    ("bir iki üç", "bir iki üç", 0.0, 0, 0, 0),
    ("bir iki üç", "bir iki dört", 1 / 3, 1, 0, 0),
    ("bir iki üç", "bir üç", 1 / 3, 0, 1, 0),
    ("bir iki", "bir iki üç", 1 / 2, 0, 0, 1),
    ("Evet, İSTEMİYORUM.", "evet istemiyorum", 0.0, 0, 0, 0),
])
def test_wer_counts(ref, hyp, rate, sub, dele, ins):
    r = wer(ref, hyp)
    assert r.wer == pytest.approx(rate)
    assert (r.substitutions, r.deletions, r.insertions) == (sub, dele, ins)


def test_wer_empty_reference_is_none():
    assert wer("", "bir şey").wer is None


class SttExact(STTProvider):
    kind = "stt_exact"

    def transcribe(self, audio, sample_rate, language="tr"):
        return STTResult(REF, 0.2, self.kind, self.model)


class SttWrong(STTProvider):
    kind = "stt_wrong"

    def transcribe(self, audio, sample_rate, language="tr"):
        return STTResult("Merhaba ilanınız için teşekkürler", 0.4, self.kind, self.model)


class SttBroken(STTProvider):
    kind = "stt_broken"

    def transcribe(self, audio, sample_rate, language="tr"):
        raise RuntimeError("model patladı")


YAML = """
profiles:
  S1:
    name: Bir
    stt: {provider: stt_exact, model: m1}
  S2:
    name: İki
    stt: {provider: stt_wrong, model: m2}
  S3:
    name: Üç (aynı model S1 ile)
    stt: {provider: stt_exact, model: m1}
  S4:
    name: Bozuk
    stt: {provider: stt_broken, model: m4}
  NOSTT:
    name: STT yok
    stt: null
"""


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "profiles.yaml"
    cfg.write_text(YAML, encoding="utf-8")
    monkeypatch.setenv("SVA_PROFILES", str(cfg))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path / "data"))
    for cls in (SttExact, SttWrong, SttBroken):
        monkeypatch.setitem(registry.PROVIDERS, cls.kind, cls)
    registry._cache.clear()
    yield tmp_path
    registry._cache.clear()


def warm(pid):
    res = client.post(f"/api/profiles/{pid}/warmup", params={"keep_others": "true"})
    assert res.status_code == 202, res.text
    for _ in range(200):
        job = client.get(f"/api/profiles/{pid}/warmup").json()
        if job["state"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("warmup bitmedi")


def wav_bytes(seconds=2.0, rate=16000):
    buf = io.BytesIO()
    sf.write(buf, np.zeros(int(seconds * rate), dtype=np.float32), rate, format="WAV")
    return buf.getvalue()


def compare(profiles, reference=REF, data=None):
    return client.post("/api/stt/compare", files={"audio": ("t.wav", data or wav_bytes(), "audio/wav")},
                       data={"profiles": profiles, "reference": reference})


def test_models_lists_distinct_stt_with_profiles(env):
    models = client.get("/api/stt/models").json()
    assert [m["model"] for m in models] == ["m1", "m2", "m4"]  # S3, S1 ile aynı model: tek satır
    m1 = models[0]
    assert m1["profile"] == "S1" and m1["profiles"] == ["S1", "S3"] and m1["warm"] is False and m1["ready"] is True
    warm("S1")
    assert client.get("/api/stt/models").json()[0]["warm"] is True


def test_compare_side_by_side_with_wer_and_rtf(env):
    warm("S1"), warm("S2")
    res = compare("S1,S2")
    assert res.status_code == 200, res.text
    run = res.json()
    exact, wrong = run["results"]
    assert exact["status"] == "ok" and exact["wer"] == 0.0 and exact["text"] == REF
    assert wrong["status"] == "ok" and wrong["wer"] == pytest.approx(0.4)  # 5 kelimede 2 hata (teşekkür ederiz -> teşekkürler)
    assert exact["rtf"] == pytest.approx(0.2 / 2.0, abs=1e-3) and exact["seconds"] == 0.2
    assert run["audio_seconds"] == 2.0 and run["reference"] == REF


def test_compare_without_reference_has_no_wer(env):
    warm("S1")
    item = compare("S1", reference="").json()["results"][0]
    assert item["status"] == "ok" and "wer" not in item


def test_cold_model_is_reported_not_measured(env):
    warm("S1")
    run = compare("S1,S2").json()
    ok, cold = run["results"]
    assert ok["status"] == "ok"
    assert cold["status"] == "cold" and "Hazırla" in cold["error"] and "text" not in cold


def test_same_model_under_two_profiles_runs_once(env):
    warm("S1")
    assert len(compare("S1,S3").json()["results"]) == 1


def test_provider_failure_is_isolated_per_model(env):
    warm("S1"), warm("S4")
    # S4 ısıtma sırasında bozuk sağlayıcıyla soğuk kalır veya çağrıda patlar; ikisi de S1'i etkilememeli
    results = compare("S1,S4").json()["results"]
    assert results[0]["status"] == "ok"
    assert results[1]["status"] in ("failed", "cold")


def test_validation_errors(env):
    assert compare("").status_code in (400, 422)
    assert compare("NOSTT").status_code == 400
    assert client.post("/api/stt/compare", files={"audio": ("x.wav", b"not audio", "audio/wav")},
                       data={"profiles": "S1"}).status_code == 400


def test_run_is_saved_listed_and_reopened_with_audio(env):
    warm("S1"), warm("S2")
    run = compare("S1,S2").json()
    listed = client.get("/api/stt/runs").json()
    assert [r["id"] for r in listed] == [run["id"]]
    assert listed[0]["best_wer"] == 0.0 and listed[0]["reference"] == REF
    reopened = client.get(f"/api/stt/runs/{run['id']}").json()
    assert reopened["results"] == run["results"]
    audio = client.get(f"/api/stt/runs/{run['id']}/audio")
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
    data, rate = sf.read(io.BytesIO(audio.content))
    assert rate == 16000 and len(data) == 32000


def test_unknown_or_malicious_run_id(env):
    assert client.get("/api/stt/runs/yok").status_code == 404
    assert client.get("/api/stt/runs/..%2F..%2Fetc/audio").status_code in (404, 422)


def test_stt_calls_are_logged_with_source(env):
    warm("S1")
    compare("S1")
    import json
    lines = [json.loads(x) for x in (env / "logs" / "provider-calls.jsonl").read_text().splitlines()]
    assert any(e.get("source") == "stt-test" and e["component"] == "stt" for e in lines)


def test_warmup_only_stt_component_does_not_touch_others(env):
    res = client.post("/api/profiles/S1/warmup", params={"components": "stt"})
    assert res.status_code == 202
    for _ in range(200):
        job = client.get("/api/profiles/S1/warmup").json()
        if job["state"] != "running":
            break
        time.sleep(0.01)
    assert job["state"] == "ready" and list(job["components"]) == ["stt"] and job["evicted"] == []
    assert client.post("/api/profiles/S1/warmup", params={"components": "tts"}).status_code == 400
    assert client.post("/api/profiles/S1/warmup", params={"components": "foo"}).status_code == 400
