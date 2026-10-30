"""lab-004: Aramalar listesi, detayı ve kıyası (data/voice-sessions oturum kayıtlarından)."""
import json

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    d = tmp_path / "voice-sessions"
    d.mkdir()
    return d


def session(folder, sid, profile, started, firsts, *, scenario="anket", outcome="completed", answers=(("Q1", "evet", False),),
            tts=None, tone=None, wav=False, deleted=False, realtime=False, barge=0, rejected=0):
    turns = [{"turn": 0, "greeting": True, "first_audio_after_end_s": 9.9}]   # açılış turu hariç tutulmalı
    for i, f in enumerate(firsts, 1):
        t = {"turn": i, "first_audio_after_end_s": f}
        if not realtime:
            t.update({"stt_s": 0.4, "llm_s": 0.8, "tts_first_s": round(f - 1.2, 3), "tts_total_s": round(f - 1.2, 3) + 0.5})
        turns.append(t)
    doc = {"id": sid, "profile": profile, "started_at": started, "stats": {"seconds_in": 30.0, "barge_ins": barge,
           "stt_rejected": rejected, **({"realtime": True} if realtime else {})},
           "turns": turns, "transcript": [{"role": "agent", "text": "Merhaba", "t": 1.0}, {"role": "user", "text": "Evet", "t": 20.5}],
           "flow": {"scenario": scenario, "outcome": outcome, "path": ["intro", "q1"], "prompt": {"version": "v5"},
                    "answers": [{"step": s, "code": s, "title": s, "kind": "yesno", "value": v, "utterance": v, "unanswered": u}
                                for s, v, u in answers]},
           "phone_filter": False}
    if tts:
        doc.update({"stt": "mlx_whisper:large-v3-turbo", "llm": "ollama:qwen3", "tts": tts, "tts_tone": tone, "tts_speed": 1.0})
    if deleted:
        doc["audio"] = {"deleted": True}
    (folder / f"{sid}.json").write_text(json.dumps(doc), encoding="utf-8")
    if wav:
        (folder / f"{sid}.wav").write_bytes(b"RIFF0000WAVE")


def seed(folder):
    session(folder, "aaaaaaaaaaa1", "L2", "2026-10-30T10:00:00", [2.0, 3.0], tts="ema", wav=True)
    session(folder, "aaaaaaaaaaa2", "L2", "2026-10-30T11:00:00", [1.0], outcome="refused", answers=(("Q1", None, True),), barge=2)
    session(folder, "bbbbbbbbbbb1", "L2-EL", "2026-10-30T12:00:00", [1.5, 2.5, 3.5], tts="elevenlabs:eleven_v4_turbo", tone="enerjik",
            wav=True, deleted=True, rejected=1)


def test_list_is_newest_first_with_summaries_and_facets(folder):
    seed(folder)
    r = client.get("/api/calls").json()
    assert [c["id"] for c in r["calls"]] == ["bbbbbbbbbbb1", "aaaaaaaaaaa2", "aaaaaaaaaaa1"] and r["total"] == 3
    assert r["facets"] == {"profiles": ["L2", "L2-EL"], "scenarios": ["anket"], "outcomes": ["completed", "refused"]}
    a1 = next(c for c in r["calls"] if c["id"] == "aaaaaaaaaaa1")
    assert a1["turns"] == 2 and a1["first_audio_p50_s"] == 2.5 and a1["first_audio_max_s"] == 3.0   # açılış turu (9.9) sayılmaz
    assert a1["stt_p50_s"] == 0.4 and a1["llm_p50_s"] == 0.8 and a1["answers"] == 1 and a1["duration_s"] == 20.5
    assert a1["tts"] == "ema" and a1["has_audio"] is True
    el = next(c for c in r["calls"] if c["id"] == "bbbbbbbbbbb1")
    assert el["tts"] == "elevenlabs:eleven_v4_turbo" and el["tts_tone"] == "enerjik"
    assert el["has_audio"] is False                      # KVKK: kayıt silinmiş, dosya olsa bile ses yok sayılır
    assert el["stt_rejected"] == 1
    refused = next(c for c in r["calls"] if c["id"] == "aaaaaaaaaaa2")
    assert refused["answers"] == 0 and refused["unanswered"] == 1 and refused["barge_ins"] == 2 and refused["tts"] is None   # eski kayıt


