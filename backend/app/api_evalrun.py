"""Kıyas koşusu API'si (eval-001): kayıtlı persona seslerini hazırlar ve bir profil için 20 aramalık seti başsız koşturur.

GET  /api/evalrun/set            — personalar, yollar, klip durumu, hazır mı
POST /api/evalrun/set/build      — eksik klipleri ElevenLabs ile üretir (arka planda; GET /set ile izlenir)
POST /api/evalrun/runs           — {profile, phone_filter: off|on|both, personas?, paths?} koşuyu başlatır (202)
GET  /api/evalrun/runs[/{id}]    — liste / ilerleme (her arama: persona, yol, telefon filtresi, oturum kimliği, sonuç)
POST /api/evalrun/runs/{id}/cancel
ADR 0001: profil sıcak olmalı (409 profile_not_warm). Aynı anda tek koşu: yerel modeller paylaşılır, çakışan koşu ölçümü bozar.
"""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import evalrun
from .api_profiles import _provider
from .profiles import load_profiles
from .providers import ProviderNotReady

router = APIRouter(prefix="/api/evalrun", tags=["evalrun"])


class RunBody(BaseModel):
    profile: str
    phone_filter: Literal["off", "on", "both"] = "both"
    personas: list[str] | None = None
    paths: list[str] | None = None


def _providers(profile):
    """(stt, llm, tts): soğuksa 409, yoksa 400 (api_voice ile aynı kural). Testler burayı sahteyle değiştirir."""
    return tuple(_provider(profile, c) for c in ("stt", "llm", "tts"))


@router.get("/set")
def get_set() -> dict:
    return evalrun.set_status()


@router.post("/set/build", status_code=202)
async def build_set() -> dict:
    if evalrun.BUILD["state"] == "running":
        raise HTTPException(409, {"error": "build_running", "message": "Klip üretimi zaten sürüyor."})
    cfg = evalrun.load_config()
    try:
        evalrun.default_tts(cfg)           # anahtar yoksa 400: arka plana girmeden söyle
    except ProviderNotReady as exc:
        raise HTTPException(400, {"error": "provider_not_ready", "message": str(exc), "missing_env": exc.missing_env}) from exc

    async def job() -> None:
        try:
            await asyncio.to_thread(evalrun.build_clips, cfg)
        except Exception:  # noqa: BLE001 - hata BUILD durumuna yazıldı, GET /set gösterir
            pass

    asyncio.get_running_loop().create_task(job())
    evalrun.BUILD.update(state="running", done=0, total=0, error=None)
    return {"started": True}


@router.post("/runs", status_code=202)
async def start_run(body: RunBody) -> dict:
    profile = load_profiles().get(body.profile)
    if profile is None:
        raise HTTPException(404, {"error": "unknown_profile", "message": f"Profil bulunamadı: {body.profile}"})
    if profile.mode == "realtime":
        raise HTTPException(400, {"error": "realtime_not_supported", "profile": body.profile,
                                  "message": "Kıyas koşusu şimdilik kademeli (STT→LLM→TTS) profillerle çalışır; realtime profiller sonraki adım."})
    cfg = evalrun.load_config()
    for ids, known, what in ((body.personas, {p["id"] for p in cfg["personas"]}, "persona"), (body.paths, {p["id"] for p in cfg["paths"]}, "yol")):
        bad = [i for i in ids or [] if i not in known]
        if bad:
            raise HTTPException(422, {"error": "unknown_id", "message": f"Bilinmeyen {what}: {', '.join(bad)}"})
    if evalrun.active_run():
        raise HTTPException(409, {"error": "run_active", "message": "Zaten bir koşu sürüyor; bitmesini bekleyin ya da iptal edin."})
    if not evalrun.set_status(cfg)["ready"]:
        raise HTTPException(409, {"error": "set_not_ready", "message": "Persona sesleri hazır değil: önce 'Test setini hazırla'."})
    stt, llm, tts = _providers(profile)
    run = evalrun.new_run(body.profile, body.phone_filter, cfg, body.personas, body.paths)
    evalrun.start(run, cfg, stt, llm, tts)
    return {"run_id": run["id"], "total": run["total"]}


@router.get("/runs")
def runs() -> list[dict]:
    return evalrun.list_runs()


@router.get("/runs/{run_id}")
def run(run_id: str) -> dict:
    r = evalrun.get_run(run_id)
    if r is None:
        raise HTTPException(404, {"error": "unknown_run", "message": "Koşu bulunamadı."})
    return r


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str) -> dict:
    if not evalrun.cancel(run_id):
        raise HTTPException(409, {"error": "not_running", "message": "Koşu sürmüyor."})
    return {"cancelled": True}
