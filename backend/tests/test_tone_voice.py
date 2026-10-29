"""core-005 / ADR 0010: persona tonu -> TTS parametreleri (EMA hız, Chatterbox, ElevenLabs model ailesine göre) ve ton demosu."""
import sys
import types

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import tone_voice as TV
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))
    return tmp_path


def test_default_mapping_is_valid_and_covers_all_tones():
    m = TV.load()
    assert TV.validate(m) == []
    for kind in ("ema", "chatterbox", "elevenlabs"):
        assert set(m["params"][kind]["default"]) == set(TV.TONE_IDS)


def test_params_fallback_model_then_default_then_empty():
    assert TV.params("elevenlabs", "eleven_v4_turbo", "enerjik")["tag"] == "[excited]"
    assert "tag" not in TV.params("elevenlabs", "eleven_unknown", "enerjik")          # model yoksa default
    assert TV.params("elevenlabs", None, None) == {} and TV.params("nope", "x", "samimi") == {}


@pytest.mark.parametrize("bad", [
    {"elevenlabs": {"default": {"kaba": {"speed": 1}}}},
    {"elevenlabs": {"default": {"samimi": {"zorbalik": 1}}}},
    {"elevenlabs": {"default": {"samimi": {"stability": 2}}}},
    {"ema": {"default": {"samimi": {"speed": 3}}}},
    {"elevenlabs": {"default": {"samimi": {"tag": "uyar"}}}},
    {"chatterbox": {"default": {"samimi": {"exaggeration": "çok"}}}},
])
def test_validate_rejects_bad_values(bad):
    assert TV.validate({"params": bad})


def test_override_is_merged_and_reset(data):
    TV.save({"params": {"ema": {"default": {"enerjik": {"speed": 1.25}}}}})
    assert TV.params("ema", None, "enerjik")["speed"] == 1.25
    assert TV.params("ema", None, "sakin")["speed"] == 0.88                                # diğerleri varsayılan
    TV.reset()
    assert TV.params("ema", None, "enerjik")["speed"] == 1.15


def test_ema_tone_changes_speed_only(monkeypatch):
    from backend.app.providers.local import EmaTTS
    seen = []

    class Engine:
        def say(self, text, speed=1.0, seed=None, sample_rate=48000, path=None):
            seen.append(speed)
            return types.SimpleNamespace(audio=np.zeros(240, dtype=np.float32))

    monkeypatch.setitem(sys.modules, "ema_lightning", types.SimpleNamespace(EMA=Engine))
    t = EmaTTS()
    t.synthesize("a")
    t.synthesize("b", "tr", 1.0, "enerjik")
    t.synthesize("c", "tr", 1.0, "sakin")
    t.synthesize("d", "tr", 1.1, "resmi")                                                   # persona hızıyla çarpılır
    assert seen[:3] == [1.0, 1.15, 0.88] and seen[3] == pytest.approx(1.1 * 0.95)


def _eleven(monkeypatch, model=None, **opts):
    from backend.app.providers import remote
    sent = []

    class Res:
        content = (np.sin(np.arange(24000) / 20) * 8000).astype("<i2").tobytes()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")
    monkeypatch.setattr(remote, "_post", lambda url, **kw: sent.append(kw["json"]) or Res())
    return remote.ElevenLabsTTS(model, **opts), sent


def test_elevenlabs_flash_uses_stability_and_speed_but_no_tag(monkeypatch):
    t, sent = _eleven(monkeypatch, "eleven_flash_v2_5")
    t.synthesize("Merhaba.", "tr", 1.0, "enerjik")
    t.synthesize("Merhaba.", "tr", 1.0, "resmi")
    assert sent[0]["text"] == "Merhaba." and sent[0]["language_code"] == "tr"
    assert sent[0]["voice_settings"]["stability"] < sent[1]["voice_settings"]["stability"]
    assert sent[0]["voice_settings"]["speed"] > sent[1]["voice_settings"]["speed"]
    assert "style" not in sent[0]["voice_settings"]                                         # Flash'ta style etkisi doğrulanmadı


def test_elevenlabs_v4_turbo_prefixes_audio_tag(monkeypatch):
    t, sent = _eleven(monkeypatch, "eleven_v4_turbo")
    t.synthesize("Merhaba.", "tr", 1.0, "enerjik")
    t.synthesize("Merhaba.", "tr", 1.0, "sakin")
    assert sent[0]["text"] == "[excited] Merhaba." and sent[1]["text"] == "[calm] Merhaba."


def test_elevenlabs_multilingual_v2_has_no_language_code_and_uses_style(monkeypatch):
    t, sent = _eleven(monkeypatch, "eleven_multilingual_v2")
    t.synthesize("Merhaba.", "tr", 1.0, "enerjik")
    assert "language_code" not in sent[0] and sent[0]["voice_settings"]["style"] == 0.6
    assert sent[0]["text"] == "Merhaba."


