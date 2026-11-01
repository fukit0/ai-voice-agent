"""lab-005: Kıyas matrisi — puan kuralları, ağırlıklar, eksik veri, lisans eleme, yeni koşu sonrası güncelleme."""
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import matrix
from backend.app.main import app
from backend.app.profiles import load_profiles

client = TestClient(app)
PROFILES = load_profiles()


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    (tmp_path / "voice-sessions").mkdir()
    monkeypatch.setattr(matrix, "tts_rows", lambda: [])
    return tmp_path


def call(data, sid, profile, firsts):
    turns = [{"turn": 0, "greeting": True, "first_audio_after_end_s": 9.9}] + [{"turn": i, "first_audio_after_end_s": f} for i, f in enumerate(firsts, 1)]
    doc = {"id": sid, "profile": profile, "started_at": "2026-10-30T10:00:00", "stats": {"seconds_in": 30.0}, "turns": turns, "transcript": [],
           "flow": {"scenario": "anket", "outcome": "completed", "path": [], "answers": []}, "phone_filter": False}
    (data / "voice-sessions" / f"{sid}.json").write_text(json.dumps(doc), encoding="utf-8")


def stt_run(data, rid, provider, model, wer, status="ok"):
    d = data / "stt-runs" / rid
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"id": rid, "created_at": "2026-10-30T10:00:00+00:00", "results": [
        {"profile": "x", "provider": provider, "model": model, "status": status, "wer": wer}]}), encoding="utf-8")


def llm_run(data, rid, created, provider, model, full_rate):
    d = data / "llm-evals"
    d.mkdir(exist_ok=True)
    (d / f"{rid}.json").write_text(json.dumps({"id": rid, "created_at": created, "n_samples": 20, "results": [
        {"provider": provider, "model": model, "status": "ok", "summary": {"full_rate": full_rate}}]}), encoding="utf-8")


def row(body, pid):
    return next(r for r in body["rows"] if r["profile"] == pid)


def spec(pid, kind):
    return PROFILES[pid].components[kind]


# ---- saf puan kuralları ----
def test_score_rules():
    assert matrix.latency_score(1.0, 1.2, 3.0) == 100
    assert matrix.latency_score(3.5, 1.2, 3.0) == 0
    assert matrix.latency_score(2.1, 1.2, 3.0) == 50
    assert matrix.naturalness_score(1) == 0 and matrix.naturalness_score(5) == 100 and matrix.naturalness_score(3) == 50
    assert matrix.wer_score(0.1) == 90 and matrix.wer_score(1.7) == 0
    assert matrix.accuracy_score(0.85) == 85


def test_combine_renormalises_over_available_criteria():
    w = {"latency": 30, "naturalness": 25, "accuracy": 25, "wer": 10, "resources": 10}
    r = matrix.combine({"latency": 100, "naturalness": 50, "accuracy": None, "wer": None, "resources": None}, w, 0.5)
    assert r["total"] == round((30 * 100 + 25 * 50) / 55, 1) and r["coverage"] == round(55 / 100, 3)
    assert set(r["missing"]) == {"accuracy", "wer", "resources"}
    low = matrix.combine({"latency": 100}, w, 0.5)            # kapsam %30 < %50 → sayı yok
    assert low["total"] is None and low["coverage"] == 0.3


def test_parse_weights():
    d = {"latency": 30, "naturalness": 25, "accuracy": 25, "wer": 10, "resources": 10}
    assert matrix.parse_weights("latency:50", d)["latency"] == 50 and matrix.parse_weights("", d) == d
    for bad in ("foo:1", "latency:-1", "latency:abc", "latency:0,naturalness:0,accuracy:0,wer:0,resources:0"):
        with pytest.raises(ValueError):
            matrix.parse_weights(bad, d)


# ---- API ----
def test_empty_data_invents_nothing(data):
    body = client.get("/api/matrix").json()
    assert len(body["rows"]) == len(PROFILES)
    assert all(r["total"] is None and r["rank"] is None and all(m is None for m in r["metrics"].values()) for r in body["rows"])
    assert [c["id"] for c in body["criteria"]] == matrix.IDS


