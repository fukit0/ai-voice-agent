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
        # Serbest cevap (docs/serbest-cevap-haiku.md): Haiku'ya giden konu dışı karşılık istekleri AYRI sayılır (llm_* ayrıştırıcı içindir).
        # Hiç Haiku isteği yoksa rapora alan eklenmez (Qwen/L2 ve eski aramaların raporu birebir aynı kalır).
        self.free_reply = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0, "tokens_missing": 0, "cost_usd": 0.0,
                           "cost_verified": True, "unpriced": 0, "models": []}

    def add_stt(self, audio_s: float, seconds: float) -> None:
        self.stt["calls"] += 1
        self.stt["audio_s"] += audio_s
        self.stt["seconds"] += seconds

    def add_stt_stream(self, audio_s: float, seconds: float, stream_s: float, aborted: bool = False) -> None:
        """Akışlı STT (faz 3, A1S): canlı bağlantı süresince faturalanır. `stream_s` = bağlantının açık kaldığı süre
        (muhafazakâr üst sınır; Deepgram akışta gönderilen ses süresini faturalıyorsa gerçek ücret `stream_audio_s`'e yakındır).
        `aborted`: konuşma sayılmayan (kısa gürültü, ajan konuşurken düşen) akış: çağrı sayılmaz ama süresi faturaya girer.
        Toplu (batch) çağrılar `add_stt` ile ayrı sayılır; akış yokken bu alanlar oluşmaz ve rapor eskisiyle birebir aynıdır."""
        st = self.stt
        for k in ("stream_calls", "stream_aborted", "stream_s", "stream_audio_s"):
            st.setdefault(k, 0 if k in ("stream_calls", "stream_aborted") else 0.0)
        if aborted:
            st["stream_aborted"] += 1
        else:
            st["calls"] += 1
            st["stream_calls"] += 1
            st["seconds"] += seconds
        st["stream_s"] += max(0.0, stream_s)
        st["stream_audio_s"] += max(0.0, audio_s)

    def add_llm(self, res: Any, seconds: float) -> None:
        self.llm["calls"] += 1
        self.llm["seconds"] += seconds
        i, o = getattr(res, "input_tokens", None), getattr(res, "output_tokens", None)
        if i is None or o is None:
            self.llm["tokens_missing"] += 1     # bu cagrinin tokeni bilinmiyor: toplam eksik sayilir
        self.llm["input_tokens"] += i or 0
        self.llm["output_tokens"] += o or 0

    def add_free_reply(self, event: dict) -> None:
        """Tur olayı `free_reply` (FreeResult.event). Yalnız Haiku'ya GERÇEKTEN istek giden denemeler sayılır (anahtar yok / kategori dışı /
        kapalı sayılmaz). Zaman aşımı ya da hata istisnasında token bilinmez: `tokens_missing` artar (API yine ücretlendirmiş olabilir)."""
        if event.get("backend") != "haiku" or event.get("reason") in ("disabled", "category", "no_key", "cold", "unreachable"):
            return
        fr = self.free_reply
        fr["calls"] += 1
        fr["seconds"] += float(event.get("seconds") or 0.0)
        i, o = event.get("input_tokens"), event.get("output_tokens")
        if i is None or o is None:
            fr["tokens_missing"] += 1
        fr["input_tokens"] += i or 0
        fr["output_tokens"] += o or 0
        if event.get("cost_usd") is not None:
            fr["cost_usd"] += float(event["cost_usd"])
        elif i is not None and o is not None:
            fr["unpriced"] += 1                  # token var ama config/pricing.json'da bu modelin fiyatı yok
        fr["cost_verified"] = fr["cost_verified"] and bool(event.get("cost_verified", False))
        if event.get("model") and event["model"] not in fr["models"]:
            fr["models"].append(event["model"])

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


