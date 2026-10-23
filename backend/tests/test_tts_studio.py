"""lab-001: TTS stüdyosu backend'i — üretim, seviye normalizasyonu, telefon turu, kör dinleme, puanlar, CSV.

Gerçek modellerle doğrulama Mac'te yapılır (evidence/lab-001-*.json).
"""
import csv
import io
import json
import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from backend.app import tts_studio
from backend.app.main import app
from backend.app.providers import registry
from backend.app.providers.base import TTSProvider, TTSResult

client = TestClient(app)
RATE = 16000


def tone(seconds, amp, freq=220.0, rate=RATE):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class TtsQuiet(TTSProvider):
    kind = "tts_quiet"

    def synthesize(self, text, language="tr"):
        return TTSResult(tone(0.5 + 0.02 * len(text), 0.05), RATE, 0.1, self.kind, self.model)


class TtsLoud(TTSProvider):
    kind = "tts_loud"

    def synthesize(self, text, language="tr"):
        return TTSResult(tone(0.4 + 0.02 * len(text), 0.6, 330.0), 24000, 0.3, self.kind, self.model)


class TtsStream(TTSProvider):
    kind = "tts_stream"

    def synthesize(self, text, language="tr"):
        return TTSResult(tone(0.6, 0.3), RATE, 0.5, self.kind, self.model, extra={"first_audio_seconds": 0.07})


class TtsBroken(TTSProvider):
    kind = "tts_broken"

    def warmup_call(self):
        return TTSResult(tone(0.1, 0.1), RATE, 0.01, self.kind, self.model)

    def synthesize(self, text, language="tr"):
        raise RuntimeError("ses üretilemedi")


YAML = """
profiles:
  Q:
    name: Sessiz
    tts: {provider: tts_quiet, model: mq}
  Q2:
    name: Aynı model
    tts: {provider: tts_quiet, model: mq}
  LD:
    name: Gürültülü
    tts: {provider: tts_loud, model: ml}
  ST:
    name: Akış
    tts: {provider: tts_stream, model: ms}
  BR:
    name: Bozuk
    tts: {provider: tts_broken, model: mb}
  NOTTS:
    name: TTS yok
    tts: null
studio_profiles:
  S-only:
    name: Yalnız stüdyo
    stt: null
    llm: null
    tts: {provider: tts_quiet, model: msolo}
"""
SENTENCES = [f"Örnek cümle numara {i} için merhaba." for i in range(1, 11)]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "profiles.yaml"
    cfg.write_text(YAML, encoding="utf-8")
    monkeypatch.setenv("SVA_PROFILES", str(cfg))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path / "data"))
    for cls in (TtsQuiet, TtsLoud, TtsStream, TtsBroken):
        monkeypatch.setitem(registry.PROVIDERS, cls.kind, cls)
    registry._cache.clear()
    yield tmp_path
    registry._cache.clear()


def warm(pid):
    res = client.post(f"/api/profiles/{pid}/warmup", params={"keep_others": "true"})
    assert res.status_code == 202, res.text
    for _ in range(300):
        job = client.get(f"/api/profiles/{pid}/warmup").json()
        if job["state"] != "running":
            assert job["state"] == "ready", job
            return job
        time.sleep(0.01)
    raise AssertionError("warmup bitmedi")


def make_session(profiles, sentences=SENTENCES, **extra):
    res = client.post("/api/tts/sessions", json={"sentences": sentences, "profiles": profiles, **extra})
    assert res.status_code == 202, res.text
    sid = res.json()["id"]
    for _ in range(600):
        s = client.get(f"/api/tts/sessions/{sid}").json()
        if s["state"] != "running":
            return s
        time.sleep(0.02)
    raise AssertionError("üretim bitmedi")


def clip_wav(sid, clip):
    res = client.get(f"/api/tts/sessions/{sid}/clips/{clip['id']}/audio")
    assert res.status_code == 200
    return sf.read(io.BytesIO(res.content), dtype="float32")


