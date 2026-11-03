"""Ayarlar > Cevaba bağlı tepkiler (hum-001 aç/kapa; docs/cevaba-bagli-tepki-ayari.md).

Açık (varsayılan): hum-001 davranışı — cevaptan sonra kovaya göre (puan düşük/orta/yüksek, evet/hayır, diğer) havuzdan kısa tepki,
persona `reaction_rate` oranında; aynı aramada tekrarsız.
Kapalı: hum-001 öncesi davranış (commit f2b40d4 öncesi flow.py) — her kabul edilen cevaptan sonra persona `acknowledgements` sırayla
('Anladım.', 'Teşekkür ederim.' ...), oran uygulanmaz. Persona'daki tepki havuzu ve oranı SİLİNMEZ, yalnız kullanılmaz; açınca geri gelir.
off-001 bağlam tepkileri (müşterinin cevapla birlikte sorduğu meta soruya kısa yanıt, şikayete empati) bu ayardan bağımsızdır.

Tek kaynak: data/reactions.json (yalnız varsayılandan farklıysa yazılır). Ayar yeni aramalara uygulanır (arama başında FlowDriver'a
kopyalanır); açık arama başladığı ayarla sürer. Her arama kaydı config.reactions.enabled alanına değeri yazar.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENABLED = True


def path() -> Path:
    return Path(os.environ.get("SVA_DATA_DIR", ROOT / "data")) / "reactions.json"


def _load_raw() -> dict:
    """Dosya yoksa/bozuksa boş; tip dışı değer yok sayılır (varsayılan geçerli)."""
    try:
        raw = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {"enabled": raw["enabled"]} if isinstance(raw, dict) and isinstance(raw.get("enabled"), bool) else {}


def enabled() -> bool:
    return _load_raw().get("enabled", DEFAULT_ENABLED)


def save(value: bool | None) -> bool:
    """value: True/False ya da None (varsayılana dön). Varsayılana eşitse dosya silinir. Atomik yazar (.new + replace)."""
    if value is not None and not isinstance(value, bool):
        raise ValueError("enabled true/false olmalı")
    p = path()
    if value is None or value == DEFAULT_ENABLED:
        if p.is_file():
            p.unlink()
        return DEFAULT_ENABLED
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.new")
    tmp.write_text(json.dumps({"enabled": value}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return value


def apply_to(flow) -> None:
    """Arama başında çağrılır: değer FlowDriver'a kopyalanır, arama boyunca değişmez."""
    flow.reactions_enabled = enabled()


def view() -> dict:
    from . import persona as persona_mod
    p = persona_mod.load()
    pools = p.get("reactions") or {}
    return {"enabled": enabled(), "default": DEFAULT_ENABLED, "overridden": "enabled" in _load_raw(),
            "reaction_rate": p.get("reaction_rate", 1.0), "pool_sizes": {b: len(v) for b, v in pools.items()},
            "acknowledgements": list(p.get("acknowledgements") or [])}