def llm_cost(provider: str, model: str | None, input_tokens: int | None, output_tokens: int | None,
             pricing: dict | None = None) -> tuple[float | None, bool]:
    """(USD, fiyat doğrulandı mı). config/pricing.json 'llm' tablosundan (report ile aynı arama: 'saglayici:model', yoksa 'saglayici').
    Fiyat ya da token yoksa None. Yerel sağlayıcı 0 (API ücreti yok)."""
    pricing = pricing if pricing is not None else load_pricing()
    if provider in set(pricing.get("local_providers", [])):
        return 0.0, True
    p = _lookup(pricing.get("llm", {}), {"provider": provider, "model": model})
    if not p or input_tokens is None or output_tokens is None:
        return None, bool(p and p.get("verified"))
    return (input_tokens * p["input_per_mtok"] + output_tokens * p["output_per_mtok"]) / 1e6, bool(p.get("verified"))


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
    streamed = "stream_s" in meter.stt                 # akışlı STT kullanıldı mı (yoksa rapor eskisiyle aynı)
    stt_billed_s = meter.stt["audio_s"] + (meter.stt["stream_s"] if streamed else 0.0)   # toplu ses + akış bağlantı süresi
    items = {
        "duration_s": round(duration_s, 2), "user_speech_s": round(user_speech_s, 2), "agent_speech_s": round(agent_speech_s, 2),
        "speech_share": round(min(1.0, (user_speech_s + agent_speech_s) / duration_s), 3) if duration_s > 0 else None,
        "stt_minutes": round(stt_billed_s / 60, 4), "stt_calls": meter.stt["calls"],
        "llm_calls": meter.llm["calls"], "llm_input_tokens": meter.llm["input_tokens"] if "llm_tokens" not in missing else None,
        "llm_output_tokens": meter.llm["output_tokens"] if "llm_tokens" not in missing else None,
        "tts_chars": meter.tts["chars"], "tts_calls": meter.tts["calls"], "tts_audio_s": round(meter.tts["audio_s"], 2),
        "gpu_s": round(gpu_s, 2),
    }
    if streamed:
        items.update({"stt_stream_minutes": round(meter.stt["stream_s"] / 60, 4),
                      "stt_stream_audio_minutes": round(meter.stt["stream_audio_s"] / 60, 4),
                      "stt_batch_minutes": round(meter.stt["audio_s"] / 60, 4),
                      "stt_stream_calls": meter.stt["stream_calls"], "stt_stream_aborted": meter.stt["stream_aborted"]})
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
            cost[kind] = stt_billed_s / 60 * p["usd"]
        elif kind == "tts":
            cost[kind] = meter.tts["chars"] / 1000 * p["usd"]
        elif items["llm_input_tokens"] is None:
            cost[kind] = None
            unpriced.append("llm(token yok)")
        else:
            cost[kind] = (items["llm_input_tokens"] * p["input_per_mtok"] + items["llm_output_tokens"] * p["output_per_mtok"]) / 1e6
    fr = getattr(meter, "free_reply", None)
    if fr and fr["calls"]:
        # Serbest cevap (Haiku) ayrı kalem: by_component.free_reply, toplam maliyete dahil. Token eksikse maliyet alt sınırdır.
        items.update({"free_reply_calls": fr["calls"], "free_reply_input_tokens": fr["input_tokens"],
                      "free_reply_output_tokens": fr["output_tokens"], "free_reply_s": round(fr["seconds"], 3),
                      "free_reply_models": list(fr["models"])})
        cost["free_reply"] = fr["cost_usd"]
        verified = verified and fr["cost_verified"]
        if fr["unpriced"]:
            unpriced.append("free_reply")
        if fr["tokens_missing"]:
            missing.append("free_reply_tokens")
            items["free_reply_tokens_missing"] = fr["tokens_missing"]
    priced = [v for v in cost.values() if v is not None]
    return {"items": items, "missing": missing,
            "cost": {"currency": pricing.get("currency", "USD"), "by_component": {k: None if v is None else round(v, 6) for k, v in cost.items()},
                     "total": round(sum(priced), 6) if priced else None, "complete": not unpriced, "unpriced": unpriced,
                     "prices_verified": verified, "note": "yerel bilesenler 0 (API ucreti yok); donanim/enerji dahil degil"
                     + ("; akisli STT: stt_minutes = toplu ses + canli baglanti suresi (muhafazakar ust sinir)" if streamed else "")}}
