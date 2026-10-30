"""Kıyas matrisi API'si (lab-005): GET /api/matrix?weights=latency:30,naturalness:25,... — salt okunur, her istekte kayıtlardan yeniden hesaplanır
(yeni bir koşu/arama/puan sonrası ekran yenilenince güncel görünür; önbellek yoktur)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import matrix

router = APIRouter(prefix="/api/matrix", tags=["matrix"])


@router.get("")
def get_matrix(weights: str | None = None) -> dict:
    try:
        return matrix.build(weights)
    except ValueError as exc:
        raise HTTPException(422, {"error": "invalid_weights", "message": str(exc)}) from exc
