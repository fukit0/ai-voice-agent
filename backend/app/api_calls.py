"""Aramalar API'si (lab-004): kayıtlı test aramalarının listesi, detayı ve kıyası.

GET /api/calls                 — liste (profil/senaryo/sonuç süzgeci), en yeni üstte
GET /api/calls/compare         — profil bazlı (group=profile) ya da seçilen aramalar (group=call&ids=a,b) kıyası
GET /api/calls/{id}            — transkript, tur gecikmeleri, cevaplar, ses kaydı bağlantısı
Salt okunur; ses dosyası `GET /api/voice/recordings/{id}.wav` ile iner (silme de orada).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

from . import calls, stt_runs

router = APIRouter(prefix="/api/calls", tags=["calls"])
_SID = re.compile(r"^[0-9a-f]{12}$")   # yol gezintisini engeller (api_voice ile aynı kural)


def _folder():
    return stt_runs.data_dir() / "voice-sessions"


@router.get("")
def list_calls(profile: str | None = None, scenario: str | None = None, outcome: str | None = None,
               limit: int = Query(200, ge=1, le=1000)) -> dict:
    return calls.list_calls(_folder(), profile, scenario, outcome, limit)


@router.get("/compare")
def compare(group: str = Query("profile", pattern="^(profile|call)$"), ids: str = "", baseline: str | None = None,
            profile: str | None = None, scenario: str | None = None, outcome: str | None = None) -> dict:
    wanted = [i for i in ids.split(",") if i]
    if len(wanted) > 12 or any(not _SID.match(i) for i in wanted):
        raise HTTPException(422, {"error": "invalid_ids", "message": "ids: en çok 12 adet, 12 haneli onaltılık arama kimliği."})
    if group == "call" and len(wanted) < 1:
        raise HTTPException(422, {"error": "no_ids", "message": "Karşılaştırmak için en az bir arama seçin."})
    return calls.compare(_folder(), group, wanted, baseline, profile, scenario, outcome)


@router.get("/{sid}")
def call_detail(sid: str) -> dict:
    if not _SID.match(sid):
        raise HTTPException(404, {"error": "unknown_call", "message": "Arama bulunamadı."})
    doc = calls.detail(_folder(), sid)
    if doc is None:
        raise HTTPException(404, {"error": "unknown_call", "message": f"Arama bulunamadı: {sid}"})
    return {**doc, "audio_url": f"/api/voice/recordings/{sid}.wav" if doc["has_audio"] else None}
