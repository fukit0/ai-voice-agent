"""core-011: realtime profiller (A2 OpenAI, A3 Gemini) — hibrit yöntem.

Doğrulama maddeleri: (1) realtime profille senaryo seçilip konuşma başlar, ajan sesi çıkışa gider; (2) model her cevabı
fonksiyon çağrısıyla bildirir, FlowDriver sonraki soruyu seçer, cevaplar listelenir; (3) tur başına uçtan uca gecikme
(STT/LLM/TTS ayrımı yok); (4) fonksiyon çağrısı güvenilirliği: bozuk/yanlış tipli/eksik çağrı 'anlaşılamadı' sayılır.
Sağlayıcı bağdaştırıcıları ağ olmadan, protokol mesajları seviyesinde sınanır; canlı API doğrulaması Mac'te yapılır.
"""
import asyncio
import base64
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import scenario as S
from backend.app.main import app
from backend.app.voice import realtime as R
from backend.app.voice.flow import FlowDriver
from backend.app.voice.realtime import (FakeRealtime, GeminiLive, OpenAIRealtime, RealtimeVoiceSession,
                                        make_backend, parse_tool_args)
from backend.tests.test_voice import FakeOut, YAML, env, silence, speech  # noqa: F401


# ---- fonksiyon çağrısı argümanları ---------------------------------------------------------------------------------
@pytest.mark.parametrize("args,expected", [
    ({"intent": "answer", "value_json": "8"}, {"intent": "answer", "value": 8}),
    ('{"intent": "answer", "value_json": "true"}', {"intent": "answer", "value": True}),
    ({"intent": "answer", "value_json": "\"yarın saat on beşte\""}, {"intent": "answer", "value": "yarın saat on beşte"}),
    ({"intent": "answer", "value_json": "yarın saat on beşte"}, {"intent": "answer", "value": "yarın saat on beşte"}),
    ({"intent": "refuse", "value_json": "null"}, {"intent": "refuse", "value": None}),
    ({"value_json": "1"}, None), ("not json", None), (None, None), ([], None),
])
def test_parse_tool_args(args, expected):
    assert parse_tool_args(args) == expected


# ---- bağdaştırıcılar: protokol mesajları (ağ yok) -------------------------------------------------------------------
class Sent:
    def __init__(self):
        self.msgs = []

    async def send(self, raw):
        self.msgs.append(json.loads(raw))


def _backend(cls, monkeypatch):
    b = cls("model-x")
    b.ws = Sent()
    return b


def test_openai_requests_function_only_answer_then_exact_speech(monkeypatch):
    b = _backend(OpenAIRealtime, monkeypatch)
    b.set_answer_rule("true (evet) veya false (hayır)")

    async def go():
        await b.request_answer()
        await b.tool_result("c1", "report_answer")
        await b.speak("Merhaba Ahmet Bey.", "0-10 arası tam sayı")
        await b.interrupt()
        await b.send_audio(b"\x00\x01")
    asyncio.run(go())
    ans, out, speak, cancel, audio = b.ws.msgs
    assert ans["type"] == "response.create" and ans["response"]["output_modalities"] == ["text"]
    assert ans["response"]["tool_choice"] == {"type": "function", "name": "report_answer"}
    assert "true (evet)" in ans["response"]["instructions"]
    assert out["item"] == {"type": "function_call_output", "call_id": "c1", "output": '{"ok": true}'}
    assert speak["response"]["output_modalities"] == ["audio"] and speak["response"]["tool_choice"] == "none"
    assert "«Merhaba Ahmet Bey.»" in speak["response"]["instructions"] and "AYNEN SÖYLE" in speak["response"]["instructions"]
    assert cancel == {"type": "response.cancel"}
    assert audio["type"] == "input_audio_buffer.append" and base64.b64decode(audio["audio"]) == b"\x00\x01"


