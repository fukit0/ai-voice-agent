"""STT karşılaştırması: kanal seçimi (stereo ses kaydının sol=müşteri kanalı) ve Whisper alan ipucu (initial_prompt) satırı.

Gerçek modelle etkisi Mac'te ölçülür (kullanıcı); burada yalnızca mekanik doğrulanır.
"""
import io
import sys
import time
import types

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.providers import registry
from backend.app.providers.audio import decode_audio
from backend.app.providers.base import STTResult
from backend.app.providers.local import MlxWhisperSTT

client = TestClient(app)
CALLS: list[dict] = []


class MlxStub(MlxWhisperSTT):
    kind = "mlx_stub"

    def transcribe(self, audio, sample_rate, language="tr", prompt=None):
        CALLS.append({"prompt": prompt or self.options.get("initial_prompt"), "rms": float(np.sqrt(np.mean(np.square(audio))))})
        return STTResult("ses var" if CALLS[-1]["rms"] > 0.005 else "", 0.1, self.kind, self.model)


YAML = """
profiles:
  M1:
    name: Mlx sahte
    stt: {provider: mlx_stub, model: m}
"""


def stereo_wav(left_amp, right_amp, seconds=1.0, rate=16000):
    n = int(seconds * rate)
    t = np.sin(np.linspace(0, 200 * np.pi, n)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, np.column_stack([t * left_amp, t * right_amp]), rate, format="WAV")
    return buf.getvalue()


def test_decode_audio_channel_selection():
    data = stereo_wav(0.5, 0.0)
    left, _ = decode_audio(data, "left")
    right, _ = decode_audio(data, "right")
    mix, _ = decode_audio(data, "mix")
    assert np.abs(left).max() > 0.4 and np.abs(right).max() == 0.0
    assert 0.2 < np.abs(mix).max() < 0.3           # ortalama: iki ses karışır, yani müşteri sesi yarıya iner
    mono = io.BytesIO()
    sf.write(mono, np.ones(1600, np.float32) * 0.3, 16000, format="WAV")
    assert decode_audio(mono.getvalue(), "left")[0].shape == (1600,)   # tek kanallı dosyada seçim yok sayılır


def test_mlx_option_and_prompt_reach_whisper(monkeypatch):
    seen = {}
    fake = types.SimpleNamespace(transcribe=lambda audio, **kw: seen.update(kw) or {"text": " merhaba "})
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake)
    audio = np.zeros(1600, np.float32)
    MlxWhisperSTT("m").transcribe(audio, 16000)
    assert "initial_prompt" not in seen                                  # varsayılan: ipucu yok
    MlxWhisperSTT("m", initial_prompt="sahibinden.com").transcribe(audio, 16000)
    assert seen["initial_prompt"] == "sahibinden.com"                    # profil seçeneği
    MlxWhisperSTT("m", initial_prompt="a").transcribe(audio, 16000, prompt="b")
    assert seen["initial_prompt"] == "b"                                 # istek anındaki ipucu seçeneği ezer


