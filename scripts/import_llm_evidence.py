"""evidence/eval-llm-*.json kayıtlarını data/llm-evals/ altına alır; Kıyas matrisi (Cevap doğruluğu) yalnızca orayı okur.

    .venv/bin/python scripts/import_llm_evidence.py

Neden: scripts/eval_llm.py sonuçları evidence/ altına yazar, ekrandaki LLM testi ise data/llm-evals/ altına yazar. Matris ikincisini
okuduğu için komut satırından koşulan gerçek ölçümler matriste görünmüyordu. Bu betik yeni sayı üretmez; var olan kayıtları kopyalar
(aynı kimlik varsa dokunmaz), kayıt kimliği dosya adıdır.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    dst = Path(os.environ.get("SVA_DATA_DIR", ROOT / "data")) / "llm-evals"
    dst.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    for src in sorted((ROOT / "evidence").glob("eval-llm-*.json")):
        out = dst / src.name
        if out.exists():
            skipped += 1
            continue
        doc = json.loads(src.read_text(encoding="utf-8"))
        doc["id"] = src.stem
        out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        copied += 1
    print(f"{copied} kayıt alındı, {skipped} zaten vardı -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