def test_openai_parses_server_events():
    b = OpenAIRealtime("m")
    pcm = base64.b64encode(b"\x01\x00\x02\x00").decode()
    assert b.parse({"type": "response.output_audio.delta", "delta": pcm}) == [{"type": "audio", "pcm": b"\x01\x00\x02\x00"}]
    assert b.parse({"type": "response.audio.delta", "delta": pcm})[0]["type"] == "audio"       # beta adı
    assert b.parse({"type": "input_audio_buffer.speech_stopped"}) == [{"type": "speech_stopped"}]
    assert b.parse({"type": "conversation.item.input_audio_transcription.completed", "transcript": "evet"}) == [
        {"type": "user_text", "text": "evet"}]
    call = {"type": "response.function_call_arguments.done", "call_id": "c1", "name": "report_answer",
            "arguments": '{"intent":"answer","value_json":"8"}'}
    assert b.parse(call) == [{"type": "tool_call", "id": "c1", "name": "report_answer",
                              "args": '{"intent":"answer","value_json":"8"}'}]
    assert b.parse(call) == []                                                                   # aynı çağrı iki kez işlenmez
    assert b.parse({"type": "response.done"}) == [{"type": "response_done"}]
    assert b.parse({"type": "error", "error": {"message": "kota"}}) == [{"type": "error", "message": "kota"}]
    assert b.parse({"type": "session.updated"}) == []


def test_gemini_messages_and_events(monkeypatch):
    b = _backend(GeminiLive, monkeypatch)

    async def go():
        await b.speak("Merhaba.", "true (evet) veya false (hayır)")
        await b.tool_result("f1", "report_answer")
        await b.send_audio(b"\x00\x00")
    asyncio.run(go())
    speak, result, audio = b.ws.msgs
    assert "realtimeInput" in speak and "«Merhaba.»" in speak["realtimeInput"]["text"] and "clientContent" not in speak
    assert result == {"toolResponse": {"functionResponses": [{"id": "f1", "name": "report_answer", "response": {"ok": True}}]}}
    assert audio["realtimeInput"]["audio"]["mimeType"] == "audio/pcm;rate=16000"
    assert b.in_rate == 16000 and b.out_rate == 24000
    pcm = base64.b64encode(b"\x05\x00").decode()
    msg = {"serverContent": {"modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm", "data": pcm}}]},
                             "inputTranscription": {"text": "tamam"}, "outputTranscription": {"text": "Merhaba"},
                             "interrupted": True, "turnComplete": True},
           "toolCall": {"functionCalls": [{"id": "f1", "name": "report_answer", "args": {"intent": "answer", "value_json": "true"}}]}}
    kinds = [e["type"] for e in b.parse(msg)]
    assert kinds == ["audio", "user_text", "agent_text", "interrupted", "response_done", "tool_call"]


def test_make_backend_known_and_unknown(monkeypatch):
    assert isinstance(make_backend({"provider": "openai_realtime", "model": "x"}), OpenAIRealtime)
    assert isinstance(make_backend({"provider": "gemini_live", "model": "x"}), GeminiLive)
    monkeypatch.delenv("SVA_FAKE_PROVIDERS", raising=False)
    with pytest.raises(ValueError):
        make_backend({"provider": "fake_realtime"})        # sahte sağlayıcı yalnızca SVA_FAKE_PROVIDERS=1 iken
    with pytest.raises(ValueError):
        make_backend({"provider": "yok"})


# ---- oturum: hibrit akış (FakeRealtime) ----------------------------------------------------------------------------
async def settle_rt(s, cond, timeout=3.0):
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("beklenen koşul gerçekleşmedi")


def build(tmp_path, monkeypatch, scenario="welcome", script=None):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path / "data"))
    events, out = [], FakeOut()
    backend = FakeRealtime("m", script)
    s = RealtimeVoiceSession("rt1", "RT", backend, out, events.append, FlowDriver(S.get(scenario), None))
    return s, backend, out, events


async def user_says(s, out, seconds=0.8):
    """Müşteri konuşur: ses + bitiş sessizliği gerçek zamanlıdan hızlı beslenir; ajanın önceki sesi bitmiş sayılır."""
    out.cb()                                                 # oynatma bitti -> dinliyor
    s.feed(np.concatenate([silence(0.3), speech(seconds, amp=0.2), silence(1.2)]))


