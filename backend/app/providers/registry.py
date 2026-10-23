"""Sağlayıcı kayıt defteri: `provider` adı -> sınıf, örnek önbelleği ve çağrı loglaması."""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import Provider, ProviderNotReady
from .local import ChatterboxTTS, EmaTTS, HfWhisperSTT, MlxWhisperSTT, OllamaLLM
from .remote import AnthropicLLM, DeepgramSTT, ElevenLabsTTS

PROVIDERS: dict[str, type[Provider]] = {
    cls.kind: cls
    for cls in (MlxWhisperSTT, HfWhisperSTT, OllamaLLM, EmaTTS, ChatterboxTTS,
                DeepgramSTT, AnthropicLLM, ElevenLabsTTS)
}

log = logging.getLogger("sva.providers")
_cache: dict[tuple, Provider] = {}
_cache_lock = threading.Lock()


def missing_env(cls: type[Provider]) -> list[str]:
    return [name for name in cls.required_env if not os.environ.get(name)]


def get_provider(spec: dict[str, Any], component: str, profile_id: str = "") -> Provider:
    """Profil bileşen tanımından (ör. {"provider": "ema"}) sağlayıcı örneği döndürür.

    Aynı tanım için tek örnek tutulur: modeller bir kez yüklenir, profiller arası geçişte yeniden yüklenmez.
    """
    kind = spec.get("provider")
    cls = PROVIDERS.get(kind)
    if cls is None:
        raise ProviderNotReady(f"{profile_id}: bilinmeyen sağlayıcı '{kind}' ({component}).")
    if cls.component != component:
        raise ProviderNotReady(f"{profile_id}: '{kind}' bir {cls.component} sağlayıcısı, {component} değil.")
    missing = missing_env(cls)
    if missing:
        raise ProviderNotReady(
            f"{profile_id} profili için {', '.join(missing)} tanımlı değil. "
            f"Anahtarı ortam değişkeni olarak veya proje kökündeki .env dosyasına ekleyip backend'i yeniden başlatın.",
            missing_env=missing)
    options = {k: v for k, v in spec.items() if k not in ("provider", "model")}
    key = (kind, spec.get("model"), tuple(sorted(options.items())))
    with _cache_lock:
        if key not in _cache:
            _cache[key] = cls(spec.get("model"), **options)
        return _cache[key]


def log_dir() -> Path:
    return Path(os.environ.get("SVA_LOG_DIR", Path(__file__).resolve().parents[3] / "logs"))


def record_call(profile_id: str, component: str, provider: Provider, seconds: float,
                ok: bool, **fields: Any) -> dict:
    """Her sağlayıcı çağrısını hem uygulama loguna hem logs/provider-calls.jsonl'a yazar."""
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "profile": profile_id,
             "component": component, "provider": provider.kind, "model": provider.model,
             "seconds": round(seconds, 3), "ok": ok, **fields}
    log.info("provider_call %s", json.dumps(entry, ensure_ascii=False))
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        with (d / "provider-calls.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:  # log yazılamaması çağrıyı bozmamalı
        log.warning("provider-calls.jsonl yazılamadı: %s", exc)
    return entry
