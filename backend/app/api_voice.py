"""Sesli konuşma API'si (core-001): tarayıcıdan WebRTC ile mikrofonla ajanla konuşma.

POST /api/voice/offer   — tarayıcının SDP teklifi + profil; cevap SDP'si ve oturum kimliği döner.
GET  /api/voice/sessions — açık oturumlar ve sayaçları (hata ayıklama / doğrulama).
DELETE /api/voice/{id}  — oturumu kapatır, konuşma dökümünü data/voice-sessions/ altına yazar.
ADR 0001: profil sıcak olmalı; soğuksa 409 profile_not_warm döner (Hazırla).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .api_profiles import _provider
from .profiles import load_profiles

router = APIRouter(prefix="/api/voice", tags=["voice"])
CONNECTIONS: dict[str, "RtcVoiceConnection"] = {}  # noqa: F821 (aiortc yoksa import edilmez)
MAX_SESSIONS = 3  # tek Mac'te modeller paylaşılır; çok sayıda eşzamanlı oturum ölçümleri bozar


class OfferRequest(BaseModel):
    sdp: str
    type: str = "offer"
    profile: str
    scenario: str | None = None          # verilirse konuşmayı senaryo akışı yönetir (lab-003)
    phone_filter: bool = False           # dar bant telefon sesi (300-3400 Hz)
    values: dict[str, str] | None = None  # müşteri değerleri: HITAP, MT_HITAP, GORUSME_TARIHI...


@router.post("/offer")
async def offer(req: OfferRequest) -> dict:
    profile = load_profiles().get(req.profile)
    if profile is None:
        raise HTTPException(404, {"error": "unknown_profile", "message": f"Profil bulunamadı: {req.profile}"})
    if profile.mode == "realtime":
        raise HTTPException(400, {"error": "realtime_unsupported", "profile": req.profile,
                                  "message": f"{req.profile} tek modelli realtime profil; Playground desteği lab-003'te."})
    if not profile.component("stt"):
        raise HTTPException(400, {"error": "component_unavailable", "profile": req.profile,
                                  "message": f"{req.profile} profilinde STT yok (ses doğrudan LLM'e gider, core-010); "
                                             "sesli konuşma için STT'li bir profil seçin."})
    try:  # aiortc opsiyonel: yoksa yalnızca sesli konuşma kapanır, diğer ekranlar çalışır
        from .voice.rtc import RtcVoiceConnection
    except ImportError as exc:
        raise HTTPException(503, {"error": "voice_deps_missing",
                                  "message": f"Sesli konuşma için aiortc kurulu değil ({exc.name}). "
                                             "`pip install aiortc` çalıştırıp backend'i yeniden başlatın."}) from exc
    stt, llm, tts = (_provider(profile, c) for c in ("stt", "llm", "tts"))  # soğuksa 409
    for sid in [k for k, v in CONNECTIONS.items() if v.closed]:
        CONNECTIONS.pop(sid, None)
    if len(CONNECTIONS) >= MAX_SESSIONS:
        raise HTTPException(429, {"error": "too_many_sessions", "message": f"En fazla {MAX_SESSIONS} açık oturum."})
    flow = None
    if req.scenario:
        from . import scenario as S
        from .voice.flow import FlowDriver
        try:
            flow = FlowDriver(S.get(req.scenario), llm, req.values)
        except KeyError:
            raise HTTPException(404, {"error": "unknown_scenario", "message": f"Senaryo bulunamadı: {req.scenario}"}) from None
    conn = RtcVoiceConnection(req.profile, stt, llm, tts, flow=flow, phone_filter=req.phone_filter)
    CONNECTIONS[conn.sid] = conn
    try:
        answer = await conn.accept(req.sdp, req.type)
    except Exception as exc:  # noqa: BLE001
        await conn.close()
        CONNECTIONS.pop(conn.sid, None)
        raise HTTPException(400, {"error": "bad_offer", "message": f"SDP teklifi işlenemedi: {exc}"}) from exc
    return {"session_id": conn.sid, "sdp": answer.sdp, "type": answer.type}


class PhoneBody(BaseModel):
    on: bool


@router.post("/{sid}/phone-filter")
async def phone_filter(sid: str, body: PhoneBody) -> dict:
    conn = CONNECTIONS.get(sid)
    if conn is None:
        raise HTTPException(404, {"error": "unknown_session", "message": f"Oturum bulunamadı: {sid}"})
    conn.session.set_phone_filter(body.on)
    return {"phone_filter": body.on}


@router.get("/sessions")
def sessions() -> list[dict]:
    return [c.info() for c in CONNECTIONS.values()]


@router.delete("/{sid}")
async def close(sid: str) -> dict:
    conn = CONNECTIONS.pop(sid, None)
    if conn is None:
        raise HTTPException(404, {"error": "unknown_session", "message": f"Oturum bulunamadı: {sid}"})
    await conn.close()
    return {"closed": sid, "turns": len(conn.session.turns)}
