#!/usr/bin/env python3
"""eval-llm'i terminalden koşar (arayüzdeki 'LLM testi' ile aynı veri seti ve puanlama) ve kanıt dosyası yazar.

Kullanım (proje kökünde, Ollama açıkken; API'li profiller için .env'de anahtar):
  ./.venv/bin/python scripts/eval_llm.py L2 A1              # iki profilin LLM'i, 30 örnek
  ./.venv/bin/python scripts/eval_llm.py L2 --limit 5       # hızlı deneme
Çıktı: tablo + evidence/eval-llm-<tarih>.json (ham model çıktıları dahil).

ADR 0001: ölçüm sıcak modelle yapılır; betik her model için önce bir ısınma çağrısı yapar ve süresini ayrı raporlar.
Not: Ollama'da birden çok büyük model aynı anda yüklü kalırsa bellek çekişir; profilleri sırayla koşar ve
biri bitince Ollama modelini boşaltır (--keep ile kapatılabilir).
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
    from backend.app import llm_eval
    from backend.app.profiles import load_dotenv, load_profiles
    from backend.app.providers import ProviderNotReady, get_provider

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profiles", nargs="+", help="profil kimlikleri (config/profiles.yaml)")
    ap.add_argument("--limit", type=int, default=None, help="yalnızca ilk N örnek")
    ap.add_argument("--out", type=Path, default=None, help="kanıt dosyası (varsayılan evidence/eval-llm-<tarih>.json)")
    ap.add_argument("--keep", action="store_true", help="koşudan sonra Ollama modelini boşaltma")
    args = ap.parse_args(argv)

    load_dotenv()
    dataset = llm_eval.load_dataset()
    profiles = load_profiles()
    results, seen = [], set()
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
        except ProviderNotReady as exc:
            results.append({**base, "status": "not_ready", "error": str(exc)})
            print(f"{pid}: hazır değil — {exc}")
            continue
        issues = provider.readiness_issues()
        if issues:
            results.append({**base, "status": "not_ready", "error": "; ".join(issues)})
            print(f"{pid}: hazır değil — {'; '.join(issues)}")
            continue
        t0 = time.perf_counter()
        try:
            provider.warmup_call()
        except Exception as exc:  # noqa: BLE001
            results.append({**base, "status": "failed", "error": f"ısınma başarısız: {exc}"})
            print(f"{pid}: ısınma başarısız — {exc}")
            continue
        warm_seconds = round(time.perf_counter() - t0, 2)
        out = llm_eval.run_eval(provider, dataset, args.limit)
        if out["rows"] and all(r["seconds"] is None for r in out["rows"]):
            results.append({**base, "status": "failed", "error": out["rows"][0]["problem"], **out})
        else:
            results.append({**base, "status": "ok", "warmup_seconds": warm_seconds, **out})
        if not args.keep and base["provider"] == "ollama":
            provider.unload()

    print(f"\n{'model':32} {'JSON':>6} {'normalize':>10} {'dal':>6} {'tam':>6} {'p50':>7} {'p95':>7}")
    pct = lambda v: "—" if v is None else f"{v * 100:.0f}%"  # noqa: E731
    for r in results:
        if r["status"] != "ok":
            print(f"{r['model'][:32]:32} {r['status']}: {r.get('error', '')[:60]}")
            continue
        s = r["summary"]
        print(f"{r['model'][:32]:32} {pct(s['json_valid_rate']):>6} {pct(s['normalize_rate']):>10} "
              f"{pct(s['branch_rate']):>6} {pct(s['full_rate']):>6} {s['latency_p50']!s:>7} {s['latency_p95']!s:>7}")
        for row in r["rows"]:
            if not row["full_ok"]:
                print(f"   {row['id']} «{row['utterance']}» beklenen {row['expected']['intent']}/{row['expected']['value']} "
                      f"-> {row['parsed'] if row['parsed'] else repr(row['raw'][:50])} ({row['problem'] or 'farklı'})")

    stamp = datetime.now(timezone.utc)
    path = args.out or ROOT / "evidence" / f"eval-llm-{stamp:%Y%m%d-%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"created_at": stamp.isoformat(timespec="seconds"), "n_samples": len(dataset["samples"][:args.limit]),
                                "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nKanıt: {path}")
    return 0 if any(r["status"] == "ok" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
