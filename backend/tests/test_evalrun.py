"""eval-001: kayıtlı persona sesleriyle otomatik koşu (5 persona x 4 yol = 20 arama, telefon filtresi açık/kapalı, sonuçlar arama listesinde)."""
import asyncio
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import calls, evalrun
from backend.app import scenario as S
from backend.app.main import app
from backend.app.providers.base import LLMProvider, LLMResult, STTProvider, STTResult, TTSResult
from backend.app.providers.fake import FakeTTS

CFG = evalrun.load_config()
TEXTS = evalrun.needed_texts(CFG)
RATE = 16000


def freq_of(text: str) -> float:
    return 400 + 70 * TEXTS.index(text)                          # 400-2220 Hz: telefon bandında, her cümle ayrı frekans


class ToneTTS:
    """Müşteri klip üreticisi (ElevenLabs yerine): cümleyi frekansına kodlar; sahte STT bunu geri çözer."""
    def __init__(self):
        self.calls = []

    def synthesize(self, text, language="tr", speed=1.0, voice=None):
        self.calls.append((text, voice))
        t = np.arange(int(RATE * 0.6)) / RATE
        return TTSResult((0.3 * np.sin(2 * np.pi * freq_of(text) * t)).astype(np.float32), RATE, 0.0, "tone", "m")


class ToneSTT(STTProvider):
    kind = "tone_stt"
    table = {round(freq_of(t)): t for t in TEXTS}

    def transcribe(self, audio, sample_rate, language="tr"):
        if len(audio) == 0 or float(np.sqrt(np.mean(np.square(audio)))) < 0.01:
            return STTResult("", 0.0, self.kind, self.model)
        spec = np.abs(np.fft.rfft(audio, n=1 << 17))
        f = np.argmax(spec[: int(3000 / (sample_rate / (1 << 17)))]) * sample_rate / (1 << 17)
        key = min(self.table, key=lambda k: abs(k - f))
        return STTResult(self.table[key], 0.0, self.kind, self.model)


_NUM = {"bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10}


class RuleLLM(LLMProvider):
    kind = "rule_llm"

    def complete(self, messages, max_tokens=256, temperature=0.3):
        system, user = messages[0]["content"], messages[-1]["content"]
        text = user.split("Müşteri:", 1)[1].strip().replace("İ", "i").replace("I", "ı").casefold()
        rule = system.split("value kuralı:", 1)[1].split("\n", 1)[0]
        out = {"intent": "answer", "value": None}
        if "ilgilenmiyorum" in text:
            out = {"intent": "refuse", "value": None}
        elif "müsait değilim" in text:
            out = {"intent": "callback", "value": None}
        elif any(w in text for w in ("bilmiyorum", "diyemem", "söyleyemem")):
            out = {"intent": "unclear", "value": None}
        elif "anlamadım" in text:
            out = {"intent": "repeat", "value": None}
        elif "kampanya" in text:
            out = {"intent": "off_topic", "value": None}
        elif "true (evet)" in rule:
            out["value"] = "hayır" not in text
        elif "seçenek anahtarlarından" in rule:
            out["value"] = "devam" if "hayır" in text else "dinle"
        elif "arası tam sayı" in rule:
            out["value"] = next(_NUM[w] for w in text.replace(".", "").split() if w in _NUM)
        elif "saniye" in rule:
            out["value"] = 45
        elif "gün/saat" in rule:
            out["value"] = text.rstrip(".")
        elif "true: müşterinin sormak" in rule:
            out["value"] = False
        return LLMResult(json.dumps(out, ensure_ascii=False), 0.0, self.kind, self.model)


def lister(gender, age):
    n = {"female": 0, "male": 100}[gender] + {"young": 0, "middle_aged": 10, "old": 20, "": 30}[age]
    return [{"voice_id": f"v{n + i}"} for i in range(3)]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))
    (tmp_path / "voice-sessions").mkdir()
    evalrun.RUNS.clear()
    return tmp_path


@pytest.fixture()
def ready(env):
    evalrun.build_clips(CFG, tts=ToneTTS(), lister=lister)
    return env


def run_set(pf="off", personas=None, paths=None, **kw):
    run = evalrun.new_run("TEST", pf, CFG, personas, paths)
    asyncio.run(evalrun.execute(run, CFG, ToneSTT("m"), RuleLLM("m"), FakeTTS("m"), **kw))
    return run


# ---- yapılandırma ----
def test_config_is_five_personas_by_four_paths_and_matches_the_scenario():
    assert len(CFG["personas"]) == 5 and len(CFG["paths"]) == 4
    assert len(evalrun.plan_calls(CFG, "off", None, None)) == 20 and len(evalrun.plan_calls(CFG, "both", None, None)) == 40
    steps = S.get("anket")["steps"]
    keys = {s["key"] for s in steps} if isinstance(steps, list) else set(steps)
    for p in CFG["paths"]:
        assert set(p["script"]) <= keys, (p["id"], set(p["script"]) - keys)      # betikteki her adım senaryoda var
    assert len({p["id"] for p in CFG["personas"]}) == 5
    assert len(TEXTS) == len(set(TEXTS)) and freq_of(TEXTS[-1]) < 3000          # test STT'si için cümle kodları ayrı ve bantta


