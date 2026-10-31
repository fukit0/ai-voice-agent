"""Ekrandan ElevenLabs TTS modeli seçimi: yalnız ElevenLabs'li profiller, geçerli model, kalıcı, varsayılana dönüş."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.profiles import load_profiles

client = TestClient(app)


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path))


def _tts(pid):
    return load_profiles(include_studio=True)[pid].component("tts")["model"]


def test_list_has_only_elevenlabs_profiles_and_models():
    d = client.get("/api/profiles/tts-models").json()
    ids = {p["id"] for p in d["profiles"]}
    assert {"L2-EL", "A1", "A1S"} <= ids and "L2" not in ids
    assert {"eleven_flash_v2_5", "eleven_v4_turbo"} <= {m["id"] for m in d["models"]}


def test_override_applies_everywhere_and_persists_and_resets():
    assert _tts("A1S") == "eleven_flash_v2_5"
    r = client.put("/api/profiles/A1S/tts-model", json={"model": "eleven_multilingual_v2"})
    assert r.status_code == 200 and r.json()["default"] == "eleven_flash_v2_5"
    assert _tts("A1S") == "eleven_multilingual_v2" and _tts("A1") == "eleven_flash_v2_5"   # başka profil etkilenmez
    row = next(p for p in client.get("/api/profiles", params={"check": "false"}).json() if p["id"] == "A1S")
    assert row["components"]["tts"]["model"] == "eleven_multilingual_v2" and row["tts_default_model"] == "eleven_flash_v2_5"
    client.put("/api/profiles/A1S/tts-model", json={"model": None})
    assert _tts("A1S") == "eleven_flash_v2_5"


def test_streaming_flag_survives_override():
    client.put("/api/profiles/A1S/tts-model", json={"model": "eleven_turbo_v2_5"})
    assert load_profiles()["A1S"].component("tts")["streaming"] is True


def test_selecting_the_default_clears_override():
    client.put("/api/profiles/A1/tts-model", json={"model": "eleven_v3"})
    client.put("/api/profiles/A1/tts-model", json={"model": "eleven_flash_v2_5"})
    assert _tts("A1") == "eleven_flash_v2_5" and load_profiles()["A1"].tts_default_model is None


def test_rejects_unknown_model_and_non_elevenlabs_profile():
    assert client.put("/api/profiles/A1/tts-model", json={"model": "yok"}).status_code == 400
    assert client.put("/api/profiles/L2/tts-model", json={"model": "eleven_v3"}).status_code == 400
    assert client.put("/api/profiles/ZZZ/tts-model", json={"model": "eleven_v3"}).status_code == 404
