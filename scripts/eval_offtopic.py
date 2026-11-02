#!/usr/bin/env python3
"""off-001: konu dışı söz + bağlama bağlı karşılık ölçümü (offline; gerçek LLM/ses YOK).

Kullanım (proje kökünde):
  python scripts/eval_offtopic.py --label once          # değişiklik öncesi
  python scripts/eval_offtopic.py --label sonra         # değişiklik sonrası
  python scripts/eval_offtopic.py --compare evidence/offtopic-eval-once-*.json evidence/offtopic-eval-sonra-*.json
Çıktı: özet tablo + evidence/offtopic-eval-<label>-<tarih>.json (vaka bazında ajan cümleleri dahil).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))


def _print(summary: dict) -> None:
    print(f"vaka {summary['cases']}, koşu {summary['runs']}, genel başarı {summary['ok_rate']}")
    for g, v in summary["by_group"].items():
        print(f"  {g:9s} başarı {v['ok_rate']}  ({v['cases']} vaka)  başarısız: {', '.join(v['failed_cases']) or '-'}")
    o = summary["offtopic"]
    print(f"  konu dışı: ilgili cevap {o['relevant_reply_rate']}, soruya dönüş {o['reask_rate']}, uydurma cevap yok {o['no_fabricated_answer_rate']},"
          f" yasak metin yok {o['forbidden_text_free_rate']}, robotik şablon oranı {o['robot_template_rate']}")
    print(f"  LLM etiketine göre: {o['by_llm_label']}")
    c = summary["context"]
    print(f"  bağlam: uygun tepki {c['reaction_fit_rate']}, yanlış ton yok {c['no_wrong_tone_rate']}")
    dl = summary["dialog"]
    print(f"  diyalog: art arda aynı cevap {dl['consecutive_identical_replies']}, tekrar eden açılış cümlesi {dl['repeated_lead_sentences']}")
    lt = summary["latency"]
    print(f"  gecikme: LLM çağrısı {lt['llm_calls_total']} / {lt['turns']} tur, katman p50 {lt['layer_ms_p50']} ms, en çok {lt['layer_ms_max']} ms")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--compare", nargs=2, type=Path, default=None, metavar=("ONCE", "SONRA"))
    args = ap.parse_args(argv)
    if args.compare:
        a, b = (json.loads(p.read_text(encoding="utf-8")) for p in args.compare)
        changed = sorted(k for k in a["frozen_branches"] if a["frozen_branches"][k] != b["frozen_branches"].get(k))
        print("ÖNCE"); _print(a["summary"]); print("SONRA"); _print(b["summary"])
        print(f"dondurulmuş setler (114+79) beklenen nesneyle dal: değişen {len(changed)} / {len(a['frozen_branches'])}: {changed or '-'}")
        return 0
    from backend.app import offtopic_eval as E
    res = E.run()
    res["label"] = args.label
    out = args.out or ROOT / "evidence" / f"offtopic-eval-{args.label}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    _print(res["summary"])
    print(f"kanıt: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
