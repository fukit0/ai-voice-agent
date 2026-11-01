"""core-010 yoklaması: Ollama'daki model sesi doğrudan kabul ediyor mu, doğru cevaplıyor mu, ne kadar sürüyor?

    .venv/bin/python scripts/audio_llm_probe.py --wav data/stt-clips/<klip>.wav --model gemma4:12b --reps 5
    .venv/bin/python scripts/audio_llm_probe.py --clips data/stt-clips --limit 10        # klasörden ilk N klip

Ne yapar: seçilen adımın (varsayılan `musaitlik`, Evet/Hayır) gerçek ayrıştırıcı istemiyle (flow.build_audio_messages) klibi modele
`input_audio` olarak yollar; yanıtı parse eder, transkripti ve gecikmeyi yazar. Her klip için beklenen metin manifestten ya da
dosya adından DEĞİL, sizin vereceğiniz --expect'ten (örn. true/false/8) gelir; verilmezse yalnızca "yanıt geçerli JSON mu" ölçülür.
Çıktı: ekrana tablo + evidence/audio-llm-<model>-<zaman>.json. İlk HTTP hatası (örn. 400 'audio not supported') açıkça yazılır ve
betik kod 3 ile çıkar: bu, Ollama'nın bu biçimi/bu modeli ses için kabul etmediği anlamına gelir (core-010 BLOCKED, çözüm: başka taşıma).
Gerçek model gerektirir; bulutta çalıştırılamaz.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", help="tek klip")
    ap.add_argument("--clips", help="klasör (*.wav)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--model", default="gemma4:12b")
    ap.add_argument("--step", default="musaitlik")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--expect", help="beklenen value (true/false/sayı/metin); yoksa yalnız JSON geçerliliği ölçülür")
    a = ap.parse_args()
    if not a.wav and not a.clips:
        ap.error("--wav ya da --clips verin")

    from backend.app import scenario as S
    from backend.app.providers.audio import decode_audio, resample
    from backend.app.providers.base import ProviderError
    from backend.app.providers.local import OllamaLLM
    from backend.app.voice.flow import FlowDriver, build_audio_messages, parse_output

    files = [Path(a.wav)] if a.wav else sorted(Path(a.clips).glob("*.wav"))[: a.limit]
    if not files:
        print("Klip bulunamadı.")
        return 2
    flow = FlowDriver(S.get("anket"), None, None)
    step = flow.steps[a.step]
    msgs = build_audio_messages(step, flow.text_of(a.step))
    llm = OllamaLLM(a.model, audio=True)
    issues = llm.readiness_issues()
    if issues:
        print("Hazır değil:", "; ".join(issues))
        return 2
    expect = None if a.expect is None else (json.loads(a.expect) if a.expect.lower() in ("true", "false") or a.expect.replace(".", "").isdigit() else a.expect)

    rows, secs = [], []
    for f in files:
        audio, rate = decode_audio(f.read_bytes(), "left")
        audio = resample(audio, rate, 16000)
        for i in range(a.reps):
            t0 = time.perf_counter()
            try:
                res = llm.complete_audio(msgs, audio, 16000, 160, 0.0)
            except ProviderError as exc:
                print(f"\nHATA ({f.name}): {exc}\n-> Ollama bu modelle bu biçimde ses kabul etmiyor olabilir; core-010 BLOCKED, başka taşıma gerekir.")
                _save(a.model, rows, str(exc))
                return 3
            dt = time.perf_counter() - t0
            obj, err = parse_output(res.text)
            diag = res.extra or {}
            row = {"diag": {k: diag.get(k) for k in ("finish_reason", "reasoning_chars", "message_keys")}, "input_tokens": res.input_tokens,
                   "output_tokens": res.output_tokens, "clip": f.name, "rep": i + 1, "seconds": round(dt, 3), "json_ok": obj is not None, "intent": (obj or {}).get("intent"),
                   "value": (obj or {}).get("value"), "transcript": (obj or {}).get("transcript"), "raw": res.text[:200],
                   "match": None if expect is None else (obj or {}).get("value") == expect}
            rows.append(row)
            secs.append(dt)
            if not res.text:
                print(f"   BOS CEVAP: finish={diag.get('finish_reason')} reasoning_chars={diag.get('reasoning_chars')} "
                      f"giris_token={res.input_tokens} cikis_token={res.output_tokens} alanlar={diag.get('message_keys')}")
            print(f"{f.name:30s} #{i + 1} {dt:5.2f}s json={row['json_ok']} intent={row['intent']} value={row['value']} heard={row['transcript']!r}")
    warm = secs[1:] or secs
    summ = {"n": len(rows), "json_ok_rate": round(sum(r["json_ok"] for r in rows) / len(rows), 3), "p50_s": round(statistics.median(warm), 3),
            "cold_s": round(secs[0], 3), "match_rate": None if expect is None else round(sum(bool(r["match"]) for r in rows) / len(rows), 3)}
    print("\nÖzet:", summ)
    _save(a.model, rows, None, summ)
    return 0


def _save(model: str, rows: list, error: str | None, summary: dict | None = None) -> None:
    out = ROOT / "evidence" / f"audio-llm-{model.replace(':', '-')}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"model": model, "error": error, "summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Kanıt:", out)


if __name__ == "__main__":
    raise SystemExit(main())
