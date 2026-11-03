"""Serbest cevap 'Qwen thinking' ölçüm ayarı (docs/serbest-cevap-qwen.md 'Qwen thinking'). Ağsız: sahte istemci ve sahte httpx.

Kapsam: model/think seçimi, düşünme metninin cevaba sızmaması, zaman aşımı ve token sınırı seçimi, aynı düşüş kuralları (soğuk, zaman
aşımı, denetim), serbest cevap kapalı + thinking açık = çağrı yok, ayar dosyası/API, tur kaydı alanları, Ayarlar özeti, eval betiği.
Gerçek Qwen thinking modeliyle ÖLÇÜLMEDİ (bulutta Ollama yok)."""
from __future__ import annotations

import asyncio
import json
import runpy
import sys

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import scenario as S
from backend.app.voice import free_reply as F
from backend.app.voice.flow import FlowDriver
from backend.tests.test_flow import ScriptedLLM, ans
from backend.tests.test_free_reply import ALL_CATEGORIES, GOOD, OFF, STEP_Q31, FakeChat, drv

THINK_MODEL = "qwen3:30b-a3b-thinking-2507-q4_K_M"


class FakeThinkChat(FakeChat):
    """Thinking modeli taklidi: ChatReply ile ayrı düşünme metni ve Ollama ölçüm alanları döndürür; çağrı parametrelerini tutar."""
    model = THINK_MODEL

    def __init__(self, out=GOOD, thinking="Müşteri puanı bana soruyor. Puan vermemeliyim, sekiz demeyeceğim.", meta=None, **kw):
        super().__init__(out, **kw)
        self.thinking, self.meta = thinking, meta if meta is not None else {"eval_tokens": 412, "ollama_s": 5.2}
        self.params: list[tuple[float, int]] = []

    def chat(self, messages, timeout_s, max_tokens, temperature):
        self.params.append((timeout_s, max_tokens))
        content = super().chat(messages, timeout_s, max_tokens, temperature)
        return F.ChatReply(content, self.thinking, self.meta)


class ParamChat(FakeChat):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.params: list[tuple[float, int]] = []

    def chat(self, messages, timeout_s, max_tokens, temperature):
        self.params.append((timeout_s, max_tokens))
        return super().chat(messages, timeout_s, max_tokens, temperature)


def think_replier(base=None, think=None, **cfg):
    cfg.setdefault("categories", ALL_CATEGORIES)
    cfg.setdefault("use_pool_fallback_only", False)   # eski kategori mekanizması (geniş kapsam test_free_reply_wide.py)
    cfg.setdefault("thinking", True)
    return F.FreeReplier(base or ParamChat(), cfg, thinking_client=think or FakeThinkChat())


# ---- varsayılanlar ----
def test_defaults_thinking_off_with_separate_model_and_timeout():
    d = F.defaults()
    assert d["thinking"] is False and d["thinking_model"] == THINK_MODEL and d["thinking_timeout_s"] == 8.0
    assert d["thinking_max_tokens"] > d["max_tokens"]                 # 90 token düşünmeyi yarıda keser
    assert "ollama list" in d["thinking_note"]                        # etiketin varlığı doğrulanmadı: kullanıcıya nasıl doğrulanacağı yazılı


# ---- model / zaman aşımı / token seçimi ----
def test_thinking_off_uses_instruct_client_and_live_limits():
    base, think = ParamChat(), FakeThinkChat()
    r = F.FreeReplier(base, {"categories": ALL_CATEGORIES, "use_pool_fallback_only": False}, thinking_client=think)
    res = r.generate(STEP_Q31, "soru", "sende kaç puan vereyim", "counter")
    assert res.source == "qwen" and res.model == FakeChat.model and res.thinking is False
    assert base.params == [(1.5, 90)] and think.calls == []
    assert "thinking" not in res.event("q3_1")                          # kapalıyken olay eski alanlarla aynı
    assert r.describe()["thinking"] is False and r.describe()["timeout_s"] == 1.5