def _env(tmp_path, monkeypatch):
    cfg = tmp_path / "profiles.yaml"
    cfg.write_text(YAML, encoding="utf-8")
    monkeypatch.setenv("SVA_PROFILES", str(cfg))
    monkeypatch.setenv("SVA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("SVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setitem(registry.PROVIDERS, MlxStub.kind, MlxStub)
    registry._cache.clear()
    assert client.post("/api/profiles/M1/warmup", params={"keep_others": "true"}).status_code == 202
    for _ in range(200):
        if client.get("/api/profiles/M1/warmup").json()["state"] != "running":
            break
        time.sleep(0.01)
    CALLS.clear()


def test_compare_channel_left_hears_customer_only_and_prompt_adds_a_row(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    data = stereo_wav(0.0, 0.5)                    # sol (müşteri) sessiz, sağ (ajan) yüksek
    left = client.post("/api/stt/compare", files={"audio": ("k.wav", data, "audio/wav")},
                       data={"profiles": "M1", "channel": "left"}).json()
    assert left["channel"] == "left" and left["results"][0]["text"] == ""            # ajan sesi STT'ye karışmadı
    right = client.post("/api/stt/compare", files={"audio": ("k.wav", data, "audio/wav")},
                        data={"profiles": "M1", "channel": "right"}).json()
    assert right["results"][0]["text"] == "ses var"
    CALLS.clear()
    both = client.post("/api/stt/compare", files={"audio": ("k.wav", data, "audio/wav")},
                       data={"profiles": "M1", "channel": "right", "prompt": "sahibinden.com, çağrı merkezi"}).json()
    rows = both["results"]
    assert [r["model"] for r in rows] == ["m", "m + ipucu"] and rows[1]["prompt"] == "sahibinden.com, çağrı merkezi"
    assert [c["prompt"] for c in CALLS] == [None, "sahibinden.com, çağrı merkezi"]    # ipucuz ve ipuçlu iki çağrı


def test_compare_both_separates_customer_and_agent_without_reference(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    data = stereo_wav(0.5, 0.5)                    # iki kanalda da konuşma
    run = client.post("/api/stt/compare", files={"audio": ("k.wav", data, "audio/wav")},
                      data={"profiles": "M1", "channel": "both"}).json()
    row = run["results"][0]
    assert run["channel"] == "both" and run["reference"] == "" and row["status"] == "ok"
    assert row["speakers"]["customer"]["text"] == "ses var" and row["speakers"]["agent"]["text"] == "ses var"
    assert row["speakers"]["customer"]["silent"] is False and "wer" not in row
    assert row["text"] == "Müşteri: ses var\nAjan: ses var"
    assert len(CALLS) == 2                          # her kanal ayrı çağrı


def test_compare_both_skips_silent_channel_instead_of_feeding_whisper(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    data = stereo_wav(0.0, 0.5)                    # müşteri kanalı tamamen sessiz
    row = client.post("/api/stt/compare", files={"audio": ("k.wav", data, "audio/wav")},
                      data={"profiles": "M1", "channel": "both"}).json()["results"][0]
    assert row["speakers"]["customer"] == {"text": "", "silent": True, "level_dbfs": -120.0}
    assert row["speakers"]["agent"]["text"] == "ses var"
    assert len(CALLS) == 1                          # sessiz kanal STT'ye hiç gitmedi
    assert row["text"] == "Müşteri: (konuşma yok)\nAjan: ses var"


def test_compare_both_rejects_mono_audio(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    mono = io.BytesIO()
    sf.write(mono, np.ones(16000, np.float32) * 0.3, 16000, format="WAV")
    res = client.post("/api/stt/compare", files={"audio": ("m.wav", mono.getvalue(), "audio/wav")},
                      data={"profiles": "M1", "channel": "both"})
    assert res.status_code == 400 and res.json()["detail"]["error"] == "not_stereo"
    assert CALLS == []


def test_decode_falls_back_to_ffmpeg_for_formats_libsndfile_cannot_read(tmp_path):
    import shutil
    import subprocess
    import pytest
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg yok")
    m4a = tmp_path / "s.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-f", "lavfi",
                    "-i", "sine=frequency=880:duration=1", "-filter_complex", "[0][1]amerge=inputs=2", "-c:a", "aac",
                    "-f", "ipod", str(m4a)], check=True)
    with pytest.raises(Exception):
        sf.read(io.BytesIO(m4a.read_bytes()))                    # libsndfile bunu tanımıyor (kullanıcının aldığı hata)
    from backend.app.providers.audio import decode_stereo
    left, right, rate = decode_stereo(m4a.read_bytes())          # ffmpeg yedeği: stereo korunur
    assert len(left) == len(right) > 0 and rate > 0 and np.abs(left).max() > 0.05


def test_empty_audio_is_a_400_not_a_500(tmp_path, monkeypatch):
    """Veri uzunluğu 0 olan WAV (yarım kalmış kayıt): eskiden 0'a bölme ile 500 veriyordu."""
    _env(tmp_path, monkeypatch)
    empty = io.BytesIO()
    sf.write(empty, np.zeros((0, 2), np.float32), 16000, format="WAV")
    for channel in ("mix", "both"):
        res = client.post("/api/stt/compare", files={"audio": ("e.wav", empty.getvalue(), "audio/wav")},
                          data={"profiles": "M1", "channel": channel})
        assert res.status_code == 400, channel
        assert res.json()["detail"]["message"].startswith("Ses çözülemedi: ses boş"), res.text
    assert CALLS == []
