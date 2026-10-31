#!/usr/bin/env python3
"""Kıyas koşusunu (eval-001: 5 persona x 4 yol = 20 arama) bir profil için ayrıştırıcı prompt sürümlerinin HER BİRİYLE koşar.

Kullanım (proje kökünde, Mac; L2 için Ollama + MLX Whisper yerelde, persona klipleri hazır: Kıyas ekranı > Test setini hazırla):
  ./.venv/bin/python scripts/eval_variants.py                     # L2, v1..v5, hızlı yol KAPALI, 20 arama x 5 sürüm = 100 arama
  ./.venv/bin/python scripts/eval_variants.py --variants v1 v5    # yalnız iki sürüm
  ./.venv/bin/python scripts/eval_variants.py --personas p1 --paths t1 --variants v1 v5   # hızlı deneme (persona/yol kimlikleri config/eval/*.json)
  ./.venv/bin/python scripts/eval_variants.py --fast-path on      # hızlı yol AÇIK (kural yolu LLM'siz çözer; sürüm farkı azalır)

Hızlı yol varsayılan KAPALI: amaç prompt sürümünün etkisini izole etmek (kural yolu LLM'i atlayınca sürümler birbirine benzer görünür).
Sürümler sırayla koşulur (her sürüm için tüm set), arama başına ham oturum JSON'u data/voice-sessions/ altına da düşer.
Çıktı: terminalde sürüm tablosu + evidence/eval-variants-<profil>-<tarih>.json (arama başına: müşterinin söylediği, ajanın kaydettiği cevaplar,
transkript, tur süreleri; analiz için bu dosyayı paylaşın). Ölçüm sıcak modelle yapılır (ADR 0001): koşudan önce ısınma çağrısı yapılır.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _warm(provider, label: str) -> None:
    t0 = time.perf_counter()
    provider.warmup_call()
    print(f"  {label} sıcak ({time.perf_counter() - t0:.1f} sn)")


def _call_detail(call: dict, sessions_dir: Path) -> dict:
    """Arama sonucuna oturum JSON'undan analiz için gereken ham alanları ekler."""
    out = {k: call.get(k) for k in ("index", "persona", "path", "phone_filter", "status", "error", "session_id", "outcome", "answers",
                                    "unanswered", "turns", "first_audio_p50_s")}
    sid = call.get("session_id")
    f = sessions_dir / f"{sid}.json" if sid else None
    if f and f.is_file():
        doc = json.loads(f.read_text(encoding="utf-8"))
        flow = doc.get("flow") or {}
        out["customer_said"] = (doc.get("eval") or {}).get("customer")
        out["recorded_answers"] = [{k: a.get(k) for k in ("step", "kind", "value", "utterance", "unanswered")} for a in flow.get("answers", [])]
        out["path_steps"] = flow.get("path")
        out["prompt"] = flow.get("prompt")
        out["transcript"] = doc.get("transcript")
        out["turns_detail"] = [{k: t.get(k) for k in ("turn", "stt_s", "llm_s", "fast_path", "first_audio_after_end_s", "stt_rejected")}
                               for t in doc.get("turns", []) if not t.get("greeting")]
        out["stats"] = {k: (doc.get("stats") or {}).get(k) for k in ("silences", "dropped", "stt_rejected")}
    return out


def _summary(calls: list[dict]) -> dict:
    ok = [c for c in calls if c.get("status") == "ok"]
    done = [c for c in ok if c.get("outcome") == "tamamlandi"]
    firsts = [c["first_audio_p50_s"] for c in ok if c.get("first_audio_p50_s") is not None]
    return {"calls": len(calls), "status_ok": len(ok), "errors": sum(1 for c in calls if c.get("status") == "error"),
            "not_finished": sum(1 for c in calls if c.get("status") in ("not_finished", "max_turns", "timeout")),
            "completed": len(done), "completed_rate": round(len(done) / len(calls), 3) if calls else None,
            "avg_answers": round(statistics.mean([c["answers"] for c in ok]), 2) if ok else None,
            "avg_unanswered": round(statistics.mean([c["unanswered"] for c in ok]), 2) if ok else None,
            "avg_turns": round(statistics.mean([c["turns"] for c in ok]), 1) if ok else None,
            "first_audio_p50_s": round(statistics.median(firsts), 3) if firsts else None}