@pytest.fixture()
def three_models(env):
    for pid in ("Q", "LD", "ST"):
        warm(pid)
    return make_session(["Q", "LD", "ST"])


def test_models_lists_distinct_with_studio_only(env):
    models = client.get("/api/tts/models").json()
    assert [m["model"] for m in models] == ["mq", "ml", "ms", "mb", "msolo"]  # Q2, Q ile aynı: tek satır
    assert models[0]["profiles"] == ["Q", "Q2"] and models[-1]["studio_only"] is True
    assert "S-only" not in [p["id"] for p in client.get("/api/profiles").json()]  # profil listesinde görünmez


def test_ten_sentences_three_models_with_timing(three_models):
    s = three_models
    assert s["state"] == "done" and s["total"] == 30 and s["done"] == 30
    ok = [c for c in s["clips"] if c["status"] == "ok"]
    assert len(ok) == 30 and {c["profile"] for c in ok} == {"Q", "LD", "ST"}
    for c in ok:
        assert c["first_audio_seconds"] > 0 and c["rtf"] > 0 and c["audio_seconds"] > 0
    stream = next(c for c in ok if c["profile"] == "ST")
    assert stream["first_audio_seconds"] == 0.07 and stream["first_audio_measured"] is True
    batch = next(c for c in ok if c["profile"] == "Q")
    assert batch["first_audio_seconds"] == batch["gen_seconds"] and batch["first_audio_measured"] is False


def test_clips_levelled_to_same_loudness(three_models):
    s = three_models
    levels = []
    for c in s["clips"]:
        audio, _ = clip_wav(s["id"], c)
        levels.append(tts_studio.rms_dbfs(audio))
        assert abs(c["rms_dbfs"] - levels[-1]) < 0.3
    assert max(levels) - min(levels) < 1.0  # 0.05 ve 0.6 genlikli kaynaklar aynı düzeye geldi
    assert all(abs(lv - tts_studio.TARGET_RMS_DBFS) < 1.0 for lv in levels)


def test_peak_limit_prevents_clipping():
    out = tts_studio.normalize_level(np.array([0.9, -0.9, 0.0, 0.0] * 100, dtype=np.float32), -6.0)
    assert float(np.max(np.abs(out))) <= tts_studio.PEAK_LIMIT + 1e-6


def test_phone_round_is_8khz_bandlimited(env):
    warm("LD")
    s = make_session(["LD"], sentences=SENTENCES[:2], phone=True)
    assert s["phone"] is True
    _, rate = clip_wav(s["id"], s["clips"][0])
    assert rate == 8000 and s["clips"][0]["sample_rate"] == 8000
    low = tts_studio.phone_filter(tone(1.0, 0.5, 100.0, 8000), 8000)[0]
    mid = tts_studio.phone_filter(tone(1.0, 0.5, 1000.0, 8000), 8000)[0]
    assert tts_studio.rms_dbfs(low) < tts_studio.rms_dbfs(mid) - 15  # 100 Hz bastırılır, 1 kHz geçer


def test_cold_and_failed_models_do_not_block_others(env):
    warm("Q")
    warm("BR")
    s = make_session(["Q", "LD", "BR"], sentences=SENTENCES[:3])  # LD ısıtılmadı
    by = {}
    for c in s["clips"]:
        by.setdefault(c["profile"], []).append(c["status"])
    assert by["Q"] == ["ok"] * 3
    assert by["LD"] == ["cold"]  # soğuk model için ilk cümlede durur
    assert by["BR"] == ["failed"] * 3
    assert s["state"] == "done" and s["done"] == s["total"]


def test_validation(env):
    assert client.post("/api/tts/sessions", json={"sentences": ["  "], "profiles": ["Q"]}).status_code == 400
    assert client.post("/api/tts/sessions", json={"sentences": ["a"], "profiles": ["NOTTS"]}).status_code == 400
    assert client.post("/api/tts/sessions", json={"sentences": ["a"], "profiles": ["YOK"]}).status_code == 400
    assert client.post("/api/tts/sessions", json={"sentences": ["a" * 401], "profiles": ["Q"]}).status_code == 400
    assert client.get("/api/tts/sessions/20260101-000000-abcdef").status_code == 404
    assert client.get("/api/tts/sessions/..%2f..%2fetc").status_code == 404


