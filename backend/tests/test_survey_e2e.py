"""core-004: JSON senaryodan anket yürütme — ses oturumu seviyesinde uçtan uca.

Doğrulama maddeleri: (1) örnek anket iki farklı daldan uçtan uca tamamlanır; (2) anlaşılmayan cevapta
tekrar sorma gözlenir; (3) cevaplar tipe uygun JSON olarak kaydedilir.
Konuşma sesi → VAD → (sahte) STT → FlowDriver → (sahte) TTS → kaydedilen oturum JSON'u.
"""
import asyncio
import json

import numpy as np

from backend.app import scenario as S
from backend.app.voice.flow import FlowDriver
from backend.tests.test_turntaking import ScriptSTT
from backend.tests.test_flow import ScriptedLLM
from backend.tests.test_voice import make_session, settle, silence, speech


def ans(value, intent="answer"):
    return {"intent": intent, "value": value}


async def run_survey(tmp_path, monkeypatch, turns, llm_outputs):
    """turns: STT'nin döndüreceği metinler; her biri ayrı bir konuşma turu olarak sese çevrilir."""
    s, out, events = make_session(tmp_path, monkeypatch, stt=ScriptSTT(turns))
    s.flow = FlowDriver(S.get("anket"), ScriptedLLM(llm_outputs))
    s.flow.start()
    s._apply_endpointing()
    for _ in turns:
        s.state = "listening"
        s._apply_endpointing()
        s.feed(np.concatenate([silence(0.3), speech(1.0), silence(1.5)]))
        await settle(s)
        if s.flow.outcome:
            break
    path = await s.close()
    return s, events, json.loads(path.read_text(encoding="utf-8"))


def test_branch_a_completes_full_survey_and_saves_typed_answers(tmp_path, monkeypatch):
    turns = ["devam", "evet müsaitim", "hayır katılmadım", "evet hatırlıyorum", "sekiz",
             "çok yardımcı oldular", "yedi", "sekiz", "dokuz", "altı", "on", "kırk beş saniye", "dokuz", "on",
             "güvenilir bir site", "eklemek istediğim bir şey yok", "hayır aranmak istemem", "evet paylaşabilirsiniz"]
    llm = [ans("devam"), ans(True), ans(False), ans(True), ans(8),
           ans(7), ans(8), ans(9), ans(6), ans(10), ans(45), ans(9), ans(10), ans(False), ans(True)]
    s, events, saved = asyncio.run(run_survey(tmp_path, monkeypatch, turns, llm))
    flow = saved["flow"]
    assert flow["outcome"] == "tamamlandi" and flow["path"][-1] == "kapanis"
    by = {a["code"]: a["value"] for a in flow["answers"] if a["code"]}
    assert by["Q3"] is False and by["Q3X"] is True                       # bool
    assert by["Q2"] == 8 and by["Q3_1"] == 7 and by["Q12"] == 10         # int (puan)
    assert by["Q5"] == 45 and isinstance(by["Q5"], int)                  # süre -> saniye
    assert by["Q4"] == "çok yardımcı oldular" and isinstance(by["Q4"], str)   # açık uçlu: metin
    assert not any(isinstance(a["value"], str) and a["value"].isdigit() for a in flow["answers"])
    assert any(e["type"] == "outcome" and e["outcome"] == "tamamlandi" for e in events)


def test_branch_b_not_remembered_with_reask_closes_early(tmp_path, monkeypatch):
    turns = ["devam", "evet", "hayır", "hımm", "ne demek", "hayır hatırlamıyorum"]
    llm = [ans("devam"), ans(True), ans(False), ans(None, "unclear"), ans(None, "unclear"), ans(False)]
    s, events, saved = asyncio.run(run_survey(tmp_path, monkeypatch, turns, llm))
    flow = saved["flow"]
    assert flow["outcome"] == "gorusmeyi_hatirlamiyor" and flow["path"][-1] == "kapanis_hatirlamiyor"
    assert "q2" not in flow["path"]                                      # dal farklı: puan soruları hiç sorulmadı
    agent = [e["text"] for e in events if e["type"] == "transcript" and e["role"] == "agent"]
    assert any(t.startswith("Özür dilerim, tam anlayamadım.") for t in agent)      # 1. tekrar
    assert any(t.startswith("Kusura bakmayın, tekrar soruyorum.") for t in agent)  # 2. tekrar farklı biçimde
    assert agent.count(agent[-1]) == 1
    assert next(a for a in flow["answers"] if a["code"] == "Q3X")["value"] is False
