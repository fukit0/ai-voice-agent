#!/usr/bin/env python3
"""core-012: kademeli hat ayrıştırma isteminin (cascade-parser prompt sürümleri) ÜRETİM promptuyla ölçümü.

Kullanım (proje kökünde; L2 için Ollama açık, A1 için .env'de ANTHROPIC_API_KEY):
  ./.venv/bin/python scripts/eval_prompt.py L2 A1                      # v1..v4, 3 tekrar, 114 örnek
  ./.venv/bin/python scripts/eval_prompt.py L2 --variants v1 v3 --repeats 1 --limit 20   # hızlı deneme
Çıktı: tablo + kabul ölçütleri + evidence/eval-prompt-<tarih>.json (ham model çıktıları dahil).
Ölçüm sıcak modelle yapılır (ADR 0001): her model için önce ısınma çağrısı yapılır.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    from backend.app import prompt_eval as P
    from backend.app.profiles import load_dotenv, load_profiles
    from backend.app.providers import ProviderNotReady, get_provider
    from backend.app.voice.flow import prompt_info

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profiles", nargs="+")
    ap.add_argument("--variants", nargs="+", default=["v1", "v2", "v3", "v4", "v5"])
    ap.add_argument("--dataset", type=Path, default=None, help="veri seti (varsayılan config/eval/prompt-samples.json; karar için config/eval/prompt-holdout.json)")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)

    load_dotenv()
    dataset = P.load_dataset(args.dataset)
    if not P.dataset_frozen(args.dataset):
        print("UYARI: prompt-samples.json dondurulmuş hash ile uyuşmuyor (beklenen değerler değişmiş!)", file=sys.stderr)
    profiles, results, seen = load_profiles(), [], set()
    for pid in args.profiles:
        profile = profiles.get(pid)
        spec = profile.component("llm") if profile else None
        if not spec:
            print(f"{pid}: profilde LLM yok", file=sys.stderr)
            return 2
        base = {"profile": pid, "provider": spec.get("provider"), "model": spec.get("model") or ""}
        if (base["provider"], base["model"]) in seen:
            continue
        seen.add((base["provider"], base["model"]))
        try:
            provider = get_provider(spec, "llm", pid)
            issues = provider.readiness_issues()
            if issues:
                raise ProviderNotReady("; ".join(issues))
            t0 = time.perf_counter()
            provider.warmup_call()
        except Exception as exc:  # noqa: BLE001
            results.append({**base, "status": "not_ready", "error": str(exc)})
            print(f"{pid}: hazır değil — {exc}")
            continue
        warm = round(time.perf_counter() - t0, 2)
        for variant in args.variants:
            out = P.run(provider, dataset, variant, args.repeats, args.limit)
            results.append({**base, "status": "ok", "variant": variant, "prompt": prompt_info(variant), "warmup_seconds": warm, **out})
            s = out["summary"]
            print(f"{pid} {variant}: tam {s['full_rate']:.1%}  şema {s['schema_valid_rate']:.1%}  p50 {s['latency_p50']}  p95 {s['latency_p95']}")
        if not args.keep and base["provider"] == "ollama":
            provider.unload()

    print(f"\n{'model':26} {'sür':>4} {'tam':>6} {'şema':>6} {'dal':>6} {'inj.yanlış':>10} {'p50':>6} {'p95':>6}  ölçüt")
    for r in results:
        if r["status"] != "ok":
            print(f"{r['model'][:26]:26} {r['status']}: {r.get('error', '')[:60]}")
            continue
        s = r["summary"]
        t = P.meets_targets(s, is_local_l2=r["provider"] == "ollama")
        r["targets"] = t
        inj = s["by_subset"].get("injection", {}).get("wrong_branch", "—")
        print(f"{r['model'][:26]:26} {r['variant']:>4} {s['full_rate']:>6.1%} {s['schema_valid_rate']:>6.1%} {s['branch_rate']:>6.1%} "
              f"{inj!s:>10} {s['latency_p50']!s:>6} {s['latency_p95']!s:>6}  {'GEÇTİ' if all(t.values()) else 'kaldı: ' + ','.join(k for k, v in t.items() if not v)}")
    stamp = datetime.now(timezone.utc)
    path = args.out or ROOT / "evidence" / f"eval-prompt-{stamp:%Y%m%d-%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"created_at": stamp.isoformat(timespec="seconds"), "dataset": str(args.dataset or P.DATASET_PATH), "dataset_frozen": P.dataset_frozen(args.dataset),
                                "n_samples": len(dataset["samples"][:args.limit]), "repeats": args.repeats, "results": results},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nKanıt: {path}")
    return 0 if any(r["status"] == "ok" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