def test_opening_is_spoken_verbatim_with_value_rule_and_session_goes_to_speaking(tmp_path, monkeypatch):
    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch)
        await s.start()
        await settle_rt(s, lambda: out.pushed)
        text, rule = backend.spoken[0]
        assert text == S.fill(S.get("welcome")["steps"][0]["defaultText"], s.flow.values)       # metni akış seçti
        assert "true (evet)" in rule and "AYNEN SÖYLE" not in text
        assert "report_answer" in backend.instructions and s.state == "speaking"
        assert any(e["type"] == "transcript" and e["role"] == "agent" for e in events)
        await s.close()
    asyncio.run(main())


def test_function_call_drives_flow_and_latency_is_end_to_end(tmp_path, monkeypatch):
    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch)
        await s.start()
        await settle_rt(s, lambda: s.turns)                    # açılış turu tamam
        await user_says(s, out)
        await settle_rt(s, lambda: len(s.turns) == 2)
        ans = [e for e in events if e["type"] == "answer"]
        assert ans[0]["step"] == "acilis" and ans[0]["value"] is True and ans[0]["utterance"] == "evet"
        assert s.flow.current == "hosgeldin" and backend.results == ["call1"]
        t = s.turns[1]
        assert t["realtime"] is True and "stt_s" not in t and "llm_s" not in t and "tts_first_s" not in t
        assert t["first_audio_after_end_s"] >= t["answer_s"] >= 0 and t["speak_s"] >= 0
        assert s.stats["tool_calls"] == 1 and s.stats["invalid_tool_calls"] == 0
        await s.close()
    asyncio.run(main())


def test_unreliable_function_calls_are_reasked_not_accepted(tmp_path, monkeypatch):
    bad = [{"intent": "answer", "value_json": "\"evet\""},      # YesNo için metin: yanlış tip
           None,                                                # model fonksiyon çağırmadı
           {"intent": "answer", "value_json": "true"}]          # üçüncüde düzgün
    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch, script=bad)
        await s.start()
        await settle_rt(s, lambda: s.turns)
        for n in (2, 3, 4):
            await user_says(s, out)
            await settle_rt(s, lambda n=n: len(s.turns) == n)
        spoken = [t for t, _ in backend.spoken]
        assert spoken[1].startswith("Özür dilerim, tam anlayamadım.") and spoken[2].startswith("Kusura bakmayın, tekrar soruyorum.")
        assert s.flow.current == "hosgeldin" and [a["value"] for a in s.flow.answers] == [True]
        assert s.stats["invalid_tool_calls"] == 2
        assert s.turns[2].get("no_tool_call") is True
        await s.close()
    asyncio.run(main())


def test_barge_in_flushes_agent_audio_and_interrupts_provider(tmp_path, monkeypatch):
    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch)
        await s.start()
        await settle_rt(s, lambda: out.pushed)
        s.feed(speech(0.5, amp=0.2))                         # ajan konuşurken müşteri araya girer
        await settle_rt(s, lambda: backend.interrupts == 1)
        ev = next(e for e in events if e["type"] == "barge_in")
        assert ev["cut_ms"] < 150 and out.flushed >= 1 and s.state == "listening"
        n = len(out.pushed)
        await s._on_event({"type": "audio", "pcm": b"\x00\x01" * 100})   # iptal edilen cevabın geç gelen sesi atılır
        assert len(out.pushed) == n
        await s.close()
    asyncio.run(main())


