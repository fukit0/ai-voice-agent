"""Ayarlar > Cevaba bağlı tepkiler (hum-001 aç/kapa; docs/cevaba-bagli-tepki-ayari.md).

GET: geçerli değer, varsayılan, persona tepki oranı / havuz büyüklükleri / sabit onay sözleri (kapalıyken söylenecekler).
PUT {"enabled": true|false|null}: null varsayılana (açık) döner. Yeni aramalara uygulanır; her arama kaydı config.reactions'a yazar."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import reaction_setting as R

router = APIRouter(prefix="/api/reactions", tags=["reactions"])


@router.get("")
def get_settings() -> dict:
    return R.view()


class ReactionsBody(BaseModel):
    enabled: bool | None = None


@router.put("")
def put_settings(body: ReactionsBody) -> dict:
    if "enabled" in body.model_fields_set:
        try:
            R.save(body.enabled)
        except ValueError as exc:
            raise HTTPException(400, {"error": "invalid_reactions_setting", "message": str(exc)}) from exc
    return R.view()