def test_new_session_updates_without_restart(data):
    assert row(client.get("/api/matrix").json(), "L1")["metrics"]["latency"] is None
    for i in range(5):
        call(data, f"s{i}", "L1", [1.2, 1.2])
    m = row(client.get("/api/matrix").json(), "L1")["metrics"]["latency"]
    assert m["value"] == 1.2 and m["score"] == 100 and m["n"] == 5 and m["note"] is None
    call(data, "slow", "L1", [3.0] * 40)                       # yeni koşu sonrası değer değişir
    assert row(client.get("/api/matrix").json(), "L1")["metrics"]["latency"]["score"] < 100


def test_few_sessions_flagged(data):
    call(data, "a", "L1", [1.5])
    assert "örnek az" in row(client.get("/api/matrix").json(), "L1")["metrics"]["latency"]["note"]


def test_wer_and_accuracy_joined_by_provider_and_model(data):
    s, l = spec("L1", "stt"), spec("L1", "llm")
    stt_run(data, "20261030-100000-aaaaaa", s["provider"], s["model"], 0.2)
    stt_run(data, "20261030-100001-bbbbbb", s["provider"], s["model"] + " + ipucu", 0.01)   # ipucu varyantı sayılmaz
    llm_run(data, "old", "2026-10-29T10:00:00", l["provider"], l["model"], 0.5)
    llm_run(data, "new", "2026-10-30T10:00:00", l["provider"], l["model"], 0.9)
    m = row(client.get("/api/matrix").json(), "L1")["metrics"]
    assert m["wer"]["score"] == 80 and m["wer"]["n"] == 1
    assert m["accuracy"]["score"] == 90 and "new" in m["accuracy"]["note"]       # en yeni koşu


def test_tts_ratings_join_and_each_row_counted_once(data, monkeypatch):
    t = spec("L1", "tts")
    m_ = t.get("model") or ""
    rows = [{"profile": "L1", "provider": t["provider"], "model": m_, "naturalness": 5, "humanlike": 4},
            {"profile": "zz", "provider": t["provider"], "model": m_, "naturalness": 3, "humanlike": 2},
            {"profile": "zz", "provider": "baska", "model": "x", "naturalness": 1, "humanlike": 1}]
    monkeypatch.setattr(matrix, "tts_rows", lambda: rows)
    m = row(client.get("/api/matrix").json(), "L1")["metrics"]["naturalness"]
    assert m["n"] == 2 and m["value"] == 4 and m["score"] == 75


def test_weights_recompute_totals_and_ranking(data, monkeypatch):
    for i in range(5):
        call(data, f"f{i}", "L1", [1.2])
        call(data, f"s{i}", "L2", [3.0])
    for pid, rate in (("L1", 0.4), ("L2", 0.9)):
        l = spec(pid, "llm")
        llm_run(data, f"r{pid}", "2026-10-30T10:00:00", l["provider"], l["model"], rate)
    base = client.get("/api/matrix?weights=latency:50,accuracy:50,naturalness:0,wer:0,resources:0").json()
    acc = client.get("/api/matrix?weights=latency:1,accuracy:99,naturalness:0,wer:0,resources:0").json()
    b1, b2 = row(base, "L1"), row(base, "L2")
    assert b1["total"] == 70 and b2["total"] == 45 and b1["rank"] < b2["rank"]   # (100+40)/2 ; (0+90)/2
    a1, a2 = row(acc, "L1"), row(acc, "L2")
    assert a2["total"] > a1["total"] and a2["rank"] < a1["rank"]                        # ağırlık değişince sıra değişir


def test_invalid_weights_422(data):
    for bad in ("foo:1", "latency:-3", "latency:0,naturalness:0,accuracy:0,wer:0,resources:0"):
        assert client.get("/api/matrix", params={"weights": bad}).status_code == 422