def test_blind_view_hides_identity(three_models):
    sid = three_models["id"]
    res = client.post(f"/api/tts/sessions/{sid}/listen", json={"listener": "Ayşe"})
    assert res.status_code == 200
    body = res.json()
    text = json.dumps(body, ensure_ascii=False)
    for secret in ("tts_quiet", "tts_loud", "tts_stream", '"mq"', '"ml"', '"ms"', '"Q"', '"LD"', '"ST"',
                   "profile", "provider", "model", "c001-", "gen_seconds", "rtf"):
        assert secret not in text, secret
    assert len(body["items"]) == 30 and body["rated"] == 0
    assert all(set(it) == {"position", "token", "sentence", "rating"} for it in body["items"])


def test_order_differs_per_listener_and_is_stable_per_listener(three_models):
    sid = three_models["id"]

    def order(name, **kw):
        res = client.post(f"/api/tts/sessions/{sid}/listen", json={"listener": name, **kw}).json()
        return [it["token"] for it in res["items"]], [it["sentence"] for it in res["items"]]

    results = [order(n) for n in ("Ayşe", "Mehmet", "Zeynep", "Can")]
    assert len({tuple(s) for _, s in results}) > 1  # sıra dinleyiciye göre farklı
    assert order("Ayşe") == results[0]  # aynı dinleyici sayfayı yenileyince aynı sıra ve jetonlar
    assert order("Ayşe", restart=True)[0] != results[0][0]  # yeniden başlatma yeni jeton / sıra üretir
    assert sorted(results[0][1]) == sorted(results[1][1])  # herkes aynı cümleleri dinler


def test_blind_audio_needs_matching_listener_token(three_models):
    sid = three_models["id"]
    items = client.post(f"/api/tts/sessions/{sid}/listen", json={"listener": "Ayşe"}).json()["items"]
    client.post(f"/api/tts/sessions/{sid}/listen", json={"listener": "Mehmet"})
    ok = client.get(f"/api/tts/sessions/{sid}/blind/{items[0]['token']}/audio", params={"listener": "Ayşe"})
    assert ok.status_code == 200 and ok.headers["content-type"] == "audio/wav"
    assert client.get(f"/api/tts/sessions/{sid}/blind/{items[0]['token']}/audio",
                      params={"listener": "Mehmet"}).status_code == 404
    assert client.get(f"/api/tts/sessions/{sid}/blind/{'0' * 16}/audio", params={"listener": "Ayşe"}).status_code == 404
    assert client.get(f"/api/tts/sessions/{sid}/blind/..%2fsession.json/audio",
                      params={"listener": "Ayşe"}).status_code == 404


def rate(sid, listener, token, n=4, h=3, m=1, comment=""):
    return client.post(f"/api/tts/sessions/{sid}/ratings", json={
        "listener": listener, "token": token, "naturalness": n, "humanlike": h, "mispronunciation": m,
        "comment": comment})


def test_ratings_saved_summarised_and_exported_as_csv(three_models):
    sid, clips = three_models["id"], {c["id"]: c for c in three_models["clips"]}
    items = client.post(f"/api/tts/sessions/{sid}/listen", json={"listener": "Ayşe"}).json()["items"]
    listener_file = next((tts_studio.sessions_dir() / sid / "listeners").iterdir())
    order = json.loads(listener_file.read_text(encoding="utf-8"))["order"]
    profile_of = {e["token"]: clips[e["clip_id"]]["profile"] for e in order}
    for it in items:
        good = profile_of[it["token"]] == "ST"
        res = rate(sid, "Ayşe", it["token"], n=5 if good else 2, h=5 if good else 2, m=0 if good else 3)
        assert res.status_code == 201
    again = client.post(f"/api/tts/sessions/{sid}/listen", json={"listener": "Ayşe"}).json()
    assert again["rated"] == 30 and again["items"][0]["rating"]["naturalness"] in (2, 5)  # yenileyince puanlar geri gelir
    summary = {r["profile"]: r for r in client.get(f"/api/tts/sessions/{sid}/summary").json()}
    assert summary["ST"]["naturalness"] == 5 and summary["Q"]["naturalness"] == 2 and summary["ST"]["ratings"] == 10
    res = client.get(f"/api/tts/sessions/{sid}/ratings.csv")
    assert res.headers["content-type"].startswith("text/csv") and "attachment" in res.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert len(rows) == 30 and list(rows[0]) == tts_studio.CSV_COLUMNS
    assert {r["profile"] for r in rows} == {"Q", "LD", "ST"} and {r["model"] for r in rows} == {"mq", "ml", "ms"}
    assert all(r["first_audio_s"] and r["rtf"] for r in rows)