def test_list_filters(folder):
    seed(folder)
    ids = lambda q: [c["id"] for c in client.get("/api/calls", params=q).json()["calls"]]   # noqa: E731
    assert ids({"profile": "L2-EL"}) == ["bbbbbbbbbbb1"]
    assert ids({"outcome": "refused"}) == ["aaaaaaaaaaa2"]
    assert ids({"scenario": "yok"}) == []
    assert client.get("/api/calls", params={"profile": "L2"}).json()["facets"]["profiles"] == ["L2", "L2-EL"]   # facet süzgeçten bağımsız


def test_detail_has_transcript_turns_answers_and_audio_url(folder):
    seed(folder)
    d = client.get("/api/calls/aaaaaaaaaaa1").json()
    assert d["transcript"][1]["text"] == "Evet" and len(d["turns"]) == 3 and d["answers"][0]["value"] == "evet"
    assert d["path"] == ["intro", "q1"] and d["audio_url"] == "/api/voice/recordings/aaaaaaaaaaa1.wav"
    assert client.get("/api/calls/aaaaaaaaaaa2").json()["audio_url"] is None
    assert client.get("/api/calls/bbbbbbbbbbb1").json()["audio_url"] is None   # silinmiş kayıt
    assert client.get("/api/calls/cccccccccccc").status_code == 404
    assert client.get("/api/calls/..%2Fetc").status_code == 404


def test_compare_by_profile_computes_percentiles_and_deltas(folder):
    seed(folder)
    r = client.get("/api/calls/compare").json()
    assert r["group"] == "profile" and r["baseline"] == "L2"
    l2, el = r["groups"]
    assert (l2["key"], l2["sessions"], l2["turns"]) == ("L2", 2, 3)
    assert l2["first_audio"]["p50"] == 2.0 and l2["first_audio"]["min"] == 1.0 and l2["first_audio"]["max"] == 3.0   # 1,0 / 2,0 / 3,0
    assert l2["first_audio"]["p95"] <= 3.0
    assert l2["is_baseline"] is True and l2["delta_p50_s"] == 0.0 and l2["tts"] == ["ema"]
    assert l2["outcomes"] == {"completed": 1, "refused": 1} and l2["barge_ins_per_call"] == 1.0
    assert (el["sessions"], el["turns"]) == (1, 3) and el["first_audio"]["p50"] == 2.5
    assert el["delta_p50_s"] == 0.5 and el["delta_pct"] == 25.0 and el["tones"] == ["enerjik"]
    assert el["stages"]["stt"] == 0.4 and el["stages"]["tts_first"] == 1.3
    assert l2["enough_sessions"] is False and l2["meets_p50_target"] is False and r["min_sessions"] == 5
    flipped = client.get("/api/calls/compare", params={"baseline": "L2-EL"}).json()
    assert flipped["baseline"] == "L2-EL" and flipped["groups"][0]["delta_p50_s"] == -0.5


def test_compare_selected_calls_and_validation(folder):
    seed(folder)
    r = client.get("/api/calls/compare", params={"group": "call", "ids": "bbbbbbbbbbb1,aaaaaaaaaaa1,cccccccccccc"}).json()
    assert [g["key"] for g in r["groups"]] == ["bbbbbbbbbbb1", "aaaaaaaaaaa1"]   # bilinmeyen kimlik yok sayılır, sıra korunur
    assert r["baseline"] == "bbbbbbbbbbb1" and r["groups"][0]["delta_p50_s"] == 0.0 and r["groups"][1]["label"].startswith("L2 · ")
    assert client.get("/api/calls/compare", params={"group": "call"}).status_code == 422
    assert client.get("/api/calls/compare", params={"group": "call", "ids": "../x"}).status_code == 422
    assert client.get("/api/calls/compare", params={"group": "kaba"}).status_code == 422


def test_compare_handles_realtime_and_empty(folder):
    assert client.get("/api/calls/compare").json()["groups"] == []
    assert client.get("/api/calls").json()["calls"] == []
    session(folder, "dddddddddddd", "A2", "2026-10-30T09:00:00", [0.9, 1.1], realtime=True)
    g = client.get("/api/calls/compare").json()["groups"][0]
    assert g["realtime"] is True and g["stages"] == {"stt": None, "llm": None, "tts_first": None, "tts_total": None}
    assert g["first_audio"]["p50"] == 1.0 and g["meets_p50_target"] is True
    (folder / "bozuk.json").write_text("{not json", encoding="utf-8")   # bozuk dosya listeyi bozmaz
    assert len(client.get("/api/calls").json()["calls"]) == 1
