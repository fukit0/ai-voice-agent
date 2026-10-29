"""Persona API'si (core-005): ekrandan persona okuma/kaydetme/sıfırlama, üretilen istem önizlemesi ve cümle uzunluğu raporu."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import persona as P

router = APIRouter(prefix="/api/persona", tags=["persona"])


class PersonaBody(BaseModel):
    name: str
    tone: str
    address: str
    max_sentences: int
    max_words_per_sentence: int
    speed: float = 1.0
    acknowledgements: list[str]
    avoid_phrases: list[str]
    extra_rules: str = ""


def _view(p: dict) -> dict:
    return {"persona": p, "defaults": P.defaults(), "options": {"tone": list(P.TONES), "address": list(P.ADDRESS)},
            "prompt": P.system_prompt(p), "greeting": P.greeting(p),
            "preview_ack": [P.ack(p, i) for i in range(len(p["acknowledgements"]))],
            "prompt_stats": P.sentence_stats([P.greeting(p), *p["acknowledgements"]], p)}


@router.get("")
def get_persona() -> dict:
    return _view(P.load())


@router.put("")
def put_persona(body: PersonaBody) -> dict:
    data = body.model_dump()
    problems = P.validate(data)
    if problems:
        raise HTTPException(422, {"error": "invalid_persona", "problems": problems, "message": " ".join(problems)})
    return _view(P.save(data))


@router.post("/preview")
def preview(body: PersonaBody) -> dict:
    """Kaydetmeden istem önizlemesi (ekranda yazarken canlı görünür)."""
    data = body.model_dump()
    problems = P.validate(data)
    return {"problems": problems, **({} if problems else _view(data))}


@router.post("/reset")
def reset_persona() -> dict:
    return _view(P.reset())


@router.get("/report")
def report(limit: int = 20) -> dict:
    return P.report(max(1, min(limit, 100)))
