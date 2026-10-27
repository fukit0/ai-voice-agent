"""Giriş eşiği karşılaştırması (core-015): aynı SENTETİK gürültülü ses, varsayılan ve yükseltilmiş eşiklerle VoiceSession'dan geçer.

    .venv/bin/python scripts/vad_noise_report.py                     # sentetik gürültü karışımı
    .venv/bin/python scripts/vad_noise_report.py --wav gurultu.wav   # gerçek kayıt (16 kHz mono ya da stereo sol kanal)

ÖNEMLİ: Varsayılan girdi sentetiktir (sürekli TV/trafik uğultusu + klavye tıkları + uzaktan konuşma). Mantığı kanıtlar,
gerçek ortamı kanıtlamaz; gerçek WAV ile (--wav) ya da Playground'da elle doğrulanmalıdır. Sonuç evidence/core-015-vad-noise.json.
"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SVA_FAKE_PROVIDERS", "1")

from backend.app.providers.fake import FakeLLM, FakeSTT, FakeTTS  # noqa: E402
from backend.app.voice.session import VoiceSession  # noqa: E402
from backend.app.voice.vad import FRAME, Endpointer  # noqa: E402

SR = 16000
CONFIGS = [("otomatik (varsayılan)", None), ("-40 dBFS", -40.0), ("-35 dBFS", -35.0), ("-30 dBFS", -30.0), ("-25 dBFS", -25.0)]


class Out:
    def __init__(self):
        self.cb = None

    def set_on_drained(self, cb):
        self.cb = cb

    def push(self, pcm):
        pass

    def flush(self):
        pass

    def mark_end(self):
        pass


def db(x):
    return 10 ** (x / 20)


def synthetic_noise(seconds=20.0, seed=3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    x = rng.standard_normal(n) * db(-41)                       # sürekli TV/trafik uğultusu (eşiğin üstünde: uyarlanır taban kilitlenir)
    for t in np.arange(0.5, seconds, 0.7):                      # klavye tıkları: 10 ms, -25 dBFS
        i = int(t * SR)
        x[i:i + 160] += rng.standard_normal(160) * db(-22)
    for t0 in (3.0, 9.0, 15.0):                                 # uzaktan konuşma: 1,2 sn, -34 dBFS
        i = int(t0 * SR)
        x[i:i + int(1.2 * SR)] += rng.standard_normal(int(1.2 * SR)) * db(-34)
    for t0 in (6.0, 12.0):                                      # yakın gürültü patlaması: 0,3 sn, -30 dBFS
        i = int(t0 * SR)
        x[i:i + int(0.3 * SR)] += rng.standard_normal(int(0.3 * SR)) * db(-30)
    return x.astype(np.float32)


def speech_burst(seconds=0.6, rms_db=-22.0, seed=11) -> np.ndarray:
    return (np.random.default_rng(seed).standard_normal(int(seconds * SR)) * db(rms_db)).astype(np.float32)


async def run_agent_speaking(noise: np.ndarray, threshold) -> dict:
    """Ajan konuşurken yalnızca gürültü: kaç söz kesme? Sonra normal seviyede konuşma: kesiyor mu?"""
    events = []
    s = VoiceSession("n", "V1", FakeSTT("m"), FakeLLM("m"), FakeTTS("m"), Out(), events.append)
    if threshold is not None:
        s.set_vad({"db": threshold})
    noise_cuts = 0
    for i in range(0, len(noise) - FRAME + 1, FRAME):
        s.state = "speaking"
        s._synth_done = False
        before = s.stats["barge_ins"]
        s.feed(noise[i:i + FRAME])
        noise_cuts += s.stats["barge_ins"] - before
    s.state = "speaking"
    before = s.stats["barge_ins"]
    s.feed(speech_burst())
    return {"noise_barge_ins": noise_cuts, "speech_interrupts": s.stats["barge_ins"] > before}


def run_listening(noise: np.ndarray, threshold) -> dict:
    """Ajan dinlerken: gürültü kaç 'start' / 'drop' / 'end' (STT'ye giden yanlış enunciance) üretiyor?"""
    v = Endpointer()
    if threshold is not None:
        v.configure(threshold_db=threshold)
    n = {"start": 0, "drop": 0, "end": 0}
    for i in range(0, len(noise) - FRAME + 1, FRAME):
        for k, _ in v.feed(noise[i:i + FRAME]):
            n[k] += 1
    return {"starts": n["start"], "drops": n["drop"], "false_utterances_to_stt": n["end"]}


def load_wav(path: str) -> np.ndarray:
    import soundfile as sf
    data, sr = sf.read(path, dtype="float32")
    if data.ndim > 1:
        data = data[:, 0]
    if sr != SR:
        from backend.app.providers.audio import resample
        data = resample(data, sr, SR)
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", help="gerçek gürültü kaydı (yoksa sentetik)")
    ap.add_argument("--out", default=str(ROOT / "evidence" / "core-015-vad-noise.json"))
    args = ap.parse_args()
    noise = load_wav(args.wav) if args.wav else synthetic_noise()
    os.environ.setdefault("SVA_DATA_DIR", tempfile.mkdtemp())
    rows = []
    for label, thr in CONFIGS:
        r = {"config": label, "threshold_db": thr, **asyncio.run(run_agent_speaking(noise, thr)), **run_listening(noise, thr)}
        rows.append(r)
    report = {"input": args.wav or "sentetik (scripts/vad_noise_report.py synthetic_noise)", "synthetic": not args.wav,
              "seconds": round(len(noise) / SR, 1), "rows": rows,
              "caveat": None if args.wav else "Sentetik gürültü: mantığı doğrular, gerçek ortamı kanıtlamaz; gerçek mikrofonla elle doğrulama gerekir."}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{'ayar':24} {'gürültüyle kesme':>17} {'konuşma keser':>14} {'start':>6} {'yanlış STT':>11}")
    for r in rows:
        print(f"{r['config']:24} {r['noise_barge_ins']:>17} {str(r['speech_interrupts']):>14} {r['starts']:>6} {r['false_utterances_to_stt']:>11}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
