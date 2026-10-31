"""core-027: arama başında bağlantı ısıtma ve Anthropic istem önbelleği (opt-in)."""
import asyncio
import copy
import time

import pytest

from backend.app.providers import registry, remote
from backend.app.providers.base import LLMResult


class Warm:
    def __init__(self, name, delay=0.0, fail=False):
        self.name, self.delay, self.fail, self.calls = name, delay, fail, 0

    def describe(self):
        return self.name

    def prewarm(self):
        self.calls += 1
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("ağ yok")
        return 0.123


class NoWarm:
    def describe(self):
        return "yerel"


def test_prewarm_runs_in_parallel_skips_local_and_swallows_errors():
    a, b, bad = Warm("deepgram:nova-3", 0.3), Warm("anthropic:haiku", 0.3), Warm("elevenlabs:x", fail=True)
    t0 = time.perf_counter()
    out = asyncio.run(registry.prewarm(a, b, bad, NoWarm(), None))
    assert time.perf_counter() - t0 < 0.55                         # paralel: 0,3 + 0,3 sıralı olmaz
    assert out == {"deepgram:nova-3": 0.123, "anthropic:haiku": 0.123, "elevenlabs:x": None}


def test_prewarm_timeout_does_not_block_the_call():
    slow = Warm("slow", 1.0)
    async def main():
        t0 = time.perf_counter()
        out = await registry.prewarm(slow, timeout=0.1)
        return out, time.perf_counter() - t0       # ölçüm çağrı içinde: asyncio.run kapanışı arka plan iş parçacığını bekler
    out, took = asyncio.run(main())
    assert out == {"slow": None} and took < 0.5


def test_prewarm_with_only_local_providers_is_noop():
    assert asyncio.run(registry.prewarm(NoWarm(), None)) == {}


class FakeRes:
    def __init__(self, body):
        self._b = body

    def json(self):
        return self._b


def llm(monkeypatch, bodies, **opts):
    sent = []
    it = iter(bodies)

    def post(url, **kw):
        sent.append(copy.deepcopy(kw["json"]))
        b = next(it)
        if isinstance(b, Exception):
            raise b
        return FakeRes(b)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(remote, "_post", post)
    return remote.AnthropicLLM("claude-haiku-5-5", **opts), sent


OK = {"content": [{"type": "text", "text": "{}"}], "stop_reason": "end_turn", "usage": {"input_tokens": 100, "output_tokens": 5}}
MSGS = [{"role": "system", "content": "SİSTEM"}, {"role": "user", "content": "x"}]


def test_default_system_prompt_is_unchanged_plain_string(monkeypatch):
    m, sent = llm(monkeypatch, [OK])
    r = m.complete(MSGS, 50, 0.0)
    assert sent[0]["system"] == "SİSTEM" and "cache_creation_input_tokens" not in r.extra and r.input_tokens == 100


def test_prompt_cache_option_sends_cache_block_and_counts_cached_tokens(monkeypatch):
    body = {**OK, "usage": {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 600}}
    m, sent = llm(monkeypatch, [body], prompt_cache=True)
    r = m.complete(MSGS, 50, 0.0)
    assert sent[0]["system"] == [{"type": "text", "text": "SİSTEM", "cache_control": {"type": "ephemeral"}}]
    assert r.extra["cache_read_input_tokens"] == 600 and r.input_tokens == 610     # maliyet üst sınırı: hepsi tam fiyat


def test_cache_control_rejection_falls_back_to_plain_text_once(monkeypatch):
    err = remote.ProviderError("HTTP 400: system.0.cache_control: Extra inputs are not permitted")
    m, sent = llm(monkeypatch, [err, OK, OK], prompt_cache=True)
    m.complete(MSGS, 50, 0.0)
    m.complete(MSGS, 50, 0.0)
    assert isinstance(sent[0]["system"], list) and sent[1]["system"] == "SİSTEM" and sent[2]["system"] == "SİSTEM"


def test_anthropic_prewarm_makes_one_short_request_and_swallows_errors(monkeypatch):
    monkeypatch.setattr(remote, "warm_connection", lambda url, timeout=5.0: 0.01)
    m, sent = llm(monkeypatch, [OK])
    sec = m.prewarm()
    assert sec is not None and len(sent) == 1 and sent[0]["max_tokens"] == 16
    monkeypatch.setattr(remote, "warm_connection", lambda url, timeout=5.0: None)
    m2, _ = llm(monkeypatch, [remote.ProviderError("HTTP 500")])
    assert m2.prewarm() is None                       # ne TLS ne istek başardı
    monkeypatch.setattr(remote, "warm_connection", lambda url, timeout=5.0: 0.05)
    m3, _ = llm(monkeypatch, [remote.ProviderError("HTTP 500")])
    assert m3.prewarm() == 0.05                       # istek başarısız ama bağlantı ısındı


def test_voice_offer_prewarms_stt_tts_before_accept_and_llm_in_background(monkeypatch):
    pytest.importorskip("aiortc")
    import asyncio as aio
    from backend.app import api_voice
    order = []
    stt, llm_p, tts = object(), object(), object()

    async def fake_prewarm(*ps, timeout=4.0):
        if ps == (llm_p,):
            order.append("llm_start")
            await aio.sleep(0.05)               # LLM ısıtması yavaş: kabulü geciktirmemeli
            order.append("llm_done")
            return {"llm": 1.5}
        order.append("stt_tts")
        return {"x": 0.1}

    class Conn:
        sid = "a" * 12
        closed = False

        class session:
            stats = {}

            @staticmethod
            def set_vad(v):
                pass

        async def accept(self, sdp, typ):
            order.append("accept")
            return type("A", (), {"sdp": "s", "type": "answer"})()

    objs = iter([stt, llm_p, tts])
    monkeypatch.setattr(registry, "prewarm", fake_prewarm)
    monkeypatch.setattr(api_voice, "_provider", lambda prof, c: next(objs))
    import backend.app.voice.rtc as rtc
    monkeypatch.setattr(rtc, "RtcVoiceConnection", lambda *a, **k: Conn())
    monkeypatch.setattr(api_voice, "CONNECTIONS", {})

    async def run():
        res = await api_voice.offer(api_voice.OfferRequest(sdp="v=0", profile="L2"))
        assert order[:2] == ["stt_tts", "accept"] and "llm_done" not in order[:2]
        assert Conn.session.stats["prewarm_llm_pending"] is True
        await aio.sleep(0.15)
        return res

    res = aio.run(run())
    assert res["session_id"] == "a" * 12 and "llm_done" in order
    assert Conn.session.stats["prewarm_s"] == {"x": 0.1, "llm": 1.5}
    assert Conn.session.stats["prewarm_llm_pending"] is False