def test_rating_overwrite_and_validation(three_models):
    sid = three_models["id"]
    token = client.post(f"/api/tts/sessions/{sid}/listen", json={"listener": "Ayşe"}).json()["items"][0]["token"]
    assert rate(sid, "Ayşe", token, n=1).status_code == 201
    assert rate(sid, "Ayşe", token, n=4).status_code == 201
    rows = list(csv.DictReader(io.StringIO(client.get(f"/api/tts/sessions/{sid}/ratings.csv").text.lstrip("﻿"))))
    assert len(rows) == 1 and rows[0]["naturalness"] == "4"
    assert rate(sid, "Ayşe", token, n=6).status_code == 422
    assert rate(sid, "Ayşe", token, n=0).status_code == 422
    assert rate(sid, "Ayşe", "f" * 16).status_code == 404
    assert rate(sid, "Mehmet", token).status_code == 404  # başkasının jetonu ile puan verilemez


def test_sessions_listed_and_studio_only_model_works(env):
    warm("S-only")
    s = make_session(["S-only"], sentences=SENTENCES[:2])
    assert [c["status"] for c in s["clips"]] == ["ok", "ok"]
    listed = client.get("/api/tts/sessions").json()
    assert listed[0]["id"] == s["id"] and listed[0]["clips"] == 2 and listed[0]["models"] == ["S-only"]


def test_generation_logged_with_source(env):
    warm("Q")
    make_session(["Q"], sentences=SENTENCES[:2])
    lines = [json.loads(x) for x in (env / "logs" / "provider-calls.jsonl").read_text().splitlines()]
    studio = [x for x in lines if x.get("source") == "tts-studio"]
    assert len(studio) == 2 and all(x["first_audio_seconds"] > 0 and x["rtf"] > 0 for x in studio)


def test_interrupted_session_is_not_stuck_running(env):
    """Backend üretim sırasında ölürse oturum 'running' kalmaz; tamamlanan klipler dinlenebilir."""
    clip = {"id": "c001-Q", "sentence_idx": 0, "profile": "Q", "provider": "tts_quiet", "model": "mq", "status": "ok",
            "first_audio_seconds": 0.1, "rtf": 0.1, "audio_seconds": 1.0}
    from backend.app.providers.audio import encode_wav
    stale = tts_studio.save_session({"id": "20260101-000000-abcdef", "language": "tr", "phone": False,
                                     "sentences": ["a", "b"], "profiles": ["Q"], "clips": [clip], "done": 1,
                                     "total": 2, "state": "running"}, {"c001-Q": encode_wav(tone(1.0, 0.3), RATE)})
    got = client.get(f"/api/tts/sessions/{stale['id']}").json()
    assert got["state"] == "interrupted" and "yarıda" in got["error"]
    assert client.get(f"/api/tts/sessions/{stale['id']}").json()["state"] == "interrupted"  # kalıcı
    assert client.post(f"/api/tts/sessions/{stale['id']}/listen", json={"listener": "Ayşe"}).status_code == 200
    assert client.post("/api/tts/sessions", json={"sentences": ["a"], "profiles": ["Q"]}).status_code in (202, 409)