def test_thinking_on_uses_thinking_client_timeout_and_token_budget():
    base, think = ParamChat(), FakeThinkChat()
    r = think_replier(base, think, thinking_timeout_s=9.0, thinking_max_tokens=600)
    res = r.generate(STEP_Q31, "soru", "sende kaç puan vereyim", "counter")
    assert res.source == "qwen" and res.text == GOOD and res.model == THINK_MODEL and res.thinking is True
    assert base.calls == [] and think.params == [(9.0, 600)]
    assert res.eval_tokens == 412 and res.ollama_s == 5.2 and res.think_chars == len(think.thinking)
    ev = res.event("q3_1")
    assert ev["thinking"] is True and ev["model"] == THINK_MODEL and ev["think_chars"] > 0
    d = r.describe()
    assert d["thinking"] is True and d["model"] == THINK_MODEL and d["timeout_s"] == 9.0 and d["max_tokens"] == 600


def test_thinking_text_never_leaks_into_answer_or_audit():
    """Düşünmede 'sekiz' ve 'ben olsam' geçiyor: ayrıştırılmasaydı denetim reddederdi; cevap temiz olduğu için geçer ve söylenen yalnız cevap."""
    think = FakeThinkChat(thinking="Ben olsam sekiz verirdim ama bunu söylememeliyim.")
    res = think_replier(think=think).generate(STEP_Q31, "soru", "sende kaç puan vereyim", "counter")
    assert res.text == GOOD and "sekiz" not in res.text and res.fails == []


@pytest.mark.parametrize("raw", [
    "<think>Puan vermemeliyim, sekiz demeyeceğim.</think>\n" + GOOD,
    "Puan vermemeliyim, sekiz demeyeceğim.</think>" + GOOD,          # açılışı istem şablonunda kalmış blok
    "<THINK>sekiz</THINK> " + GOOD,
])
def test_inline_think_blocks_are_stripped(raw):
    res = think_replier(think=FakeThinkChat(out=raw, thinking="")).generate(STEP_Q31, "soru", "sende kaç puan vereyim", "counter")
    assert res.text == GOOD and res.think_chars > 0


def test_unclosed_think_block_means_empty_answer_and_pool():
    """num_predict düşünmenin ortasında keserse cevap yoktur: düşünme metni söylenmez, havuz konuşur."""
    res = think_replier(think=FakeThinkChat(out="<think>Müşteri puan soruyor, sekiz", thinking="")).generate(
        STEP_Q31, "soru", "sende kaç puan vereyim", "counter")
    assert res.text is None and res.reason == "audit" and res.fails == ["empty"] and "sekiz" not in (res.candidate or "")


def test_split_thinking_plain_text_unchanged():
    assert F.split_thinking("Merhaba.") == ("Merhaba.", "")
    assert F.split_thinking(F.ChatReply("Cevap.", "düşünce")) == ("Cevap.", "düşünce")
    assert F.ChatReply("x", "y", {"a": 1}) == "x"                         # str gibi davranır (eski çağıranlar bozulmaz)


# ---- aynı düşüş kuralları ----
def test_thinking_cold_model_not_called():
    think = FakeThinkChat(warm=False)
    res = think_replier(think=think).generate(STEP_Q31, "soru", "sende kaç puan vereyim", "counter")
    assert res.source == "pool" and res.reason == "cold" and think.calls == [] and res.thinking is True


def test_thinking_unreachable_and_timeout_fall_back():
    import httpx
    res = think_replier(think=FakeThinkChat(warm=None)).generate(STEP_Q31, "soru", "x y z", "counter")
    assert res.reason == "unreachable"
    res = think_replier(think=FakeThinkChat(exc=httpx.ReadTimeout("yavaş"))).generate(STEP_Q31, "soru", "x y z", "counter")
    assert res.reason == "timeout" and res.text is None
    ticks = iter([0.0, 8.5])                                             # toplam süre thinking sınırını (8 sn) aşıyor
    r = F.FreeReplier(ParamChat(), {"categories": ALL_CATEGORIES, "thinking": True, "use_pool_fallback_only": False}, clock=lambda: next(ticks),
                      thinking_client=FakeThinkChat())
    res = r.generate(STEP_Q31, "soru", "x y z", "counter")
    assert res.reason == "timeout" and res.text is None and res.seconds == 8.5


