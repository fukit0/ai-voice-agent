"""Gerçek zamanlı profil (A2/A3) oturum raporu (core-023, core-011).

    .venv/bin/python scripts/realtime_report.py A3
Çıktı evidence/core-023-<profil>-report.json. Önce Playground'da en az 5 arama yapın.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.stt_runs import data_dir  # noqa: E402
from backend.app.voice import realtime_report as R  # noqa: E402
from backend.app.voice.latency_report import load_sessions  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profile", help="A2 veya A3")
    ap.add_argument("--scenario")
    args = ap.parse_args()
    rep = R.summarize(load_sessions(data_dir() / "voice-sessions", args.scenario), args.profile)
    print(R.render(rep))
    out = ROOT / "evidence" / f"core-023-{args.profile.lower()}-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"yazıldı: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
