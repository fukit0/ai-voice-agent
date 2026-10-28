"""core-024: A2'de model okunacak metni/akışı bozmasın — tüm sabit sorular sabit sesle, bağlam temizliği, evet/hayır çapraz kontrolü."""
import asyncio
import json

from backend.app import scenario as S
from backend.app.voice.fixedaudio import FixedAudio, fake_speech
from backend.app.voice.flow import FlowDriver, crosscheck_yesno
from backend.app.voice.realtime import FakeRealtime, OpenAIRealtime, RealtimeVoiceSession
from backend.tests.test_realtime import settle_rt
from backend.tests.test_voice import FakeOut

YESNO = {"kind": "YesNo"}


def test_fixed_audio_default_covers_every_step():
    fa = FixedAudio(fetch=fake_speech)
    assert fa.applies("musaitlik") and fa.applies("q2") and fa.applies("giris") and not fa.applies(None)
    assert not FixedAudio(steps=("giris",), fetch=fake_speech).applies("q2")      # profilde daraltılabilir


def test_crosscheck_fixes_musaitim_reported_as_refuse():
    """Canlı oturum eaee33b00412: 'Müsaitim' -> model refuse bildirdi (eski 'Dinlemek istemiyorum' bağlamda kalmıştı)."""
    obj, fix = crosscheck_yesno(YESNO, {"intent": "refuse", "value": None}, "Müsaitim.")
    assert obj == {"intent": "answer", "value": True} and fix == "refuse->evet"


def test_crosscheck_flips_contradicting_boolean_and_leaves_ambiguous_alone():
    assert crosscheck_yesno(YESNO, {"intent": "answer", "value": True}, "Hayır, müsait değilim")[0]["value"] is False
    assert crosscheck_yesno(YESNO, {"intent": "answer", "value": False}, "Evet olur")[0]["value"] is True
    same = {"intent": "answer", "value": True}
    assert crosscheck_yesno(YESNO, same, "Evet ama hayır")[1] is None             # çelişik cümle: dokunulmaz
    assert crosscheck_yesno(YESNO, same, "bir dakika bakayım")[1] is None         # işaret yok: dokunulmaz
    assert crosscheck_yesno({"kind": "Score"}, {"intent": "refuse"}, "evet")[1] is None   # yalnız YesNo
    assert crosscheck_yesno(YESNO, {"intent": "refuse"}, "Hayır, istemiyorum")[1] is None  # gerçek ret korunur


def test_flow_applies_crosscheck_only_on_voice_path_and_emits_event():
    sc = S.get("anket")
    flow = FlowDriver(sc, None)
    flow.coerce = True
    flow.start()
    while flow.current != "musaitlik":
        flow.handle_structured({"intent": "answer", "value": "devam"}, "devam")
        assert not flow.finished
    reply = flow.handle_structured({"intent": "refuse", "value": None}, "Müsaitim")
    assert any(e.get("type") == "crosscheck" for e in reply.events) and not flow.finished


def test_openai_commit_event_is_tracked_and_deleted_after_answer():
    b = OpenAIRealtime("m")
    assert b.parse({"type": "input_audio_buffer.committed", "item_id": "item_9"}) == [{"type": "user_item", "id": "item_9"}]
    sent = []

    async def fake_send(obj):
        sent.append(obj)
    b._send = fake_send
    b.user_items = ["item_9", "item_10"]
    asyncio.run(b.forget_user_items())
    assert [m["item_id"] for m in sent if m["type"] == "conversation.item.delete"] == ["item_9", "item_10"] and b.user_items == []


def test_answer_request_carries_the_asked_question_and_ignores_older_sentences():
    b = OpenAIRealtime("m")
    sent = []

    async def fake_send(obj):
        sent.append(obj)
    b._send = fake_send
    b.set_answer_rule("true (evet) veya false (hayır)", "Görüşme yapmak için müsait misiniz?")
    asyncio.run(b.request_answer())
    instr = sent[0]["response"]["instructions"]
    assert "müsait misiniz" in instr and "SON cevabına" in instr


def test_session_forgets_user_items_after_tool_call_and_logs_deviation(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path / "data"))

    class Spy(FakeRealtime):
        forgot = 0

        async def forget_user_items(self):
            Spy.forgot += 1

    async def main():
        backend = Spy()
        events = []
        s = RealtimeVoiceSession("c24", "RT", backend, FakeOut(), events.append, FlowDriver(S.get("welcome"), None))
        s.fixed_audio = FixedAudio(fetch=fake_speech, cache_dir=tmp_path / "fx")
        await s.start()
        await settle_rt(s, lambda: s.turns)
        await s._on_event({"type": "user_item", "id": "x1"})
        assert backend.user_items == ["x1"]
        await s._on_tool_call({"type": "tool_call", "id": "c1", "name": "report_answer", "args": {"intent": "answer", "value_json": "true"}})
        # beklenen tur değilse yok sayılır; doğrudan cevap beklentisi kurup tekrar dene
        s._expect, s._got_tool = "answer", False
        await s._on_tool_call({"type": "tool_call", "id": "c2", "name": "report_answer", "args": {"intent": "answer", "value_json": "true"}})
        assert Spy.forgot >= 1
        # sapma: modelin söylediği metin beklenenden farklı
        s._rec = {"turn": 99, "agent_said": "tamamen başka bir cümle"}
        s._last_spoken = "Görüşme yapmak için müsait misiniz?"
        s._finish_speak()
        assert s.stats["deviations"] == 1 and any(e.get("type") == "speech_deviation" for e in events)
        await s.close()
    asyncio.run(main())
