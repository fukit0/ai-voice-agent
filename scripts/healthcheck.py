#!/usr/bin/env python3
"""Lokal model sağlık kontrolü: Ollama (LLM), mlx-whisper (STT), EMA Lightning ve Chatterbox (TTS).

Her bileşen için küçük bir çağrı yapar, süreyi ölçer ve sonucu evidence/ altına JSON olarak yazar.
Kanıt dosyası feature_list.json'daki `evidence` alanına referans olarak eklenebilir.

Kullanım:
    python scripts/healthcheck.py           # hızlı: Ollama + EMA -> STT (modeller önbellekteyse ~10 sn)
    python scripts/healthcheck.py --full    # + Chatterbox (yükleme ~1 dk, ~3 GB bellek)
Ortam değişkenleri:
    OLLAMA_URL   (varsayılan http://localhost:11434)
    OLLAMA_MODEL (varsayılan: Ollama'daki ilk model)
    STT_MODEL    (varsayılan mlx-community/whisper-large-v3-turbo)
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT / "evidence"
AUDIO_DIR = EVIDENCE_DIR / "healthcheck-audio"

TEST_SENTENCE = "Merhaba, sahibinden anketine hoş geldiniz. İlanınızı satabildiniz mi?"
KEYWORDS = ("merhaba", "anket", "ilan")  # STT çıktısında en az biri bulunmalı

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
STT_MODEL = os.environ.get("STT_MODEL", "mlx-community/whisper-large-v3-turbo")

results: list[dict] = []
shared: dict = {}  # bileşenler arası ses aktarımı (TTS -> STT)


def check(name: str):
    def deco(fn):
        def run():
            start = time.perf_counter()
            entry = {"component": name, "status": "fail", "seconds": None, "detail": {}}
            try:
                entry["detail"] = fn() or {}
                entry["status"] = "pass"
            except Exception as exc:  # noqa: BLE001 — her hatayı kanıta yaz
                entry["detail"] = {"error": f"{type(exc).__name__}: {exc}",
                                   "trace": traceback.format_exc(limit=3)}
            entry["seconds"] = round(time.perf_counter() - start, 2)
            results.append(entry)
            mark = "PASS" if entry["status"] == "pass" else "FAIL"
            short = entry["detail"].get("summary") or entry["detail"].get("error", "")
            print(f"  [{mark}] {name:<12} {entry['seconds']:>6}s  {short}", flush=True)
        run.component = name
        return run
    return deco


@check("ollama")
def ollama():
    import requests

    tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).json().get("models", [])
    if not tags:
        raise RuntimeError("Ollama çalışıyor ama yüklü model yok. Örn: ollama pull qwen3:30b-a3b (32 GB+) veya ollama pull gemma4:e4b (16 GB)")
    model = os.environ.get("OLLAMA_MODEL") or tags[0]["name"]
    t0 = time.perf_counter()
    r = requests.post(f"{OLLAMA_URL}/api/generate", timeout=120, json={
        "model": model,
        "prompt": "Tek kelimeyle cevap ver: Türkiye'nin başkenti neresidir?",
        "stream": False,
        # Qwen3 gibi "düşünen" modeller önce düşünce token'ı üretir; kısa limitte cevap boş kalır.
        # Ajan da gecikme için düşünmeyi kapalı kullanacak.
        "think": False,
        # Kontrolden sonra modeli bellekten at: STT/TTS ile aynı RAM'i paylaşıyor.
        "keep_alive": 0,
        "options": {"num_predict": 32, "temperature": 0},
    })
    r.raise_for_status()
    body = r.json()
    answer = re.sub(r"<think>.*?</think>", "", body.get("response", ""), flags=re.S).strip()
    if not answer:
        raise RuntimeError(f"Boş yanıt (done_reason={body.get('done_reason')})")
    ns = 1e9
    load_s = body.get("load_duration", 0) / ns
    tok_s = body.get("eval_count", 0) / max(body.get("eval_duration", 1) / ns, 1e-9)
    return {"model": model, "answer": answer, "generate_seconds": round(time.perf_counter() - t0, 2),
            "load_seconds": round(load_s, 1), "tokens_per_second": round(tok_s, 1),
            "installed_models": [m["name"] for m in tags],
            "summary": f"{model} -> {answer[:30]!r}, {tok_s:.0f} tok/s (yükleme {load_s:.0f}s)"}


@check("ema")
def ema():
    from ema_lightning import EMA

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIO_DIR / "ema.wav"
    t0 = time.perf_counter()
    engine = EMA()
    load = time.perf_counter() - t0
    t0 = time.perf_counter()
    speech = engine.say(TEST_SENTENCE, sample_rate=16000, path=str(path))
    if speech.duration <= 0.5:
        raise RuntimeError(f"Ses çok kısa: {speech.duration:.2f}s")
    shared["audio_16k"] = speech.audio  # STT testinde kullanılır
    took = time.perf_counter() - t0
    return {"wav": str(path.relative_to(ROOT)), "audio_seconds": round(speech.duration, 2),
            "load_seconds": round(load, 1), "rtf": round(took / speech.duration, 3),
            "summary": f"{speech.duration:.1f}s ses, RTF {took / speech.duration:.2f} (yükleme {load:.0f}s)"}


@check("stt")
def stt():
    import numpy as np
    import mlx_whisper

    audio = shared.get("audio_16k")
    source = "ema.wav (TTS -> STT)"
    if audio is None:  # EMA atlandıysa/başarısızsa sessiz olmayan bir sinyal yerine net hata
        raise RuntimeError("Test sesi yok: önce EMA kontrolü geçmeli (STT, TTS çıktısını dinler)")
    out = mlx_whisper.transcribe(np.asarray(audio, dtype=np.float32), path_or_hf_repo=STT_MODEL,
                                 language="tr", verbose=None)
    text = out.get("text", "").strip()
    hits = [k for k in KEYWORDS if k in text.lower()]
    if not hits:
        raise RuntimeError(f"Beklenen kelimeler yok. Transkript: {text!r}")
    return {"model": STT_MODEL, "source": source, "transcript": text, "matched_keywords": hits,
            "summary": repr(text[:50])}


@check("chatterbox")
def chatterbox():
    import torch
    import soundfile as sf
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    t0 = time.perf_counter()
    # Cihaz string olarak verilmeli: kütüphane "mps"/"cpu" string karşılaştırmasıyla CPU'ya map ediyor.
    model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    load = time.perf_counter() - t0
    t1 = time.perf_counter()
    wav = model.generate(TEST_SENTENCE, language_id="tr")
    gen = time.perf_counter() - t1
    audio = wav.squeeze().detach().cpu().numpy()
    seconds = len(audio) / model.sr
    if seconds <= 0.5:
        raise RuntimeError(f"Ses çok kısa: {seconds:.2f}s")
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIO_DIR / "chatterbox.wav"
    sf.write(path, audio, model.sr)
    return {"device": device, "wav": str(path.relative_to(ROOT)), "audio_seconds": round(seconds, 2),
            "load_seconds": round(load, 1), "rtf": round(gen / seconds, 3),
            "summary": f"{device}, {seconds:.1f}s ses, RTF {gen / seconds:.2f} (yükleme {load:.0f}s)"}


CHECKS = [ollama, ema, stt, chatterbox]
HEAVY = {"chatterbox"}  # sadece --full ile


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="Ağır kontrolleri de çalıştır (Chatterbox)")
    ap.add_argument("--skip", nargs="*", default=[], choices=[c.component for c in CHECKS])
    args = ap.parse_args()
    if not args.full:
        args.skip = sorted(set(args.skip) | HEAVY)

    print("==> Model sağlık kontrolü")
    for c in CHECKS:
        if c.component in args.skip:
            results.append({"component": c.component, "status": "skipped"})
            print(f"  [SKIP] {c.component}")
            continue
        c()

    EVIDENCE_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report = {"timestamp": datetime.now().isoformat(timespec="seconds"), "host": platform.platform(),
              "python": sys.version.split()[0], "test_sentence": TEST_SENTENCE, "results": results}
    out = EVIDENCE_DIR / f"healthcheck-{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failed = [r["component"] for r in results if r["status"] == "fail"]
    print(f"==> Kanıt: {out.relative_to(ROOT)}")
    if failed:
        print(f"==> BAŞARISIZ: {', '.join(failed)}")
        return 1
    print("==> Tüm kontroller geçti")
    return 0


if __name__ == "__main__":
    sys.exit(main())
