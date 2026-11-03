"""Ayarlar > Konu dışı serbest cevap (ADR 0009 adım 2; docs/serbest-cevap-qwen.md).

GET: geçerli ayar, varsayılanlar, Ollama/model durumu (ulaşılıyor mu, model bellekte mi; thinking açıksa thinking modeli için de) ve
son serbest cevap turlarının thinking açık/kapalı süre özeti (`stats`). PUT: enabled / model / timeout_s / thinking / thinking_model /
thinking_timeout_s / backend / haiku_model / haiku_timeout_s (null -> varsayılan; docs/serbest-cevap-haiku.md). thinking, enabled'dan bağımsız saklanır; ama enabled kapalıyken Qwen hiç çağrılmaz. Ayar yeni aramalara uygulanır; her arama kendi kaydına hangi ayarla yapıldığını yazar (config.free_reply)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import stt_runs
from .voice import free_reply as F

router = APIRouter(prefix="/api/free-reply", tags=["free-reply"])


def _view(with_status: bool = True) -> dict:
    cfg, d, ov = F.settings(), F.defaults(), F.load_overrides()
    out = {"enabled": bool(cfg["enabled"]), "model": cfg["model"], "timeout_s": float(cfg["timeout_s"]),
           "defaults": {k: d[k] for k in F.OVERRIDABLE}, "overridden": sorted(ov), "categories": list(cfg.get("categories", [])),
           "haiku_categories": F.categories_for(cfg, "haiku"),   # off-003: Haiku'nun kategori kapsamı (Qwen: categories)
           "timeout_range": list(F.TIMEOUT_RANGE), "prompt": {"version": F.PROMPT_VERSION, "hash": F.prompt_hash()},
           "thinking": bool(cfg.get("thinking", False)), "thinking_model": cfg["thinking_model"],
           "thinking_timeout_s": float(cfg["thinking_timeout_s"]), "thinking_timeout_range": list(F.THINKING_TIMEOUT_RANGE),
           "thinking_max_tokens": int(cfg.get("thinking_max_tokens", 768)),
           # Arka uç (docs/serbest-cevap-haiku.md): auto = profilin LLM'ine göre; haiku_model null = profilin Anthropic modeli
           "backend": cfg.get("backend", "auto"), "backends": list(F.BACKENDS), "haiku_model": cfg.get("haiku_model"),
           "haiku_default_model": cfg.get("haiku_default_model") or "claude-haiku-5-5",
           "haiku_timeout_s": float(cfg.get("haiku_timeout_s", 2.0)), "haiku_timeout_range": list(F.HAIKU_TIMEOUT_RANGE),
           "haiku_max_tokens": int(cfg.get("haiku_max_tokens", 120)), "haiku_status": F.haiku_status(cfg)}
    if with_status:
        out["status"] = F.status(cfg)
        if out["thinking"]:
            out["thinking_status"] = F.status({**cfg, "model": cfg["thinking_model"]})
    out["stats"] = F.thinking_stats(stt_runs.data_dir() / "voice-sessions")
    return out


@router.get("")
def get_settings() -> dict:
    return _view()


class FreeReplyBody(BaseModel):
    enabled: bool | None = None
    model: str | None = None
    timeout_s: float | None = None
    thinking: bool | None = None
    thinking_model: str | None = None
    thinking_timeout_s: float | None = None
    backend: str | None = None
    haiku_model: str | None = None
    haiku_timeout_s: float | None = None


@router.put("")
def put_settings(body: FreeReplyBody) -> dict:
    """Yalnız gönderilen alanlar değişir; alan açıkça null gönderilirse varsayılana döner."""
    patch = {k: getattr(body, k) for k in body.model_fields_set if k in F.OVERRIDABLE}
    try:
        F.save_overrides(patch)
    except ValueError as exc:
        raise HTTPException(400, {"error": "invalid_free_reply_setting", "message": str(exc)}) from exc
    return _view()
