"""Lab backend (FastAPI).

Faz 0–1'de model test ekranlarının (TTS stüdyosu, STT test, playground, aramalar,
kıyas matrisi) API'sini sunar; Faz 2'de yönetim panelinin backend'ine büyür.

Geliştirme:  uvicorn backend.app.main:app --reload --port 8000  (Vite /api'yi buraya proxy'ler)
Tek süreç:   frontend/dist varsa aynı uygulama arayüzü de sunar (npm run build sonrası).
"""
from __future__ import annotations

import os
import platform
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api_profiles import router as profiles_router
from .profiles import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = ROOT / "frontend" / "dist"
STARTED_AT = time.time()

load_dotenv()  # .env içindeki API anahtarları (varsa); ortamdakileri ezmez
app = FastAPI(title="Sahibinden Voice Agent Lab", version=__version__)
app.include_router(profiles_router)


@app.get("/api/health")
def health() -> dict:
    """Ayakta mı kontrolü. Model durumunu içermez: modeller scripts/healthcheck.py ile
    kontrol edilir (yükleme saniyeler sürer, bu endpoint hızlı kalmalı)."""
    return {
        "status": "ok",
        "service": "lab-backend",
        "version": __version__,
        "python": platform.python_version(),
        "uptime_seconds": round(time.time() - STARTED_AT, 1),
    }


@app.get("/api/system")
def system() -> dict:
    """Bilgisayarın bellek bilgisi: hangi profillerin aynı anda sıcak tutulabileceğine karar vermek için."""
    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        total = None
    return {"platform": platform.platform(), "machine": platform.machine(),
            "memory_gb": round(total / 1024**3, 1) if total else None}


@app.get("/api/{path:path}", include_in_schema=False)
def api_not_found(path: str) -> None:
    # /api altındaki bilinmeyen yollar arayüze (SPA) düşmesin, JSON 404 dönsün.
    raise HTTPException(status_code=404, detail=f"Bilinmeyen API yolu: /api/{path}")


# Derlenmiş arayüz varsa tek süreçte sun: /assets statik, diğer yollar SPA'ya düşer.
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        target = (FRONTEND_DIST / path).resolve()
        if path and target.is_file() and FRONTEND_DIST.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
