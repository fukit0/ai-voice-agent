"""Arama basina kaynak ve maliyet olcumu (eval-003, plan F6.3).

Her VoiceSession bir `UsageMeter` tasir; STT, LLM ve TTS cagrilari sayaci besler, close() oturum JSON'una `usage` blogunu yazar.
Kalemler: sure, konusma payi, STT dakikasi, LLM girdi/cikti token, TTS karakter, yerel hesaplama (GPU) saniyesi, API maliyeti.

Durustluk kurallari
- Saglayici sayi vermediyse (ornegin token) kalem `None` kalir ve `missing` listesine girer; sifir yazilmaz.
- "GPU saniyesi" = yerel saglayicilarin cagri suresi toplami (duvar saati). GPU doluluk yuzdesi DEGILDIR; esanli aramada ayni GPU paylasilir.
- Maliyet yalniz config/pricing.json'da fiyati olan API bilesenleri icin hesaplanir; fiyati olmayan bilesen `unpriced`ta gorunur,
  yerel bilesenler API ucreti almaz (0), toplam yalniz fiyatli kalemleri kapsar ve `complete` bayragi bunu soyler.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def pricing_path() -> Path:
    return Path(os.environ.get("SVA_PRICING", ROOT / "config" / "pricing.json"))


def load_pricing() -> dict[str, Any]:
    return json.loads(pricing_path().read_text(encoding="utf-8"))


class UsageMeter:
    def __init__(self) -> None:
        self.stt = {"calls": 0, "audio_s": 0.0, "seconds": 0.0}
        self.llm = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0, "tokens_missing": 0}
        self.tts = {"calls": 0, "chars": 0, "audio_s": 0.0, "seconds": 0.0}

    def add_stt(self, audio_s: float, seconds: float) -> None:
        self.stt["calls"] += 1
        self.stt["audio_s"] += audio_s
        self.stt["seconds"] += seconds

    def add_llm(self, res: Any, seconds: float) -> None:
        self.llm["calls"] += 1
        self.llm["seconds"] += seconds
        i, o = getattr(res, "input_tokens", None), getattr(res, "output_tokens", None)
        if i is None or o is None:
            self.llm["tokens_missing"] += 1     # bu cagrinin tokeni bilinmiyor: toplam eksik sayilir
        self.llm["input_tokens"] += i or 0
        self.llm["output_tokens"] += o or 0

    def add_tts(self, chars: int, audio_s: float, seconds: float) -> None:
        self.tts["calls"] += 1
        self.tts["chars"] += chars
        self.tts["audio_s"] += audio_s
        self.tts["seconds"] += seconds


class MeteredLLM:
    """FlowDriver'in kullandigi LLM'i sarar; cagrilar oturumun sayacina yazilir. Diger nitelikler sarilan nesneye gecer."""

    def __init__(self, inner: Any, meter: UsageMeter) -> None:
        self._inner, self._meter = inner, meter

    def complete(self, *args: Any, **kwargs: Any) -> Any:
        import time
        t0 = time.perf_counter()
        res = self._inner.complete(*args, **kwargs)
        self._meter.add_llm(res, time.perf_counter() - t0)
        return res

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _key(spec: dict | None) -> str | None:
    return f"{spec['provider']}:{spec.get('model') or ''}" if spec else None


def _lookup(table: dict, spec: dict | None) -> dict | None:
    if not spec:
        return None
    return table.get(_key(spec)) or table.get(spec["provider"])


def report(meter: UsageMeter, *, duration_s: float, user_speech_s: float, agent_speech_s: float,
           components: dict[str, dict | None], pricing: dict | None = None) -> dict[str, Any]:
    """Oturum JSON'una yazilan `usage` blogu. `components` = {"stt": {provider, model}, "llm": ..., "tts": ...} (bilinmeyen None)."""
    pricing = pricing if pricing is not None else load_pricing()
    local = set(pricing.get("local_providers", []))
    missing: list[str] = []
    if meter.llm["tokens_missing"]:
        missing.append("llm_tokens")
    gpu_s = sum(m["seconds"] for kind, m in (("stt", meter.stt), ("llm", meter.llm), ("tts", meter.tts))
                if (components.get(kind) or {}).get("provider") in local)
    items = {
        "duration_s": round(duration_s, 2), "user_speech_s": round(user_speech_s, 2), "agent_speech_s": round(agent_speech_s, 2),
        "speech_share": round(min(1.0, (user_speech_s + agent_speech_s) / duration_s), 3) if duration_s > 0 else None,
        "stt_minutes": round(meter.stt["audio_s"] / 60, 4), "stt_calls": meter.stt["calls"],
        "llm_calls": meter.llm["calls"], "llm_input_tokens": meter.llm["input_tokens"] if "llm_tokens" not in missing else None,
        "llm_output_tokens": meter.llm["output_tokens"] if "llm_tokens" not in missing else None,
        "tts_chars": meter.tts["chars"], "tts_calls": meter.tts["calls"], "tts_audio_s": round(meter.tts["audio_s"], 2),
        "gpu_s": round(gpu_s, 2),
    }
    cost: dict[str, float | None] = {}
    unpriced: list[str] = []
    verified = True
    for kind, tbl in (("stt", pricing.get("stt", {})), ("llm", pricing.get("llm", {})), ("tts", pricing.get("tts", {}))):
        spec = components.get(kind)
        if not spec:
            continue                                   # profilde bu bilesen yok
        if spec["provider"] in local:
            cost[kind] = 0.0                           # yerel: API ucreti yok
            continue
        p = _lookup(tbl, spec)
        if not p:
            cost[kind] = None
            unpriced.append(kind)
            continue
        verified = verified and bool(p.get("verified"))
        if kind == "stt":
            cost[kind] = meter.stt["audio_s"] / 60 * p["usd"]
        elif kind == "tts":
            cost[kind] = meter.tts["chars"] / 1000 * p["usd"]
        elif items["llm_input_tokens"] is None:
            cost[kind] = None
            unpriced.append("llm(token yok)")
        else:
            cost[kind] = (items["llm_input_tokens"] * p["input_per_mtok"] + items["llm_output_tokens"] * p["output_per_mtok"]) / 1e6
    priced = [v for v in cost.values() if v is not None]
    return {"items": items, "missing": missing,
            "cost": {"currency": pricing.get("currency", "USD"), "by_component": {k: None if v is None else round(v, 6) for k, v in cost.items()},
                     "total": round(sum(priced), 6) if priced else None, "complete": not unpriced, "unpriced": unpriced,
                     "prices_verified": verified, "note": "yerel bilesenler 0 (API ucreti yok); donanim/enerji dahil degil"}}