async def _run(args, profile, cfg, stt, llm, tts) -> list[dict]:
    from backend.app import evalrun
    sessions_dir = evalrun.stt_runs.data_dir() / "voice-sessions"
    results = []
    for v in args.variants:
        run = evalrun.new_run(args.profile, args.phone_filter, cfg, args.personas, args.paths)
        print(f"\n== {v}: {run['total']} arama ==")
        t0 = time.perf_counter()
        task = asyncio.create_task(evalrun.execute(run, cfg, stt, llm, tts, fast_path=args.fast_path == "on", prompt_variant=v))
        while not task.done():
            await asyncio.sleep(5)
            print(f"  {run['done']}/{run['total']}", end="\r", flush=True)
        await task
        calls = [_call_detail(c, sessions_dir) for c in run["calls"]]
        s = _summary(calls)
        print(f"  bitti: {run['status']} · {time.perf_counter() - t0:.0f} sn · tamamlanan {s['completed']}/{s['calls']} · hata {s['errors']}")
        results.append({"variant": v, "run_id": run["id"], "run_status": run["status"], "summary": s, "calls": calls})
    return results


def main(argv: list[str] | None = None) -> int:
    from backend.app import evalrun
    from backend.app.profiles import load_dotenv, load_profiles
    from backend.app.providers import ProviderNotReady, get_provider
    from backend.app.voice.flow import prompt_info, prompt_variant

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profile", nargs="?", default="L2")
    ap.add_argument("--variants", nargs="+", default=["v1", "v2", "v3", "v4", "v5"])
    ap.add_argument("--fast-path", choices=["off", "on"], default="off")
    ap.add_argument("--phone-filter", choices=["off", "on", "both"], default="off")
    ap.add_argument("--personas", nargs="+", default=None)
    ap.add_argument("--paths", nargs="+", default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    load_dotenv()
    for v in args.variants:
        try:
            prompt_variant(v)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
    profile = load_profiles(apply_overrides=False).get(args.profile)
    if profile is None or profile.mode != "cascade":
        print(f"{args.profile}: kademeli (cascade) profil değil ya da yok", file=sys.stderr)
        return 2
    cfg = evalrun.load_config()
    st = evalrun.set_status(cfg)
    if not st["ready"]:
        print("Persona klipleri hazır değil: önce Kıyas ekranında 'Test setini hazırla'.", file=sys.stderr)
        return 2
    print(f"Profil {args.profile} · sürümler {', '.join(args.variants)} · hızlı yol {args.fast_path} · telefon filtresi {args.phone_filter}")
    try:
        stt, llm, tts = (get_provider(profile.component(c), c, profile.id) for c in ("stt", "llm", "tts"))
        for name, p in (("STT", stt), ("LLM", llm), ("TTS", tts)):
            issues = p.readiness_issues()
            if issues:
                raise ProviderNotReady(f"{name}: " + "; ".join(issues))
            _warm(p, name)
    except Exception as exc:  # noqa: BLE001
        print(f"Profil hazır değil: {exc}", file=sys.stderr)
        return 2

    results = asyncio.run(_run(args, profile, cfg, stt, llm, tts))

    print(f"\n{'sürüm':6} {'hash':13} {'tamam':>7} {'cevap/arama':>11} {'cevapsız':>9} {'tur':>5} {'ilk ses p50':>11} {'hata':>5}")
    for r in results:
        s = r["summary"]
        r["prompt"] = prompt_info(r["variant"])
        print(f"{r['variant']:6} {r['prompt']['hash']:13} {s['completed']:>3}/{s['calls']:<3} {s['avg_answers']!s:>11} {s['avg_unanswered']!s:>9} "
              f"{s['avg_turns']!s:>5} {s['first_audio_p50_s']!s:>11} {s['errors'] + s['not_finished']:>5}")
    stamp = datetime.now(timezone.utc)
    path = args.out or ROOT / "evidence" / f"eval-variants-{args.profile}-{stamp:%Y%m%d-%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"created_at": stamp.isoformat(timespec="seconds"), "profile": args.profile,
                                "components": {c: profile.component(c) for c in ("stt", "llm", "tts")},
                                "fast_path": args.fast_path, "phone_filter": args.phone_filter, "personas": args.personas, "paths": args.paths,
                                "note": "Sürümler sırayla koşuldu; her sürüm aynı persona x yol setini bir kez çalıştırdı (tekrar yok: sonuçlar tek örneklem).",
                                "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nKanıt: {path}")
    return 0 if any(r["run_status"] == "done" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
