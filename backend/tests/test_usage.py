"""eval-003: arama basina sure, konusma payi, STT dakikasi, LLM token, TTS karakter, GPU saniyesi ve API maliyeti."""
import asyncio
import json

import pytest

from backend.app import calls, evalrun, usage
from backend.app.providers.fake import FakeTTS
from backend.tests.test_evalrun import CFG, RuleLLM, ToneSTT, ToneTTS, lister

PRICING = {"currency": "USD", "local_providers": ["mlx_whisper", "ollama", "ema"],
           "stt": {"deepgram:nova-3": {"unit": "minute", "usd": 0.0092, "verified": True}},
           "llm": {"anthropic:claude-haiku-5-5": {"input_per_mtok": 0.10, "output_per_mtok": 0.50, "verified": False}},
           "tts": {"elevenlabs:eleven_flash_v2_5": {"unit": "1k_chars", "usd": 0.04, "verified": False}}}
API = {"stt": {"provider": "deepgram", "model": "nova-3"}, "llm": {"provider": "anthropic", "model": "claude-haiku-5-5"},
       "tts": {"provider": "elevenlabs", "model": "eleven_flash_v2_5"}}
LOCAL = {"stt": {"provider": "mlx_whisper", "model": "w"}, "llm": {"provider": "ollama", "model": "g"}, "tts": {"provider": "ema", "model": ""}}


def filled(kind, model, base):
    cls = type(f"X{kind}", (base,), {"kind": kind})
    return cls(model)


class TokenLLM(RuleLLM):
    def complete(self, messages, max_tokens=256, temperature=0.3):
        res = super().complete(messages, max_tokens, temperature)
        res.input_tokens, res.output_tokens = 500, 20
        return res


class NoTokenLLM(RuleLLM):
    pass


@pytest.fixture()
def ready(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))
    (tmp_path / "voice-sessions").mkdir()
    evalrun.RUNS.clear()
    evalrun.build_clips(CFG, tts=ToneTTS(), lister=lister)
    return tmp_path


def one_call(tmp, stt, llm, tts):
    res = asyncio.run(evalrun.run_call(profile_id="TEST", stt=stt, llm=llm, tts=tts, persona=CFG["personas"][0],
                                       path=next(p for p in CFG["paths"] if p["id"] == "tam_katilim"), phone_filter=False, cfg=CFG, run_id="r"))
    return json.loads((tmp / "voice-sessions" / f"{res['session_id']}.json").read_text(encoding="utf-8"))


def api_trio(llm_cls=TokenLLM):
    stt = filled("deepgram", "nova-3", ToneSTT)
    return stt, llm_cls("claude-haiku-5-5"), FakeTTS("eleven_flash_v2_5")


def patch_kinds(monkeypatch, stt, llm, tts):
    llm.kind = "anthropic"
    tts.kind = "elevenlabs"
    monkeypatch.setattr(usage, "pricing_path", lambda: None)
    monkeypatch.setattr(usage, "load_pricing", lambda: PRICING)


# ---- saf hesap ----
def test_cost_math_for_api_components():
    m = usage.UsageMeter()
    m.add_stt(90, 0.4)
    m.add_stt(30, 0.2)
    m.add_llm(type("R", (), {"input_tokens": 1000, "output_tokens": 100})(), 0.5)
    m.add_tts(250, 12.0, 0.3)
    m.add_tts(750, 30.0, 0.9)
    r = usage.report(m, duration_s=100, user_speech_s=40, agent_speech_s=30, components=API, pricing=PRICING)
    assert r["items"]["stt_minutes"] == 2.0 and r["items"]["tts_chars"] == 1000 and r["items"]["gpu_s"] == 0
    assert r["items"]["speech_share"] == 0.7 and r["items"]["llm_input_tokens"] == 1000
    by = r["cost"]["by_component"]
    assert by["stt"] == pytest.approx(2 * 0.0092) and by["tts"] == pytest.approx(0.04) and by["llm"] == pytest.approx((1000 * 0.10 + 100 * 0.50) / 1e6)
    assert r["cost"]["total"] == pytest.approx(sum(by.values()), abs=1e-6) and r["cost"]["complete"] is True
    assert r["cost"]["prices_verified"] is False          # LLM ve TTS fiyatlari dogrulanmadi: rapor bunu gizlemez


def test_local_components_cost_zero_and_count_gpu_seconds():
    m = usage.UsageMeter()
    m.add_stt(10, 0.8)
    m.add_llm(type("R", (), {"input_tokens": 300, "output_tokens": 30})(), 1.5)
    m.add_tts(100, 6.0, 0.7)
    r = usage.report(m, duration_s=60, user_speech_s=10, agent_speech_s=6, components=LOCAL, pricing=PRICING)
    assert r["items"]["gpu_s"] == pytest.approx(3.0)
    assert r["cost"]["by_component"] == {"stt": 0.0, "llm": 0.0, "tts": 0.0} and r["cost"]["total"] == 0.0


def test_missing_tokens_stay_none_and_cost_is_incomplete_not_zero():
    m = usage.UsageMeter()
    m.add_llm(type("R", (), {"input_tokens": None, "output_tokens": None})(), 0.4)
    r = usage.report(m, duration_s=10, user_speech_s=1, agent_speech_s=1, components=API, pricing=PRICING)
    assert r["items"]["llm_input_tokens"] is None and "llm_tokens" in r["missing"]
    assert r["cost"]["by_component"]["llm"] is None and r["cost"]["complete"] is False and "llm(token yok)" in r["cost"]["unpriced"]