def test_thinking_slow_answer_within_thinking_timeout_is_kept():
    """3 sn canlı sınırı (1,5) aşar ama thinking sınırı (8) içinde: thinking açıkken söylenir (ölçüm amaçlı)."""
    ticks = iter([0.0, 3.0, 3.0, 3.0])
    r = F.FreeReplier(ParamChat(), {"categories": ALL_CATEGORIES, "thinking": True, "use_pool_fallback_only": False}, clock=lambda: next(ticks),
                      thinking_client=FakeThinkChat())
    assert r.generate(STEP_Q31, "soru", "x y z", "counter").source == "qwen"


def test_thinking_audit_still_applies_to_final_answer():
    res = think_replier(think=FakeThinkChat(out="Ben olsam sekiz verirdim.")).generate(STEP_Q31, "soru", "x y z", "counter")
    assert res.reason == "audit" and "number_word" in res.fails


def test_thinking_respects_categories_and_disabled():
    think = FakeThinkChat()
    r = think_replier(think=think, categories=["counter"])
    assert r.generate(STEP_Q31, "soru", "hava nasıl", "weather").reason == "category"
    r = think_replier(think=think, enabled=False)
    assert r.generate(STEP_Q31, "soru", "sende kaç puan vereyim", "counter").reason == "disabled"
    assert think.calls == [] and think.warm_checks == 0


def test_flow_with_thinking_speaks_answer_then_question_verbatim():
    think = FakeThinkChat()
    d, _ = drv(OFF, free=think_replier(think=think))
    r = d.handle("sende kaç puan vereyim")
    assert r.utterances[0] == GOOD and r.utterances[-1] == d.retry_of("q3_1")
    assert not any(think.thinking in u for u in r.utterances)


# ---- ayarlar: bağımsız, kapalı serbest cevapta çağrı yok ----
def test_settings_thinking_independent_of_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    F.save_overrides({"thinking": True, "thinking_timeout_s": 12})
    s = F.settings()
    assert s["thinking"] is True and s["enabled"] is True and s["thinking_timeout_s"] == 12.0
    F.save_overrides({"enabled": False})
    assert F.settings()["thinking"] is True                             # serbest cevabı kapatmak thinking ayarını silmez
    assert F.make_default() is None                                      # ama serbest cevap kapalıyken Qwen hiç çağrılmaz
    F.save_overrides({"enabled": None})
    fr = F.make_default()
    assert fr.client.model == THINK_MODEL and fr.client.think is True and fr.base_client.think is False
    assert fr.describe()["timeout_s"] == 12.0
    F.save_overrides({"thinking": False})
    fr = F.make_default()
    assert fr.client.model == F.defaults()["model"] and fr.client.think is False and fr.describe()["timeout_s"] == 1.5
    for bad in ({"thinking": "evet"}, {"thinking_timeout_s": 0.5}, {"thinking_timeout_s": 60}, {"thinking_model": " "}):
        with pytest.raises(ValueError):
            F.save_overrides(bad)
    (tmp_path / "free-reply.json").write_text(json.dumps({"thinking": "x", "thinking_timeout_s": 99}), encoding="utf-8")
    assert F.settings()["thinking"] is False and F.settings()["thinking_timeout_s"] == 8.0   # bozuk değer yok sayılır


def test_disabled_free_reply_with_thinking_on_never_calls_in_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    F.save_overrides({"enabled": False, "thinking": True})
    d, _ = drv(OFF, free=F.make_default())
    assert d.free_reply is None
    r = d.handle("sende kaç puan vereyim")
    assert not any(e["type"] == "free_reply" for e in r.events)


