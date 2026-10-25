"""A2/A3 canlı duman testi. Proje kökünde, .env'de OPENAI_API_KEY / GEMINI_API_KEY varken (ağ erişimi gerekir):

    .venv/bin/python scripts/realtime_smoke.py            # A2 ve A3
    .venv/bin/python scripts/realtime_smoke.py A2

Sonuç evidence/core-011-live-smoke.json'a yazılır; ajan sesleri data/realtime-smoke/*.wav (kulakla dinleyin: Türkçe kalitesi).
Bu betik API'ye gerçek istek atar (ücretli, birkaç sent); anahtarlar yazdırılmaz.
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.profiles import load_dotenv, load_profiles  # noqa: E402
from backend.app.voice.realtime import make_backend  # noqa: E402
from backend.app.voice.realtime_smoke import run_smoke  # noqa: E402


async def main(ids: list[str]) -> int:
    load_dotenv()
    profiles = load_profiles()
    results = []
    for pid in ids:
        spec = profiles[pid].realtime
        print(f"== {pid} {spec} ==")
        res = await run_smoke(make_backend(spec), ROOT / "data" / "realtime-smoke")
        res["profile"] = pid
        results.append(res)
        s = res["summary"]
        print(f"  ses: {res['speak'].get('got_audio')} ilk ses {res['speak'].get('first_audio_s')} sn · "
              f"fonksiyon çağrısı {s['called']}/{s['cases']} · tip geçerli {s['valid_type']} · doğru {s['correct']}")
        for e in res["errors"]:
            print("  HATA:", e)
    out = ROOT / "evidence" / "core-011-live-smoke.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("yazıldı:", out)
    return 0 if all(r["summary"]["correct"] and not r["errors"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:] or ["A2", "A3"])))