def test_elevenlabs_per_tone_voice_id_overrides_default(monkeypatch):
    from backend.app.providers import remote
    urls = []

    class Res:
        content = b"\x00\x00" * 100

    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "genel")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_ENERJIK", "canli")
    monkeypatch.setattr(remote, "_post", lambda url, **kw: urls.append(url) or Res())
    t = remote.ElevenLabsTTS("eleven_flash_v2_5")
    t.synthesize("a", "tr", 1.0, "enerjik")
    t.synthesize("a", "tr", 1.0, "sakin")      # sakin için ayrı ses tanımlı değil -> genel
    t.synthesize("a")
    assert [u.rsplit("/", 1)[1] for u in urls] == ["canli", "genel", "genel"]


def test_elevenlabs_seed_is_sent_and_no_tone_keeps_old_body(monkeypatch):
    t, sent = _eleven(monkeypatch, None, seed=42)
    t.synthesize("a")
    assert sent[0]["seed"] == 42 and "voice_settings" not in sent[0]


def test_chatterbox_passes_expressiveness_params(monkeypatch):
    from backend.app.providers.local import ChatterboxTTS
    torch = pytest.importorskip("torch")
    seen = []

    class Wav:
        def squeeze(self): return self
        def detach(self): return self
        def cpu(self): return self
        def numpy(self): return np.zeros(100, dtype=np.float32)

    class Model:
        sr = 24000
        def generate(self, text, language_id=None, **kw):
            seen.append(kw)
            return Wav()

    t = ChatterboxTTS(seed=7)
    t._tts = Model()
    monkeypatch.setitem(sys.modules, "chatterbox", types.ModuleType("chatterbox"))
    monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", types.SimpleNamespace(ChatterboxMultilingualTTS=object))
    t.synthesize("a")
    t.synthesize("b", "tr", 1.0, "enerjik")
    assert seen[0] == {} and seen[1]["exaggeration"] == 0.9 and seen[1]["cfg_weight"] == 0.3 and seen[1]["temperature"] == 0.9
    assert torch is not None


def test_acoustics_reports_pitch_and_rate():
    rate = 16000
    tt = np.arange(rate * 2) / rate
    a = TV.acoustics(0.3 * np.sin(2 * np.pi * 200 * tt), rate, "bir iki üç dört")
    assert a["seconds"] == 2.0 and a["words_per_sec"] == 2.0
    assert 190 < a["pitch_median_hz"] < 210 and a["pitch_std_semitones"] < 0.5


def test_tone_endpoints_and_demo_with_elevenlabs_profile(data, monkeypatch):
    t, sent = _eleven(monkeypatch, "eleven_flash_v2_5")
    from backend.app import api_profiles
    prof = types.SimpleNamespace(id="x", component=lambda c: {"provider": "elevenlabs", "model": "eleven_flash_v2_5"})
    monkeypatch.setattr(api_profiles, "_profile", lambda pid: prof)
    info = client.get("/api/persona/tones").json()
    assert [x["id"] for x in info["tones"]] == list(TV.TONE_IDS)
    r = client.post("/api/persona/tone-demo", json={"profile": "x", "tones": ["samimi", "enerjik"], "model": "eleven_v4_turbo"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tag_model"] is True and [c["tone"] for c in body["clips"]] == ["samimi", "enerjik"]
    assert body["clips"][1]["applied"]["tag"] == "[excited]" and body["clips"][1]["acoustics"]["seconds"] > 0
    assert sent[-1]["seed"] == 1234 and sent[-1]["text"].startswith("[excited] ")
    wav = client.get(body["clips"][0]["url"])
    assert wav.status_code == 200 and wav.content[:4] == b"RIFF"
    assert client.post("/api/persona/tone-demo", json={"profile": "x", "tones": ["kaba"]}).status_code == 422
    assert client.get("/api/persona/tone-demo/yok.wav").status_code == 404


def test_tone_map_put_validates_and_resets(data):
    bad = client.put("/api/persona/tones", json={"params": {"ema": {"default": {"samimi": {"speed": 9}}}}})
    assert bad.status_code == 422
    ok = client.put("/api/persona/tones", json={"params": {"ema": {"default": {"samimi": {"speed": 1.05}}}}})
    assert ok.json()["mapping"]["params"]["ema"]["default"]["samimi"]["speed"] == 1.05
    assert client.post("/api/persona/tones/reset").json()["mapping"]["params"]["ema"]["default"]["samimi"]["speed"] == 1.0


def test_persona_accepts_new_tones_and_prompt_mentions_them():
    from backend.app import persona as P
    for tone in ("enerjik", "sakin"):
        p = {**P.defaults(), "tone": tone}
        assert P.validate(p) == [] and "adlı" in P.system_prompt(p)
