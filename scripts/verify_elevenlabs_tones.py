#!/usr/bin/env python3
"""ElevenLabs ton doğrulaması (ADR 0010): aynı cümleyi model x ton için sabit tohumla üretir, WAV + akustik özet kaydeder.

Kullanım (Mac'te, ELEVENLABS_API_KEY ve ELEVENLABS_VOICE_ID tanımlı):
  python scripts/verify_elevenlabs_tones.py                     # tüm modeller
  python scripts/verify_elevenlabs_tones.py --models eleven_flash_v2_5 eleven_v4_turbo --seed 7

Çıktı: evidence/elevenlabs-tones-<zaman>/ altında <model>-<ton>.wav ve report.json.
Karar ölçütü: bir model "ton destekliyor" sayılır, yalnız ton çiftleri arasında akustik fark (hız, perde oynaklığı, şiddet
dalgalanması) AYNI yönde ve belirgin ise VE dinleyince fark duyuluyorsa. Sayılar yaklaşıktır; son karar dinlemedir.
Bu betik ağa çıkar (ElevenLabs'e para harcar: model x 4 ton kadar kısa istek).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from backend.app import tone_voice as TV  # noqa: E402
from backend.app.providers.audio import encode_wav  # noqa: E402
from backend.app.providers.remote import ElevenLabsTTS  # noqa: E402

MODELS = ["eleven_flash_v2_5", "eleven_multilingual_v2", "eleven_v4_turbo", "eleven_v3"]
TEXT = "Merhaba Ahmet Bey, ben Ayşe. sahibinden.com adına arıyorum. Size kısa bir anket yapabilir miyim?"


def spread(rows: list[dict], key: str) -> float | None:
    vals = [r["acoustics"].get(key) for r in rows if r["acoustics"].get(key) is not None]
    return round(max(vals) - min(vals), 2) if len(vals) >= 2 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=MODELS)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--text", default=TEXT)
    args = ap.parse_args()
    missing = [k for k in ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID") if not os.environ.get(k)]
    if missing:
        print("Eksik ortam değişkeni:", ", ".join(missing))
        return 2
    out = ROOT / "evidence" / time.strftime("elevenlabs-tones-%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    report: dict = {"text": args.text, "seed": args.seed, "models": {}}
    for model in args.models:
        tts = ElevenLabsTTS(model, seed=args.seed)
        rows = []
        for tone in TV.TONE_IDS:
            try:
                res = tts.synthesize(args.text, "tr", 1.0, tone)
            except Exception as exc:  # noqa: BLE001 — model hesapta/dilde desteklenmeyebilir; raporda görünsün
                rows.append({"tone": tone, "error": str(exc)[:200], "acoustics": {}})
                print(f"  {model}/{tone}: HATA {str(exc)[:120]}")
                continue
            audio = np.asarray(res.audio, dtype=np.float32)
            (out / f"{model}-{tone}.wav").write_bytes(encode_wav(audio, res.sample_rate))
            rows.append({"tone": tone, "seconds_to_synthesize": round(res.seconds, 2),
                         "applied": TV.params("elevenlabs", model, tone), "acoustics": TV.acoustics(audio, res.sample_rate, args.text)})
        ok = [r for r in rows if "error" not in r]
        report["models"][model] = {
            "tag_model": TV.uses_tags(model), "clips": rows,
            "spread": {k: spread(ok, k) for k in ("words_per_sec", "pitch_std_semitones", "loudness_std_db", "pitch_median_hz")},
        }
        sp = report["models"][model]["spread"]
        print(f"{model}: tonlar arası fark -> hız {sp['words_per_sec']} kel/sn, perde oynaklığı {sp['pitch_std_semitones']} yarım ton, "
              f"şiddet {sp['loudness_std_db']} dB")
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nKlipler ve rapor: {out}\nŞimdi her modelin 4 klibini DİNLEYİN; fark duyulmuyorsa o model ton için yeterli değildir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