def test_license_elimination_and_unknown(data, tmp_path, monkeypatch):
    cfg = matrix.load_config()
    t = spec("L1", "tts")
    cfg["license"][f"{t['provider']}:{t.get('model') or ''}"] = {"license": "Ticari değil", "commercial_ok": False, "verified": True}
    p = tmp_path / "m.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("SVA_MATRIX", str(p))
    for i in range(5):
        call(data, f"c{i}", "L1", [1.2])
    r = row(client.get("/api/matrix?weights=latency:100,naturalness:0,accuracy:0,wer:0,resources:0").json(), "L1")
    assert r["eliminated"] is True and r["total"] is None and r["rank"] is None
    cfg["license"].pop(f"{t['provider']}:{t.get('model') or ''}")                  # tabloda yok → belirsiz, elenmez
    p.write_text(json.dumps(cfg), encoding="utf-8")
    r = row(client.get("/api/matrix?weights=latency:100,naturalness:0,accuracy:0,wer:0,resources:0").json(), "L1")
    assert r["eliminated"] is False and r["total"] == 100 and r["license_unknown"]


def test_corrupt_llm_run_does_not_break(data):
    (data / "llm-evals").mkdir()
    (data / "llm-evals" / "bad.json").write_text("{", encoding="utf-8")
    assert client.get("/api/matrix").status_code == 200


# ---- kaynak kullanımı ve uygulanamaz kriter ----
def test_resources_score_rule():
    assert matrix.resources_score(0.02, 0.02, 0.20) == 100 and matrix.resources_score(0.25, 0.02, 0.20) == 0
    assert matrix.resources_score(0.11, 0.02, 0.20) == 50
    with pytest.raises(ValueError):
        matrix.resources_score(0.1, 0.2, 0.2)


def test_not_applicable_criteria_leave_the_denominator():
    na = matrix.not_applicable(PROFILES["A2"])
    assert set(na) == {"wer", "accuracy"} and set(matrix.not_applicable(PROFILES["L5"])) == {"wer"} and matrix.not_applicable(PROFILES["L2"]) == {}
    w = {"latency": 30, "naturalness": 25, "accuracy": 25, "wer": 10, "resources": 10}
    r = matrix.combine({"latency": 100, "naturalness": 100, "accuracy": None, "wer": None, "resources": 100}, w, 0.5, na)
    assert r["total"] == 100 and r["coverage"] == 1.0 and r["missing"] == []      # accuracy/wer ne eksik ne ağırlık
    assert matrix.combine({"latency": 100, "naturalness": 100, "accuracy": None, "wer": None, "resources": 100}, w, 0.5)["missing"] == ["accuracy", "wer"]


def test_resources_from_usage_with_gpu_assumption(data):
    sid = "r1"
    doc = {"id": sid, "profile": "L2", "started_at": "2026-10-30T10:00:00", "stats": {"seconds_in": 30.0},
           "turns": [{"turn": 1, "first_audio_after_end_s": 1.0}], "transcript": [], "phone_filter": False,
           "flow": {"scenario": "anket", "outcome": "completed", "path": [], "answers": []},
           "usage": {"items": {"duration_s": 30.0, "gpu_s": 36.0, "stt_minutes": 0.5, "stt_calls": 1, "llm_calls": 1, "llm_input_tokens": 10, "llm_output_tokens": 5, "tts_chars": 100, "tts_calls": 1, "tts_audio_s": 5.0}, "missing": [], "cost": {"total": 0.05, "complete": True, "unpriced": []}}}
    (data / "voice-sessions" / f"{sid}.json").write_text(json.dumps(doc), encoding="utf-8")
    m = row(client.get("/api/matrix").json(), "L2")["metrics"]["resources"]
    assert m is not None and m["unit"] == "$/arama" and m["n"] == 1
    assert m["value"] == pytest.approx(0.05 + 36 / 3600 * matrix.load_config()["resources"]["gpu_usd_per_hour"], abs=1e-4)
    assert "varsayım" in m["note"]
    assert row(client.get("/api/matrix").json(), "A2")["not_applicable"].keys() == {"wer", "accuracy"}
