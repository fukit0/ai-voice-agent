"""Hızlı yol ayarı: ekrandan profil bazlı aç/kapa, arama kaydına yazılır, ölçümler açık/kapalı ayrı kıyaslanır."""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.profiles import load_profiles

client = TestClient(app)


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    (tmp_path / "voice-sessions").mkdir()
    return tmp_path


def test_setting_defaults_and_toggle_for_cascade_profiles_only():
    assert load_profiles()["A1S"].fast_path is True and load_profiles()["L2-EL"].fast_path is False
    r = client.put("/api/profiles/L2-EL/fast-path", json={"enabled": True})
    assert r.status_code == 200 and r.json() == {"profile": "L2-EL", "enabled": True, "default": False}
    assert load_profiles()["L2-EL"].fast_path is True and load_profiles()["L2"].fast_path is False
    row = next(p for p in client.get("/api/profiles", params={"check": "false"}).json() if p["id"] == "L2-EL")
    assert row["fast_path"] is True and row["fast_path_default"] is False
    client.put("/api/profiles/L2-EL/fast-path", json={"enabled": None})
    assert load_profiles()["L2-EL"].fast_path is False
    client.put("/api/profiles/A1S/fast-path", json={"enabled": False})      # yaml'da açık olan da kapatılabilir
    assert load_profiles()["A1S"].fast_path is False
    assert client.put("/api/profiles/A2/fast-path", json={"enabled": True}).status_code == 400
    assert client.put("/api/profiles/ZZ/fast-path", json={"enabled": True}).status_code == 404


def _call(folder, sid, profile, fast, firsts, llm=None):
    """firsts: tur başına ilk ses; llm: tur başına LLM süresi ('F' = kural yolu)."""
    turns = [{"turn": 1, "greeting": True, "first_audio_after_end_s": 0.2}]
    for i, f in enumerate(firsts):
        t = {"turn": i + 2, "first_audio_after_end_s": f}
        if llm and llm[i] == "F":
            t["fast_path"] = True
        else:
            t["llm_s"] = (llm[i] if llm else 0.5)
        turns.append(t)
    doc = {"id": sid, "profile": profile, "started_at": "2026-11-01T10:00:00+00:00", "turns": turns, "stats": {}, "flow": {"outcome": "tamamlandi", "answers": []}}
    if fast is not None:
        doc["config"] = {"fast_path": fast}
    (folder / "voice-sessions" / f"{sid}.json").write_text(json.dumps(doc), encoding="utf-8")


def test_compare_variant_separates_on_off_and_old_records(data_dir):
    _call(data_dir, "a" * 12, "L2-EL", False, [1.6, 1.8], [0.5, 0.6])
    _call(data_dir, "b" * 12, "L2-EL", True, [0.8, 1.7], ["F", 0.5])
    _call(data_dir, "c" * 12, "L2-EL", None, [1.5], [0.5])           # config yazılmadan önceki eski kayıt
    d = client.get("/api/calls/compare", params={"group": "variant"}).json()
    g = {x["key"]: x for x in d["groups"]}
    assert set(g) == {"L2-EL|kapali", "L2-EL|acik", "L2-EL|bilinmiyor"}
    off, on, old = g["L2-EL|kapali"], g["L2-EL|acik"], g["L2-EL|bilinmiyor"]
    assert off["fast_turns"] == 0 and on["fast_turns"] == 1 and on["fast_share"] == 0.5
    assert on["first_audio_fast_p50"] == 0.8 and on["first_audio_llm_p50"] == 1.7
    assert off["is_baseline"] and on["delta_p50_s"] is not None and on["delta_p50_s"] < 0
    assert old["delta_p50_s"] is None and "eski" in old["label"]        # eski kayıt kapalıyla kıyaslanmaz, uydurulmaz
    assert on["stages"]["llm"] == 0.5                                      # kural turları LLM süresini kirletmez


def test_compare_variant_without_off_group_has_no_delta(data_dir):
    _call(data_dir, "d" * 12, "A1S", True, [0.9, 1.0], ["F", "F"])
    g = client.get("/api/calls/compare", params={"group": "variant"}).json()["groups"][0]
    assert g["delta_p50_s"] is None and g["fast_share"] == 1.0


def test_flow_turn_marks_fast_and_does_not_record_llm_time():
    from app.voice import flow as F
    from app import scenario as S

    class Boom:
        def complete(self, *a, **k):
            raise AssertionError("LLM çağrılmamalı")
    d = F.FlowDriver(S.get("anket"), Boom(), score_policy="clarify")
    d.fast_path = True
    d.current = "musaitlik"
    r = d.handle("evet")
    assert any(e["type"] == "fast_path" for e in r.events)
