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


def test_assigned_tone_voice_is_used_after_env_and_before_default(data, monkeypatch):
    from backend.app.providers import remote
    urls = []

    class Res:
        content = b"\x00\x00" * 100

    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "genel")
    monkeypatch.delenv("ELEVENLABS_VOICE_ID_SAKIN", raising=False)
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_ENERJIK", "envses")
    monkeypatch.setattr(remote, "_post", lambda url, **kw: urls.append(url) or Res())
    r = client.put("/api/persona/tones/voices", json={"voices": {"enerjik": "ekranses12345", "sakin": "sakinses12345"}})
    assert r.status_code == 200 and r.json()["assigned"] == {"enerjik": "ekranses12345", "sakin": "sakinses12345"}
    t = remote.ElevenLabsTTS("eleven_v4_turbo")
    for tone in ("enerjik", "sakin", "resmi"):
        t.synthesize("a", "tr", 1.0, tone)
    assert [u.rsplit("/", 1)[1] for u in urls] == ["envses", "sakinses12345", "genel"]
    # parametre kaydı ve sıfırlama atanan sesleri silmez
    client.put("/api/persona/tones", json={"params": {"ema": {"default": {"samimi": {"speed": 1.05}}}}})
    client.post("/api/persona/tones/reset")
    assert TV.voices()["sakin"] == "sakinses12345"
    assert client.put("/api/persona/tones/voices", json={"voices": {"sakin": ""}}).json()["assigned"].get("sakin") is None


def test_voice_assignment_rejects_bad_ids(data):
    assert client.put("/api/persona/tones/voices", json={"voices": {"kaba": "abcdefghij12"}}).status_code == 422
    assert client.put("/api/persona/tones/voices", json={"voices": {"sakin": "../etc"}}).status_code == 422


def _clear_voice_env(monkeypatch):
    for k in ("ELEVENLABS_VOICE_ID", *(f"ELEVENLABS_VOICE_ID_{t.upper()}" for t in TV.TONE_IDS)):
        monkeypatch.delenv(k, raising=False)


def test_general_voice_slot_precedence_and_validation(data, monkeypatch):
    _clear_voice_env(monkeypatch)
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "envgenel")
    assert TV.resolve_voice("sakin") == "envgenel"
    r = client.put("/api/persona/tones/voices", json={"voices": {"default": "ekrangenel12", "enerjik": "ekranener123"}})
    assert r.status_code == 200 and r.json()["assigned"] == {"default": "ekrangenel12", "enerjik": "ekranener123"}
    # Persona'da seçilen Genel ses .env'deki genel sesten önce gelir; o tona atanan ses Genel sesten önce gelir
    assert TV.resolve_voice("sakin") == "ekrangenel12" and TV.resolve_voice(None) == "ekrangenel12"
    assert TV.resolve_voice("enerjik") == "ekranener123"
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_ENERJIK", "envener")
    assert TV.resolve_voice("enerjik") == "envener"   # ton ortam değişkeni en üstte (mevcut davranış korunur)
    assert client.put("/api/persona/tones/voices", json={"voices": {"default": "../x"}}).status_code == 422
    client.put("/api/persona/tones/voices", json={"voices": {"default": ""}})
    assert TV.resolve_voice("sakin") == "envgenel"    # atama kaldırılınca ortam değişkenine döner


def test_voice_assignment_affects_existing_tts_instance_immediately(data, monkeypatch):
    """Profil yeniden başlatılmadan: Persona'da ses değişince aynı TTS örneğinin bir sonraki cümlesi yeni sesi kullanır."""
    from backend.app.providers import remote
    _clear_voice_env(monkeypatch)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    urls = []

    class Res:
        content = b"\x00\x00" * 100

    monkeypatch.setattr(remote, "_post", lambda url, **kw: urls.append(url) or Res())
    t = remote.ElevenLabsTTS("eleven_v4_turbo")
    client.put("/api/persona/tones/voices", json={"voices": {"default": "birinciSes123"}})
    t.synthesize("a", "tr", 1.0, "samimi")
    client.put("/api/persona/tones/voices", json={"voices": {"default": "ikinciSes1234", "samimi": "samimiSes1234"}})
    t.synthesize("a", "tr", 1.0, "samimi")
    t.synthesize("a", "tr", 1.0, "resmi")
    assert [u.rsplit("/", 1)[1] for u in urls] == ["birinciSes123", "samimiSes1234", "ikinciSes1234"]