def test_welcome_call_completes_end_to_end_and_saves_typed_answers(tmp_path, monkeypatch):
    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch)     # varsayılan betik: her cevap true
        await s.start()
        await settle_rt(s, lambda: s.turns)
        for _ in range(20):
            if s.flow.finished:
                break
            n = len(s.turns)
            await user_says(s, out)
            await settle_rt(s, lambda n=n: len(s.turns) > n)
        assert s.flow.finished and s.flow.outcome == "tamamlandi" and s.flow.path[-1] == "kapanis"
        assert {"type": "finished", "outcome": "tamamlandi"} in events
        path = await s.close()
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["profile"] == "RT" and saved["stats"]["realtime"] == "fake_realtime"
        assert all(isinstance(a["value"], bool) for a in saved["flow"]["answers"])
        assert len(saved["turns"]) == len(saved["flow"]["answers"]) + 1
    asyncio.run(main())


def test_phone_filter_applies_to_realtime_audio_both_ways(tmp_path, monkeypatch):
    async def main():
        s, backend, out, events = build(tmp_path, monkeypatch)
        s.set_phone_filter(True)
        await s.start()
        await settle_rt(s, lambda: out.pushed)
        assert {"type": "phone_filter", "on": True} in events
        low = np.sqrt(np.mean(np.concatenate(out.pushed).astype(np.float32) ** 2))
        assert low > 0                                       # filtreli ses de çıkışa gider
        await s.close()
    asyncio.run(main())


# ---- API -----------------------------------------------------------------------------------------------------------
def test_offer_for_realtime_profile_requires_scenario_and_key(env, monkeypatch):
    c = TestClient(app)
    body = {"sdp": "v=0", "type": "offer", "profile": "RT"}
    r = c.post("/api/voice/offer", json=body)
    assert r.status_code == 400 and r.json()["detail"]["error"] == "scenario_required"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = c.post("/api/voice/offer", json={**body, "scenario": "welcome"})
    assert r.status_code == 400 and r.json()["detail"]["error"] == "missing_env"
    assert r.json()["detail"]["missing_env"] == ["OPENAI_API_KEY"]
    prof = {p["id"]: p for p in c.get("/api/profiles").json()}["RT"]
    assert prof["mode"] == "realtime" and prof["ready"] is False and prof["missing_env"] == ["OPENAI_API_KEY"]
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    prof = {p["id"]: p for p in c.get("/api/profiles").json()}["RT"]
    assert prof["ready"] is True and prof["issues"] == []


# ---- canlı duman testi mantığı (sahte sağlayıcıyla) ------------------------------------------------------------------
def test_smoke_runner_scores_function_call_reliability(tmp_path):
    from backend.app.voice.realtime_smoke import CASES, run_smoke
    good = [{"intent": "answer", "value_json": "true"}, {"intent": "answer", "value_json": "false"},
            {"intent": "answer", "value_json": "8"}, {"intent": "answer", "value_json": "10"},
            {"intent": "answer", "value_json": "45"}, {"intent": "callback", "value_json": "null"},
            {"intent": "dnc", "value_json": "null"}, {"intent": "refuse", "value_json": "null"}]
    script = list(good)
    script[2] = {"intent": "answer", "value_json": "\"sekiz\""}      # yanlış tip: sayı yerine metin
    script[4] = None                                                 # fonksiyon çağrılmadı
    res = asyncio.run(run_smoke(FakeRealtime("m", script), tmp_path, timeout=0.5))
    assert res["summary"] == {"cases": len(CASES), "called": 7, "valid_type": 6, "correct": 6}
    assert res["speak"]["got_audio"] and res["speak"]["first_audio_s"] is not None and (tmp_path / "fake_realtime.wav").exists()
    bad = {r["step"]: r for r in res["tool_calls"] if not r["correct"]}
    assert set(bad) == {"q2", "q5"} and bad["q2"]["valid_type"] is False and bad["q5"]["called"] is False
    assert not res["errors"]


def test_parse_tool_args_accepts_answer_key_alias():
    """Canlı A2 ölçümü: model {"answer":"answer","value_json":"true"} döndü (anahtar adı sapması)."""
    from app.voice.realtime import parse_tool_args
    assert parse_tool_args('{"answer":"answer","value_json":"true"}') == {"intent": "answer", "value": True}
    assert parse_tool_args('{"answer":"dnc","value_json":null}') == {"intent": "dnc", "value": None}
