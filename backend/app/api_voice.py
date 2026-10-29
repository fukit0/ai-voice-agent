"""Sesli konuşma API'si (core-001): tarayıcıdan WebRTC ile mikrofonla ajanla konuşma.

POST /api/voice/offer   — tarayıcının SDP teklifi + profil; cevap SDP'si ve oturum kimliği döner.
GET  /api/voice/sessions — açık oturumlar ve sayaçları (hata ayıklama / doğrulama).
DELETE /api/voice/{id}  — oturumu kapatır, konuşma dökümünü data/voice-sessions/ altına yazar.
ADR 0001: profil sıcak olmalı; soğuksa 409 profile_not_warm döner (Hazırla).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import persona as persona_mod
from . import stt_runs
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
    score_policy: Literal["clarify", "free"] = "clarify"   # core-021: sözlü/aralıklı puan netleştirilsin mi (clarify) yoksa model mi karar versin (free)
    vad: dict | None = None              # core-015: başlangıç giriş eşiği {"db"|"auto", "barge_frames", "barge_margin_db"}
    record: bool = False                 # core-013: stereo ses kaydı (sol müşteri, sağ ajan); varsayılan kapalı (gizlilik)


@router.post("/offer")
async def offer(req: OfferRequest) -> dict:
    profile = load_profiles().get(req.profile)
    if profile is None:
        raise HTTPException(404, {"error": "unknown_profile", "message": f"Profil bulunamadı: {req.profile}"})
    realtime = profile.mode == "realtime"
    if realtime:
        if not req.scenario:   # hibrit yöntem akışı flow motoru yürütür; senaryosuz serbest sohbet bu profillerde yok
            raise HTTPException(400, {"error": "scenario_required", "profile": req.profile,
                                      "message": f"{req.profile} realtime profil; modelin cevabı fonksiyon çağrısıyla "
                                                 "bildirmesi için bir senaryo seçin."})
        missing = profile.status(check_local=False)["missing_env"]
        if missing:
            raise HTTPException(400, {"error": "missing_env", "profile": req.profile, "missing_env": missing,
                                      "message": f"{req.profile} için ortam değişkeni eksik: {', '.join(missing)} (.env)."})
    elif not profile.component("stt"):
        raise HTTPException(400, {"error": "component_unavailable", "profile": req.profile,
                                  "message": f"{req.profile} profilinde STT yok (ses doğrudan LLM'e gider, core-010); "
                                             "sesli konuşma için STT'li bir profil seçin."})
    try:  # aiortc opsiyonel: yoksa yalnızca sesli konuşma kapanır, diğer ekranlar çalışır
        from .voice.rtc import RtcVoiceConnection
    except ImportError as exc:
        raise HTTPException(503, {"error": "voice_deps_missing",
                                  "message": f"Sesli konuşma için aiortc kurulu değil ({exc.name}). "
                                             "`pip install aiortc` çalıştırıp backend'i yeniden başlatın."}) from exc
    stt = llm = tts = backend = None
    if realtime:
        from .voice.realtime import make_backend
        try:
            backend = make_backend(profile.realtime or {})
        except ValueError as exc:
            raise HTTPException(400, {"error": "unknown_realtime_provider", "message": str(exc)}) from exc
    else:
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
            persona = persona_mod.load()   # core-005: ekrandaki persona (ad -> {ASISTAN}, onay sözleri)
            flow = FlowDriver(S.get(req.scenario), llm, {**persona_mod.scenario_values(persona), **(req.values or {})},
                              score_policy=req.score_policy, persona=None if realtime else persona)
        except KeyError:
            raise HTTPException(404, {"error": "unknown_scenario", "message": f"Senaryo bulunamadı: {req.scenario}"}) from None
    conn = RtcVoiceConnection(req.profile, stt, llm, tts, flow=flow, phone_filter=req.phone_filter,
                              realtime_backend=backend, record=req.record, persona=persona_mod.load())
    CONNECTIONS[conn.sid] = conn
    if realtime:
        from .voice.fixedaudio import FixedAudio
        conn.session.fixed_audio = FixedAudio.from_spec(profile.realtime)   # core-019: sabit yasal metinler OpenAI TTS ile
    if req.vad:
        conn.session.set_vad(req.vad)
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


_SID = re.compile(r"^[0-9a-f]{12}$")   # yol gezintisini engeller: yalnızca oturum kimliği biçimi


def _recording_path(sid: str) -> Path:
    if not _SID.match(sid):
        raise HTTPException(404, {"error": "unknown_recording", "message": "Kayıt bulunamadı."})
    return stt_runs.data_dir() / "voice-sessions" / f"{sid}.wav"


@router.get("/recordings/{sid}.wav")
def recording(sid: str) -> FileResponse:
    path = _recording_path(sid)
    if not path.is_file():
        raise HTTPException(404, {"error": "unknown_recording", "message": f"Kayıt bulunamadı: {sid}"})
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@router.delete("/recordings/{sid}")
def delete_recording(sid: str) -> dict:
    """Kaydı siler (KVKK: saklama/silme kontrolü kullanıcıda); oturum dökümü (JSON) kalır, `audio` alanı işaretlenir."""
    path = _recording_path(sid)
    if not path.is_file():
        raise HTTPException(404, {"error": "unknown_recording", "message": f"Kayıt bulunamadı: {sid}"})
    path.unlink()
    meta = path.with_suffix(".json")
    if meta.is_file():
        doc = json.loads(meta.read_text(encoding="utf-8"))
        doc["audio"] = {"deleted": True}
        meta.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"deleted": sid}


@router.delete("/{sid}")
async def close(sid: str) -> dict:
    conn = CONNECTIONS.pop(sid, None)
    if conn is None:
        raise HTTPException(404, {"error": "unknown_session", "message": f"Oturum bulunamadı: {sid}"})
    await conn.close()
    return {"closed": sid, "turns": len(conn.session.turns)}