def test_elevenlabs_without_voice_gives_clear_error_and_readiness(data, monkeypatch):
    from backend.app.providers import remote
    from backend.app.providers.base import ProviderError
    _clear_voice_env(monkeypatch)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    t = remote.ElevenLabsTTS("eleven_v4_turbo")
    with pytest.raises(ProviderError, match="Genel ses"):
        t.synthesize("a", "tr", 1.0, "sakin")
    issues = t.readiness_issues()
    assert len(issues) == 1 and all(tone in issues[0] for tone in TV.TONE_IDS)
    TV.set_voices({"samimi": "samimiSes1234", "resmi": "resmiSes12345", "enerjik": "enerjikSes123"})
    assert "sakin" in t.readiness_issues()[0] and "samimi" not in t.readiness_issues()[0]   # yalnız eksik ton söylenir
    TV.set_voices({"default": "genelSes12345"})
    assert t.readiness_issues() == []


def test_l2_el_profile_listed_and_needs_only_api_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    res = {p["id"]: p for p in client.get("/api/profiles", params={"check": "false"}).json()}
    p = res["L2-EL"]
    assert p["components"]["tts"]["provider"] == "elevenlabs" and p["components"]["tts"]["model"] == "eleven_v4_turbo"
    assert "ELEVENLABS_API_KEY" in p["missing_env"] and "ELEVENLABS_VOICE_ID" not in p["missing_env"]
    assert res["L2"]["components"]["tts"]["provider"] == "ema"


def test_list_voices_merges_account_and_turkish_library(data, monkeypatch):
    from backend.app.providers import remote
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    seen = []

    class Res:
        def __init__(self, body): self.body = body
        def json(self): return self.body

    def fake_get(url, **kw):
        seen.append((url, kw["params"]))
        if "shared-voices" in url:
            return Res({"voices": [{"voice_id": "libses1234567", "public_owner_id": "owner12345678", "name": "Gökçe Deniz",
                                    "description": "Joyful", "preview_url": "http://x/p.mp3", "gender": "female", "use_case": "conversational"}]})
        return Res({"voices": [{"voice_id": "hesapses12345", "name": "Benim", "labels": {"gender": "male"}, "preview_url": "http://x/b.mp3"}]})

    monkeypatch.setattr(remote, "_get", fake_get)
    r = client.get("/api/persona/voices").json()
    assert [(v["name"], v["source"]) for v in r["voices"]] == [("Benim", "account"), ("Gökçe Deniz", "library")]
    assert r["voices"][1]["tags"] == ["female", "conversational"] and seen[1][1]["language"] == "tr"
    assert [v["source"] for v in client.get("/api/persona/voices?library=false").json()["voices"]] == ["account"]
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    assert client.get("/api/persona/voices").status_code == 400


def test_list_voices_filters_sort_and_page(data, monkeypatch):
    from backend.app.providers import remote
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    seen = []

    class Res:
        def __init__(self, body): self.body = body
        def json(self): return self.body

    def fake_get(url, **kw):
        seen.append((url, kw["params"]))
        if "shared-voices" in url:
            return Res({"has_more": True, "voices": [{"voice_id": "libses1234567", "public_owner_id": "owner12345678", "name": "Gökçe",
                                                      "gender": "female", "age": "young", "accent": "standard", "descriptive": "cheerful",
                                                      "use_case": "social_media", "cloned_by_count": 321, "preview_url": "http://x/p.mp3"}]})
        return Res({"voices": [{"voice_id": "hesapses12345", "name": "Erkek", "labels": {"gender": "male", "age": "old"}},
                               {"voice_id": "hesapses67890", "name": "Kadın", "labels": {"gender": "female"}}]})

    monkeypatch.setattr(remote, "_get", fake_get)
    r = client.get("/api/persona/voices?gender=female&age=young&use_case=social_media&sort=popular&search=g").json()
    lib = [p for u, p in seen if "shared-voices" in u][0]
    assert lib["gender"] == "female" and lib["age"] == "young" and lib["use_cases"] == "social_media"
    assert lib["sort"] == "cloned_by_count" and lib["search"] == "g" and lib["page"] == 0
    row = r["voices"][-1]
    assert (row["gender"], row["age"], row["accent"], row["descriptive"], row["use_case"], row["cloned_by_count"]) == (
        "female", "young", "standard", "cheerful", "social_media", 321)
    assert r["has_more"] is True
    # hesap sesleri istemci tarafında değil sunucuda süzülür: yaş=young olan hesap sesi yok
    assert [v["name"] for v in r["voices"] if v["source"] == "account"] == []
    # ikinci sayfa yalnız kütüphane sesi getirir (hesap sesleri tekrar edilmez)
    seen.clear()
    r2 = client.get("/api/persona/voices?page=1").json()
    assert [u for u, _ in seen] == ["https://api.elevenlabs.io/v1/shared-voices"] and r2["page"] == 1
    assert client.get("/api/persona/voices?sort=bogus").status_code == 400


