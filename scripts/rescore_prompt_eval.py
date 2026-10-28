#!/usr/bin/env python3
"""Mevcut eval-prompt kanıtını (ham model çıktıları) GÜNCEL puanlayıcıyla yeniden puanlar; model çağrısı yapmaz.

Neden: puanlayıcı hatası düzeltilince (örn. clarify politikası davranışı 'unclear' ile aynı olan örnekler yanlış sayılıyordu) eski koşuyu
tekrar harcamadan doğru sayıya ulaşmak. Orijinal dosya değişmez; <ad>-rescored.json yazılır.
Kullanım: ./.venv/bin/python scripts/rescore_prompt_eval.py evidence/eval-prompt-20261028-193504.json config/eval/prompt-holdout.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str]) -> int:
    from backend.app import prompt_eval as P

    src = Path(argv[0])
    data = json.loads(src.read_text(encoding="utf-8"))
    dataset = P.load_dataset(Path(argv[1]) if len(argv) > 1 else None)
    by_id = {s["id"]: s for s in dataset["samples"]}
    for res in data["results"]:
        if res.get("status") != "ok":
            continue
        rows = []
        for old in res["rows"]:
            row = P.score(by_id[old["id"]], old["raw"], error=old["problem"] if old["problem"] and old["problem"].startswith("sağlayıcı") else None)
            row["seconds"], row["rep"] = old.get("seconds"), old.get("rep")
            rows.append(row)
        res["rows"], res["summary"] = rows, P.summarize(rows)
        res["targets"] = P.meets_targets(res["summary"], is_local_l2=res["provider"] == "ollama")
        s = res["summary"]
        print(f"{res['profile']} {res['variant']}: tam {s['full_rate']:.1%} şema {s['schema_valid_rate']:.1%} "
              f"inj.yanlış {s['by_subset'].get('injection', {}).get('wrong_branch')} p95 {s['latency_p95']}  {res['targets']}")
    data["rescored_with"] = "prompt_eval.score (clarify-aware)"
    out = src.with_name(src.stem + "-rescored.json")
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Yazıldı:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
