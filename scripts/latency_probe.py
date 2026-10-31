"""Production benzeri gecikme ölçümü (A1 / A1S): bileşen bazında STT, LLM ve TTS süreleri, gerçek API'lerle.

    .venv/bin/python scripts/latency_probe.py --profile A1S --wav data/stt-clips/ornek.wav --reps 5
    .venv/bin/python scripts/latency_probe.py --profile A1  --wav data/stt-clips/ornek.wav --reps 5

Anahtarlar (.env ya da ortam): DEEPGRAM_API_KEY, ANTHROPIC_API_KEY, ELEVENLABS_API_KEY (+ ses kimliği: Persona'da atanmış ses ya da
ELEVENLABS_VOICE_ID). Eksikse hiçbir çağrı yapılmadan açık bir mesajla çıkar (kod 2).

Ne ölçer (her biri `--reps` kez; ilk tekrar SOĞUK bağlantıyı, kalanlar ısınmış bağlantıyı temsil eder ve ayrı raporlanır)
- STT toplu: ses -> metin süresi. STT akışlı (profilde streaming:true ise): ses gerçek zamanlı hızda (20 ms'lik çerçeveler) canlı
  bağlantıya akıtılır; ölçülen süre konuşma bitişinden (son çerçeve) `finish()` dönene kadardır. Üretimde asıl önemli sayı budur.
- LLM: cevap ayrıştırıcı isteminin (flow.build_messages) tek çağrısı.
- TTS: üç Türkçe cümle için toplam süre; akışlı ise ilk ses parçasına kadar süre ve toplam.
- Tahmini ilk ses = STT(bitişten sonra) + LLM + TTS(ilk ses) medyanları toplamı. VAD'in bitiş bekleme süresini (~0,5 sn) İÇERMEZ ve
  tek tek çağrıların toplamıdır; canlı aramadaki "ilk ses" ölçümünün yerini tutmaz, ona yaklaşık bir alt sınırdır.

Çıktı: ekrana tablo, evidence/latency-probe-<profil>-<zaman>.json. Not: bu bir ölçüm aracıdır; bulutta (anahtarsız) yalnızca sahte
sağlayıcılarla birim testi vardır, gerçek sayılar kullanıcının makinesinde alınır.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SENTENCES = ["Merhaba, ben sahibinden.com'dan arıyorum, kısaca birkaç soru sormak istiyorum.",
             "Teşekkür ederim, şimdi bir sonraki soruya geçiyorum.",
             "Görüşme için çok teşekkürler, iyi günler dilerim."]
FRAME_S = 0.02


def med(v: list[float]) -> float | None:
    return round(statistics.median(v), 3) if v else None


def p95(v: list[float]) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return round(s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))], 3)


def summarize(values: list[float]) -> dict[str, Any]:
    """İlk tekrar soğuk bağlantı sayılır; kalanlar ısınmış. Tek tekrar varsa yalnız soğuk vardır."""
    warm = values[1:]
    return {"cold": round(values[0], 3) if values else None, "warm_median": med(warm), "warm_p95": p95(warm),
            "warm_min": round(min(warm), 3) if warm else None, "warm_max": round(max(warm), 3) if warm else None,
            "n_warm": len(warm), "all": [round(x, 3) for x in values]}


def measure(fn: Callable[[], float], reps: int) -> list[float]:
    return [fn() for _ in range(reps)]


def stt_batch_once(stt, audio, rate) -> float:
    t0 = time.perf_counter()
    stt.transcribe(audio, rate, "tr")
    return time.perf_counter() - t0


def stt_stream_once(stt, audio, rate, pace: bool = True) -> float:
    """Konuşma bitişinden (son çerçevenin gönderilmesi) finish() dönene kadar süre."""
    import numpy as np
    stream = stt.open_stream(rate, "tr")
    stream.open()
    n = int(rate * FRAME_S)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    t_next = time.perf_counter()
    try:
        for i in range(0, len(pcm), n):
            stream.send(pcm[i:i + n].tobytes())
            if pace:
                t_next += FRAME_S
                time.sleep(max(0.0, t_next - time.perf_counter()))
        t0 = time.perf_counter()
        stream.finish()
        return time.perf_counter() - t0
    except Exception:
        stream.abort()
        raise


def llm_messages() -> list[dict]:
    from backend.app import scenario as S
    from backend.app.voice.flow import build_messages
    steps = S.get("anket")["steps"]
    items = list(steps.values()) if isinstance(steps, dict) else steps
    step = next(s for s in items if s["kind"] == "YesNo")
    return build_messages(step, "Hizmetimizden memnun kaldınız mı?", "evet memnun kaldım", "clarify")


def llm_once(llm, messages) -> float:
    t0 = time.perf_counter()
    res = llm.complete(messages, 120, 0.0)
    dt = time.perf_counter() - t0
    ex = getattr(res, "extra", None) or {}
    if "cache_read_input_tokens" in ex:      # önbellek açıkken son çağrının önbellek sayıları (rapora yazılır)
        llm.last_cache = {"creation": ex.get("cache_creation_input_tokens"), "read": ex.get("cache_read_input_tokens")}
    return dt


def tts_once(tts, text: str, stream: bool) -> tuple[float, float]:
    """(ilk ses, toplam). Akışsızda ilk ses = toplam."""
    t0 = time.perf_counter()
    if not stream:
        tts.synthesize(text, "tr")
        dt = time.perf_counter() - t0
        return dt, dt
    first = None
    s = tts.synthesize_stream(text, "tr")
    try:
        for chunk in s:
            if first is None and len(chunk):
                first = time.perf_counter() - t0
    finally:
        s.close()
    total = time.perf_counter() - t0
    return (first if first is not None else total), total


def load_clip(path: Path) -> tuple[Any, int]:
    from backend.app.providers.audio import decode_audio
    return decode_audio(path.read_bytes())


def probe(profile_id: str, stt, llm, tts, audio, rate: int, reps: int, pace: bool = True, sentences: list[str] | None = None) -> dict[str, Any]:
    sentences = sentences or SENTENCES
    out: dict[str, Any] = {"profile": profile_id, "reps": reps, "clip_seconds": round(len(audio) / rate, 2),
                           "components": {"stt": stt.describe(), "llm": llm.describe(), "tts": tts.describe()}}
    out["stt_batch"] = summarize(measure(lambda: stt_batch_once(stt, audio, rate), reps))
    stt_stream = bool(getattr(stt, "streaming", False)) and callable(getattr(stt, "open_stream", None))
    if stt_stream:
        out["stt_stream_after_speech"] = summarize(measure(lambda: stt_stream_once(stt, audio, rate, pace), reps))
    msgs = llm_messages()
    out["llm"] = summarize(measure(lambda: llm_once(llm, msgs), reps))
    tts_stream = bool(getattr(tts, "streaming", False)) and callable(getattr(tts, "synthesize_stream", None))
    firsts, totals = [], []
    for _ in range(reps):
        f = t = 0.0
        for s in sentences:
            a, b = tts_once(tts, s, tts_stream)
            f += a
            t += b
        firsts.append(f / len(sentences))
        totals.append(t / len(sentences))
    out["tts_first_audio"] = summarize(firsts)
    out["tts_total"] = summarize(totals)
    out["tts_streaming"] = tts_stream
    out["stt_streaming"] = stt_stream
    stt_key = "stt_stream_after_speech" if stt_stream else "stt_batch"
    parts = [out[stt_key]["warm_median"], out["llm"]["warm_median"], out["tts_first_audio"]["warm_median"]]
    out["estimated_first_audio_s"] = round(sum(parts), 3) if all(p is not None for p in parts) else None
    out["note"] = ("Tahmini ilk ses = STT(bitişten sonra) + LLM + TTS(ilk ses), ısınmış medyanlar; VAD bitiş beklemesi (~0,5 sn) dahil değil. "
                   "Hedef: canlı aramada p50 ≤ 1,2 sn (Aramalar ekranı). Tek ses klibi ve az tekrar: p95 yaklaşıktır.")
    return out


def render(r: dict[str, Any]) -> str:
    rows = [("STT toplu", r["stt_batch"])]
    if r.get("stt_streaming"):
        rows.append(("STT akışlı (bitişten sonra)", r["stt_stream_after_speech"]))
    rows += [("LLM", r["llm"]), ("TTS ilk ses" + (" (akışlı)" if r["tts_streaming"] else ""), r["tts_first_audio"]), ("TTS toplam", r["tts_total"])]
    lines = [f"Profil {r['profile']} · klip {r['clip_seconds']} sn · {r['reps']} tekrar (ilk soğuk)", "",
             f"{'Bileşen':32} {'soğuk':>8} {'ısınmış med':>12} {'p95':>8}"]
    for name, s in rows:
        f = lambda v: "—" if v is None else f"{v:.2f}"
        lines.append(f"{name:32} {f(s['cold']):>8} {f(s['warm_median']):>12} {f(s['warm_p95']):>8}")
    est = r["estimated_first_audio_s"]
    if r.get("prewarm_s"):
        lines += ["", "Isıtma (sn): " + ", ".join(f"{k}={'—' if v is None else v}" for k, v in r["prewarm_s"].items())]
    if r.get("llm_cache_tokens"):
        c = r["llm_cache_tokens"]
        lines += ["", f"Anthropic önbellek (son çağrı): yazılan {c['creation']}, okunan {c['read']} token" + ("  ← 0/0 ise istem asgari uzunluğun altında, önbelleklenmedi" if not (c['creation'] or c['read']) else "")]
    lines += ["", f"Tahmini ilk ses (ısınmış): {'—' if est is None else f'{est:.2f} sn'}", r["note"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="A1S")
    ap.add_argument("--wav", help="Türkçe kısa konuşma klibi (verilmezse data/stt-clips altındaki ilk .wav)")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--prewarm", action="store_true", help="ölçümden önce arama başındaki bağlantı ısıtmasını (registry.prewarm) uygula; ilk (soğuk) tekrar bunun etkisini gösterir")
    ap.add_argument("--llm-cache", action="store_true", help="Anthropic istem önbelleğini aç (llm.prompt_cache); önbellek token sayıları rapora yazılır")
    ap.add_argument("--no-pace", action="store_true", help="akışlı STT'de sesi gerçek zamanlı hızda göndermez (ölçüm yanıltır)")
    ap.add_argument("--out-dir", default=str(ROOT / "evidence"))
    args = ap.parse_args(argv)
    if args.reps < 2:
        print("--reps en az 2 olmalı (ilk tekrar soğuk bağlantı, kalanlar ısınmış).")
        return 2
    from backend.app.profiles import load_dotenv, load_profiles
    load_dotenv()   # backend ile aynı .env okuyucu; ortamdakileri ezmez
    from backend.app.providers import registry
    from backend.app.providers.base import ProviderNotReady
    profiles = load_profiles()
    if args.profile not in profiles:
        print(f"Profil bulunamadı: {args.profile}. Seçenekler: {', '.join(profiles)}")
        return 2
    prof = profiles[args.profile]
    if prof.mode == "realtime" or not (prof.component("stt") and prof.component("llm") and prof.component("tts")):
        print(f"{args.profile} STT+LLM+TTS bileşenli bir kademeli profil değil; bu araç yalnız A1/A1S gibi API profilleri içindir.")
        return 2
    try:
        specs = {c: dict(prof.component(c)) for c in ("stt", "llm", "tts")}
        if args.llm_cache:
            specs["llm"]["prompt_cache"] = True
        stt, llm, tts = (registry.get_provider(specs[c], c, args.profile) for c in ("stt", "llm", "tts"))
    except ProviderNotReady as exc:
        print(f"Ölçüm yapılamadı: {exc}")
        return 2
    wav = Path(args.wav) if args.wav else next(iter(sorted((ROOT / "data" / "stt-clips").glob("*.wav"))), None)
    if wav is None or not wav.is_file():
        print("Klip yok: --wav ile gerçek bir Türkçe konuşma kaydı verin (sessizlik/ton ile STT süresi anlamlı olmaz).")
        return 2
    audio, rate = load_clip(wav)
    if rate != 16000:   # canlı STT bağlantısı 16 kHz linear16 bekler
        from backend.app.providers.audio import resample
        audio, rate = resample(audio, rate, 16000), 16000
    issues = [i for p in (stt, llm, tts) for i in p.readiness_issues()]
    if issues:
        print("Ölçüm yapılamadı: " + "; ".join(issues))
        return 2
    import asyncio
    warm = asyncio.run(registry.prewarm(stt, llm, tts)) if args.prewarm else None
    report = probe(args.profile, stt, llm, tts, audio, rate, args.reps, pace=not args.no_pace)
    report["prewarm_s"] = warm
    report["llm_prompt_cache"] = bool(args.llm_cache)
    cache = getattr(llm, "last_cache", None)
    if cache:
        report["llm_cache_tokens"] = cache
    report["clip"] = wav.name
    report["created_at"] = datetime.now().isoformat(timespec="seconds")
    print(render(report))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"latency-probe-{args.profile}-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"yazıldı: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
