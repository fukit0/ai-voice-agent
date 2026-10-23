"""Bellek durumu: hangi modellerin aynı anda sıcak tutulabileceğini görmek için (ADR 0001)."""
from __future__ import annotations

import os
import platform
import re
import subprocess


def _sysctl(name: str) -> str | None:
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:  # noqa: BLE001 — macOS dışında yok
        return None


def memory() -> dict:
    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        total = None
    swap_used_gb = None
    raw = _sysctl("vm.swapusage")  # "total = 2048.00M  used = 1234.56M  free = ..."
    if raw:
        m = re.search(r"used = ([\d.]+)([MG])", raw)
        if m:
            swap_used_gb = round(float(m.group(1)) / (1024 if m.group(2) == "M" else 1), 2)
    ollama = []
    try:
        import httpx

        from .providers.local import OLLAMA_URL

        for m in httpx.get(f"{OLLAMA_URL}/api/ps", timeout=1.0).json().get("models", []):
            ollama.append({"name": m.get("name"), "size_gb": round(m.get("size", 0) / 1e9, 1),
                           "gpu_gb": round(m.get("size_vram", 0) / 1e9, 1), "expires_at": m.get("expires_at")})
    except Exception:  # noqa: BLE001
        pass
    return {"platform": platform.platform(), "machine": platform.machine(),
            "memory_gb": round(total / 1024**3, 1) if total else None,
            "swap_used_gb": swap_used_gb, "ollama_loaded": ollama}