def test_utterance_for_uses_script_visits_then_defaults():
    path = {"script": {"q2": ["a", "b", "c"], "q4": "d"}}
    d = {"Score": "Sekiz."}
    assert [evalrun.utterance_for(path, d, "q2", "Score", n) for n in range(5)] == ["a", "b", "c", "c", "c"]
    assert evalrun.utterance_for(path, d, "q4", "OpenText", 3) == "d"
    assert evalrun.utterance_for(path, d, "q6", "Score", 0) == "Sekiz."


def test_persona_effects_gain_noise_and_reaction_delay():
    clip = (0.3 * np.sin(2 * np.pi * 800 * np.arange(RATE) / RATE)).astype(np.float32)
    base = {"gain_db": 0, "noise_snr_db": None, "reaction_s": 0.0}
    assert np.allclose(evalrun.apply_persona(clip, base), clip)
    quiet = evalrun.apply_persona(clip, {**base, "gain_db": -9})
    assert abs(20 * np.log10(np.max(quiet) / np.max(clip)) + 9) < 0.2
    lead = evalrun.apply_persona(clip, {**base, "reaction_s": 1.2})
    assert len(lead) == len(clip) + int(1.2 * RATE) and not lead[: int(1.2 * RATE)].any()
    noisy = evalrun.apply_persona(clip, {**base, "noise_snr_db": 15})
    snr = 10 * np.log10(np.mean(clip ** 2) / np.mean((noisy - clip) ** 2))
    assert 14 < snr < 16
    assert np.array_equal(noisy, evalrun.apply_persona(clip, {**base, "noise_snr_db": 15}))   # tekrarlanabilir


# ---- ses seti ----
def test_pick_voices_distinct_persistent_and_respects_config(env):
    cfg = {**CFG, "personas": [dict(p) for p in CFG["personas"]]}
    cfg["personas"][0]["voice_id"] = "sabit"
    chosen = evalrun.pick_voices(cfg, lister)
    assert "ayse_sakin" not in chosen and len(set(chosen.values())) == 4          # ilk persona sabit ses taşıyor
    assert evalrun.assigned_voices() == chosen
    assert evalrun.pick_voices(cfg, lambda g, a: 1 / 0) == chosen                 # ikinci çağrı yeniden seçmez


def test_pick_voices_without_candidates_explains(env):
    with pytest.raises(RuntimeError, match="uygun ses bulunamadı"):
        evalrun.pick_voices(CFG, lambda g, a: [])


def test_build_clips_is_idempotent_and_makes_set_ready(env):
    assert evalrun.set_status(CFG)["ready"] is False
    tts = ToneTTS()
    first = evalrun.build_clips(CFG, tts=tts, lister=lister)
    assert first == {"made": 5 * len(TEXTS), "skipped": 0} and len(tts.calls) == 5 * len(TEXTS)
    assert {v for _, v in tts.calls} == set(evalrun.assigned_voices().values())   # her persona kendi sesiyle
    second = evalrun.build_clips(CFG, tts=ToneTTS(), lister=lister)
    assert second == {"made": 0, "skipped": 5 * len(TEXTS)}                       # ücretsiz yeniden çalıştırma
    st = evalrun.set_status(CFG)
    assert st["ready"] is True and st["calls"] == 20 and all(p["clips"] == p["clips_needed"] for p in st["personas"])


# ---- koşu ----
def test_twenty_calls_complete_with_expected_outcomes_and_land_in_calls_list(ready):
    run = run_set("off")
    assert run["status"] == "done" and run["done"] == 20, [c for c in run["calls"] if c["status"] != "ok"][:3]
    assert all(c["status"] == "ok" and c["session_id"] for c in run["calls"])
    by_path = {}
    for c in run["calls"]:
        by_path.setdefault(c["path"], set()).add(c["outcome"])
    assert by_path["tam_katilim"] == {"tamamlandi"}
    assert by_path["ret"] == {"katilmak_istemedi"}
    assert by_path["geri_arama"] == {"geri_arama"}
    assert by_path["belirsiz"] <= {"tamamlandi"} and all(c["unanswered"] >= 1 for c in run["calls"] if c["path"] == "belirsiz")
    assert all(c["first_audio_p50_s"] is not None for c in run["calls"])
    listing = calls.list_calls(ready / "voice-sessions", None, None, None, 100)
    assert listing["total"] == 20                                                   # "Sonuçlar arama listesine düşer"
    ids = {c["session_id"] for c in run["calls"]}
    assert {c["id"] for c in listing["calls"]} == ids and {c["profile"] for c in listing["calls"]} == {"TEST"}
    doc = json.loads((ready / "voice-sessions" / f"{run['calls'][0]['session_id']}.json").read_text(encoding="utf-8"))
    assert doc["eval"]["run_id"] == run["id"] and doc["eval"]["customer"] and doc["phone_filter"] is False


