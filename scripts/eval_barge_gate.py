#!/usr/bin/env python3
"""core-016 kanıt aracı: akıllı söz kesme süzgecinin yanlış kesme / kaçan kesme oranını ölçer ve evidence/core-016-*.json yazar.

Kullanım:
  python scripts/eval_barge_gate.py                         # yalnız SENTETİK taban çizgisi (gerçek doğrulama DEĞİL)
  python scripts/eval_barge_gate.py --dir kayitlar/          # gerçek kayıtlar: dosya adı önekiyle etiket
        speech_*.wav / konusma_*.wav  -> ajanı KESMELİ
        cough_*, throat_*, keyboard_*, door_*, breath_*, noise_*  -> ajanı KESMEMELİ
  --legacy   süzgeci kapat (voiced_min=0): karşılaştırma için eski seviye+süre davranışı

Her ses, ajanın konuştuğu durumdaki söz kesme karar mantığından (Endpointer + BargeTracker) geçirilir. Kesme gecikmesi = ilk yüksek çerçeveden kesme
kararına kadar (ms); 500 ms sınırı (core-002) bu ölçümde ayrıca denetlenir. Gerçek mikrofon/telefon yolu ve ajan yankısı bu araca dahil değildir.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.voice import synthsounds as snd  # noqa: E402
from backend.app.voice.vad import FRAME, BargeTracker, Endpointer  # noqa: E402

SPEECH_PREFIXES = ("speech", "konusma")


def decide(audio: np.ndarray, legacy: bool = False) -> tuple[bool, int | None]:
    """(kesti mi, ilk yüksek çerçeveden kesmeye ms). Ajan konuşuyor varsayılır."""
    vad = Endpointer()
    if legacy:
        vad.configure(voiced_min=0)
    gate = BargeTracker(vad)
    t0_frame = None
    for i in range(0, len(audio) - FRAME + 1, FRAME):
        f = audio[i:i + FRAME].astype(np.float32)
        vad.feed(f)
        loud = vad.level > vad.barge_level_db
        if loud and t0_frame is None:
            t0_frame = i // FRAME
        if gate.update(f, 0.0) == "barge":
            return True, (i // FRAME + 1 - (t0_frame or 0)) * 20
    return False, None


def load_wav(path: Path) -> np.ndarray:
    from scipy.io import wavfile
    from scipy.signal import resample_poly
    sr, data = wavfile.read(path)
    x = data.astype(np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if np.issubdtype(data.dtype, np.integer):
        x = x / float(np.iinfo(data.dtype).max)
    if sr != 16000:
        from math import gcd
        g = gcd(sr, 16000)
        x = resample_poly(x, 16000 // g, sr // g).astype(np.float32)
    return x


def summarize(results: dict[str, list[tuple[bool, int | None]]], should_barge: dict[str, bool]) -> dict:
    out = {}
    for cls, rs in results.items():
        cuts = [ms for ok, ms in rs if ok and ms is not None]
        barged = sum(1 for ok, _ in rs if ok)
        out[cls] = {"n": len(rs), "barged": barged, "rate": round(barged / len(rs), 3) if rs else None,
                    "expected": "keser" if should_barge[cls] else "kesmez",
                    "median_cut_ms": statistics.median(cuts) if cuts else None, "max_cut_ms": max(cuts) if cuts else None}
    return out


def synthetic(legacy: bool) -> tuple[dict, dict]:
    results: dict[str, list] = {"speech": []}
    for f0 in (100.0, 140.0, 220.0):
        for rms in (0.03, 0.1, 0.3):
            results["speech"].append(decide(snd.voiced(0.8, rms, f0=f0), legacy))
    for name, fn in snd.NON_SPEECH.items():
        results[name] = [decide(fn(0.5, rms=rms, seed=seed), legacy) for rms in (0.1, 0.3) for seed in range(3)]
    return results, {k: k == "speech" for k in results}


def from_dir(folder: Path, legacy: bool) -> tuple[dict, dict]:
    results: dict[str, list] = {}
    expect: dict[str, bool] = {}
    for p in sorted(folder.glob("*.wav")):
        cls = p.stem.split("_")[0].lower()
        expect[cls] = cls in SPEECH_PREFIXES
        results.setdefault(cls, []).append(decide(load_wav(p), legacy))
    return results, expect


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, help="etiketli gerçek kayıt klasörü (*.wav)")
    ap.add_argument("--legacy", action="store_true", help="süzgeci kapat (eski davranış)")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "evidence")
    a = ap.parse_args()
    results, expect = from_dir(a.dir, a.legacy) if a.dir else synthetic(a.legacy)
    classes = summarize(results, expect)
    false_barge = [c for c, v in classes.items() if v["expected"] == "kesmez" and v["barged"]]
    missed = [c for c, v in classes.items() if v["expected"] == "keser" and v["barged"] < v["n"]]
    slow = [c for c, v in classes.items() if v["expected"] == "keser" and (v["max_cut_ms"] or 0) > 500]
    vad = Endpointer()
    if a.legacy:
        vad.configure(voiced_min=0)
    report = {"source": f"gercek kayit: {a.dir}" if a.dir else "SENTETIK (gerçek doğrulama değildir)", "legacy_no_filter": a.legacy,
              "settings": vad.settings(), "classes": classes, "false_barge_classes": false_barge, "missed_barge_classes": missed,
              "over_500ms_classes": slow, "passed": not (false_barge or missed or slow)}
    a.out.mkdir(exist_ok=True)
    tag = "gercek" if a.dir else "sentetik"
    path = a.out / f"core-016-{tag}{'-legacy' if a.legacy else ''}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for c, v in classes.items():
        print(f"{c:14s} n={v['n']:3d} kesen={v['barged']:3d} beklenen={v['expected']:6s} medyan_kesme_ms={v['median_cut_ms']}")
    print("yanlış kesme:", false_barge or "yok", "| kaçan kesme:", missed or "yok", "| 500 ms üstü:", slow or "yok", "->", path)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