def test_unpriced_api_component_is_reported():
    m = usage.UsageMeter()
    comps = {**API, "tts": {"provider": "elevenlabs", "model": "unknown_model"}}
    m.add_tts(100, 5, 0.2)
    r = usage.report(m, duration_s=10, user_speech_s=1, agent_speech_s=5, components=comps, pricing=PRICING)
    assert r["cost"]["by_component"]["tts"] is None and r["cost"]["unpriced"].count("tts") == 1 and r["cost"]["complete"] is False


def test_metered_llm_counts_calls_and_delegates_attributes():
    m = usage.UsageMeter()
    inner = TokenLLM("claude-haiku-5-5")
    wrapped = usage.MeteredLLM(inner, m)
    res = wrapped.complete([{"role": "system", "content": "value kuralı: x"}, {"role": "user", "content": "Müşteri: ilgilenmiyorum"}])
    assert res.input_tokens == 500 and m.llm["calls"] == 1 and m.llm["input_tokens"] == 500 and wrapped.kind == inner.kind


# ---- oturum ----
def test_session_records_all_cost_items_and_prices_an_api_profile(ready, monkeypatch):
    stt, llm, tts = api_trio()
    patch_kinds(monkeypatch, stt, llm, tts)
    doc = one_call(ready, stt, llm, tts)
    u = doc["usage"]
    items = u["items"]
    assert all(items[k] is not None for k in items), items                   # tum kalemler dolu
    assert items["stt_calls"] > 0 and items["stt_minutes"] > 0 and items["tts_chars"] > 0 and items["llm_calls"] > 0
    assert items["llm_input_tokens"] == 500 * items["llm_calls"] and items["llm_output_tokens"] == 20 * items["llm_calls"]
    assert items["gpu_s"] == 0 and items["duration_s"] > 0 and 0 < items["speech_share"] <= 1
    c = u["cost"]
    expected = items["stt_minutes"] * 0.0092 + items["tts_chars"] / 1000 * 0.04 + (items["llm_input_tokens"] * 0.10 + items["llm_output_tokens"] * 0.50) / 1e6
    assert c["total"] == pytest.approx(expected, abs=1e-5) and c["complete"] is True and c["total"] > 0


def test_session_without_token_info_marks_it_missing(ready, monkeypatch):
    stt, _, tts = api_trio()
    llm = NoTokenLLM("claude-haiku-5-5")
    patch_kinds(monkeypatch, stt, llm, tts)
    u = one_call(ready, stt, llm, tts)["usage"]
    assert u["items"]["llm_input_tokens"] is None and "llm_tokens" in u["missing"] and u["cost"]["complete"] is False


def test_local_profile_session_has_gpu_seconds_and_zero_api_cost(ready, monkeypatch):
    stt = filled("mlx_whisper", "w", ToneSTT)
    llm = TokenLLM("g")
    llm.kind = "ollama"
    tts = FakeTTS("")
    tts.kind = "ema"
    monkeypatch.setattr(usage, "load_pricing", lambda: PRICING)
    u = one_call(ready, stt, llm, tts)["usage"]
    assert u["items"]["gpu_s"] > 0 and u["cost"]["total"] == 0.0 and u["cost"]["complete"] is True


def test_every_call_of_a_run_has_all_items_and_calls_api_exposes_cost(ready, monkeypatch):
    stt, llm, tts = api_trio()
    patch_kinds(monkeypatch, stt, llm, tts)
    run = evalrun.new_run("TEST", "off", CFG, None, None)
    asyncio.run(evalrun.execute(run, CFG, stt, llm, tts))
    listing = calls.list_calls(ready / "voice-sessions")
    rows = listing["calls"] if isinstance(listing, dict) else listing
    assert len(rows) == 20
    for r in rows:
        assert r["cost_usd"] is not None and r["cost_usd"] > 0 and r["gpu_s"] == 0
    for f in (ready / "voice-sessions").glob("*.json"):
        items = json.loads(f.read_text(encoding="utf-8"))["usage"]["items"]
        assert all(v is not None for v in items.values()), (f.name, items)
    g = calls.compare(ready / "voice-sessions", "profile")["groups"][0]
    assert g["usage_calls"] == 20 and g["avg_cost_usd"] > 0 and g["cost_complete"] is True and g["avg_stt_minutes"] > 0


def test_old_sessions_without_usage_show_none_not_zero():
    doc = {"id": "a" * 12, "profile": "OLD", "turns": [], "transcript": [], "stats": {}}
    from pathlib import Path
    s = calls.summary(doc, Path("/nonexistent"))
    assert s["cost_usd"] is None and s["gpu_s"] is None
    g = calls._group("OLD", "OLD", [doc])
    assert g["usage_calls"] == 0 and g["avg_cost_usd"] is None and g["cost_complete"] is False and g["avg_gpu_s"] is None


def test_shipped_pricing_file_prices_the_api_profile_components():
    p = usage.load_pricing()
    for kind, key in (("stt", "deepgram:nova-3"), ("llm", "anthropic:claude-haiku-5-5"), ("tts", "elevenlabs:eleven_flash_v2_5")):
        assert key in p[kind], key
    assert set(p["local_providers"]) >= {"mlx_whisper", "ollama", "ema", "chatterbox"}
