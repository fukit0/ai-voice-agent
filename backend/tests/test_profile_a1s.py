"""A1 gecikme işi, faz 5: A1S profili = A1 + canlı STT + akışlı TTS. A1 ve diğer profiller değişmedi; Lab uçları profil
listesinden A1S'yi kod değişikliği olmadan tanır (profil güdümlü)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import matrix
from backend.app.main import app
from backend.app.profiles import load_profiles
from backend.app.providers import registry, remote
from backend.app.providers.fake import FakeLLM
from backend.app.voice.session import VoiceSession

client = TestClient(app)
PROFILES = load_profiles(apply_overrides=False)   # yaml tanımı; ekrandan yapılan model/akış seçimleri bu testleri etkilemesin
KEYS = ("DEEPGRAM_API_KEY", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY")


def test_a1s_is_a1_plus_streaming_flags_and_a1_is_untouched():
    a1, a1s = PROFILES["A1"], PROFILES["A1S"]
    assert a1s.name == "API referansı (streaming)" and a1s.mode == "cascade"
    assert a1.component("stt") == {"provider": "deepgram", "model": "nova-3"}
    assert a1.component("llm") == {"provider": "anthropic", "model": "claude-haiku-5-5"}
    assert a1.component("tts") == {"provider": "elevenlabs", "model": "eleven_flash_v2_5"}
    assert a1s.component("stt") == {**a1.component("stt"), "streaming": True}
    assert a1s.component("llm") == a1.component("llm")
    assert a1s.component("tts") == {**a1.component("tts"), "streaming": True}
    for pid, p in PROFILES.items():                       # başka hiçbir profilde akış bayrağı yok
        if pid != "A1S":
            for c in ("stt", "llm", "tts"):
                assert "streaming" not in (p.component(c) or {}), (pid, c)


def test_a1s_providers_are_built_with_options_and_share_the_llm(monkeypatch):
    for k in KEYS:
        monkeypatch.setenv(k, "k")
    get = lambda pid, c: registry.get_provider(PROFILES[pid].component(c), c, pid)
    stt, tts = get("A1S", "stt"), get("A1S", "tts")
    assert isinstance(stt, remote.DeepgramSTT) and stt.streaming and stt.options == {"streaming": True}
    assert isinstance(tts, remote.ElevenLabsTTS) and tts.streaming and tts.options == {"streaming": True}
    assert get("A1S", "llm") is get("A1", "llm")          # aynı LLM tanımı: tek örnek
    assert get("A1", "stt") is not stt and not get("A1", "stt").streaming
    assert not get("A1", "tts").streaming


def test_voice_session_enables_streaming_only_for_a1s_providers(tmp_path, monkeypatch):
    for k in KEYS:
        monkeypatch.setenv(k, "k")
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))

    class Out:
        def set_on_drained(self, cb):
            pass
    get = lambda pid, c: registry.get_provider(PROFILES[pid].component(c), c, pid)
    s1 = VoiceSession("a", "A1", get("A1", "stt"), FakeLLM("m"), get("A1", "tts"), Out(), lambda e: None)
    s2 = VoiceSession("b", "A1S", get("A1S", "stt"), FakeLLM("m"), get("A1S", "tts"), Out(), lambda e: None)
    assert (s1._stt_streaming, s1._tts_streaming) == (False, False)
    assert (s2._stt_streaming, s2._tts_streaming) == (True, True)


def test_profile_list_and_status_include_a1s(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    rows = {p["id"]: p for p in client.get("/api/profiles", params={"check": "false"}).json()}
    a1s = rows["A1S"]
    assert a1s["name"] == "API referansı (streaming)" and a1s["ready"] is False
    assert set(a1s["missing_env"]) == set(KEYS)
    assert a1s["components"]["stt"] == {"provider": "deepgram", "model": "nova-3", "missing_env": ["DEEPGRAM_API_KEY"], "warm": False}
    assert rows["A1"]["components"] == {**a1s["components"]}       # bileşen özeti aynı (akış bayrağı ayrıntıdır)


def test_component_model_lists_show_a1s(monkeypatch):
    stt = client.get("/api/stt/models").json()
    assert any("A1S" in m["profiles"] and m["provider"] == "deepgram" for m in stt)
    tts = client.get("/api/tts/models").json()
    assert any("A1S" in m["profiles"] and m["provider"] == "elevenlabs" for m in tts)


def test_matrix_license_lookup_uses_provider_model_for_a1s(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    (tmp_path / "voice-sessions").mkdir()
    monkeypatch.setattr(matrix, "tts_rows", lambda: [])
    rows = {r["profile"]: r for r in matrix.build()["rows"]}
    assert rows["A1S"]["license"] == rows["A1"]["license"]
    assert [c["model"] for c in rows["A1S"]["components"]] == ["nova-3", "claude-haiku-5-5", "eleven_flash_v2_5"]


@pytest.mark.parametrize("pid", ["A1S"])
def test_evalrun_rejects_cold_a1s_like_any_cascade_profile(pid, monkeypatch):
    for k in KEYS:
        monkeypatch.setenv(k, "k")
    res = client.post("/api/evalrun/runs", json={"profile": pid, "phone_filter": "off"})
    assert res.status_code in (400, 409), res.text            # soğuk profil: ölçüm yapılmaz (ADR 0001), realtime hatası değil
    assert "realtime" not in res.text