def test_phone_filter_on_and_off_runs_are_both_recorded(ready):
    run = run_set("both", personas=["ayse_sakin"])
    assert run["total"] == 8 and run["done"] == 8 and all(c["status"] == "ok" for c in run["calls"])
    flags = {}
    for c in run["calls"]:
        doc = json.loads((ready / "voice-sessions" / f"{c['session_id']}.json").read_text(encoding="utf-8"))
        assert doc["phone_filter"] is c["phone_filter"] and doc["eval"]["phone_filter"] is c["phone_filter"]
        flags.setdefault(c["phone_filter"], set()).add(c["path"])
    assert flags[True] == flags[False] == {"tam_katilim", "ret", "geri_arama", "belirsiz"}


def test_customer_audio_is_the_recorded_clip_not_generated_at_run_time(ready):
    tts = ToneTTS()
    loaded = []
    def loader(v, s, t):
        loaded.append(t)
        return evalrun.read_clip(v, s, t)
    run_set("off", personas=["ayse_sakin"], paths=["geri_arama"], clip_loader=loader)
    assert loaded == ["Hayır, devam edelim.", "Şu an müsait değilim.", "Yarın saat on beşte."] and tts.calls == []


def test_one_failing_call_does_not_stop_the_rest(ready):
    def loader(v, s, t):
        if v == evalrun.assigned_voices()["mehmet_hizli"]:
            raise OSError("klip bozuk")
        return evalrun.read_clip(v, s, t)
    run = run_set("off", paths=["ret"], clip_loader=loader)
    st = {c["persona"]: c["status"] for c in run["calls"]}
    assert st["mehmet_hizli"] == "error" and sum(s == "ok" for s in st.values()) == 4 and run["status"] == "done"
    assert "klip bozuk" in next(c for c in run["calls"] if c["persona"] == "mehmet_hizli")["error"]


def test_max_turns_guard_marks_call_instead_of_looping(ready):
    cfg_run = evalrun.new_run("TEST", "off", CFG, ["ayse_sakin"], ["tam_katilim"])
    res = asyncio.run(evalrun.run_call(profile_id="TEST", stt=ToneSTT("m"), llm=RuleLLM("m"), tts=FakeTTS("m"), persona=CFG["personas"][0],
                                       path=CFG["paths"][0], phone_filter=False, cfg=CFG, run_id=cfg_run["id"], max_turns=3))
    assert res["status"] == "max_turns" and res["session_id"]


# ---- API ----
def fake_providers(monkeypatch):
    from backend.app import api_evalrun
    monkeypatch.setattr(api_evalrun, "_providers", lambda profile: (ToneSTT("m"), RuleLLM("m"), FakeTTS("m")))


def test_api_rejects_unknown_realtime_unready_and_bad_ids(env, monkeypatch):
    fake_providers(monkeypatch)
    with TestClient(app) as c:
        assert c.post("/api/evalrun/runs", json={"profile": "yok"}).status_code == 404
        assert c.post("/api/evalrun/runs", json={"profile": "A2"}).json()["detail"]["error"] == "realtime_not_supported"
        assert c.post("/api/evalrun/runs", json={"profile": "L1", "personas": ["x"]}).json()["detail"]["error"] == "unknown_id"
        r = c.post("/api/evalrun/runs", json={"profile": "L1"})
        assert r.status_code == 409 and r.json()["detail"]["error"] == "set_not_ready"      # sesler hazır değil
        assert c.get("/api/evalrun/set").json()["ready"] is False
        assert c.get("/api/evalrun/runs/20200101-000000-abcdef").status_code == 404
        assert c.get("/api/evalrun/runs/../../etc").status_code in (404, 422)


def test_api_blocks_a_second_run_while_one_is_active(ready, monkeypatch):
    fake_providers(monkeypatch)
    evalrun.RUNS["x"] = {"id": "x", "status": "running"}
    with TestClient(app) as c:
        r = c.post("/api/evalrun/runs", json={"profile": "L1"})
        assert r.status_code == 409 and r.json()["detail"]["error"] == "run_active"


def test_api_starts_a_run_reports_progress_and_blocks_a_second_one(ready, monkeypatch):
    fake_providers(monkeypatch)
    with TestClient(app) as c:
        assert c.get("/api/evalrun/set").json()["ready"] is True
        r = c.post("/api/evalrun/runs", json={"profile": "L1", "phone_filter": "off", "personas": ["ayse_sakin"], "paths": ["ret", "geri_arama"]})
        assert r.status_code == 202 and r.json()["total"] == 2
        rid = r.json()["run_id"]
        for _ in range(600):
            body = c.get(f"/api/evalrun/runs/{rid}").json()
            if body["status"] != "running":
                break
            time.sleep(0.1)
        assert body["status"] == "done" and body["done"] == 2 and {x["outcome"] for x in body["calls"]} == {"katilmak_istemedi", "geri_arama"}
        assert [x["id"] for x in c.get("/api/evalrun/runs").json()] == [rid]
        assert c.post(f"/api/evalrun/runs/{rid}/cancel").status_code == 409                # bitmiş koşu iptal edilmez
    assert evalrun.get_run(rid)["status"] == "done"                                         # diske yazıldı: yeniden başlatmada da görünür
