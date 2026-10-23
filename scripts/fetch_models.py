#!/usr/bin/env python3
"""Hugging Face modellerini önbelleğe indirir; çalışan backend'i yeniden başlatmaya gerek yoktur.

Backend çevrimdışı modda (HF_HUB_OFFLINE=1) çalışır ve modeli yalnızca önbellekten okur. Bu betik çevrimdışı
bayrağını kendi sürecinde kapatıp indirir; ardından arayüzde Hazırla'yı tekrar çalıştırmak yeterlidir.

Kullanım:
  ./.venv/bin/python scripts/fetch_models.py                 # profillerdeki tüm hf_whisper modelleri
  ./.venv/bin/python scripts/fetch_models.py BuzzASR/turkish # belirli model(ler)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):  # huggingface_hub içe aktarılmadan önce
    os.environ.pop(var, None)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def profile_models() -> list[str]:
    from backend.app.profiles import load_profiles

    found: list[str] = []
    for p in load_profiles().values():
        spec = p.component("stt")
        if spec and spec.get("provider") == "hf_whisper" and spec.get("model") not in found:
            found.append(spec["model"])
    return found


def main(argv: list[str]) -> int:
    from huggingface_hub import snapshot_download

    repos = argv or profile_models()
    if not repos:
        print("İndirilecek model yok.")
        return 0
    failed = 0
    for repo in repos:
        print(f"==> {repo} indiriliyor (ilk seferde birkaç GB olabilir)...", flush=True)
        try:
            path = snapshot_download(repo_id=repo)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[HATA] {repo}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        size = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file()) / 1e9
        print(f"[TAMAM] {repo} -> {path} ({size:.2f} GB)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