def test_api_get_put_thinking(tmp_path, monkeypatch):
    from backend.app.main import app
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    probed = []
    monkeypatch.setattr(F, "status", lambda cfg=None: probed.append(cfg["model"]) or {"reachable": True, "warm": False, "model": cfg["model"]})
    c = TestClient(app)
    g = c.get("/api/free-reply").json()
    assert g["thinking"] is False and g["thinking_model"] == THINK_MODEL and g["thinking_timeout_s"] == 8.0
    assert g["thinking_timeout_range"] == [1.0, 30.0] and "thinking_status" not in g and g["defaults"]["thinking"] is False
    assert g["stats"]["turns"] == 0 and g["stats"]["on"]["p50_s"] is None
    p = c.put("/api/free-reply", json={"thinking": True, "thinking_timeout_s": 10}).json()
    assert p["thinking"] is True and p["enabled"] is True and p["overridden"] == ["thinking", "thinking_timeout_s"]
    assert p["thinking_status"]["model"] == THINK_MODEL and THINK_MODEL in probed
    assert c.put("/api/free-reply", json={"thinking_timeout_s": 0.2}).status_code == 400
    p = c.put("/api/free-reply", json={"enabled": False}).json()
    assert p["enabled"] is False and p["thinking"] is True
    p = c.put("/api/free-reply", json={"thinking": None, "thinking_timeout_s": None}).json()
    assert p["thinking"] is False and p["overridden"] == ["enabled"]


# ---- Ollama istemcisi (ağsız) ----
def test_ollama_think_client_sends_think_true_and_returns_split_fields(monkeypatch):
    import httpx
    posts = []

    class Resp:
        def json(self):
            return {"message": {"content": "Tamam.", "thinking": "uzun düşünce"}, "eval_count": 321, "total_duration": 4_500_000_000,
                    "eval_duration": 4_000_000_000, "load_duration": 10_000_000}

        def raise_for_status(self):
            return None
    monkeypatch.setattr(httpx, "post", lambda url, timeout, json: posts.append(json) or Resp())
    out = F.OllamaChatClient(THINK_MODEL, "http://x:1", think=True).chat([{"role": "user", "content": "x"}], 8.0, 768, 0.6)
    assert posts[0]["think"] is True and posts[0]["model"] == THINK_MODEL and posts[0]["options"]["num_predict"] == 768
    assert out == "Tamam." and out.thinking == "uzun düşünce"
    assert out.meta == {"eval_tokens": 321, "ollama_s": 4.5, "eval_s": 4.0, "load_s": 0.01}
    F.OllamaChatClient("m1", "http://x:1").chat([{"role": "user", "content": "x"}], 1.5, 90, 0.6)
    assert posts[1]["think"] is False                                    # instruct: eskisi gibi false


def test_ollama_client_registry_separates_think_clients():
    a, b = F.ollama_client("m-reg", 30), F.ollama_client("m-reg", 30, think=True)
    assert a is not b and a.think is False and b.think is True and F.ollama_client("m-reg", 30) is a


# ---- tur kaydı ve Ayarlar özeti ----
def _session_run(tmp_path, monkeypatch, free):
    from backend.tests.test_turntaking import ScriptSTT
    from backend.tests.test_voice import make_session, settle, silence, speech

    async def run():
        turns = ["devam", "evet", "hayır", "evet", "sende kaç puan vereyim"]
        s, _, _ = make_session(tmp_path, monkeypatch, stt=ScriptSTT(turns))
        s.flow = FlowDriver(S.get("anket"), ScriptedLLM([ans("devam"), ans(True), ans(False), ans(True), OFF]))
        s.flow.free_reply = free
        s.flow.start()
        s._apply_endpointing()
        for _ in turns:
            s.state = "listening"
            s._apply_endpointing()
            s.feed(np.concatenate([silence(0.3), speech(1.0), silence(1.5)]))
            await settle(s)
        path = await s.close()
        return path, json.loads(path.read_text(encoding="utf-8"))
    return asyncio.run(run())


def test_session_record_thinking_fields(tmp_path, monkeypatch):
    path, saved = _session_run(tmp_path, monkeypatch, think_replier())
    t = next(t for t in saved["turns"] if "reply_source" in t)
    assert t["reply_source"] == "qwen" and t["free_reply_thinking"] is True and t["free_reply_model"] == THINK_MODEL
    assert t["free_reply_eval_tokens"] == 412 and t["free_reply_ollama_s"] == 5.2 and t["free_reply_think_chars"] > 0
    assert "free_reply_s" in t
    cfg = saved["config"]["free_reply"]
    assert cfg["thinking"] is True and cfg["model"] == THINK_MODEL and cfg["timeout_s"] == 8.0
    st = F.thinking_stats(path.parent)
    assert st["on"]["turns"] == 1 and st["on"]["qwen_rate"] == 1.0 and st["on"]["models"] == [THINK_MODEL] and st["off"]["turns"] == 0


