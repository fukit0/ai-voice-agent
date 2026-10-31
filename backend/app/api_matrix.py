"""Kıyas matrisi API'si (lab-005): GET /api/matrix?weights=latency:30,naturalness:25,... — salt okunur, her istekte kayıtlardan yeniden hesaplanır
(yeni bir koşu/arama/puan sonrası ekran yenilenince güncel görünür; önbellek yoktur)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from . import decisions, matrix

router = APIRouter(prefix="/api/matrix", tags=["matrix"])


@router.get("")
def get_matrix(weights: str | None = None) -> dict:
    try:
        return matrix.build(weights)
    except ValueError as exc:
        raise HTTPException(422, {"error": "invalid_weights", "message": str(exc)}) from exc


class DecisionBody(BaseModel):
    status: str
    reason: str = ""


@router.put("/decisions/{pid}")
def put_decision(pid: str, body: DecisionBody) -> dict:
    """Profil için karar kaydı (secildi / elendi / aday=kaydı sil). Elenen ya da seçilen profil için gerekçe zorunlu."""
    row = next((r for r in matrix.build()["rows"] if r["profile"] == pid), None)
    if row is None:
        raise HTTPException(404, {"error": "unknown_profile", "message": f"Profil yok: {pid}"})
    try:
        return decisions.set_decision(pid, body.status, body.reason, row)
    except ValueError as exc:
        raise HTTPException(422, {"error": "invalid_decision", "message": str(exc)}) from exc


@router.get("/decisions/report", response_class=PlainTextResponse)
def decisions_report() -> str:
    """Demo için profil bazlı karar özeti (Markdown)."""
    return decisions.report(matrix.build())
