"""Profil yapılandırması: config/profiles.yaml okunur, her bileşenin hazır olup olmadığı raporlanır."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .providers import PROVIDERS, missing_env

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = ("stt", "llm", "tts")
# Realtime (speech-to-speech) sağlayıcıların gerektirdiği anahtar
REALTIME_ENV = {"openai_realtime": "OPENAI_API_KEY", "gemini_live": "GEMINI_API_KEY", "fake_realtime": ""}


def profiles_path() -> Path:
    return Path(os.environ.get("SVA_PROFILES", ROOT / "config" / "profiles.yaml"))


@dataclass
class Profile:
    id: str
    name: str
    purpose: str = ""
    mode: str = "cascade"  # cascade: STT -> LLM -> TTS; realtime: tek model
    components: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    realtime: dict[str, Any] | None = None
    notes: str = ""

    def component(self, name: str) -> dict[str, Any] | None:
        return self.components.get(name)

    def status(self, check_local: bool = True) -> dict[str, Any]:
        """Model yüklemeden profil durumu: eksik anahtarlar ve hızlı bulunabilen sorunlar."""
        comps: dict[str, Any] = {}
        missing: set[str] = set()
        issues: list[str] = []
        for name in COMPONENTS:
            spec = self.components.get(name)
            if not spec:
                comps[name] = None
                continue
            cls = PROVIDERS.get(spec.get("provider"))
            entry = {"provider": spec.get("provider"), "model": spec.get("model") or ""}
            if cls is None:
                issues.append(f"{name}: bilinmeyen sağlayıcı '{spec.get('provider')}'")
            else:
                m = missing_env(cls)
                missing.update(m)
                entry["missing_env"] = m
                entry["warm"] = False
                if check_local and not m:
                    from .providers import get_provider

                    provider = get_provider(spec, name, self.id)
                    issues += [f"{name}: {i}" for i in provider.readiness_issues()]
                    entry["warm"] = provider.is_warm()
            comps[name] = entry
        if self.realtime:
            # Realtime sağlayıcı: ayrı STT/LLM/TTS yok; yalnızca anahtar kontrolü. Konuşma core-011'de (voice/realtime.py)
            kind = self.realtime.get("provider")
            key = REALTIME_ENV.get(kind)
            if key is None:
                issues.append(f"realtime: bilinmeyen sağlayıcı '{kind}'")
            elif key and not os.environ.get(key):
                missing.add(key)
        return {"id": self.id, "name": self.name, "purpose": self.purpose, "mode": self.mode,
                "notes": self.notes, "components": comps, "realtime": self.realtime,
                "missing_env": sorted(missing), "issues": issues,
                # hazır = anahtar eksik değil, bilinen sorun yok, üç bileşen de var (cascade)
                "ready": (not missing and not issues and (
                    self.mode == "realtime" or not any(c is None for c in comps.values()))),
                # sıcak = bileşenlerin hepsi yüklü ve ısınmış; ölçümler yalnızca sıcak profilde yapılır (ADR 0001)
                "warm": (self.mode == "cascade" and any(comps.values())
                         and all(c.get("warm") for c in comps.values() if c))}


def load_profiles(path: Path | None = None, include_studio: bool = False) -> dict[str, Profile]:
    """`include_studio`: yalnızca TTS stüdyosunda kullanılan, listede görünmeyen tek bileşenli profiller de dahil."""
    raw = yaml.safe_load((path or profiles_path()).read_text(encoding="utf-8")) or {}
    out: dict[str, Profile] = {}
    entries = dict(raw.get("profiles") or {})
    if include_studio:
        entries.update(raw.get("studio_profiles") or {})
    for pid, cfg in entries.items():
        out[pid] = Profile(id=pid, name=cfg.get("name", pid), purpose=cfg.get("purpose", ""),
                           mode=cfg.get("mode", "cascade"), realtime=cfg.get("realtime"),
                           notes=cfg.get("notes", ""),
                           components={c: cfg.get(c) for c in COMPONENTS})
    if not out:
        raise ValueError(f"{path or profiles_path()} içinde profil yok")
    return out


def load_dotenv(path: Path | None = None) -> None:
    """Proje kökündeki .env'i okur (varsa). Ortamda zaten tanımlı değişkenleri ezmez."""
    path = path or ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