def test_session_record_thinking_off_fields(tmp_path, monkeypatch):
    _, saved = _session_run(tmp_path, monkeypatch, F.FreeReplier(FakeChat(), {"categories": ALL_CATEGORIES, "use_pool_fallback_only": False}))
    t = next(t for t in saved["turns"] if "reply_source" in t)
    assert t["free_reply_thinking"] is False and t["free_reply_model"] == FakeChat.model and "free_reply_think_chars" not in t
    assert saved["config"]["free_reply"]["thinking"] is False


def test_thinking_stats_groups_and_excludes_not_called(tmp_path):
    def doc(name, turns):
        (tmp_path / f"{name}.json").write_text(json.dumps({"id": name, "profile": "L2", "turns": turns}), encoding="utf-8")
    doc("a", [{"turn": 1, "greeting": True},
              {"turn": 2, "reply_source": "qwen", "free_reply_s": 0.8},                                   # eski kayıt: thinking alanı yok -> kapalı
              {"turn": 3, "reply_source": "pool", "free_reply_s": 1.6, "free_reply_fallback": "timeout", "free_reply_thinking": False},
              {"turn": 4, "reply_source": "pool", "free_reply_s": 0.01, "free_reply_fallback": "cold", "free_reply_thinking": False},
              {"turn": 5, "reply_source": "pool", "free_reply_s": 0.0, "free_reply_fallback": "category"}])
    doc("b", [{"turn": 1, "reply_source": "qwen", "free_reply_s": 4.0, "free_reply_thinking": True, "free_reply_model": THINK_MODEL},
              {"turn": 2, "reply_source": "qwen", "free_reply_s": 6.0, "free_reply_thinking": True, "free_reply_model": THINK_MODEL},
              {"turn": 3, "reply_source": "pool", "free_reply_s": 8.2, "free_reply_fallback": "timeout", "free_reply_thinking": True}])
    (tmp_path / "bozuk.json").write_text("{", encoding="utf-8")
    st = F.thinking_stats(tmp_path)
    off, on = st["off"], st["on"]
    assert st["turns"] == 6                                                          # 'category' turu sayılmaz
    assert off["turns"] == 3 and off["called"] == 2 and off["mean_s"] == 1.2 and off["fallback_reasons"] == {"timeout": 1, "cold": 1}
    assert on["turns"] == 3 and on["called"] == 3 and on["p50_s"] == 6.0 and on["p95_s"] == 8.2 and on["qwen_rate"] == 0.667
    assert on["fallback_rate"] == 0.333 and on["models"] == [THINK_MODEL]
    assert F.thinking_stats(tmp_path, last=1)["turns"] == 1
    assert F.thinking_stats(tmp_path / "yok")["turns"] == 0


# ---- değerlendirme betiği ----
def test_eval_script_fake_thinking_run(tmp_path, monkeypatch):
    out = tmp_path / "ev.json"
    monkeypatch.setattr(sys, "argv", ["eval_free_reply.py", "--fake", "--thinking", "--runs", "1", "--out", str(out)])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(str(S.ROOT / "scripts" / "eval_free_reply.py"), run_name="__main__")
    assert e.value.code == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["meta"]["thinking"] is True and doc["meta"]["timeout_s"] == F.defaults()["thinking_timeout_s"]
    assert all(r["thinking"] is True and r["think_chars"] > 0 for r in doc["rows"])
    assert all("düşünüyorum" not in (r["text"] or "") and "düşünüyorum" not in r["spoken"] for r in doc["rows"])
    assert {"pass_rate", "seconds", "think_chars_mean", "eval_tokens_mean"} <= set(doc["summary"])
    assert "thinking: açık" in out.with_suffix(".md").read_text(encoding="utf-8")
