#!/usr/bin/env python3
"""A1 (Haiku) LLM çağrılarındaki seyrek 18-55 sn takılmalarının nedenini ayırır (core-012 sapması: p95 ~16 sn).

  ./.venv/bin/python scripts/llm_stall_probe.py A1 --calls 60 --variant v5
İki mod, sırayla: 'shared' (üretimdeki gibi paylaşılan keep-alive bağlantı) ve 'fresh' (her çağrıda yeni TCP/TLS).
Takılma yalnız 'shared'da çıkıyorsa bayat/yarı kapalı bağlantı; ikisinde de çıkıyorsa API tarafı kuyruğu/ağ.
Çıktı: tablo + evidence/llm-stall-<profil>-<tarih>.json. Çağrılar tek tek, sıralı; zaman aşımı sağlayıcının varsayılanı (60 sn)."""
from __future__ import annotations

import argparse, json, statistics, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else None


def main(argv=None) -> int:
    from backend.app import prompt_eval as P
    from backend.app.profiles import load_dotenv, load_profiles
    from backend.app.providers import get_provider
    from backend.app.providers import remote

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profile")
    ap.add_argument("--calls", type=int, default=60)
    ap.add_argument("--variant", default="v5")
    ap.add_argument("--pause", type=float, default=0.0, help="çağrılar arası bekleme (sn); bayat bağlantıyı denemek için 5-20")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    load_dotenv()
    spec = load_profiles()[args.profile].component("llm")
    provider = get_provider(spec, "llm", args.profile)
    provider.warmup_call()
    samples = P.load_dataset(None)["samples"][:20]
    result = {"profile": args.profile, "model": spec.get("model"), "variant": args.variant, "pause": args.pause,
              "created_at": datetime.now(timezone.utc).isoformat(), "modes": {}}
    for mode in ("shared", "fresh"):
        rows = []
        for i in range(args.calls):
            s = samples[i % len(samples)]
            if mode == "fresh":
                remote.close_clients()
            t0 = time.perf_counter()
            err = None
            try:
                r = provider.complete(P.messages_for(s, args.variant), max_tokens=P.MAX_TOKENS, temperature=0)
                sec, extra = r.seconds, r.extra
            except Exception as exc:  # noqa: BLE001
                sec, extra, err = time.perf_counter() - t0, None, str(exc)[:160]
            rows.append({"i": i, "id": s["id"], "seconds": round(sec, 3), "wall": round(time.perf_counter() - t0, 3), "error": err,
                         "stop": (extra or {}).get("stop_reason"), "blocks": (extra or {}).get("blocks")})
            if args.pause:
                time.sleep(args.pause)
        secs = [r["seconds"] for r in rows]
        slow = [r for r in rows if r["seconds"] > 5]
        result["modes"][mode] = {"rows": rows, "p50": round(statistics.median(secs), 3), "p95": round(pct(secs, .95), 3), "max": max(secs),
                                 "slow_gt5": len(slow), "errors": sum(1 for r in rows if r["error"])}
        m = result["modes"][mode]
        print(f"{mode:7} n={len(rows)}  p50 {m['p50']}  p95 {m['p95']}  max {m['max']}  >5sn: {m['slow_gt5']}  hata: {m['errors']}", flush=True)
    out = args.out or ROOT / "evidence" / f"llm-stall-{args.profile}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("kanıt:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