def test_add_library_voice_validates_ids_and_posts(data, monkeypatch):
    from backend.app.providers import remote
    sent = []

    class Res:
        def json(self): return {"voice_id": "yeniid1234567"}

    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setattr(remote, "_post", lambda url, **kw: sent.append((url, kw["json"])) or Res())
    ok = client.post("/api/persona/voices/add", json={"public_owner_id": "owner12345678", "voice_id": "libses1234567", "name": "Gökçe"})
    assert ok.status_code == 200 and sent[0][0].endswith("/voices/add/owner12345678/libses1234567")
    bad = client.post("/api/persona/voices/add", json={"public_owner_id": "../x", "voice_id": "libses1234567", "name": "a"})
    assert bad.status_code == 422


def test_model_matrix_has_prices_and_tag_flags():
    m = client.get("/api/persona/model-matrix").json()
    by = {x["id"]: x for x in m["models"]}
    assert {"eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_v4_turbo", "eleven_v3", "eleven_multilingual_v2"} <= set(by)
    assert by["eleven_flash_v2_5"]["price_per_1k_usd"] == 0.04 and by["eleven_v3"]["price_per_1k_usd"] == 0.08
    assert by["eleven_v4_turbo"]["tags"] is True and by["eleven_flash_v2_5"]["tags"] is False and "2026-10-30" in m["source"]


def test_tts_lab_streams_measures_and_prices(data, monkeypatch):
    from backend.app.providers import remote
    calls = []

    def fake_stream(url, **kw):
        calls.append((url, kw["json"], kw["params"]))
        pcm = (np.sin(np.arange(24000) / 20) * 8000).astype("<i2").tobytes()
        return (0.12 + 0.01 * len(calls), 0.5, pcm)

    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    monkeypatch.setattr(remote, "_post_stream", fake_stream)
    r = client.post("/api/persona/tts-lab", json={"text": "Merhaba Ahmet Bey.", "model": "eleven_v4_turbo",
                                                  "voice_id": "ozelses123456", "tone": "enerjik", "runs": 3})
    assert r.status_code == 200, r.text
    b = r.json()
    assert calls[0][0].endswith("/text-to-speech/ozelses123456/stream") and len(calls) == 3
    assert b["sent_text"] == "[excited] Merhaba Ahmet Bey." and b["chars"] == len("[excited] Merhaba Ahmet Bey.")   # etiket de faturalanır
    assert b["cost_usd"] == round(b["chars"] * 0.04 / 1000, 5) and b["median_first_audio_seconds"] == 0.14
    assert b["runs"][0]["audio_seconds"] == 1.0 and client.get(b["runs"][0]["url"]).content[:4] == b"RIFF"
    assert calls[0][1]["seed"] == 1234 and calls[0][1]["voice_settings"]["stability"] == 0.25
    flash = client.post("/api/persona/tts-lab", json={"text": "abcd", "model": "eleven_flash_v2_5", "voice_id": "ozelses123456", "tone": "enerjik"}).json()
    assert flash["sent_text"] == "abcd" and flash["cost_usd"] == round(4 * 0.04 / 1000, 5)      # Flash'ta etiket yok


def test_tts_lab_validation_and_missing_config(data, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    ok = {"text": "a", "model": "eleven_flash_v2_5"}
    assert client.post("/api/persona/tts-lab", json=ok).status_code == 400                     # anahtar yok
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    assert client.post("/api/persona/tts-lab", json=ok).status_code == 400                     # ses yok
    assert client.post("/api/persona/tts-lab", json={**ok, "model": "../x"}).status_code == 422
    assert client.post("/api/persona/tts-lab", json={**ok, "voice_id": "../etc"}).status_code == 422
    assert client.post("/api/persona/tts-lab", json={**ok, "tone": "kaba", "voice_id": "ozelses123456"}).status_code == 422
    assert client.post("/api/persona/tts-lab", json={**ok, "runs": 9}).status_code == 422


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
