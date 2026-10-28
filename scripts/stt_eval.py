"""STT ölçüm seti çalıştırıcısı (core-020).

    .venv/bin/python scripts/stt_eval.py data/stt-clips/manifest.json --providers L1:stt L2:stt D1:stt

Manifest: JSON liste ya da CSV; alanlar file, text, category (öksürük/gürültü için text boş). Profil bileşenleri config/profiles.yaml'dan alınır.
Çıktı evidence/core-020-stt-eval.json. En az 50 klip yoksa rapor 'karar için kullanılamaz' uyarısı verir.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.providers import registry  # noqa: E402
from backend.app.voice import stt_eval  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--providers", nargs="+", required=True, help="PROFİL:stt (örn. L2:stt)")
    ap.add_argument("--out", default=str(ROOT / "evidence" / "core-020-stt-eval.json"))
    args = ap.parse_args()
    from backend.app.profiles import load_dotenv, load_profiles
    load_dotenv()  # .env içindeki API anahtarları (DEEPGRAM_API_KEY vb.)
    profiles = load_profiles()
    provs = {}
    for ref in args.providers:
        pid, comp = ref.split(":")
        spec = profiles[pid].component(comp)
        if not spec:
            ok = [p for p, v in profiles.items() if v.component(comp)]
            raise SystemExit(f"{ref}: {pid} profilinde '{comp}' tanımlı değil (realtime/null profil). Tanımlı olanlar: {ok}")
        provs[ref] = registry.get_provider(spec, comp, pid)
    report = stt_eval.evaluate(stt_eval.load_manifest(Path(args.manifest)), provs)
    print(stt_eval.render(report))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"yazıldı: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
