"""Playground'da yapılan aramaların gecikmesini profil bazında karşılaştırır (core-011: A2, A3 ve L2, 5 arama).

    .venv/bin/python scripts/session_latency.py                    # tüm profiller, tüm senaryolar
    .venv/bin/python scripts/session_latency.py L2 A2 A3 --scenario anket

Girdi data/voice-sessions/*.json; özet evidence/core-011-latency-compare.json'a yazılır. Ölçüm yapmaz, kayıtları özetler:
önce her profille aynı senaryoda en az 5 arama yapın (Playground, senaryo seçili, telefon filtresi her profilde aynı).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.stt_runs import data_dir  # noqa: E402
from backend.app.voice.latency_report import load_sessions, render, summarize  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profiles", nargs="*", help="örn. L2 A2 A3 (boşsa hepsi)")
    ap.add_argument("--scenario", help="yalnızca bu senaryo (örn. anket)")
    ap.add_argument("--out", default=str(ROOT / "evidence" / "core-011-latency-compare.json"))
    args = ap.parse_args()
    report = summarize(load_sessions(data_dir() / "voice-sessions", args.scenario), args.profiles or None)
    report["scenario"] = args.scenario
    print(render(report))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"yazıldı: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
